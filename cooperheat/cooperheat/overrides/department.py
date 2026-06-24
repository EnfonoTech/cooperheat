import frappe
from frappe.utils import cint, now


_LEVEL_STATE = {
	1: "Pending Level 1 Approval",
	2: "Pending Level 2 Approval",
	3: "Pending Level 3 Approval",
}


def on_update(doc, method):
	"""When the Department approval matrix changes, re-stamp current_approver
	on all pending Attendance records for this department so approvers are
	never locked out by a stale value."""
	_sync_pending_attendance(doc)


def _sync_pending_attendance(dept_doc):
	department = dept_doc.name
	matrix = {
		cint(row.approval_level): row.approver
		for row in (dept_doc.get("approval_matrix") or [])
	}
	if not matrix:
		return

	pending_states = list(_LEVEL_STATE.values())
	records = frappe.get_all(
		"Attendance",
		filters={
			"department": department,
			"workflow_state": ["in", pending_states],
			"docstatus": 1,
		},
		fields=["name", "workflow_state", "current_approver"],
	)
	if not records:
		return

	state_to_level = {v: k for k, v in _LEVEL_STATE.items()}

	for rec in records:
		level = state_to_level.get(rec.workflow_state)
		if not level:
			continue
		new_approver = matrix.get(level)
		if not new_approver or new_approver == rec.current_approver:
			continue
		approver_name = frappe.db.get_value("Employee", new_approver, "employee_name") or new_approver
		frappe.db.set_value(
			"Attendance",
			rec.name,
			{
				"current_approver": new_approver,
				"current_approver_name": approver_name,
			},
			update_modified=False,
		)
