import frappe
from frappe import _
from frappe.utils import getdate


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {"label": _("Code"),       "fieldname": "code",      "fieldtype": "Link",     "options": "Employee", "width": 120},
        {"label": _("Month"),      "fieldname": "month",     "fieldtype": "Data",     "width": 100},
        {"label": _("Total Present Days"), "fieldname": "days", "fieldtype": "Float",    "precision": 1, "width": 130},
        {"label": _("OT"),         "fieldname": "ot",        "fieldtype": "Float",    "precision": 2, "width": 80},
        {"label": _("HOT"),        "fieldname": "hot",       "fieldtype": "Float",    "precision": 2, "width": 80},
        {"label": _("TravelOT"),   "fieldname": "travel_ot", "fieldtype": "Float",    "precision": 2, "width": 100},
        {"label": _("Expenses"),   "fieldname": "expenses",  "fieldtype": "Currency", "width": 100},
        {"label": _("Other"),      "fieldname": "other",     "fieldtype": "Currency", "width": 90},
        {"label": _("Vacation"),   "fieldname": "vacation",  "fieldtype": "Float",    "precision": 2, "width": 90},
        {"label": _("Bonus"),      "fieldname": "bonus",     "fieldtype": "Currency", "width": 90},
        {"label": _("Airfare"),    "fieldname": "airfare",   "fieldtype": "Currency", "width": 90},
        {"label": _("Otherded"),   "fieldname": "otherded",  "fieldtype": "Currency", "width": 100},
        {"label": _("Housingded"), "fieldname": "housingded","fieldtype": "Currency", "width": 110},
    ]


def get_data(filters):
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    month_label = getdate(from_date).strftime("%m/%Y")

    days_map = {r.employee: r for r in _get_days(from_date, to_date)}
    ot_map = _get_ot(from_date, to_date)
    hot_map = _get_hot(from_date, to_date)

    all_employees = set(days_map) | set(ot_map) | set(hot_map)

    rows = []
    for emp in sorted(all_employees):
        d = days_map.get(emp)
        rows.append({
            "code":       d.code if d else emp,
            "month":      month_label,
            "days":       round(float(d.days or 0), 1) if d else 0,
            "ot":         round(float(ot_map.get(emp) or 0), 2),
            "hot":        round(float(hot_map.get(emp) or 0), 2),
            "travel_ot":  0,
            "expenses":   0,
            "other":      0,
            "vacation":   0,
            "bonus":      0,
            "airfare":    0,
            "otherded":   0,
            "housingded": 0,
        })

    return rows


def _get_days(from_date, to_date):
    return frappe.db.sql("""
        SELECT
            a.employee,
            emp.name AS code,
            SUM(
                CASE a.status
                    WHEN 'Present'        THEN 1
                    WHEN 'Work From Home' THEN 1
                    WHEN 'Half Day'       THEN 0.5
                    ELSE 0
                END
            ) AS days
        FROM `tabAttendance` a
        JOIN `tabEmployee` emp ON emp.name = a.employee
        WHERE a.attendance_date BETWEEN %(from_date)s AND %(to_date)s
          AND a.docstatus = 1
        GROUP BY a.employee, emp.name
        ORDER BY emp.name
    """, {"from_date": from_date, "to_date": to_date}, as_dict=True)


def _get_ot(from_date, to_date):
    rows = frappe.db.sql("""
        SELECT employee, ROUND(SUM(ot_hours), 2) AS ot_hours
        FROM (
            SELECT
                ec.employee,
                ROUND(GREATEST(
                    ROUND(TIMESTAMPDIFF(MINUTE,
                        MIN(CASE WHEN ec.log_type = 'IN'  THEN ec.time END),
                        MAX(CASE WHEN ec.log_type = 'OUT' THEN ec.time END)) / 60, 2)
                    - COALESCE(NULLIF(p.custom_regular_working_hours__day, 0),
                        ROUND(TIMESTAMPDIFF(MINUTE,
                            MIN(CASE WHEN ec.log_type = 'IN'  THEN ec.time END),
                            MAX(CASE WHEN ec.log_type = 'OUT' THEN ec.time END)) / 60, 2))
                , 0), 2) AS ot_hours
            FROM `tabEmployee Checkin` ec
            LEFT JOIN `tabProject` p ON p.name = ec.custom_project
            LEFT JOIN `tabEmployee` emp ON emp.name = ec.employee
            LEFT JOIN `tabCompany` comp ON comp.name = emp.company
            LEFT JOIN `tabHoliday` hol ON hol.parent = COALESCE(NULLIF(emp.holiday_list, ''), comp.default_holiday_list)
                AND hol.holiday_date = DATE(ec.time)
            WHERE DATE(ec.time) BETWEEN %(from_date)s AND %(to_date)s
              AND hol.holiday_date IS NULL
            GROUP BY ec.employee, DATE(ec.time), ec.custom_project

            UNION ALL

            SELECT
                att.employee,
                ROUND(GREATEST(
                    COALESCE(ash.hours, 0)
                    - COALESCE(NULLIF(p.custom_regular_working_hours__day, 0), COALESCE(ash.hours, 0))
                , 0), 2) AS ot_hours
            FROM `tabAttendance` att
            JOIN `tabAttendance Site Hours` ash
                ON ash.parent = att.name AND ash.parentfield = 'custom_site_hours'
            LEFT JOIN `tabProject` p ON p.name = ash.project
            LEFT JOIN `tabEmployee` emp ON emp.name = att.employee
            LEFT JOIN `tabCompany` comp ON comp.name = emp.company
            LEFT JOIN `tabHoliday` hol ON hol.parent = COALESCE(NULLIF(emp.holiday_list, ''), comp.default_holiday_list)
                AND hol.holiday_date = att.attendance_date
            WHERE att.attendance_date BETWEEN %(from_date)s AND %(to_date)s
              AND att.docstatus = 1
              AND hol.holiday_date IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM `tabEmployee Checkin` ec2
                  WHERE ec2.employee = att.employee
                    AND DATE(ec2.time) = att.attendance_date)
        ) ot_union
        GROUP BY employee
    """, {"from_date": from_date, "to_date": to_date}, as_dict=True)

    return {r.employee: r.ot_hours or 0 for r in rows}


def _get_hot(from_date, to_date):
    rows = frappe.db.sql("""
        SELECT employee, ROUND(SUM(hot_hours), 2) AS hot_hours
        FROM (
            SELECT
                ec.employee,
                ROUND(TIMESTAMPDIFF(MINUTE,
                    MIN(CASE WHEN ec.log_type = 'IN'  THEN ec.time END),
                    MAX(CASE WHEN ec.log_type = 'OUT' THEN ec.time END)) / 60, 2) AS hot_hours
            FROM `tabEmployee Checkin` ec
            LEFT JOIN `tabEmployee` emp ON emp.name = ec.employee
            LEFT JOIN `tabCompany` comp ON comp.name = emp.company
            JOIN `tabHoliday` hol ON hol.parent = COALESCE(NULLIF(emp.holiday_list, ''), comp.default_holiday_list)
                AND hol.holiday_date = DATE(ec.time)
            WHERE DATE(ec.time) BETWEEN %(from_date)s AND %(to_date)s
            GROUP BY ec.employee, DATE(ec.time), ec.custom_project

            UNION ALL

            SELECT
                att.employee,
                COALESCE(ash.hours, 0) AS hot_hours
            FROM `tabAttendance` att
            JOIN `tabAttendance Site Hours` ash
                ON ash.parent = att.name AND ash.parentfield = 'custom_site_hours'
            LEFT JOIN `tabEmployee` emp ON emp.name = att.employee
            LEFT JOIN `tabCompany` comp ON comp.name = emp.company
            JOIN `tabHoliday` hol ON hol.parent = COALESCE(NULLIF(emp.holiday_list, ''), comp.default_holiday_list)
                AND hol.holiday_date = att.attendance_date
            WHERE att.attendance_date BETWEEN %(from_date)s AND %(to_date)s
              AND att.docstatus = 1
              AND NOT EXISTS (
                  SELECT 1 FROM `tabEmployee Checkin` ec2
                  WHERE ec2.employee = att.employee
                    AND DATE(ec2.time) = att.attendance_date)
        ) hot_union
        GROUP BY employee
    """, {"from_date": from_date, "to_date": to_date}, as_dict=True)

    return {r.employee: r.hot_hours or 0 for r in rows}
