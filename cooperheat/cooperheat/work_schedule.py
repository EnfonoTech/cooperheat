"""Employee Work Schedule: Office Staff / Field Staff and the default shift.

Staff Category sets the employee's Holiday List to that year's calendar
(Office Staff = Friday + Saturday off, Field Staff = Friday off, both with the
Saudi public holidays; see setup_calendars). An empty Default Shift gets the
matching Office Shift / Field Shift. Picking Office Shift or Field Shift with no
category fills the category.

A daily job moves everyone onto the new year's calendar on 1 January.
"""

import frappe
from frappe.utils import getdate, nowdate

from cooperheat.cooperheat.setup_calendars import holiday_list_name

OFFICE, FIELD = "Office Staff", "Field Staff"
KIND = {OFFICE: "Office", FIELD: "Field"}
SHIFT_FOR = {OFFICE: "Office Shift", FIELD: "Field Shift"}
CATEGORY_FOR_SHIFT = {v: k for k, v in SHIFT_FOR.items()}


def calendar_for(category, date=None):
	if category not in KIND:
		return None
	name = holiday_list_name(KIND[category], getdate(date or nowdate()).year)
	return name if frappe.db.exists("Holiday List", name) else None


def sync_work_schedule(doc):
	category = doc.get("custom_staff_category")
	if not category and doc.get("default_shift") in CATEGORY_FOR_SHIFT:
		category = doc.custom_staff_category = CATEGORY_FOR_SHIFT[doc.default_shift]
	if not category:
		return
	calendar = calendar_for(category)
	if calendar:
		doc.holiday_list = calendar
	shift = SHIFT_FOR[category]
	if not doc.get("default_shift") and frappe.db.exists("Shift Type", shift):
		doc.default_shift = shift


def roll_over_calendars():
	"""Daily: employees with a Staff Category follow the current year's calendar."""
	for category in KIND:
		calendar = calendar_for(category)
		if not calendar:
			continue
		names = frappe.get_all(
			"Employee",
			filters={"custom_staff_category": category, "holiday_list": ["!=", calendar], "status": "Active"},
			pluck="name",
		)
		for name in names:
			frappe.db.set_value("Employee", name, "holiday_list", calendar, update_modified=False)


def place_default_shift_field():
	"""Show HRMS's Default Shift inside the Work Schedule section (after_migrate)."""
	name = "Employee-default_shift"
	if frappe.db.exists("Custom Field", name) and frappe.db.exists("Custom Field", "Employee-custom_staff_category"):
		if frappe.db.get_value("Custom Field", name, "insert_after") != "custom_staff_category":
			frappe.db.set_value("Custom Field", name, "insert_after", "custom_staff_category")
			frappe.clear_cache(doctype="Employee")
