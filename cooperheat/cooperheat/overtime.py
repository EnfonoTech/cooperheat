"""Overtime hours from an attendance (client rules, 2026-10-13).

* Regular hours are 8 a day. Hours beyond 8 are overtime (x1.5).
* A working day never counts more than 16 hours.
* Friday and public holidays: every hour is holiday overtime (x2).
* Only Field Staff get overtime. Office Staff never do, whatever they work.
* The date is the date the shift STARTED (see work_day): a Thursday-night shift
  that runs into Friday morning is a normal Thursday shift; one that starts on
  Friday night is holiday overtime.
* Travel overtime is not used.

The hours are shown next to the payroll Excel import (Overtime Comparison
report). The Excel stays the payroll source until the client says otherwise.
"""

import frappe
from frappe.utils import flt

REGULAR_HOURS = 8.0
MAX_DAY_HOURS = 16.0

OFFICE, FIELD = "Office Staff", "Field Staff"


def split_hours(total, staff_category, is_holiday) -> dict:
	"""regular / ot / holiday_ot hours for one day, plus the basis in words."""
	total = max(0.0, flt(total))
	counted = min(total, MAX_DAY_HOURS)
	if staff_category == FIELD:
		if is_holiday:
			return {"regular": 0.0, "ot": 0.0, "holiday_ot": flt(counted, 2), "basis": "Field staff: weekend / public holiday"}
		regular = min(counted, REGULAR_HOURS)
		return {"regular": flt(regular, 2), "ot": flt(counted - regular, 2), "holiday_ot": 0.0, "basis": "Field staff"}
	if staff_category == OFFICE:
		return {"regular": flt(counted, 2), "ot": 0.0, "holiday_ot": 0.0, "basis": "Office staff: no overtime"}
	return {"regular": flt(counted, 2), "ot": 0.0, "holiday_ot": 0.0, "basis": "Staff category not set"}


def is_holiday_for(employee: str, day) -> bool:
	"""Weekend (Friday) or public holiday in the employee's holiday list."""
	from erpnext.setup.doctype.holiday_list.holiday_list import is_holiday

	holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
	if not holiday_list:
		company = frappe.db.get_value("Employee", employee, "company")
		holiday_list = frappe.db.get_value("Company", company, "default_holiday_list") if company else None
	return bool(holiday_list and is_holiday(holiday_list, day))


def overtime_values(attendance) -> dict:
	category = frappe.db.get_value("Employee", attendance.employee, "custom_staff_category")
	holiday = bool(category == FIELD and is_holiday_for(attendance.employee, attendance.attendance_date))
	out = split_hours(attendance.working_hours, category, holiday)
	return {
		"custom_regular_hours": out["regular"],
		"custom_ot_hours": out["ot"],
		"custom_holiday_ot_hours": out["holiday_ot"],
		"custom_ot_basis": out["basis"],
	}


def apply_to_doc(doc, method=None):
	"""Attendance validate: keep the overtime fields in step with working_hours."""
	if not doc.meta.has_field("custom_ot_hours") or not doc.get("employee") or not doc.get("attendance_date"):
		return
	doc.update(overtime_values(doc))


def persist(doc) -> None:
	"""After working_hours was written straight to the database (check-in edits,
	approvals): store the overtime fields the same way."""
	if not doc.meta.has_field("custom_ot_hours"):
		return
	frappe.db.set_value("Attendance", doc.name, overtime_values(doc), update_modified=False)
