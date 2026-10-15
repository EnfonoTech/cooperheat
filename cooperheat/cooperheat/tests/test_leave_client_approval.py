import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat.overrides.leave_application import validate_client_approval


def leave(**values):
	return frappe._dict({"status": "Open", **values})


class TestLeaveClientApproval(FrappeTestCase):
	def test_not_required_never_blocks(self):
		validate_client_approval(leave(status="Approved", custom_client_approval_required="Not Required"))
		validate_client_approval(leave(status="Approved"))

	def test_open_application_without_evidence_is_allowed(self):
		validate_client_approval(leave(custom_client_approval_required="Yes"))

	def test_rejecting_without_evidence_is_allowed(self):
		validate_client_approval(leave(status="Rejected", custom_client_approval_required="Yes"))

	def test_approving_without_client_approval_is_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			validate_client_approval(
				leave(status="Approved", custom_client_approval_required="Yes", custom_client_approval_received="No")
			)

	def test_approving_without_attachment_is_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			validate_client_approval(
				leave(status="Approved", custom_client_approval_required="Yes", custom_client_approval_received="Yes")
			)

	def test_approving_with_evidence_passes(self):
		validate_client_approval(
			leave(
				status="Approved",
				custom_client_approval_required="Yes",
				custom_client_approval_received="Yes",
				custom_client_approval_attachment="/private/files/client-ok.pdf",
			)
		)
