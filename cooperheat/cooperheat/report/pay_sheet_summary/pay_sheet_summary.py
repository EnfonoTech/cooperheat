# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet import (
	EARNING_FIELDS,
	SPECIAL_EARNINGS,
)


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Pay Batch"), "fieldname": "pay_batch", "fieldtype": "Data", "width": 150},
		{"label": _("Code"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 120},
		{"label": _("Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("Designation"), "fieldname": "designation", "fieldtype": "Link", "options": "Designation", "width": 150},
		{"label": _("Division"), "fieldname": "division", "fieldtype": "Data", "width": 120},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Data", "width": 120},
		{"label": _("Worked Days"), "fieldname": "worked_days", "fieldtype": "Int", "width": 90},
		{"label": _("Basic"), "fieldname": "basic", "fieldtype": "Currency", "width": 110},
		{"label": _("Housing A"), "fieldname": "housing_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Transport A"), "fieldname": "transport_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Living A"), "fieldname": "living_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Service A"), "fieldname": "service_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Driving A"), "fieldname": "driving_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Merit Award"), "fieldname": "merit_award", "fieldtype": "Currency", "width": 110},
		{"label": _("Aramco Cert"), "fieldname": "aramco_certification", "fieldtype": "Currency", "width": 110},
		{"label": _("Supervisor A"), "fieldname": "supervisor_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Education A"), "fieldname": "education_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("RSO A"), "fieldname": "rso_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("RPP A"), "fieldname": "rpp_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Other A"), "fieldname": "other_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Normal OT"), "fieldname": "normal_ot_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Travel OT"), "fieldname": "travel_ot_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Holiday OT"), "fieldname": "holiday_ot_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Monthly Additions"), "fieldname": "monthly_additions", "fieldtype": "Currency", "width": 130},
		{"label": _("Monthly Deductions"), "fieldname": "total_deduction", "fieldtype": "Currency", "width": 130},
		{"label": _("Net"), "fieldname": "net_payable", "fieldtype": "Currency", "width": 130},
	]


def get_data(filters):
	conditions = ["docstatus = 1"] if not filters.get("include_draft") else ["docstatus < 2"]
	values = {}
	for f in ("company", "month", "year", "pay_batch", "status", "employee"):
		if filters.get(f):
			conditions.append(f"{f} = %({f})s")
			values[f] = filters[f]
	if filters.get("from_date"):
		conditions.append("posting_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("posting_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	where = " AND ".join(conditions)
	rows = frappe.db.sql(
		f"""
		SELECT
			pay_batch, employee, employee_name, designation, division, department, worked_days,
			basic, housing_allowance, transport_allowance, living_allowance,
			service_allowance, driving_allowance, merit_award, aramco_certification,
			supervisor_allowance, education_allowance, rso_allowance, rpp_allowance,
			other_allowance,
			normal_ot_amount, travel_ot_amount, holiday_ot_amount,
			others, bonus, expenses, air_fare, vacation_pay, gratuity, retention,
			total_deduction, net_payable
		FROM `tabPayroll Sheet`
		WHERE {where}
		ORDER BY pay_batch, employee
		""",
		values,
		as_dict=True,
	)

	# Monthly Additions = sum of allowances + special earnings + OT (excluding basic)
	addition_fields = [f for f in EARNING_FIELDS if f != "basic"] + SPECIAL_EARNINGS
	for r in rows:
		additions = sum(flt(r.get(f)) for f in addition_fields)
		additions += flt(r.get("normal_ot_amount")) + flt(r.get("travel_ot_amount")) + flt(r.get("holiday_ot_amount"))
		r["monthly_additions"] = additions
	return rows
