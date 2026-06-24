import frappe


def execute():
	from cooperheat.cooperheat.overrides.attendance import fix_all_attendance_status
	fix_all_attendance_status()
