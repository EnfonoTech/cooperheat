import frappe
from frappe import _
from frappe.utils import cint, flt, get_url_to_form, now, now_datetime, get_datetime, time_diff_in_hours, add_to_date

# ---------------------------------------------------------------------------
# Authorization map: (prev_workflow_state, next_workflow_state) → required level
# ---------------------------------------------------------------------------
_LEVEL_REQUIRED: dict[tuple[str, str], int] = {
	("Pending Level 1 Approval", "Pending Level 2 Approval"): 1,
	("Pending Level 1 Approval", "Rejected"): 1,
	("Pending Level 2 Approval", "Approved"): 2,
	("Pending Level 2 Approval", "Rejected"): 2,
}

_NOTIFY_LEVEL: dict[str, int] = {
	"Pending Level 1 Approval": 1,
	"Pending Level 2 Approval": 2,
}

_INITIAL_WORKFLOW_STATE = "Pending Level 1 Approval"


# ---------------------------------------------------------------------------
# doc_events entry points
# ---------------------------------------------------------------------------


def on_submit(doc, method):
	"""Seed initial approval state and notify Level 1 approver.

	Auto-attendance submits records programmatically, bypassing the workflow
	action buttons.  We therefore seed the workflow state here so the approval
	chain starts correctly for both auto-generated and manually submitted records.
	"""
	frappe.db.set_value(
		"Attendance",
		doc.name,
		"workflow_state",
		_INITIAL_WORKFLOW_STATE,
		update_modified=False,
	)
	_send_notification_for_level(doc, 1)
	_stamp_tracking_fields(doc, 1)


def validate(doc, method):
	"""Block unauthorised workflow state transitions and hours edits."""
	_validate_approver_authorization(doc)
	_validate_hours_edit_authorization(doc)
	_recalculate_working_hours(doc)


def on_update_after_submit(doc, method):
	"""Send notification and stamp tracking fields when state advances."""
	prev_state, new_state = _state_changed(doc)
	if not new_state:
		return
	level = _NOTIFY_LEVEL.get(new_state)
	if not level:
		return
	_send_notification_for_level(doc, level)
	_stamp_tracking_fields(doc, level)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_matrix(department: str) -> list:
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
	prev = doc.get_doc_before_save()
	prev_state = prev.workflow_state if prev else None
	new_state = doc.get("workflow_state")
	if prev_state == new_state:
		return None, None
	return prev_state, new_state


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_hours_edit_authorization(doc):
	"""Only the current level's approver may edit status / in_time / out_time."""
	if doc.docstatus != 1:
		return

	# Read current DB values directly — get_doc_before_save() is unreliable on submitted docs
	db_vals = frappe.db.get_value(
		"Attendance", doc.name, ["in_time", "out_time", "status"], as_dict=True
	)
	if not db_vals:
		return

	fields_changed = (
		str(doc.get("in_time")) != str(db_vals.in_time)
		or str(doc.get("out_time")) != str(db_vals.out_time)
		or str(doc.get("status") or "") != str(db_vals.status or "")
	)
	if not fields_changed:
		return

	# Block edit if approval window has already expired
	window_expires_at = frappe.db.get_value("Attendance", doc.name, "window_expires_at")
	if window_expires_at and now_datetime() > get_datetime(window_expires_at):
		frappe.throw(_("The approval window has expired. Attendance fields can no longer be edited."))

	workflow_state = doc.get("workflow_state") or ""
	level_map = {"Pending Level 1 Approval": 1, "Pending Level 2 Approval": 2}
	level = level_map.get(workflow_state)

	if not level:
		frappe.throw(_("Attendance fields can only be edited while the record is pending approval."))

	department = doc.department
	if not department:
		frappe.throw(_("Department is required to validate approver."))

	matrix = _get_matrix(department)
	row = _row_for_level(matrix, level)

	if not row:
		frappe.throw(
			_("No Level {0} approver configured for Department {1}.").format(level, department)
		)

	approver_user = _approver_user(row.approver)
	if frappe.session.user != approver_user:
		emp_name = frappe.db.get_value("Employee", row.approver, "employee_name") or row.approver
		frappe.throw(
			_("Attendance can only be corrected by the Level {0} approver: {1}.").format(
				level, emp_name
			)
		)


def _recalculate_working_hours(doc):
	"""Auto-recalculate working_hours when in_time or out_time changes on a submitted doc."""
	if doc.docstatus != 1:
		return
	if not doc.in_time or not doc.out_time:
		return
	db_vals = frappe.db.get_value("Attendance", doc.name, ["in_time", "out_time"], as_dict=True)
	if not db_vals:
		return
	if str(doc.in_time) != str(db_vals.in_time) or str(doc.out_time) != str(db_vals.out_time):
		doc.working_hours = time_diff_in_hours(doc.out_time, doc.in_time)


def _validate_approver_authorization(doc):
	new_state = doc.get("workflow_state")
	if not new_state:
		return

	prev = doc.get_doc_before_save()
	if not prev:
		return

	key = (prev.workflow_state, new_state)
	required_level = _LEVEL_REQUIRED.get(key)
	if required_level is None:
		return

	department = doc.department
	if not department:
		frappe.throw(_("Department is required on the Attendance record for approval routing."))

	matrix = _get_matrix(department)
	row = _row_for_level(matrix, required_level)

	if not row:
		frappe.throw(
			_("No Level {0} approver configured for Department {1}. "
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

	# HR Managers can always override
	if "HR Manager" in frappe.get_roles(frappe.session.user):
		return

	if frappe.session.user != approver_user:
		emp_name = frappe.db.get_value("Employee", row.approver, "employee_name") or row.approver
		frappe.throw(
			_("Level {0} approval must be performed by {1} ({2}).").format(
				required_level, emp_name, row.approver
			)
		)


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------


def _send_notification_for_level(doc, level: int):
	department = doc.department
	if not department:
		return

	matrix = _get_matrix(department)
	row = _row_for_level(matrix, level)
	if not row:
		return

	recipient = _approver_email(row.approver)
	if not recipient:
		frappe.log_error(
			title="Attendance Approval: approver email missing",
			message=f"Employee {row.approver} has no email. Cannot notify for {doc.name}.",
		)
		return

	approver_name = frappe.db.get_value("Employee", row.approver, "employee_name") or row.approver
	doc_url = get_url_to_form("Attendance", doc.name)

	frappe.sendmail(
		recipients=[recipient],
		subject=_("Action Required – Attendance Level {0} Approval: {1}").format(level, doc.name),
		message=_(
			"""<p>Dear {approver_name},</p>
<p>An Attendance record requires your <strong>Level {level} approval</strong>.</p>
<table border="0" cellpadding="6" style="border-collapse:collapse;">
  <tr><td><strong>Document</strong></td><td>{doc_name}</td></tr>
  <tr><td><strong>Employee</strong></td><td>{employee_name}</td></tr>
  <tr><td><strong>Department</strong></td><td>{department}</td></tr>
  <tr><td><strong>Date</strong></td><td>{attendance_date}</td></tr>
  <tr><td><strong>Status</strong></td><td>{status}</td></tr>
  <tr><td><strong>Approval Window</strong></td><td>{window} hours</td></tr>
</table>
<p><a href="{url}">Open in ERPNext</a></p>"""
		).format(
			approver_name=approver_name,
			level=level,
			doc_name=doc.name,
			employee_name=doc.employee_name or doc.employee,
			department=department,
			attendance_date=doc.attendance_date,
			status=doc.status,
			window=flt(row.approval_window_hours),
			url=doc_url,
		),
		now=False,
	)


# ---------------------------------------------------------------------------
# Tracking fields
# ---------------------------------------------------------------------------


def _get_project_for_attendance(doc) -> str | None:
	"""Look up the Project linked on the employee's active Shift Assignment."""
	if not doc.employee or not doc.attendance_date:
		return None
	filters = {
		"employee": doc.employee,
		"docstatus": 1,
		"start_date": ["<=", doc.attendance_date],
	}
	if doc.shift:
		filters["shift_type"] = doc.shift
	return frappe.db.get_value(
		"Shift Assignment", filters, "custom_project_", order_by="start_date desc"
	)


def _get_project_window_hours(project: str, level: int) -> float:
	"""Return the project-level approval window hours for the given level, or 0 if not set."""
	field_map = {
		1: "supervisor_approval_window",
		2: "manager_payroll_final_approval_window",
	}
	field = field_map.get(level)
	if not field or not project:
		return 0
	return flt(frappe.db.get_value("Project", project, field))


def _stamp_tracking_fields(doc, level: int):
	department = doc.department
	if not department:
		return
	matrix = _get_matrix(department)
	row = _row_for_level(matrix, level)
	if not row:
		return

	# Project window hours take priority; fall back to Department Approval Matrix
	project = _get_project_for_attendance(doc)
	window_hours = _get_project_window_hours(project, level) if project else 0
	if not window_hours:
		window_hours = flt(row.approval_window_hours)

	expires_at = add_to_date(now(), hours=window_hours) if window_hours else None

	frappe.db.set_value(
		"Attendance",
		doc.name,
		{
			"current_approval_level": level,
			"current_approver": row.approver,
			"level_assigned_at": now(),
			"approval_window_hours": window_hours,
			"window_expires_at": expires_at,
			"window_reminder_sent": 0,
		},
		update_modified=False,
	)
