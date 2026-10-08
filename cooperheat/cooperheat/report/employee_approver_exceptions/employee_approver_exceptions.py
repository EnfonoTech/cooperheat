# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Active employees whose approval chain is incomplete.

One row per employee per problem, so HR can fix them in bulk (Data Import
with ``reports_to`` / ``department`` updates)."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 190},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 190},
		{"label": _("Reports To"), "fieldname": "reports_to", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Issue"), "fieldname": "issue", "fieldtype": "Data", "width": 280},
	]


def get_data(filters):
	emp_filters = {"status": "Active"}
	if filters.get("department"):
		emp_filters["department"] = filters.department
	employees = frappe.get_all(
		"Employee",
		filters=emp_filters,
		fields=["name", "employee_name", "department", "reports_to", "user_id"],
		order_by="department asc, employee_name asc",
	)

	# employee -> Level 1 approver, inherited up the department tree (and by location)
	from cooperheat.cooperheat.org import l1_approver

	l1 = {e.name: l1_approver(e.department, e.name) for e in employees if e.department}
	approver_users = {
		e.name: e.user_id
		for e in frappe.get_all("Employee", filters={"name": ["in", list(set(filter(None, l1.values()))) or [""]]}, fields=["name", "user_id"])
	}

	out = []
	want = filters.get("issue")
	for e in employees:
		issues = []
		if not e.reports_to:
			issues.append(_("No Reports To"))
		if not e.user_id:
			issues.append(_("No User account"))
		if not e.department:
			issues.append(_("No Department"))
		else:
			approver = l1.get(e.name)
			if not approver:
				issues.append(_("Department has no Level 1 approver"))
			elif not approver_users.get(approver):
				issues.append(_("Level 1 approver has no User account"))
		for issue in issues:
			if want and issue != _(want):
				continue
			out.append(
				{
					"employee": e.name,
					"employee_name": e.employee_name,
					"department": e.department,
					"reports_to": e.reports_to,
					"issue": issue,
				}
			)
	return out
