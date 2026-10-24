"""A Service Request: an employee asks for something (IT, a repair, a villa issue ...).

It starts with the employee's reporting person. Whoever holds it can FORWARD it to any employee
(the person who can do the work) or COMPLETE / REJECT it; the requester follows every step in the
trail. The holder, not the request, decides where it goes next: no fixed approval chain.

Who sees a request: the requester, the current holder, everybody who held it before, HR Manager and
System Manager. Only the holder (or HR Manager / System Manager) can act.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from cooperheat.cooperheat.service_request_tools import can_act, first_holder, notify


class ServiceRequest(Document):
	def onload(self):
		self.set_onload("can_act", can_act(self))

	def before_insert(self):
		self.requested_by = self.requested_by or frappe.db.get_value(
			"Employee", {"user_id": frappe.session.user}, "name"
		)
		if not self.requested_by:
			frappe.throw(_("Your user is not linked to an Employee, so you cannot raise a request."))
		self.status = "Open"
		self.current_holder = first_holder(self.requested_by)
		self.employee_name = frappe.db.get_value("Employee", self.requested_by, "employee_name")
		self.holder_name = (
			frappe.db.get_value("Employee", self.current_holder, "employee_name")
			if self.current_holder
			else None
		)
		self.append(
			"trail",
			{
				"step_time": now_datetime(),
				"action": "Created",
				"from_employee": self.requested_by,
				"to_employee": self.current_holder,
			},
		)

	def after_insert(self):
		notify(self, self.current_holder, _("New request: {0}").format(self.subject))

	def validate(self):
		"""Status, holder and trail only change through forward / complete / reject."""
		if self.is_new() or self.flags.via_service_request_api:
			return
		before = self.get_doc_before_save()
		if not before:
			return
		for field in ("requested_by", "subject", "details", "status", "current_holder", "completed_on"):
			if self.get(field) != before.get(field):
				frappe.throw(
					_("{0} cannot be changed. Use Forward, Complete or Reject.").format(
						self.meta.get_label(field)
					)
				)
		if len(self.trail) != len(before.trail):
			frappe.throw(_("The trail cannot be changed."))
