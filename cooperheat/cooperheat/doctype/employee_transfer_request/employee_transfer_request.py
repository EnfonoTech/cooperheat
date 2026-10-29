# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Move an employee to another Business Line / Product Line or Division (client, 2026-10-28).

HR raises the request with a reason; the manager of the RECEIVING Business Line / Division
approves it. Only on that approval does the Employee change (Business Line, Product Line or
Department, and optionally the Direct / Immediate Reporting person).
"""

from collections import Counter

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from cooperheat.cooperheat import org

DT = "Employee Transfer Request"
OPEN, APPROVED, REJECTED = "Pending Approval", "Approved", "Rejected"
_SEES_ALL = {"HR Manager", "HR User", "System Manager"}


class EmployeeTransferRequest(Document):
	def validate(self):
		self._check_requester()
		self._fill_from()
		self._check_target()
		if not self.approver:
			self.approver = suggest_approver(self.to_business_line, self.to_department)
		if not self.approver:
			frappe.throw(_("Please choose the receiving manager who approves this transfer."))
		if self.approver == self.employee:
			frappe.throw(_("The employee cannot approve their own transfer."))
		approver_user = frappe.db.get_value("Employee", self.approver, "user_id")
		if not approver_user:
			frappe.throw(_("The receiving manager has no user account, so cannot approve."))
		if approver_user == (self.owner or frappe.session.user) and approver_user != "Administrator":
			frappe.throw(_("The person who raises a transfer cannot also approve it."))
		before = self.get_doc_before_save()
		if before and before.status in (APPROVED, REJECTED) and not self.flags.deciding:
			frappe.throw(_("This transfer is already decided."))
		if self.status == "Draft":
			self.status = OPEN

	def on_update(self):
		before = self.get_doc_before_save()
		if self.status == OPEN and (not before or before.status != OPEN or before.approver != self.approver):
			_notify(self, self.approver, _("Transfer of {0} waits for your approval").format(self.employee_name))

	def _check_requester(self):
		"""HR raises a transfer for anyone; a supervisor or manager only for their own team (client, 29 Oct)."""
		user = frappe.session.user
		if self.flags.deciding or _sees_all(user):
			return
		if not _in_team(user, self.employee):
			frappe.throw(_("You can raise a transfer only for employees of your own team."), frappe.PermissionError)

	def _fill_from(self):
		emp = frappe.db.get_value(
			"Employee",
			self.employee,
			["custom_business_line", "custom_product_line", "department", "reports_to"],
			as_dict=True,
		)
		if not emp:
			frappe.throw(_("Employee not found."))
		if self.status in (APPROVED, REJECTED):
			return
		self.from_business_line = emp.custom_business_line
		self.from_product_line = emp.custom_product_line
		self.from_department = emp.department
		self.from_reports_to = emp.reports_to

	def _check_target(self):
		if not (self.to_business_line or self.to_department):
			frappe.throw(_("Choose the Business Line, or the Department, the employee moves to."))
		if self.to_business_line:
			self.to_department = None
			if org.unit_type(self.to_business_line) != org.BUSINESS_LINE:
				frappe.throw(_("{0} is not a Business Line.").format(frappe.bold(self.to_business_line)))
			if self.to_product_line:
				if org.unit_type(self.to_product_line) not in org.PRODUCT_TYPES:
					frappe.throw(_("{0} is not a Product Line.").format(frappe.bold(self.to_product_line)))
				if org.nearest_of_type(self.to_product_line, org.BUSINESS_LINE) != self.to_business_line:
					frappe.throw(_("This Product Line does not belong to that Business Line."))
			same = (self.to_business_line, self.to_product_line or None) == (
				self.from_business_line,
				self.from_product_line or None,
			)
		else:
			self.to_product_line = None
			same = self.to_department == self.from_department
		if same and not self.new_reports_to:
			frappe.throw(_("The employee is already there."))


# --- receiving manager --------------------------------------------------------------------------
@frappe.whitelist()
def suggest_approver(business_line: str | None = None, department: str | None = None) -> str | None:
	"""The manager of the receiving unit: the Business Line head (placed on the Business Line
	with no Product Line), else the person most of its people report to."""
	if business_line:
		heads = frappe.get_all(
			"Employee",
			filters={
				"status": "Active",
				"custom_business_line": business_line,
				"custom_product_line": ["is", "not set"],
				"user_id": ["is", "set"],
			},
			pluck="name",
			order_by="creation asc",
		)
		if heads:
			return heads[0]
		units = list(org.descendants([business_line]))
	else:
		units = list(org.descendants([department])) if department else []
	if not units:
		return None
	bosses = frappe.get_all(
		"Employee",
		filters={"status": "Active", "department": ["in", units], "reports_to": ["is", "set"]},
		pluck="reports_to",
	)
	for boss, _count in Counter(bosses).most_common():
		if boss and frappe.db.get_value("Employee", boss, "user_id"):
			return boss
	return None


# --- decisions ----------------------------------------------------------------------------------
def _load_for_decision(name: str):
	doc = frappe.get_doc(DT, name)
	if doc.status != OPEN:
		frappe.throw(_("This transfer is already decided."))
	user = frappe.session.user
	if user != "Administrator" and user != frappe.db.get_value("Employee", doc.approver, "user_id"):
		frappe.throw(_("Only the receiving manager can decide this transfer."), frappe.PermissionError)
	return doc


@frappe.whitelist()
def approve(name: str) -> dict:
	doc = _load_for_decision(name)
	emp = frappe.get_doc("Employee", doc.employee)
	if doc.to_business_line:
		emp.custom_business_line = doc.to_business_line
		emp.custom_product_line = doc.to_product_line
	else:
		emp.custom_business_line = None
		emp.custom_product_line = None
		emp.department = doc.to_department
	if doc.new_reports_to:
		emp.reports_to = doc.new_reports_to
	emp.flags.ignore_permissions = True
	emp.save()  # sync_employee_org sets the department from Business Line / Product Line
	emp.add_comment("Comment", text=_("Transferred by {0}, approved by {1}: {2}").format(doc.name, doc.approver_name, doc.reason))
	_decide(doc, APPROVED)
	_notify(doc, _requester(doc), _("Transfer of {0} approved").format(doc.employee_name))
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def reject(name: str, reason: str) -> dict:
	if not (reason or "").strip():
		frappe.throw(_("Please give the reason for the rejection."))
	doc = _load_for_decision(name)
	doc.rejection_reason = reason
	_decide(doc, REJECTED)
	_notify(doc, _requester(doc), _("Transfer of {0} rejected").format(doc.employee_name))
	return {"name": doc.name, "status": doc.status}


def _requester(doc) -> str | None:
	return frappe.db.get_value("Employee", {"user_id": doc.owner}, "name")


def _decide(doc, status: str):
	doc.status = status
	doc.decided_on = now_datetime()
	doc.flags.deciding = True
	doc.flags.ignore_permissions = True
	doc.save()


def _notify(doc, employee: str | None, subject: str):
	user = frappe.db.get_value("Employee", employee, "user_id") if employee else None
	if not user or user == frappe.session.user:
		return
	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": user,
			"from_user": frappe.session.user,
			"type": "Alert",
			"subject": subject,
			"document_type": DT,
			"document_name": doc.name,
		}
	).insert(ignore_permissions=True)


# --- who sees what ------------------------------------------------------------------------------
def _sees_all(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & _SEES_ALL)


def _in_team(user: str, employee: str | None) -> bool:
	from cooperheat.cooperheat.permissions.scope import get_scope

	return bool(employee) and employee in get_scope(user).employees


def query_conditions(user=None, doctype=None):
	"""HR sees every transfer; anyone else the ones they raised, approve, or of their own team."""
	user = user or frappe.session.user
	if _sees_all(user):
		return ""
	from cooperheat.cooperheat.permissions.scope import _in_clause, get_scope

	team = get_scope(user).employees
	esc = frappe.db.escape(user)
	mine = "`tabEmployee Transfer Request`.`approver_user` = " + esc + " or `tabEmployee Transfer Request`.`owner` = " + esc
	return "(" + mine + " or " + _in_clause("`tabEmployee Transfer Request`.`employee`", team) + ")"


def has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if _sees_all(user):
		return None
	if ptype in ("create", "write"):
		# a supervisor raises (and may correct, while it waits) a transfer for their own team;
		# decisions still go through approve / reject
		if doc.get("status") in (APPROVED, REJECTED):
			return False
		if not doc.is_new() and doc.get("owner") != user:
			return False
		return None if not doc.get("employee") or _in_team(user, doc.get("employee")) else False
	if ptype not in (None, "read", "print", "email", "report", "export"):
		return False
	if user in (doc.get("approver_user"), doc.get("owner")):
		return None
	return None if _in_team(user, doc.get("employee")) else False
