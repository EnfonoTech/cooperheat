# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Backend for the Supervisor Workspace page.

Every method is permission-checked against the standard doctype permissions,
which already include the team-scoping hooks (``permissions.scope``), so a
supervisor can only ever read or change their own team.
"""

from datetime import timedelta

import frappe
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, today

from cooperheat.cooperheat.permissions.scope import SCOPED_ROLES, get_scope, is_scoped, unrestricted_roles

PENDING_STATES = (
	"Pending Level 1 Approval",
	"Pending Level 2 Approval",
	"Pending Level 3 Approval",
)

# Supervisors may correct a check-in/out time only for this long after it
# happened. HR Manager / System Manager are exempt.
EDIT_WINDOW_HOURS = 48


def _my_employee(user: str | None = None) -> str | None:
	return frappe.db.get_value("Employee", {"user_id": user or frappe.session.user}, "name")


def _sees_everyone(user: str | None = None) -> bool:
	return not is_scoped(user or frappe.session.user)


def _require_supervisor_or_hr():
	"""The workspace is for supervisors/managers and HR. A plain employee must not
	be able to list the company through these methods (they read with get_all)."""
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if user != "Administrator" and not (roles & (SCOPED_ROLES | unrestricted_roles())):
		frappe.throw(frappe._("The Supervisor Workspace is only available to supervisors, managers and HR."), frappe.PermissionError)


def _team_employees() -> list[str]:
	"""Active employees the current user supervises (never the user themself)."""
	user = frappe.session.user
	me = _my_employee(user)
	if _sees_everyone(user):
		names = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit_page_length=1000)
	else:
		scope = sorted(get_scope(user).employees)
		if not scope:
			return []
		names = frappe.get_all("Employee", filters={"name": ["in", scope], "status": "Active"}, pluck="name")
	return [n for n in names if n != me]


def can_edit_checkin_time(checkin_time, user: str | None = None) -> bool:
	"""True while a check-in is young enough for ``user`` to correct it."""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or roles & unrestricted_roles():
		return True
	return now_datetime() - get_datetime(checkin_time) <= timedelta(hours=EDIT_WINDOW_HOURS)


def _hours_from_logs(logs: list) -> float:
	"""Sum of IN->OUT pair durations in hours. A trailing IN without an OUT counts for nothing."""
	total = 0.0
	open_in = None
	for log in logs:
		if log.log_type == "IN" and open_in is None:
			open_in = get_datetime(log.time)
		elif log.log_type == "OUT" and open_in is not None:
			total += (get_datetime(log.time) - open_in).total_seconds() / 3600.0
			open_in = None
	return round(total, 2)


@frappe.whitelist()
def get_team(date=None) -> list[dict]:
	"""The current user's technicians with today's state and pending approvals."""
	_require_supervisor_or_hr()
	frappe.has_permission("Employee", "read", throw=True)
	day = str(getdate(date or today()))
	team = _team_employees()
	if not team:
		return []

	emps = frappe.get_all(
		"Employee",
		filters={"name": ["in", team]},
		fields=["name", "employee_name", "designation", "department", "reports_to", "cell_number"],
		order_by="employee_name asc",
	)

	logs_by_emp: dict[str, list] = {}
	for log in frappe.get_all(
		"Employee Checkin",
		filters={"employee": ["in", team], "time": ["between", [day + " 00:00:00", day + " 23:59:59"]]},
		fields=["employee", "log_type", "time"],
		order_by="time asc",
	):
		logs_by_emp.setdefault(log.employee, []).append(log)

	me = _my_employee()
	pending_filters = {"employee": ["in", team], "workflow_state": ["in", list(PENDING_STATES)], "docstatus": 1}
	if not _sees_everyone() and me:
		pending_filters["current_approver"] = me
	pending: dict[str, int] = {}
	pending_day: dict[str, int] = {}
	for row in frappe.get_all("Attendance", filters=pending_filters, fields=["employee", "attendance_date"]):
		pending[row.employee] = pending.get(row.employee, 0) + 1
		if str(row.attendance_date) == day:
			pending_day[row.employee] = pending_day.get(row.employee, 0) + 1

	out = []
	for e in emps:
		logs = logs_by_emp.get(e.name, [])
		if not logs:
			state = "none"
		elif logs[-1].log_type == "IN":
			state = "in"
		else:
			state = "out"
		out.append(
			{
				"employee": e.name,
				"employee_name": e.employee_name,
				"designation": e.designation,
				"department": e.department,
				"cell_number": e.cell_number,
				"state": state,
				"first_in": str(logs[0].time) if logs else None,
				"last_log": str(logs[-1].time) if logs else None,
				"hours_today": _hours_from_logs(logs),
				"pending": pending.get(e.name, 0),
				"pending_day": pending_day.get(e.name, 0),
			}
		)
	# people with something to approve first, then those currently on site
	out.sort(key=lambda r: (-r["pending"], r["state"] != "in", r["employee_name"] or ""))
	return out


@frappe.whitelist()
def get_employee_days(employee: str, from_date=None, to_date=None) -> list[dict]:
	"""Date-wise attendance of one technician: per day the Attendance, every
	check-in/out, and the day summary (in, out, total hours)."""
	_require_supervisor_or_hr()
	frappe.has_permission("Employee", "read", doc=employee, throw=True)
	frappe.has_permission("Employee Checkin", "read", throw=True)
	frappe.has_permission("Attendance", "read", throw=True)
	to_d = getdate(to_date or today())
	from_d = getdate(from_date or add_days(to_d, -13))

	logs_by_day: dict[str, list] = {}
	for log in frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "time": ["between", [str(from_d) + " 00:00:00", str(to_d) + " 23:59:59"]]},
		fields=["name", "log_type", "time", "custom_project", "attendance"],
		order_by="time asc",
	):
		logs_by_day.setdefault(str(getdate(log.time)), []).append(log)

	atts = {
		str(a.attendance_date): a
		for a in frappe.get_all(
			"Attendance",
			filters={"employee": employee, "attendance_date": ["between", [from_d, to_d]], "docstatus": ["!=", 2]},
			fields=[
				"name", "attendance_date", "status", "workflow_state", "in_time", "out_time",
				"working_hours", "current_approver", "current_approver_name",
			],
		)
	}

	projects = {}
	proj_ids = {log.custom_project for logs in logs_by_day.values() for log in logs if log.custom_project}
	if proj_ids:
		projects = {
			p.name: p
			for p in frappe.get_all(
				"Project",
				filters={"name": ["in", list(proj_ids)]},
				fields=["name", "project_name", "custom_project_code", "custom_crm_no"],
			)
		}

	can_write = frappe.has_permission("Employee Checkin", "write")
	me = _my_employee()
	hr = _sees_everyone()
	days = []
	for day in sorted(set(logs_by_day) | set(atts), reverse=True):
		logs = logs_by_day.get(day, [])
		att = atts.get(day)
		first_in = next((l.time for l in logs if l.log_type == "IN"), None)
		last_out = next((l.time for l in reversed(logs) if l.log_type == "OUT"), None)
		days.append(
			{
				"date": day,
				"attendance": att,
				"can_approve": bool(
					att and att.workflow_state in PENDING_STATES and (hr or (me and att.current_approver == me))
				),
				"first_in": str(first_in) if first_in else None,
				"last_out": str(last_out) if last_out else None,
				"total_hours": _hours_from_logs(logs),
				"complete": bool(logs) and logs[-1].log_type == "OUT",
				"checkins": [
					{
						"name": l.name,
						"log_type": l.log_type,
						"time": str(l.time),
						"project": l.custom_project,
						"project_label": project_label(projects.get(l.custom_project)),
						"editable": bool(can_write and can_edit_checkin_time(l.time)),
					}
					for l in logs
				],
			}
		)
	return days


def project_label(p) -> str | None:
	"""``CODE — Project name`` so two projects at one site are distinguishable."""
	if not p:
		return None
	code = p.get("custom_project_code") or p.get("custom_crm_no") or p.get("name")
	name = p.get("project_name")
	return code + " — " + name if name and name != code else code


@frappe.whitelist()
def get_pending_grouped(date=None, all_dates: int = 0, scope: str | None = None) -> list[dict]:
	"""Pending approvals of the current user grouped under each technician.

	``scope``: ``day`` (only ``date``, default = today), ``earlier`` (before ``date``)
	or ``all``. ``all_dates=1`` is kept as an alias for ``scope="all"``."""
	_require_supervisor_or_hr()
	frappe.has_permission("Attendance", "read", throw=True)
	team = _team_employees()
	if not team:
		return []
	filters = {"employee": ["in", team], "workflow_state": ["in", list(PENDING_STATES)], "docstatus": 1}
	me = _my_employee()
	if not _sees_everyone() and me:
		filters["current_approver"] = me
	scope = scope or ("all" if cint(all_dates) else "day")
	day = getdate(date or today())
	if scope == "day":
		filters["attendance_date"] = day
	elif scope == "earlier":
		filters["attendance_date"] = ["<", day]

	groups: dict[str, dict] = {}
	for a in frappe.get_all(
		"Attendance",
		filters=filters,
		fields=[
			"name", "employee", "employee_name", "attendance_date", "working_hours",
			"workflow_state", "status", "window_expires_at", "in_time", "out_time",
		],
		order_by="attendance_date desc",
	):
		g = groups.setdefault(a.employee, {"employee": a.employee, "employee_name": a.employee_name, "items": []})
		g["items"].append(
			{
				"attendance": a.name,
				"date": str(a.attendance_date),
				"hours": flt(a.working_hours),
				"state": a.workflow_state,
				"status": a.status,
				"in_time": str(a.in_time) if a.in_time else None,
				"out_time": str(a.out_time) if a.out_time else None,
				"window_expires_at": str(a.window_expires_at) if a.window_expires_at else None,
			}
		)
	return sorted(groups.values(), key=lambda g: g["employee_name"] or "")


def _approve_one(attendance: str) -> str:
	"""Advance one pending Attendance by the current user. The business rule (only the
	assigned approver, or HR) is checked here; the per-level authorisation and the
	hours recalculation are enforced again by the Attendance hooks on save."""
	from frappe.model.workflow import apply_workflow, get_transitions

	doc = frappe.get_doc("Attendance", attendance)
	doc.check_permission("write")
	if doc.workflow_state not in PENDING_STATES:
		frappe.throw(frappe._("{0} is no longer pending approval.").format(attendance))
	me = _my_employee()
	if _is_scoped_user() and doc.current_approver != me:
		frappe.throw(frappe._("{0} is not assigned to you.").format(attendance), frappe.PermissionError)

	wx = doc.get("window_expires_at")
	if wx and get_datetime(wx) < now_datetime() and _is_scoped_user():
		frappe.throw(frappe._("The approval window for {0} has expired; it is handled automatically.").format(attendance))

	action = next((t["action"] for t in (get_transitions(doc) or []) if "approve" in (t.get("action") or "").lower()), None)
	if not action:
		frappe.throw(frappe._("No approve action is available for {0}.").format(attendance))
	if not _is_scoped_user() and doc.current_approver != me:
		# HR Manager / System Manager stepping in for the assigned approver (same rule as the mobile app)
		doc.flags.ignore_permissions = True
	apply_workflow(doc, action)
	return doc.workflow_state


def _is_scoped_user() -> bool:
	return is_scoped(frappe.session.user)


@frappe.whitelist()
def approve_attendance(attendance: str) -> dict:
	"""Approve one pending attendance (Level 1/2/3 as appropriate for the caller)."""
	_require_supervisor_or_hr()
	return {"attendance": attendance, "state": _approve_one(attendance)}


@frappe.whitelist()
def approve_many(attendances) -> dict:
	"""Approve several attendances; one failure never stops the rest."""
	_require_supervisor_or_hr()
	if isinstance(attendances, str):
		attendances = frappe.parse_json(attendances)
	done, failed = [], []
	for name in attendances or []:
		frappe.db.savepoint("approve_one")
		try:
			_approve_one(name)
			done.append(name)
		except Exception as e:
			frappe.db.rollback(save_point="approve_one")
			failed.append({"attendance": name, "error": str(e)})
	return {"approved": done, "failed": failed}


def save_checkin_time(doc, new_time) -> None:
	"""Change the time of an Employee Checkin and save it.

	Once an Attendance exists its check-ins are linked to it, and HRMS then refuses
	every change of ``time`` ("Cannot Modify Time"). Approvers and supervisors must
	still be able to correct a time while the attendance is pending, so the link is
	lifted for this one save and put back straight afterwards. The 48-hour window,
	permissions and overlap checks all still run (``overrides.employee_checkin``)."""
	linked = doc.get("attendance")
	if linked:
		doc.attendance = None
	doc.time = get_datetime(new_time)
	doc.save()
	if linked:
		frappe.db.set_value("Employee Checkin", doc.name, "attendance", linked, update_modified=False)


@frappe.whitelist()
def set_checkin_time(checkin: str, time) -> dict:
	"""Correct one check-in/out time. Permission, team scope and the 48-hour
	window are enforced by the document itself (``overrides.employee_checkin``)."""
	doc = frappe.get_doc("Employee Checkin", checkin)
	doc.check_permission("write")
	save_checkin_time(doc, time)
	return {"checkin": doc.name, "time": str(doc.time), "attendance": linked_attendance(doc.name)}


def linked_attendance(checkin: str):
	return frappe.db.get_value("Employee Checkin", checkin, "attendance")
