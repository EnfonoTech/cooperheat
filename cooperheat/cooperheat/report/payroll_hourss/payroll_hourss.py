# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 150},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("Date"), "fieldname": "att_date", "fieldtype": "Date", "width": 100},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 150},
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 150},
		{"label": _("Project Code"), "fieldname": "project_code", "fieldtype": "Data", "width": 120},
		{"label": _("Check In"), "fieldname": "in_time", "fieldtype": "Datetime", "width": 150},
		{"label": _("Check Out"), "fieldname": "out_time", "fieldtype": "Datetime", "width": 150},
		{"label": _("Normal Hours"), "fieldname": "normal_hours", "fieldtype": "Float", "precision": 2, "width": 110},
		{"label": _("OT Hours"), "fieldname": "ot_hours", "fieldtype": "Float", "precision": 2, "width": 100},
		{"label": _("HOT Hours"), "fieldname": "hot_hours", "fieldtype": "Float", "precision": 2, "width": 100},
		{"label": _("Total Hours"), "fieldname": "total_hours", "fieldtype": "Float", "precision": 2, "width": 100},
		{"label": _("Max OT/Day"), "fieldname": "max_ot_day", "fieldtype": "Float", "precision": 2, "width": 110},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "HTML", "width": 130},
	]


def _get_access_scope():
	"""Return (scope, employee_or_depts) based on the current user's role.

	Returns:
	  ("all",   None)              — HR Manager, sees everything
	  ("depts", [dept1, dept2, …]) — user is a dept approver, sees those depts
	  ("self",  employee_id)       — everyone else, sees only their own records
	"""
	if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles(frappe.session.user):
		return "all", None

	linked_emp = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
	if linked_emp:
		approved_depts = frappe.get_all(
			"Department Approval Matrix",
			filters={"approver": linked_emp},
			pluck="parent",
		)
		if approved_depts:
			return "depts", list(set(approved_depts))

	if linked_emp:
		return "self", linked_emp

	# No linked employee and no special role — return nothing
	return "self", None


def get_data(filters):
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	employee = filters.get("employee") or None
	department = filters.get("department") or None

	scope, scope_val = _get_access_scope()

	# Enforce access scope on top of any explicit filters
	if scope == "self":
		if not scope_val:
			return []
		employee = scope_val  # override — can only see own records
	elif scope == "depts":
		if department and department not in scope_val:
			return []  # requested dept outside their approved set
		if not department:
			# restrict to approved departments
			pass  # handled via dept_scope_cond below

	# Build optional filter snippets so missing keys never reach the SQL engine
	emp_checkin_cond = "AND ec.employee = %(employee)s" if employee else ""
	emp_att_cond = "AND att.employee = %(employee)s" if employee else ""
	dept_cond = "AND emp.department = %(department)s" if department else ""

	# Department scope restriction for approvers
	if scope == "depts" and not department:
		placeholders = ", ".join([f"%(scope_dept_{i})s" for i in range(len(scope_val))])
		dept_scope_cond = f"AND emp.department IN ({placeholders})"
	else:
		dept_scope_cond = ""

	values = {"from_date": from_date, "to_date": to_date}
	if employee:
		values["employee"] = employee
	if department:
		values["department"] = department
	if scope == "depts" and not department:
		for i, d in enumerate(scope_val):
			values[f"scope_dept_{i}"] = d

	sql = f"""
		SELECT
			base.employee,
			emp.employee_name,
			base.att_date,
			emp.department,
			base.project,
			p.custom_project_code  AS project_code,
			base.in_time,
			base.out_time,
			ROUND(LEAST(base.working_hours,
						COALESCE(NULLIF(p.custom_regular_working_hours__day, 0), base.working_hours)), 2)
				AS normal_hours,
			CASE
				WHEN hol.holiday_date IS NOT NULL THEN 0
				ELSE ROUND(GREATEST(base.working_hours
							- COALESCE(NULLIF(p.custom_regular_working_hours__day, 0), base.working_hours), 0), 2)
			END AS ot_hours,
			CASE
				WHEN hol.holiday_date IS NOT NULL
				THEN ROUND(GREATEST(base.working_hours
							- COALESCE(NULLIF(p.custom_regular_working_hours__day, 0), base.working_hours), 0), 2)
				ELSE 0
			END AS hot_hours,
			ROUND(base.working_hours, 2) AS total_hours,
			ROUND(p.custom_max_overtime_hours__day, 2) AS max_ot_day,
			CASE
				WHEN COALESCE(st.working_hours_threshold_for_half_day, 0) > 0
					 AND base.working_hours > 0
					 AND base.working_hours < st.working_hours_threshold_for_half_day
					THEN '<span class="indicator-pill orange">Half Day</span>'
				WHEN base.status = 'Present'        THEN '<span class="indicator-pill green">Present</span>'
				WHEN base.status = 'Absent'         THEN '<span class="indicator-pill red">Absent</span>'
				WHEN base.status = 'Half Day'       THEN '<span class="indicator-pill orange">Half Day</span>'
				WHEN base.status = 'On Leave'       THEN '<span class="indicator-pill blue">On Leave</span>'
				WHEN base.status = 'Work From Home' THEN '<span class="indicator-pill blue">Work From Home</span>'
				ELSE base.status
			END AS status
		FROM (
			SELECT
				ec.employee,
				DATE(ec.time)                                        AS att_date,
				ec.custom_project                                    AS project,
				MIN(CASE WHEN ec.log_type = 'IN'  THEN ec.time END) AS in_time,
				MAX(CASE WHEN ec.log_type = 'OUT' THEN ec.time END) AS out_time,
				ROUND(TIMESTAMPDIFF(MINUTE,
					MIN(CASE WHEN ec.log_type = 'IN'  THEN ec.time END),
					MAX(CASE WHEN ec.log_type = 'OUT' THEN ec.time END)) / 60, 2) AS working_hours,
				(SELECT a1.status FROM `tabAttendance` a1
				 WHERE a1.employee = ec.employee AND a1.attendance_date = DATE(ec.time)
				 ORDER BY a1.docstatus DESC, a1.modified DESC LIMIT 1) AS status,
				(SELECT a1.shift FROM `tabAttendance` a1
				 WHERE a1.employee = ec.employee AND a1.attendance_date = DATE(ec.time)
				 ORDER BY a1.docstatus DESC, a1.modified DESC LIMIT 1) AS shift_type
			FROM `tabEmployee Checkin` ec
			WHERE DATE(ec.time) BETWEEN %(from_date)s AND %(to_date)s
			{emp_checkin_cond}
			GROUP BY ec.employee, DATE(ec.time), ec.custom_project

			UNION ALL

			SELECT
				att.employee,
				att.attendance_date AS att_date,
				ash.project         AS project,
				att.in_time,
				att.out_time,
				ash.hours           AS working_hours,
				att.status,
				att.shift
			FROM `tabAttendance` att
			JOIN `tabAttendance Site Hours` ash
				ON ash.parent = att.name AND ash.parentfield = 'custom_site_hours'
			WHERE att.attendance_date BETWEEN %(from_date)s AND %(to_date)s
			{emp_att_cond}
			AND NOT EXISTS (
				SELECT 1 FROM `tabEmployee Checkin` ec2
				WHERE ec2.employee = att.employee AND DATE(ec2.time) = att.attendance_date)

			UNION ALL

			SELECT
				att.employee,
				att.attendance_date AS att_date,
				NULL                AS project,
				att.in_time,
				att.out_time,
				COALESCE(att.working_hours, 0) AS working_hours,
				att.status,
				att.shift
			FROM `tabAttendance` att
			WHERE att.attendance_date BETWEEN %(from_date)s AND %(to_date)s
			{emp_att_cond}
			AND NOT EXISTS (
				SELECT 1 FROM `tabEmployee Checkin` ec2
				WHERE ec2.employee = att.employee AND DATE(ec2.time) = att.attendance_date)
			AND NOT EXISTS (
				SELECT 1 FROM `tabAttendance Site Hours` ash2
				WHERE ash2.parent = att.name AND ash2.parentfield = 'custom_site_hours')
		) base
		LEFT JOIN `tabEmployee`   emp ON emp.name  = base.employee
		LEFT JOIN `tabProject`    p   ON p.name    = base.project
		LEFT JOIN `tabShift Type` st  ON st.name   = base.shift_type
		LEFT JOIN `tabHoliday`    hol ON hol.parent = emp.holiday_list
			AND hol.holiday_date = base.att_date
		WHERE 1 = 1
		{dept_cond}
		{dept_scope_cond}
		ORDER BY base.att_date DESC, emp.employee_name, base.project
	"""

	return frappe.db.sql(sql, values, as_dict=True)
