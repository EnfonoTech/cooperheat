# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, today

# Roles that see every approver; everyone else sees only their own technicians.
FULL_ACCESS_ROLES = {"System Manager", "HR Manager", "HR User"}

PENDING_STATES = (
	"Pending Level 1 Approval",
	"Pending Level 2 Approval",
	"Pending Level 3 Approval",
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 160},
		{"label": _("Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("Type"), "fieldname": "row_type", "fieldtype": "Data", "width": 130},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 170},
		{"label": _("No. of Technicians"), "fieldname": "technician_count", "fieldtype": "Int", "width": 140},
		{"label": _("Technician Names"), "fieldname": "technician_names", "fieldtype": "Data", "width": 280},
		{"label": _("Employee Number"), "fieldname": "employee_number", "fieldtype": "Data", "width": 130},
		{"label": _("Designation"), "fieldname": "designation", "fieldtype": "Link", "options": "Designation", "width": 130},
		{"label": _("Assigned Sites (Today)"), "fieldname": "sites", "fieldtype": "Data", "width": 220},
		{"label": _("Pending Approvals"), "fieldname": "pending_approvals", "fieldtype": "Int", "width": 130},
		{"label": _("Mobile"), "fieldname": "cell_number", "fieldtype": "Data", "width": 120},
	]


def get_data(filters):
	approvers = _get_approvers(filters)
	if not approvers:
		return []

	departments = list({a.department for a in approvers})
	# Anyone who is an approver in a department is not counted as a technician there.
	approvers_by_dept = {}
	for row in frappe.get_all(
		"Department Approval Matrix",
		filters={"parent": ["in", departments], "parentfield": "approval_matrix"},
		fields=["parent", "approver"],
	):
		approvers_by_dept.setdefault(row.parent, set()).add(row.approver)

	technicians_by_dept = {}
	for emp in frappe.get_all(
		"Employee",
		filters={"department": ["in", departments], "status": "Active"},
		fields=["name", "employee_name", "department", "employee_number", "designation", "cell_number"],
		order_by="employee_name asc",
	):
		if emp.name in approvers_by_dept.get(emp.department, set()):
			continue
		technicians_by_dept.setdefault(emp.department, []).append(emp)

	all_techs = [e.name for techs in technicians_by_dept.values() for e in techs]
	sites = _get_sites_today(all_techs)
	pending = _get_pending_counts([a.approver for a in approvers])

	data = []
	for a in approvers:
		techs = technicians_by_dept.get(a.department, [])
		data.append({
			"employee": a.approver,
			"employee_name": a.approver_name,
			"row_type": _("Level {0} Approver").format(a.approval_level),
			"department": a.department,
			"technician_count": len(techs),
			"technician_names": ", ".join(t.employee_name or t.name for t in techs),
			"pending_approvals": sum(pending.get((a.approver, t.name), 0) for t in techs),
			"indent": 0,
		})
		for t in techs:
			data.append({
				"employee": t.name,
				"employee_name": t.employee_name,
				"row_type": _("Technician"),
				"department": t.department,
				"employee_number": t.employee_number,
				"designation": t.designation,
				"sites": sites.get(t.name, ""),
				"pending_approvals": pending.get((a.approver, t.name), 0),
				"cell_number": t.cell_number,
				"indent": 1,
			})
	return data


def _get_approvers(filters):
	conditions = {"parentfield": "approval_matrix"}
	if filters.get("department"):
		conditions["parent"] = filters.department
	if filters.get("approval_level"):
		conditions["approval_level"] = cint(filters.approval_level)
	if filters.get("approver"):
		conditions["approver"] = filters.approver

	if not FULL_ACCESS_ROLES.intersection(frappe.get_roles()):
		own_employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
		if not own_employee:
			return []
		conditions["approver"] = own_employee

	rows = frappe.get_all(
		"Department Approval Matrix",
		filters=conditions,
		fields=["parent as department", "approval_level", "approver", "approver_name"],
		order_by="parent asc, approval_level asc",
	)
	for r in rows:
		if not r.approver_name:
			r.approver_name = frappe.db.get_value("Employee", r.approver, "employee_name")
	return rows


def _get_sites_today(employees):
	"""Projects on each employee's active Shift Assignment for today."""
	if not employees:
		return {}
	rows = frappe.db.sql("""
		SELECT sa.employee,
			GROUP_CONCAT(DISTINCT COALESCE(NULLIF(p.custom_project_code, ''), sap.project)
				ORDER BY sap.project SEPARATOR ', ') AS sites
		FROM `tabShift Assignment` sa
		JOIN `tabShift Assignment Project` sap
			ON sap.parent = sa.name AND sap.parentfield = 'custom_project_sites'
		LEFT JOIN `tabProject` p ON p.name = sap.project
		WHERE sa.docstatus = 1
		  AND sa.status = 'Active'
		  AND sa.employee IN %(employees)s
		  AND sa.start_date <= %(today)s
		  AND (sa.end_date IS NULL OR sa.end_date >= %(today)s)
		GROUP BY sa.employee
	""", {"employees": employees, "today": today()}, as_dict=True)
	return {r.employee: r.sites for r in rows}


def _get_pending_counts(approvers):
	"""Submitted Attendance currently waiting on each approver, per employee."""
	if not approvers:
		return {}
	rows = frappe.db.sql("""
		SELECT current_approver, employee, COUNT(*) AS cnt
		FROM `tabAttendance`
		WHERE docstatus = 1
		  AND workflow_state IN %(states)s
		  AND current_approver IN %(approvers)s
		GROUP BY current_approver, employee
	""", {"states": PENDING_STATES, "approvers": approvers}, as_dict=True)
	return {(r.current_approver, r.employee): r.cnt for r in rows}
