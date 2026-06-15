import frappe
from frappe import _
from frappe.utils import cint, now_datetime


def process_attendance_approval_windows():
	"""Hourly task: auto-approve attendance when the approval window expires."""
	expired = frappe.get_all(
		"Attendance",
		filters={
			"docstatus": 1,
			"workflow_state": ["in", ["Pending Level 1 Approval", "Pending Level 2 Approval"]],
			"window_expires_at": ["<", now_datetime()],
		},
		fields=[
			"name", "department", "employee", "employee_name",
			"attendance_date", "status", "workflow_state", "current_approval_level",
		],
	)

	for att in expired:
		frappe.db.set_value(
			"Attendance", att.name, "workflow_state", "Approved", update_modified=False
		)
