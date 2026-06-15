import frappe
from frappe import _
from frappe.utils import cint, get_url_to_form

# Maps (prev_workflow_state, next_workflow_state) → required approval level from matrix.
# Only transitions that must be performed by the designated approver are listed here.
_LEVEL_REQUIRED: dict[tuple[str, str], int] = {
	("Pending Level 1 Approval", "Pending Level 2 Approval"): 1,
	("Pending Level 1 Approval", "Rejected"): 1,
	("Pending Level 2 Approval", "Approved"): 2,
	("Pending Level 2 Approval", "Rejected"): 2,
}

# Maps the state we are entering → the level whose approver we should notify.
_NOTIFY_ON_ENTER: dict[str, int] = {
	"Pending Level 1 Approval": 1,
	"Pending Level 2 Approval": 2,
}


# ---------------------------------------------------------------------------
# doc_events entry points
# ---------------------------------------------------------------------------


def validate(doc, method):
	_validate_approver_authorization(doc)


def on_update(doc, method):
	_send_approval_notification(doc)
	_update_tracking_fields(doc)


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _get_matrix(department: str) -> list:
	"""Return all approval matrix rows for *department*, ordered by level."""
	if not department:
		return []
	return frappe.get_all(
		"Department Approval Matrix",
		filters={"parent": department, "parentfield": "approval_matrix"},
		fields=["approval_level", "approver", "approval_window_hours"],
		order_by="approval_level asc",
	)


def _row_for_level(matrix: list, level: int):
	return next((r for r in matrix if cint(r.approval_level) == level), None)


def _approver_user(employee: str) -> str | None:
	return frappe.db.get_value("Employee", employee, "user_id")


def _approver_email(employee: str) -> str | None:
	return (
		frappe.db.get_value("Employee", employee, "company_email")
		or frappe.db.get_value("Employee", employee, "personal_email")
		or _approver_user(employee)
	)


def _state_changed(doc) -> tuple[str | None, str | None]:
	"""Return (prev_state, new_state). Returns (None, None) if unchanged."""
	prev = doc.get_doc_before_save()
	prev_state = prev.workflow_state if prev else None
	new_state = doc.get("workflow_state")
	if prev_state == new_state:
		return None, None
	return prev_state, new_state


# ---------------------------------------------------------------------------
# validation: enforce designated approver
# ---------------------------------------------------------------------------


def _validate_approver_authorization(doc):
	new_state = doc.get("workflow_state")
	if not new_state:
		return

	prev = doc.get_doc_before_save()
	if not prev:
		return

	prev_state = prev.workflow_state
	key = (prev_state, new_state)

	required_level = _LEVEL_REQUIRED.get(key)
	if required_level is None:
		return

	department = doc.department
	if not department:
		frappe.throw(_("Department is required on Shift Assignment for approval routing."))

	matrix = _get_matrix(department)
	row = _row_for_level(matrix, required_level)

	if not row:
		frappe.throw(
			_("No Level {0} approver is configured for Department {1}. "
			  "Please set up the Approval Matrix on the Department record.").format(
				required_level, department
			)
		)

	approver_user = _approver_user(row.approver)
	if not approver_user:
		frappe.throw(
			_("Employee {0} (Level {1} approver) has no linked User account. "
			  "Please link a User to that Employee before proceeding.").format(
				row.approver, required_level
			)
		)

	# HR Manager can always override — useful for admin corrections.
	if "HR Manager" in frappe.get_roles(frappe.session.user):
		return

	if frappe.session.user != approver_user:
		emp_name = frappe.db.get_value("Employee", row.approver, "employee_name") or row.approver
		frappe.throw(
			_("Level {0} approval must be performed by {1} ({2}). "
			  "Current user is not authorised.").format(
				required_level, emp_name, row.approver
			)
		)


# ---------------------------------------------------------------------------
# notification: email designated approver on state entry
# ---------------------------------------------------------------------------


def _send_approval_notification(doc):
	prev_state, new_state = _state_changed(doc)
	if not new_state:
		return

	notify_level = _NOTIFY_ON_ENTER.get(new_state)
	if not notify_level:
		return

	department = doc.department
	if not department:
		return

	matrix = _get_matrix(department)
	row = _row_for_level(matrix, notify_level)
	if not row:
		return

	recipient = _approver_email(row.approver)
	if not recipient:
		frappe.log_error(
			title="Shift Assignment: approver email missing",
			message=f"Employee {row.approver} has no email. Cannot notify for {doc.name}.",
		)
		return

	approver_name = frappe.db.get_value("Employee", row.approver, "employee_name") or row.approver
	doc_url = get_url_to_form("Shift Assignment", doc.name)

	frappe.sendmail(
		recipients=[recipient],
		subject=_("Action Required – Shift Assignment Level {0} Approval: {1}").format(
			notify_level, doc.name
		),
		message=_(
			"""<p>Dear {approver_name},</p>
<p>A Shift Assignment requires your <strong>Level {level} approval</strong>.</p>
<table border="0" cellpadding="6" style="border-collapse:collapse;">
  <tr><td><strong>Document</strong></td><td>{doc_name}</td></tr>
  <tr><td><strong>Employee</strong></td><td>{employee_name}</td></tr>
  <tr><td><strong>Department</strong></td><td>{department}</td></tr>
  <tr><td><strong>Shift Type</strong></td><td>{shift_type}</td></tr>
  <tr><td><strong>Approval Window</strong></td><td>{window} hours</td></tr>
</table>
<p><a href="{url}">Open in ERPNext</a></p>"""
		).format(
			approver_name=approver_name,
			level=notify_level,
			doc_name=doc.name,
			employee_name=doc.employee_name or doc.employee,
			department=department,
			shift_type=doc.shift_type,
			window=cint(row.approval_window_hours),
			url=doc_url,
		),
		now=False,
	)


# ---------------------------------------------------------------------------
# tracking: stamp current_approval_level / current_approver on the row
# ---------------------------------------------------------------------------


def _update_tracking_fields(doc):
	prev_state, new_state = _state_changed(doc)
	if not new_state:
		return

	notify_level = _NOTIFY_ON_ENTER.get(new_state)
	if not notify_level:
		return

	department = doc.department
	if not department:
		return

	matrix = _get_matrix(department)
	row = _row_for_level(matrix, notify_level)
	if not row:
		return

	frappe.db.set_value(
		"Shift Assignment",
		doc.name,
		{
			"current_approval_level": notify_level,
			"current_approver": row.approver,
		},
		update_modified=False,
	)
