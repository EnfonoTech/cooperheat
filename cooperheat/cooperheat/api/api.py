import frappe
from frappe import _
from cooperheat.cooperheat.api.tasks import process_attendance_approval_windows


@frappe.whitelist()
def run_attendance_approval_windows():
	"""Manually trigger the attendance approval window auto-approve task."""
	frappe.has_permission("Attendance", ptype="write", throw=True)
	process_attendance_approval_windows()
	return {"status": "ok"}
