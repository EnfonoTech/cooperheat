import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class DepartmentApprovalMatrix(Document):
	def validate(self):
		if cint(self.approval_level) < 1:
			frappe.throw(_("Approval Level must be 1 or greater"))
		if cint(self.approval_window_hours) < 0:
			frappe.throw(_("Approval Window Hours cannot be negative"))
