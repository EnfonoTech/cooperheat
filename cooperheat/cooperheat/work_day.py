"""Which shift (work date) does a check-in belong to.

A shift belongs to the date it STARTED. An OUT after midnight closes the shift
opened by the previous day's IN, so a Thursday-night shift that ends on Friday
morning is a Thursday shift: its Friday hours are not weekend overtime. A shift
that starts on Friday night is a Friday shift (weekend overtime).

Rule: an OUT belongs to the date of the open IN before it, if that IN is at most
MAX_SHIFT_HOURS earlier; otherwise to its own calendar date. An IN always
belongs to its own calendar date. Nothing here needs a shift assignment, so
flexible day/night field work needs no per-day roster.
"""

from datetime import timedelta

import frappe
from frappe.utils import add_days, get_datetime, getdate

MAX_SHIFT_HOURS = 16  # client rule: a working day never exceeds 16 hours


def group_by_work_date(logs, max_hours: int = MAX_SHIFT_HOURS) -> dict:
	"""{date: [log, ...]} for ONE employee's logs sorted by time (each log has
	`.time` and `.log_type`)."""
	groups: dict = {}
	open_in = None  # (work date, time) of the IN waiting for its OUT
	for log in logs:
		t = get_datetime(log.time)
		if log.log_type == "IN":
			day = getdate(t)
			open_in = (day, t)
		else:
			if open_in and t - open_in[1] <= timedelta(hours=max_hours):
				day = open_in[0]
			else:
				day = getdate(t)
			open_in = None
		groups.setdefault(day, []).append(log)
	return groups


def _fetch(employees, day, filters=None, fields=None):
	day = getdate(day)
	flt_ = [
		["employee", "in" if isinstance(employees, (list, tuple, set)) else "=", list(employees) if isinstance(employees, (list, tuple, set)) else employees],
		["time", ">=", str(add_days(day, -1)) + " 00:00:00"],
		["time", "<=", str(add_days(day, 1)) + " 23:59:59"],
		*(filters or []),
	]
	cols = ["employee", "log_type", "time", *(fields or [])]
	return frappe.get_all(
		"Employee Checkin", filters=flt_, fields=list(dict.fromkeys(cols)), order_by="employee asc, time asc", limit=0
	)


def logs_for_work_date(employee: str, day, filters=None, fields=None) -> list:
	"""The employee's check-ins that belong to work date `day`."""
	return group_by_work_date(_fetch(employee, day, filters, fields)).get(getdate(day), [])


def has_logs_for_work_date(employee: str, day) -> bool:
	return bool(logs_for_work_date(employee, day))


def team_logs_for_work_date(employees, day, filters=None, fields=None) -> list:
	"""Same for many employees at once (one query)."""
	rows = _fetch(list(employees), day, filters, fields)
	by_employee: dict = {}
	for r in rows:
		by_employee.setdefault(r.employee, []).append(r)
	out = []
	for logs in by_employee.values():
		out.extend(group_by_work_date(logs).get(getdate(day), []))
	return out


def open_in_before(employee: str, ts, exclude: str | None = None):
	"""The employee's latest log before `ts`, if it is an IN at most
	MAX_SHIFT_HOURS earlier (an open shift), else None."""
	ts = get_datetime(ts)
	filters = [
		["employee", "=", employee],
		["time", "<", ts],
		["time", ">=", ts - timedelta(hours=MAX_SHIFT_HOURS)],
	]
	if exclude:
		filters.append(["name", "!=", exclude])
	last = frappe.get_all(
		"Employee Checkin",
		filters=filters,
		fields=["name", "log_type", "time", "custom_project"],
		order_by="time desc",
		limit=1,
	)
	if last and last[0].log_type == "IN":
		return last[0]
	return None
