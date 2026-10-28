"""Shift Assignments from inside the Employee form.

HR picks a shift and a date range on the Employee; this creates and submits the
Shift Assignment. HRMS itself refuses overlapping assignments for the same
employee and shift.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

ASSIGN_ROLES = ("HR Manager", "HR User", "System Manager")


def _check_access(employee):
	if not set(ASSIGN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only HR can assign shifts."), frappe.PermissionError)
	frappe.has_permission("Employee", "write", doc=employee, throw=True)


@frappe.whitelist()
def assign_shift(employee, shift_type, start_date, end_date=None, project=None, cost_center=None):
	"""Create and submit an active Shift Assignment. Open-ended when `end_date` is empty."""
	_check_access(employee)
	start = getdate(start_date)
	end = getdate(end_date) if end_date else None
	if end and end < start:
		frappe.throw(_("End Date cannot be before Start Date."))
	if not frappe.db.exists("Shift Type", shift_type):
		frappe.throw(_("Shift Type does not exist: ") + frappe.safe_decode(shift_type))
	if frappe.db.get_value("Employee", employee, "status") != "Active":
		frappe.throw(_("Employee is not Active: ") + employee)

	doc = frappe.get_doc(
		{
			"doctype": "Shift Assignment",
			"employee": employee,
			"shift_type": shift_type,
			"start_date": start,
			"end_date": end,
			"status": "Active",
		}
	)
	meta = frappe.get_meta("Shift Assignment")
	if project and meta.has_field("custom_project_"):
		doc.custom_project_ = project
	if cost_center and meta.has_field("custom_cost_center"):
		doc.custom_cost_center = cost_center
	doc.insert()
	doc.submit()
	return doc.name


@frappe.whitelist()
def get_employee_shifts(employee, limit=10):
	"""Recent Shift Assignments of an employee, newest first, for the Employee form."""
	frappe.has_permission("Employee", "read", doc=employee, throw=True)
	return frappe.get_all(
		"Shift Assignment",
		filters={"employee": employee, "docstatus": 1},
		fields=["name", "shift_type", "start_date", "end_date", "status"],
		order_by="start_date desc",
		limit=min(cint(limit) or 10, 50),
	)
