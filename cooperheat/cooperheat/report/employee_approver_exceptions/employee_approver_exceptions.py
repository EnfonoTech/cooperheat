# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Active employees whose approval chain is incomplete.

Approvers come from the employee's own reporting line: Direct / Immediate Reporting
(Reports To), Secondary Reporting (field staff) and the Payroll Approver in Pay Sheet
Settings. One row per employee per problem, so HR can fix them in bulk (Data Import
with ``reports_to`` / ``custom_secondary_reporting`` updates)."""

import frappe
from frappe import _

from cooperheat.cooperheat import org


def execute(filters=None):
	filters = frappe._dict(filters or {})
	message = None
	if not org.payroll_approver():
		message = _(
			"No Payroll Approver is set in Pay Sheet Settings: the final approval step passes by itself."
		)
	return get_columns(), get_data(filters), message


def get_columns():
	return [
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 140,
		},
		{"label": _("Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 190},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": 190,
		},
		{"label": _("Staff Category"), "fieldname": "staff_category", "fieldtype": "Data", "width": 120},
		{
			"label": _("Direct / Immediate Reporting"),
			"fieldname": "reports_to",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 170,
		},
		{
			"label": _("Secondary Reporting"),
			"fieldname": "secondary",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 150,
		},
		{"label": _("Issue"), "fieldname": "issue", "fieldtype": "Data", "width": 280},
	]


def get_data(filters):
	emp_filters = {"status": "Active"}
	if filters.get("department"):
		emp_filters["department"] = filters.department
	employees = frappe.get_all(
		"Employee",
		filters=emp_filters,
		fields=[
			"name",
			"employee_name",
			"department",
			"reports_to",
			"custom_secondary_reporting",
			"custom_staff_category",
			"user_id",
		],
		order_by="department asc, employee_name asc",
	)
	reporting = {e.reports_to for e in employees if e.reports_to} | {
		e.custom_secondary_reporting for e in employees if e.custom_secondary_reporting
	}
	approver_users = {
		e.name: e.user_id
		for e in frappe.get_all(
			"Employee", filters={"name": ["in", list(reporting) or [""]]}, fields=["name", "user_id"]
		)
	}

	out = []
	want = filters.get("issue")
	for e in employees:
		issues = []
		if not e.reports_to:
			issues.append(_("No Direct / Immediate Reporting"))
		elif not approver_users.get(e.reports_to):
			issues.append(_("Direct / Immediate Reporting person has no User account"))
		if e.custom_staff_category == org.FIELD_STAFF:
			if not e.custom_secondary_reporting:
				issues.append(_("Field staff without Secondary Reporting"))
			elif not approver_users.get(e.custom_secondary_reporting):
				issues.append(_("Secondary Reporting person has no User account"))
		if not e.custom_staff_category:
			issues.append(_("No Staff Category"))
		if not e.user_id:
			issues.append(_("No User account"))
		for issue in issues:
			if want and issue != _(want):
				continue
			out.append(
				{
					"employee": e.name,
					"employee_name": e.employee_name,
					"department": e.department,
					"staff_category": e.custom_staff_category,
					"reports_to": e.reports_to,
					"secondary": e.custom_secondary_reporting,
					"issue": issue,
				}
			)
	return out
