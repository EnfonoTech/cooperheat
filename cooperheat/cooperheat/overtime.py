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
			return {
				"regular": 0.0,
				"ot": 0.0,
				"holiday_ot": flt(counted, 2),
				"basis": "Field staff: weekend / public holiday",
			}
		regular = min(counted, REGULAR_HOURS)
		return {
			"regular": flt(regular, 2),
			"ot": flt(counted - regular, 2),
			"holiday_ot": 0.0,
			"basis": "Field staff",
		}
	if staff_category == OFFICE:
		return {
			"regular": flt(counted, 2),
			"ot": 0.0,
			"holiday_ot": 0.0,
			"basis": "Office staff: no overtime",
		}
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


_OT_NUMBERS = ("custom_regular_hours", "custom_ot_hours", "custom_holiday_ot_hours")


def recompute_range(from_date, to_date, employee=None, dry_run=True) -> dict:
	"""Re-derive regular / overtime hours of submitted Attendance in a date range.

	Needed when the Staff Category of employees is set (or corrected) after their
	attendance was generated: the hours were stored while the category was empty.
	``dry_run`` only counts; otherwise the stored values are updated in place."""
	filters = {"docstatus": 1, "attendance_date": ["between", [from_date, to_date]]}
	if employee:
		filters["employee"] = employee
	rows = frappe.get_all(
		"Attendance",
		filters=filters,
		fields=["name", "employee", "attendance_date", "working_hours"],
		limit=0,
	)
	changed, sample = 0, []
	for row in rows:
		new = overtime_values(row)
		old = frappe.db.get_value("Attendance", row.name, list(new), as_dict=True) or {}
		if (
			all(flt(old.get(k)) == flt(new[k]) for k in _OT_NUMBERS)
			and old.get("custom_ot_basis") == new["custom_ot_basis"]
		):
			continue
		changed += 1
		if len(sample) < 10:
			sample.append(
				{
					"attendance": row.name,
					"employee": row.employee,
					"date": str(row.attendance_date),
					"hours": flt(row.working_hours, 2),
					"ot_before": flt(old.get("custom_ot_hours"), 2),
					"ot_after": new["custom_ot_hours"],
					"basis": new["custom_ot_basis"],
				}
			)
		if not dry_run:
			frappe.db.set_value("Attendance", row.name, new, update_modified=False)
	return {"checked": len(rows), "changed": changed, "dry_run": bool(dry_run), "sample": sample}


@frappe.whitelist()
def recompute_overtime(from_date, to_date, employee=None, dry_run=1):
	"""HR button: recalculate overtime hours on stored attendance (dry run by default)."""
	from frappe.utils import cint

	frappe.only_for(("System Manager", "HR Manager"))
	return recompute_range(from_date, to_date, employee or None, dry_run=bool(cint(dry_run)))
