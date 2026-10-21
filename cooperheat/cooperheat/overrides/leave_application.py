import frappe
from frappe import _


def validate(doc, method=None):
	validate_client_approval(doc)


def validate_client_approval(doc):
	"""Employees at client sites need the client's approval on file first.

	The employee can apply without it; only the internal approval
	(status -> Approved, which is what allows submit) is blocked.
	"""
	if doc.get("custom_client_approval_required") != "Yes":
		return
	if doc.status != "Approved":
		return

	if doc.get("custom_client_approval_received") != "Yes":
		frappe.throw(
			_(
				"Client approval is required for this leave. Set Client Approval Received to Yes before approving."
			),
			title=_("Client Approval Missing"),
		)
	if not doc.get("custom_client_approval_attachment"):
		frappe.throw(
			_("Attach the client approval (email, letter or document) before approving this leave."),
			title=_("Client Approval Missing"),
		)
