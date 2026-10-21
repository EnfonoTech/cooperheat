"""Leave and Expense approvals: reporting person first, then the Payroll Approver.

Client rule (2026-10-21): a leave or expense claim goes to the employee's reporting person
(Direct / Immediate Reporting); once approved it goes by itself to the Payroll Approver for the
final approval. Shift requests keep a single approver (the reporting person) and are untouched.

Both are plain Frappe Workflows created here (idempotent, run from after_migrate):

  Pending Reporting Approval --Approve--> Pending Final Approval --Approve--> Approved
  (either step) --Reject--> Rejected              (employee cancels from the app -> Cancelled)

The reporting person is the document's leave / expense approver (filled from Reports To);
the final approver is stored on the document (custom_final_approver) when it is saved. A
final step nobody holds (no Payroll Approver, or the reporting person IS the Payroll Approver)
passes by itself. HR Managers and System Managers can step in at either step, like attendance.
"""

import frappe
from frappe import _

LEAVE, EXPENSE = "Leave Application", "Expense Claim"
PENDING_1, PENDING_2 = "Pending Reporting Approval", "Pending Final Approval"
APPROVED, REJECTED, CANCELLED = "Approved", "Rejected", "Cancelled"

# doctype -> (workflow name, reporting-approver field, status field, status value while pending)
DEFINITIONS = {
	LEAVE: ("Leave Approval", "leave_approver", "status", "Open"),
	EXPENSE: ("Expense Approval", "expense_approver", "approval_status", "Draft"),
}
FINAL_APPROVER_FIELD = "custom_final_approver"

_STATE_STYLE = {
	PENDING_1: "Warning",
	PENDING_2: "Warning",
	APPROVED: "Success",
	REJECTED: "Danger",
	CANCELLED: "",
}


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------


def final_approver_field() -> dict:
	return {
		"fieldname": FINAL_APPROVER_FIELD,
		"label": "Final Approver",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"no_copy": 1,
		"description": "The Payroll Approver. Set when the request is saved; empty = the reporting person's approval is final.",
	}


def ensure_workflows():
	"""Create or refresh both workflows and give open requests a workflow state."""
	for doctype in (LEAVE, EXPENSE):
		if not frappe.db.exists("DocType", doctype):
			continue
		_ensure_masters()
		_ensure_workflow(doctype)
		_backfill_open_requests(doctype)


def _ensure_masters():
	for name, style in _STATE_STYLE.items():
		if not frappe.db.exists("Workflow State", name):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": name, "style": style}).insert(
				ignore_permissions=True
			)
	for action in ("Approve", "Reject"):
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)


def _states(status_field, pending_value):
	def row(state, doc_status, update_value=None):
		return {
			"state": state,
			"doc_status": str(doc_status),
			"allow_edit": "All",
			"update_field": status_field if update_value else None,
			"update_value": update_value,
		}

	return [
		row(PENDING_1, 0, pending_value),
		row(PENDING_2, 0, pending_value),
		row(APPROVED, 1, "Approved"),
		row(REJECTED, 1, "Rejected"),
		row(CANCELLED, 0, "Cancelled" if status_field == "status" else None),
	]


def _transitions(approver_field):
	mine = f"doc.{approver_field} == frappe.session.user"
	final = f"doc.{FINAL_APPROVER_FIELD} == frappe.session.user"

	def row(state, action, next_state, allowed, condition=None):
		return {
			"state": state,
			"action": action,
			"next_state": next_state,
			"allowed": allowed,
			"condition": condition,
			"allow_self_approval": 0 if condition else 1,
		}

	out = []
	for state, next_state, condition in ((PENDING_1, PENDING_2, mine), (PENDING_2, APPROVED, final)):
		out.append(row(state, "Approve", next_state, "All", condition))
		out.append(row(state, "Approve", next_state, "HR Manager"))
		out.append(row(state, "Approve", next_state, "System Manager"))
		out.append(row(state, "Reject", REJECTED, "All", condition))
		out.append(row(state, "Reject", REJECTED, "HR Manager"))
		out.append(row(state, "Reject", REJECTED, "System Manager"))
	return out


def _ensure_workflow(doctype):
	name, approver_field, status_field, pending_value = DEFINITIONS[doctype]
	values = {
		"document_type": doctype,
		"is_active": 1,
		"workflow_state_field": "workflow_state",
		"override_status": 0,
		"send_email_alert": 0,
	}
	for other in frappe.get_all(
		"Workflow", filters={"document_type": doctype, "name": ["!=", name], "is_active": 1}, pluck="name"
	):
		frappe.db.set_value("Workflow", other, "is_active", 0)  # only one active workflow per document type
	if frappe.db.exists("Workflow", name):
		wf = frappe.get_doc("Workflow", name)
		wf.update(values)
	else:
		wf = frappe.new_doc("Workflow")
		wf.workflow_name = name
		wf.update(values)
	wf.set("states", [])
	wf.set("transitions", [])
	for row in _states(status_field, pending_value):
		wf.append("states", row)
	for row in _transitions(approver_field):
		wf.append("transitions", row)
	wf.flags.ignore_permissions = True
	wf.save()


def _backfill_open_requests(doctype):
	"""Requests made before the workflow existed: still-open drafts wait at the first step,
	cancelled ones are marked so nobody can approve them."""
	_name, approver_field, status_field, pending_value = DEFINITIONS[doctype]
	table = "tab" + doctype
	frappe.db.sql(
		f"UPDATE `{table}` SET workflow_state = %s WHERE docstatus = 0 AND IFNULL(workflow_state, '') = '' "
		f"AND IFNULL(`{status_field}`, '') IN (%s, '')",
		(PENDING_1, pending_value),
	)
	if status_field == "status":
		frappe.db.sql(
			f"UPDATE `{table}` SET workflow_state = %s WHERE docstatus = 0 AND IFNULL(workflow_state, '') = '' AND status = 'Cancelled'",
			(CANCELLED,),
		)
	# Open requests without an approver: the reporting person of the employee, when there is one
	for rec in frappe.get_all(
		doctype,
		filters={"docstatus": 0, "workflow_state": PENDING_1},
		fields=["name", "employee", approver_field],
	):
		if rec.get(approver_field):
			continue
		user = _reporting_user(rec.employee)
		if user:
			frappe.db.set_value(doctype, rec.name, approver_field, user, update_modified=False)
	for rec in frappe.get_all(
		doctype,
		filters={"docstatus": 0, "workflow_state": ["in", [PENDING_1, PENDING_2]]},
		fields=["name", "employee", approver_field],
	):
		frappe.db.set_value(
			doctype,
			rec.name,
			FINAL_APPROVER_FIELD,
			_final_user(rec.employee, rec.get(approver_field)),
			update_modified=False,
		)


# ---------------------------------------------------------------------------
# Document events
# ---------------------------------------------------------------------------


def _reporting_user(employee):
	boss = frappe.db.get_value("Employee", employee, "reports_to") if employee else None
	if boss and boss != employee:
		return frappe.db.get_value("Employee", boss, "user_id")
	return None


def _final_user(employee, approver_user):
	"""The Payroll Approver's User, unless nobody is left to approve at that step."""
	from cooperheat.cooperheat.org import payroll_approver

	boss = payroll_approver()
	if not boss or boss == employee:
		return None
	user = frappe.db.get_value("Employee", boss, "user_id")
	return None if not user or user == approver_user else user


def before_validate(doc, method=None):
	"""Fill the reporting approver and the final approver."""
	if doc.doctype not in DEFINITIONS or doc.docstatus != 0 or not doc.meta.has_field(FINAL_APPROVER_FIELD):
		return
	approver_field = DEFINITIONS[doc.doctype][1]
	if not doc.get(approver_field):
		doc.set(approver_field, _reporting_user(doc.get("employee")))
	if doc.get("workflow_state") in (None, "", PENDING_1, PENDING_2):
		doc.set(FINAL_APPROVER_FIELD, _final_user(doc.get("employee"), doc.get(approver_field)))


def on_update(doc, method=None):
	"""Tell the next approver; pass a final step nobody holds."""
	if doc.doctype not in DEFINITIONS or not doc.meta.has_field("workflow_state"):
		return
	state = doc.get("workflow_state")
	before = doc.get_doc_before_save()
	moved = not before or before.get("workflow_state") != state
	if not moved or state != PENDING_2:
		return
	if not doc.get(FINAL_APPROVER_FIELD):
		_pass_final_step(doc)
		return
	_notify(doc, doc.get(FINAL_APPROVER_FIELD))


def _pass_final_step(doc):
	"""Nobody holds the final step: approve it as the system."""
	from frappe.model.workflow import apply_workflow

	user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		apply_workflow(frappe.get_doc(doc.doctype, doc.name), "Approve")
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Final approval step could not pass by itself: {doc.doctype} {doc.name}",
		)
	finally:
		frappe.set_user(user)


def _notify(doc, user):
	if not user:
		return
	try:
		frappe.sendmail(
			recipients=[user],
			subject=_("Action required: final approval of {0} {1}").format(_(doc.doctype), doc.name),
			message=_(
				"{0} {1} of {2} was approved by the reporting person and now needs your final approval."
			).format(_(doc.doctype), doc.name, doc.get("employee_name") or doc.get("employee"))
			+ ' <a href="{}">{}</a>'.format(frappe.utils.get_url_to_form(doc.doctype, doc.name), _("Open")),
			now=False,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Final approval email failed: {doc.doctype} {doc.name}")
