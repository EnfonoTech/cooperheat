# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Pay Batch"), "fieldname": "pay_batch", "fieldtype": "Data", "width": 150},
		{"label": _("Employee Code"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 130},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("Location"), "fieldname": "location", "fieldtype": "Data", "width": 100},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Data", "width": 120},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 80},
		{"label": _("Bank"), "fieldname": "bank", "fieldtype": "Data", "width": 100},
		{"label": _("Worked Days"), "fieldname": "worked_days", "fieldtype": "Int", "width": 90},
		{"label": _("Basic"), "fieldname": "basic", "fieldtype": "Currency", "width": 110},
		{"label": _("Living A"), "fieldname": "living_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Housing A"), "fieldname": "housing_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Transport A"), "fieldname": "transport_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Driving A"), "fieldname": "driving_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Merit Award A"), "fieldname": "merit_award", "fieldtype": "Currency", "width": 110},
		{"label": _("Service Allow A"), "fieldname": "service_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Education A"), "fieldname": "education_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Supervisor A"), "fieldname": "supervisor_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Aramco A"), "fieldname": "aramco_certification", "fieldtype": "Currency", "width": 110},
		{"label": _("RSO A"), "fieldname": "rso_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("RPP A"), "fieldname": "rpp_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Other A"), "fieldname": "other_allowance", "fieldtype": "Currency", "width": 110},
		{"label": _("Normal OT Hrs"), "fieldname": "normal_ot_hours", "fieldtype": "Float", "width": 100},
		{"label": _("Holiday OT Hrs"), "fieldname": "holiday_ot_hours", "fieldtype": "Float", "width": 100},
		{"label": _("Travel OT Hrs"), "fieldname": "travel_ot_hours", "fieldtype": "Float", "width": 100},
		{"label": _("Normal OT"), "fieldname": "normal_ot_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Holiday OT"), "fieldname": "holiday_ot_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Travel OT"), "fieldname": "travel_ot_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Total OT"), "fieldname": "total_ot_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Others"), "fieldname": "others", "fieldtype": "Currency", "width": 100},
		{"label": _("Bonus"), "fieldname": "bonus", "fieldtype": "Currency", "width": 100},
		{"label": _("Expenses"), "fieldname": "expenses", "fieldtype": "Currency", "width": 100},
		{"label": _("Air Fare"), "fieldname": "air_fare", "fieldtype": "Currency", "width": 100},
		{"label": _("Vacation Pay"), "fieldname": "vacation_pay", "fieldtype": "Currency", "width": 110},
		{"label": _("Gratuity"), "fieldname": "gratuity", "fieldtype": "Currency", "width": 100},
		{"label": _("Retention"), "fieldname": "retention", "fieldtype": "Currency", "width": 100},
		{"label": _("Total Earnings"), "fieldname": "total_earnings", "fieldtype": "Currency", "width": 130},
		{"label": _("GOSI"), "fieldname": "gosi", "fieldtype": "Currency", "width": 100},
		{"label": _("General Advance"), "fieldname": "general_advance", "fieldtype": "Currency", "width": 110},
		{"label": _("Housing Advance"), "fieldname": "housing_advance", "fieldtype": "Currency", "width": 110},
		{"label": _("Housing Ded"), "fieldname": "housing_deduction", "fieldtype": "Currency", "width": 110},
		{"label": _("Transport Ded"), "fieldname": "transport_deduction", "fieldtype": "Currency", "width": 110},
		{"label": _("Education Ded"), "fieldname": "education_deduction", "fieldtype": "Currency", "width": 110},
		{"label": _("Retention Ded"), "fieldname": "retention_deduction", "fieldtype": "Currency", "width": 110},
		{"label": _("Other Ded"), "fieldname": "other_deduction", "fieldtype": "Currency", "width": 110},
		{"label": _("Total Deduction"), "fieldname": "total_deduction", "fieldtype": "Currency", "width": 130},
		{"label": _("Net Payable"), "fieldname": "net_payable", "fieldtype": "Currency", "width": 130},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Small Text", "width": 200},
	]


def get_data(filters):
	conditions = ["docstatus < 2"]
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
			pay_batch, employee, employee_name, location, department, currency, bank, worked_days,
			basic, living_allowance, housing_allowance, transport_allowance, driving_allowance,
			merit_award, service_allowance, education_allowance, supervisor_allowance,
			aramco_certification, rso_allowance, rpp_allowance, other_allowance,
			normal_ot_hours, holiday_ot_hours, travel_ot_hours,
			normal_ot_amount, holiday_ot_amount, travel_ot_amount, total_ot_amount,
			others, bonus, expenses, air_fare, vacation_pay, gratuity, retention,
			total_earnings, gosi, general_advance, housing_advance, housing_deduction,
			transport_deduction, education_deduction, retention_deduction, other_deduction,
			total_deduction, net_payable, remarks
		FROM `tabPayroll Sheet`
		WHERE {where}
		ORDER BY pay_batch, employee
		""",
		values,
		as_dict=True,
	)
	return rows
