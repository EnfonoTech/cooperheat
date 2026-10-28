"""Close a check-in nobody closed (client, 2026-10-28).

If an employee's last punch is a check-IN more than 24 hours old, the system adds the
check-OUT itself: 8 hours after the check-in, with the note below, so the attendance is
made and the supervisor sees on approval that the hours were not punched. The supervisor
corrects the Payable hours if the employee really worked longer or shorter.

Runs hourly (hooks.scheduler_events), before the attendance generator. Kill switch:
``cooperheat_disable_auto_checkout`` = 1 in site_config.json.
"""

from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime

OPEN_HOURS = 24  # a check-in still open after this long is closed by the system
CLOSE_AFTER_HOURS = 8  # the system check-out is this long after the check-in
LOOKBACK_DAYS = 14  # older open check-ins are left to HR
NOTE = "System generated check-out due to missed check-out from employee"


def open_checkins(now=None, employees=None) -> list:
	"""Last punch per employee when it is an IN older than OPEN_HOURS (and newer than LOOKBACK_DAYS)."""
	now = get_datetime(now or now_datetime())
	ci = frappe.qb.DocType("Employee Checkin")
	latest = (
		frappe.qb.from_(ci)
		.select(ci.employee, frappe.query_builder.functions.Max(ci.time).as_("last_time"))
		.where(ci.time >= now - timedelta(days=LOOKBACK_DAYS))
		.where(ci.time <= now)
		.where(ci.employee.isin(list(employees)) if employees else ci.employee.isnotnull())
		.groupby(ci.employee)
	).run(as_dict=True)
	cutoff = now - timedelta(hours=OPEN_HOURS)
	stale = {r.employee: r.last_time for r in latest if get_datetime(r.last_time) <= cutoff}
	if not stale:
		return []
	rows = frappe.get_all(
		"Employee Checkin",
		filters={"employee": ["in", list(stale)], "time": ["in", list(set(stale.values()))], "log_type": "IN"},
		fields=["name", "employee", "time", "custom_project"],
	)
	active = set(frappe.get_all("Employee", filters={"name": ["in", list(stale)], "status": "Active"}, pluck="name"))
	return [r for r in rows if r.employee in active and get_datetime(r.time) == get_datetime(stale[r.employee])]


def close_forgotten_checkins(now=None, employees=None) -> dict:
	if frappe.conf.get("cooperheat_disable_auto_checkout"):
		return {"skipped": "disabled"}
	closed, failed = [], []
	for r in open_checkins(now, employees):
		frappe.db.savepoint("auto_checkout")
		try:
			doc = frappe.get_doc(
				{
					"doctype": "Employee Checkin",
					"employee": r.employee,
					"log_type": "OUT",
					"time": get_datetime(r.time) + timedelta(hours=CLOSE_AFTER_HOURS),
					"custom_project": r.custom_project,
					"activity_log": NOTE,
				}
			)
			doc.flags.ignore_permissions = True
			doc.insert()
			doc.add_comment("Comment", text=NOTE)
		except Exception:
			frappe.db.rollback(save_point="auto_checkout")
			failed.append(r.employee)
			frappe.log_error(title=f"Auto check-out failed: {r.employee}", message=frappe.get_traceback())
		else:
			closed.append(r.employee)
			frappe.db.commit()
	if closed:
		frappe.logger("cooperheat").info(f"auto check-out: {len(closed)} closed")
	return {"closed": closed, "failed": failed}
