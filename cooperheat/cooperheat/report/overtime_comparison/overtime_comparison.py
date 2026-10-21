"""Overtime from check-ins (system) next to the payroll Excel import.

The Excel import stays the payroll source for now; this report shows where the
system's hours (from approved check-ins, with the 8 h / 16 h / weekend rules)
differ, so the two can be reconciled until everyone uses the app properly.
"""

import calendar

import frappe
from frappe import _
from frappe.utils import flt

MONTHS = [
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
]


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
			"width": 110,
		},
		{"label": _("Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 170},
		{"label": _("Staff Category"), "fieldname": "staff_category", "fieldtype": "Data", "width": 110},
		{"label": _("Days"), "fieldname": "days", "fieldtype": "Int", "width": 60},
		{
			"label": _("Hours Worked"),
			"fieldname": "hours",
			"fieldtype": "Float",
			"precision": 2,
			"width": 100,
		},
		{
			"label": _("System OT (x1.5)"),
			"fieldname": "sys_ot",
			"fieldtype": "Float",
			"precision": 2,
			"width": 110,
		},
		{
			"label": _("System Holiday OT (x2)"),
			"fieldname": "sys_hot",
			"fieldtype": "Float",
			"precision": 2,
			"width": 130,
		},
		{"label": _("Excel OT"), "fieldname": "xl_ot", "fieldtype": "Float", "precision": 2, "width": 90},
		{"label": _("Excel HOT"), "fieldname": "xl_hot", "fieldtype": "Float", "precision": 2, "width": 90},
		{
			"label": _("OT Difference"),
			"fieldname": "diff_ot",
			"fieldtype": "Float",
			"precision": 2,
			"width": 110,
		},
		{
			"label": _("HOT Difference"),
			"fieldname": "diff_hot",
			"fieldtype": "Float",
			"precision": 2,
			"width": 110,
		},
	]


def get_data(filters):
	if not filters.get("year") or filters.get("month") not in MONTHS:
		return []
	month_no = MONTHS.index(filters.month) + 1
	last = calendar.monthrange(int(filters.year), month_no)[1]
	start, end = f"{int(filters.year)}-{month_no:02d}-01", f"{int(filters.year)}-{month_no:02d}-{last:02d}"

	Attendance = frappe.qb.DocType("Attendance")
	Employee = frappe.qb.DocType("Employee")
	query = (
		frappe.qb.from_(Attendance)
		.join(Employee)
		.on(Employee.name == Attendance.employee)
		.select(
			Attendance.employee,
			Attendance.employee_name,
			Employee.custom_staff_category.as_("staff_category"),
			Attendance.working_hours,
			Attendance.custom_ot_hours,
			Attendance.custom_holiday_ot_hours,
		)
		.where(
			(Attendance.docstatus == 1)
			& (Attendance.attendance_date >= start)
			& (Attendance.attendance_date <= end)
			& (Attendance.workflow_state != "Rejected")
		)
	)
	if filters.get("staff_category"):
		query = query.where(Employee.custom_staff_category == filters.staff_category)
	if filters.get("department"):
		query = query.where(Attendance.department == filters.department)

	rows = {}
	for r in query.run(as_dict=True):
		row = rows.setdefault(
			r.employee,
			{
				"employee": r.employee,
				"employee_name": r.employee_name,
				"staff_category": r.staff_category or _("Not set"),
				"days": 0,
				"hours": 0.0,
				"sys_ot": 0.0,
				"sys_hot": 0.0,
				"xl_ot": 0.0,
				"xl_hot": 0.0,
			},
		)
		row["days"] += 1
		row["hours"] += flt(r.working_hours)
		row["sys_ot"] += flt(r.custom_ot_hours)
		row["sys_hot"] += flt(r.custom_holiday_ot_hours)

	if rows:
		for s in frappe.get_all(
			"Payroll Sheet",
			filters={
				"employee": ["in", list(rows)],
				"year": int(filters.year),
				"month": filters.month,
				"docstatus": ["<", 2],
			},
			fields=["employee", "normal_ot_hours", "holiday_ot_hours"],
		):
			rows[s.employee]["xl_ot"] += flt(s.normal_ot_hours)
			rows[s.employee]["xl_hot"] += flt(s.holiday_ot_hours)

	out = []
	for row in sorted(rows.values(), key=lambda r: r["employee_name"] or ""):
		for k in ("hours", "sys_ot", "sys_hot", "xl_ot", "xl_hot"):
			row[k] = flt(row[k], 2)
		row["diff_ot"] = flt(row["sys_ot"] - row["xl_ot"], 2)
		row["diff_hot"] = flt(row["sys_hot"] - row["xl_hot"], 2)
		if filters.get("only_differences") and not (row["diff_ot"] or row["diff_hot"]):
			continue
		out.append(row)
	return out
