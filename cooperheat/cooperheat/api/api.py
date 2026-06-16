import frappe
from frappe import _
from frappe.utils import cint
from cooperheat.cooperheat.api.tasks import process_attendance_approval_windows


@frappe.whitelist()
def get_approval_matrix_approver(department, level):
	"""Return the approver employee and their linked user for a given department + level."""
	from cooperheat.cooperheat.overrides.attendance import _get_matrix, _row_for_level
	matrix = _get_matrix(department)
	row = _row_for_level(matrix, cint(level))
	if not row:
		return None
	user_id = frappe.db.get_value("Employee", row.approver, "user_id")
	return {"approver": row.approver, "user_id": user_id}


@frappe.whitelist()
def run_attendance_approval_windows():
	"""Manually trigger the attendance approval window auto-approve task."""
	frappe.has_permission("Attendance", ptype="write", throw=True)
	process_attendance_approval_windows()
	return {"status": "ok"}
