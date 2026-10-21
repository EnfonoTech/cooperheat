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
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 160,
		},
		{"label": _("Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("Type"), "fieldname": "row_type", "fieldtype": "Data", "width": 130},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": 170,
		},
		{"label": _("No. of Technicians"), "fieldname": "technician_count", "fieldtype": "Int", "width": 140},
		{"label": _("Technician Names"), "fieldname": "technician_names", "fieldtype": "Data", "width": 280},
		{"label": _("Employee Number"), "fieldname": "employee_number", "fieldtype": "Data", "width": 130},
		{
			"label": _("Designation"),
			"fieldname": "designation",
			"fieldtype": "Link",
			"options": "Designation",
			"width": 130,
		},
		{"label": _("Assigned Sites (Today)"), "fieldname": "sites", "fieldtype": "Data", "width": 220},
		{"label": _("Pending Approvals"), "fieldname": "pending_approvals", "fieldtype": "Int", "width": 130},
		{"label": _("Mobile"), "fieldname": "cell_number", "fieldtype": "Data", "width": 120},
	]


def get_data(filters):
	"""One block per approver and level: Level 1 = people who report to them
	(Direct / Immediate Reporting), Level 2 = people naming them as Secondary Reporting."""
	people = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=[
			"name",
			"employee_name",
			"department",
			"employee_number",
			"designation",
			"cell_number",
			"reports_to",
			"custom_secondary_reporting",
		],
		order_by="employee_name asc",
	)
	if filters.get("department"):
		people = [p for p in people if p.department == filters.department]

	level_field = {1: "reports_to", 2: "custom_secondary_reporting"}
	wanted_level = cint(filters.get("approval_level"))
	blocks: dict[tuple[str, int], list] = {}
	for person in people:
		for level, field in level_field.items():
			approver = person.get(field)
			if approver and approver != person.name and (not wanted_level or wanted_level == level):
				blocks.setdefault((approver, level), []).append(person)

	if filters.get("approver"):
		blocks = {k: v for k, v in blocks.items() if k[0] == filters.approver}
	if not FULL_ACCESS_ROLES.intersection(frappe.get_roles()):
		own_employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
		blocks = {k: v for k, v in blocks.items() if own_employee and k[0] == own_employee}
	if not blocks:
		return []

	approver_info = {
		e.name: e
		for e in frappe.get_all(
			"Employee",
			filters={"name": ["in", sorted({k[0] for k in blocks})]},
			fields=["name", "employee_name", "department"],
		)
	}
	all_techs = sorted({t.name for techs in blocks.values() for t in techs})
	sites = _get_sites_today(all_techs)
	pending = _get_pending_counts(sorted({k[0] for k in blocks}))

	data = []
	for (approver, level), techs in sorted(blocks.items(), key=lambda kv: (kv[0][1], kv[0][0])):
		info = approver_info.get(approver)
		data.append(
			{
				"employee": approver,
				"employee_name": info.employee_name if info else approver,
				"row_type": _("Level {0} Approver").format(level),
				"department": info.department if info else None,
				"technician_count": len(techs),
				"technician_names": ", ".join(t.employee_name or t.name for t in techs),
				"pending_approvals": sum(pending.get((approver, t.name), 0) for t in techs),
				"indent": 0,
			}
		)
		for t in techs:
			data.append(
				{
					"employee": t.name,
					"employee_name": t.employee_name,
					"row_type": _("Technician"),
					"department": t.department,
					"employee_number": t.employee_number,
					"designation": t.designation,
					"sites": sites.get(t.name, ""),
					"pending_approvals": pending.get((approver, t.name), 0),
					"cell_number": t.cell_number,
					"indent": 1,
				}
			)
	return data


def _get_sites_today(employees):
	"""Projects on each employee's active Shift Assignment for today."""
	if not employees:
		return {}
	rows = frappe.db.sql(
		"""
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
	""",
		{"employees": employees, "today": today()},
		as_dict=True,
	)
	return {r.employee: r.sites for r in rows}


def _get_pending_counts(approvers):
	"""Submitted Attendance currently waiting on each approver, per employee."""
	if not approvers:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT current_approver, employee, COUNT(*) AS cnt
		FROM `tabAttendance`
		WHERE docstatus = 1
		  AND workflow_state IN %(states)s
		  AND current_approver IN %(approvers)s
		GROUP BY current_approver, employee
	""",
		{"states": PENDING_STATES, "approvers": approvers},
		as_dict=True,
	)
	return {(r.current_approver, r.employee): r.cnt for r in rows}
