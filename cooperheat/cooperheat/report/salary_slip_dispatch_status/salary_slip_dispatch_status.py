# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Per-employee view of a Payroll Import: salary slip state and email state.

The status columns are read live from Salary Slip and the Email Queue (through the same
``compute_rows`` the Payroll Import form uses), so this report is right even if nobody
has opened the import since the mail went out.
"""

import frappe
from frappe import _
from frappe.utils import cint

from cooperheat.cooperheat.doctype.payroll_import.slip_dispatch import compute_rows, import_rows

NEEDS_ATTENTION_SLIP = ("Not Created", "Sheet Draft", "Draft", "Cancelled", "Sheet Cancelled", "Not Imported")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Payroll Import", "read", throw=True)

	name = _pick_import(filters)
	if not name:
		return get_columns(), [], _("No completed Payroll Import matches these filters."), None, []

	rows = import_rows(name)
	states, ctx = compute_rows(rows)

	data = []
	for r in rows:
		st = states[r.name]
		sheet = ctx.sheets.get(r.payroll_sheet) if r.payroll_sheet else None
		slip = ctx.row_slip.get(r.name)
		emp = ctx.employees.get(r.employee or (sheet.employee if sheet else None)) or {}

		slip_status = st["slip_status"] or ("Not Imported" if not r.payroll_sheet else "")
		email_status = st["email_status"]
		if not email_status and slip_status == "Submitted":
			email_status = "Not Sent"

		data.append({
			"payroll_import": name,
			"employee": r.employee or (sheet.employee if sheet else r.code),
			"employee_name": r.employee_name or emp.get("employee_name"),
			"department": emp.get("department"),
			"payroll_sheet": r.payroll_sheet,
			"net_payable": sheet.net_payable if sheet else None,
			"salary_slip": st["salary_slip"],
			"net_pay": slip.net_pay if slip else None,
			"slip_status": slip_status,
			"email_to": st["email_to"],
			"email_status": email_status,
			"email_sent_on": st["email_sent_on"],
			"reason": st["email_error"] or st["slip_error"] or (r.message if not r.payroll_sheet else ""),
		})

	data = _apply_filters(data, filters)
	return get_columns(), data, None, None, _summary(data)


def _pick_import(filters):
	if filters.payroll_import:
		return filters.payroll_import if frappe.db.exists("Payroll Import", filters.payroll_import) else None
	conditions = {"status": "Completed"}
	for key in ("company", "month", "year"):
		if filters.get(key):
			conditions[key] = filters.get(key)
	return frappe.db.get_value("Payroll Import", conditions, "name", order_by="creation desc")


def _apply_filters(data, filters):
	if filters.slip_status:
		data = [d for d in data if d["slip_status"] == filters.slip_status]
	if filters.email_status:
		data = [d for d in data if d["email_status"] == filters.email_status]
	if cint(filters.needs_attention):
		data = [
			d for d in data
			if d["email_status"] in ("Failed", "Skipped") or d["slip_status"] in NEEDS_ATTENTION_SLIP
		]
	return data


def _summary(data):
	def count(key, *values):
		return sum(1 for d in data if d[key] in values)

	return [
		{"value": len(data), "label": _("Employees"), "datatype": "Int"},
		{"value": count("slip_status", "Submitted"), "label": _("Slips Submitted"), "datatype": "Int", "indicator": "Green"},
		{"value": count("slip_status", "Draft"), "label": _("Slips in Draft"), "datatype": "Int", "indicator": "Orange"},
		{"value": count("email_status", "Sent"), "label": _("Emails Sent"), "datatype": "Int", "indicator": "Green"},
		{"value": count("email_status", "Queued"), "label": _("Queued"), "datatype": "Int", "indicator": "Blue"},
		{"value": count("email_status", "Failed"), "label": _("Failed"), "datatype": "Int", "indicator": "Red"},
		{"value": count("email_status", "Skipped"), "label": _("No Email Address"), "datatype": "Int", "indicator": "Orange"},
		{"value": count("email_status", "Not Sent"), "label": _("Not Sent Yet"), "datatype": "Int", "indicator": "Gray"},
	]


def get_columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 110},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 190},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 150},
		{"label": _("Payroll Sheet"), "fieldname": "payroll_sheet", "fieldtype": "Link", "options": "Payroll Sheet", "width": 120},
		{"label": _("Net Payable"), "fieldname": "net_payable", "fieldtype": "Currency", "width": 110},
		{"label": _("Salary Slip"), "fieldname": "salary_slip", "fieldtype": "Link", "options": "Salary Slip", "width": 170},
		{"label": _("Slip Status"), "fieldname": "slip_status", "fieldtype": "Data", "width": 105},
		{"label": _("Email To"), "fieldname": "email_to", "fieldtype": "Data", "width": 230},
		{"label": _("Email Status"), "fieldname": "email_status", "fieldtype": "Data", "width": 100},
		{"label": _("Sent On"), "fieldname": "email_sent_on", "fieldtype": "Datetime", "width": 150},
		{"label": _("Reason / Error"), "fieldname": "reason", "fieldtype": "Data", "width": 320},
		{"label": _("Payroll Import"), "fieldname": "payroll_import", "fieldtype": "Link", "options": "Payroll Import", "width": 140},
	]
