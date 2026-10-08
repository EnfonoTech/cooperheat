# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Create an Attendance (and so start the approval chain) from Employee Checkin.

Why this exists
---------------
The approval workflow in this app starts when an Attendance is submitted
(``overrides.attendance.on_submit``). Standard HRMS only creates Attendance for
check-ins that fall inside an assigned shift (``Shift Assignment`` / the
employee's default shift) and only up to the Shift Type's
``last_sync_of_checkin``. Technicians here check in at job sites at variable
hours with no shift assignment, so those check-ins were flagged "outside
assignment shift hours" and no Attendance - hence no approval - was ever
created.

This job closes the gap: for every employee/day that has a *complete* set of
check-ins (an IN and the last log of the day is an OUT) and no live Attendance
yet, it creates and submits one, and flags the check-ins with HRMS's ``skip_auto_attendance`` so auto-attendance never
double-books the same logs.

Run hourly from the scheduler. Kill switch: set ``cooperheat_disable_attendance_generation``
to 1 in site_config.json. Look-back window: ``cooperheat_attendance_lookback_days``
(default 3).

Rules
-----
* A day is *complete* when it has an IN and its last log is an OUT. Days before
  today are generated as soon as they are complete. TODAY is only generated when the
  last OUT is at least ``cooperheat_attendance_same_day_idle_hours`` old (default 3),
  so a lunch-break OUT does not start an approval for a half day. A later IN/OUT on
  a day that already has an Attendance re-derives its hours (employee_checkin.on_update).
* Departments with no Level 1 approver are skipped and counted in ``no_approver``.
* A day that was deliberately cancelled by HR (a cancelled Attendance exists) is not
  re-created.
* Days that cannot be paired (IN without OUT on a past day, or an OUT only) are
  counted in ``incomplete`` and shown on the Supervisor Workspace as "Open check-in".
  Overnight shifts (IN on one date, OUT on the next) are not paired - the app's
  check-in validation is same-day by design.
* Concurrent runs are serialised by a file lock.
"""

from datetime import timedelta

import frappe
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime, today
from frappe.utils.synchronization import LockTimeoutError, filelock

DEFAULT_LOOKBACK_DAYS = 3
DEFAULT_LIMIT = 300
DEFAULT_SAME_DAY_IDLE_HOURS = 3


def generate_attendance_from_checkins():
	"""Scheduler entry point (hourly)."""
	if cint(frappe.conf.get("cooperheat_disable_attendance_generation")):
		return {"created": 0, "skipped": 0, "errors": 0, "disabled": 1}
	lookback = cint(frappe.conf.get("cooperheat_attendance_lookback_days")) or DEFAULT_LOOKBACK_DAYS
	return generate(add_days(today(), -lookback), today())


@frappe.whitelist()
def run_now(from_date=None, to_date=None):
	"""Manual trigger / back-fill for HR Manager and System Manager."""
	frappe.only_for(["System Manager", "HR Manager"])
	return generate(from_date or add_days(today(), -DEFAULT_LOOKBACK_DAYS), to_date or today())


def generate(from_date, to_date, limit: int = DEFAULT_LIMIT) -> dict:
	"""Create the missing Attendance for [from_date, to_date]. Serialised: a second
	caller while a run is in progress returns immediately with ``busy``."""
	try:
		with filelock("cooperheat_attendance_generation", timeout=0):
			return _generate(from_date, to_date, limit)
	except LockTimeoutError:
		return {"created": 0, "skipped": 0, "errors": 0, "no_approver": 0, "incomplete": 0, "busy": 1}


def _generate(from_date, to_date, limit: int) -> dict:
	from_date, to_date = getdate(from_date), getdate(to_date)
	result = {"created": 0, "skipped": 0, "errors": 0, "no_approver": 0, "incomplete": 0}
	idle = timedelta(
		hours=cint(frappe.conf.get("cooperheat_attendance_same_day_idle_hours")) or DEFAULT_SAME_DAY_IDLE_HOURS
	)
	current = now_datetime()
	today_str = str(getdate(today()))
	has_l1: dict[str, bool] = {}

	logs = frappe.get_all(
		"Employee Checkin",
		filters={
			"time": ["between", [str(from_date) + " 00:00:00", str(to_date) + " 23:59:59"]],
			"skip_auto_attendance": 0,
		},
		fields=["name", "employee", "log_type", "time", "attendance"],
		order_by="employee asc, time asc",
	)

	days: dict[tuple[str, str], list] = {}
	for log in logs:
		days.setdefault((log.employee, str(getdate(log.time))), []).append(log)

	for (employee, day), day_logs in days.items():
		if result["created"] >= limit:
			break
		if not _is_complete(day_logs):
			if day != today_str:
				result["incomplete"] += 1
			result["skipped"] += 1
			continue
		if day == today_str and current - get_datetime(day_logs[-1].time) < idle:
			result["skipped"] += 1  # probably a break, not the end of the day
			continue
		if any(log.attendance for log in day_logs):
			result["skipped"] += 1
			continue
		# any Attendance for the day - including a cancelled one, which means HR removed it on purpose
		if frappe.db.exists("Attendance", {"employee": employee, "attendance_date": day}):
			result["skipped"] += 1
			continue
		emp = frappe.db.get_value("Employee", employee, ["status", "department"], as_dict=True)
		if not emp or emp.status != "Active":
			result["skipped"] += 1
			continue
		# An approval nobody can action is worse than none: wait until the
		# department has a Level 1 approver (see the Employee Approver Exceptions
		# report) and back-fill with run_now().
		if emp.department not in has_l1:
			has_l1[emp.department] = bool(
				emp.department
				and frappe.db.exists(
					"Department Approval Matrix",
					{"parent": emp.department, "parentfield": "approval_matrix", "approval_level": 1, "approver": ["is", "set"]},
				)
			)
		if not has_l1[emp.department]:
			result["no_approver"] += 1
			continue

		frappe.db.savepoint("att_gen")
		try:
			name = _create_attendance(employee, day, day_logs)
		except Exception:
			frappe.db.rollback(save_point="att_gen")
			result["errors"] += 1
			frappe.log_error(
				title=f"Attendance generation failed: {employee} {day}",
				message=frappe.get_traceback(),
			)
		else:
			result["created"] += 1
			frappe.db.commit()
			frappe.logger("cooperheat").info(f"attendance generated {name} for {employee} {day}")

	return result


def _is_complete(day_logs: list) -> bool:
	"""At least one IN, and the day ends with an OUT."""
	if not any(log.log_type == "IN" for log in day_logs):
		return False
	return day_logs[-1].log_type == "OUT"


def _create_attendance(employee: str, day: str, day_logs: list) -> str:
	emp = frappe.db.get_value("Employee", employee, ["company", "department"], as_dict=True)
	doc = frappe.get_doc(
		{
			"doctype": "Attendance",
			"employee": employee,
			"attendance_date": day,
			"status": "Present",
			"company": emp.company,
			"department": emp.department,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()

	# Attendance.on_submit (_populate_site_hours) links the day's check-ins to the new
	# Attendance, which also keeps HRMS auto-attendance from booking them again.
	return doc.name

