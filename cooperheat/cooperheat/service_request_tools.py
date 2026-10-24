"""Service Request: who holds it, who may see and act, and the actions (forward, complete, reject).

Forwarding is the whole routing model: the request starts with the requester's reporting person and
whoever holds it sends it on to any employee until the right person completes it. Every action is
written to the trail on the request, and the new holder gets a notification.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

DT = "Service Request"
SEE_ALL_ROLES = frozenset({"HR Manager", "System Manager"})


# --- who ---------------------------------------------------------------------------------------
def my_employee(user: str | None = None) -> str | None:
	return frappe.db.get_value("Employee", {"user_id": user or frappe.session.user}, "name")


def first_holder(requested_by: str) -> str | None:
	"""The requester's reporting person; failing that the Secondary Reporting person, the Payroll
	Approver; None leaves it with HR Manager / System Manager, who see every request."""
	for field in ("reports_to", "custom_secondary_reporting"):
		holder = frappe.db.get_value("Employee", requested_by, field)
		if holder and holder != requested_by:
			return holder
	from cooperheat.cooperheat.org import payroll_approver

	approver = payroll_approver()
	return approver if approver and approver != requested_by else None


def _sees_all(user: str) -> bool:
	return user == "Administrator" or bool(SEE_ALL_ROLES & set(frappe.get_roles(user)))


def involved(doc, employee: str | None) -> bool:
	if not employee:
		return False
	if employee in (doc.requested_by, doc.current_holder):
		return True
	return any(employee in (s.from_employee, s.to_employee) for s in doc.trail)


def can_act(doc, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if doc.status != "Open":
		return False
	return _sees_all(user) or (bool(doc.current_holder) and my_employee(user) == doc.current_holder)


# --- permission hooks ------------------------------------------------------------------------
def query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	if _sees_all(user):
		return ""
	employee = my_employee(user)
	if not employee:
		return "1=0"
	e = frappe.db.escape(employee)
	return (
		f"(`tab{DT}`.requested_by = {e} or `tab{DT}`.current_holder = {e} or `tab{DT}`.name in "
		f"(select parent from `tabService Request Step` where parenttype = '{DT}' "
		f"and (from_employee = {e} or to_employee = {e})))"
	)


def has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if _sees_all(user):
		return True
	if doc.is_new():
		return bool(my_employee(user))
	if ptype in ("write", "delete", "submit", "cancel"):
		return can_act(doc, user)
	return involved(doc, my_employee(user))


# --- notifications -----------------------------------------------------------------------------
def notify(doc, employee: str | None, subject: str):
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


# --- actions -----------------------------------------------------------------------------------
def _load(name: str):
	"""The request, for somebody who may act on it (the holder, HR Manager, System Manager)."""
	doc = frappe.get_doc(DT, name)
	if not (_sees_all(frappe.session.user) or involved(doc, my_employee())):
		frappe.throw(_("You are not part of this request."), frappe.PermissionError)
	if not can_act(doc):
		frappe.throw(_("Only the person who holds this request can act on it."), frappe.PermissionError)
	return doc


def _act(doc, action: str, to_employee: str | None, comment: str | None):
	if not can_act(doc):
		frappe.throw(_("Only the person who holds this request can act on it."), frappe.PermissionError)
	me = my_employee() or doc.current_holder
	doc.append(
		"trail",
		{
			"step_time": now_datetime(),
			"action": action,
			"from_employee": doc.current_holder or me,
			"to_employee": to_employee,
			"comment": comment or "",
		},
	)
	doc.flags.via_service_request_api = True
	doc.flags.ignore_permissions = True
	return me


@frappe.whitelist()
def forward(name: str, to_employee: str, comment: str | None = None) -> dict:
	doc = _load(name)
	if not frappe.db.exists("Employee", {"name": to_employee, "status": "Active"}):
		frappe.throw(_("Choose an active employee to forward the request to."))
	if to_employee == doc.current_holder:
		frappe.throw(_("The request is already with {0}.").format(doc.holder_name or to_employee))
	_act(doc, "Forwarded", to_employee, comment)
	doc.current_holder = to_employee
	doc.save()
	notify(doc, to_employee, _("Request forwarded to you: {0}").format(doc.subject))
	notify(doc, doc.requested_by, _("Your request moved on: {0}").format(doc.subject))
	return {"name": doc.name, "status": doc.status, "current_holder": doc.current_holder}


def _close(name: str, status: str, comment: str | None) -> dict:
	doc = _load(name)
	_act(doc, "Completed" if status == "Completed" else "Rejected", None, comment)
	doc.status = status
	doc.completed_on = now_datetime()
	doc.save()
	notify(doc, doc.requested_by, _("Your request is {0}: {1}").format(_(status).lower(), doc.subject))
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def complete(name: str, comment: str | None = None) -> dict:
	return _close(name, "Completed", comment)


@frappe.whitelist()
def reject(name: str, comment: str | None = None) -> dict:
	return _close(name, "Rejected", comment)


@frappe.whitelist()
def people(txt: str = "", limit: int = 20) -> list[dict]:
	"""Active employees to forward to (name, designation, department only)."""
	txt = (txt or "").strip()
	filters = {"status": "Active"}
	or_filters = [["employee_name", "like", f"%{txt}%"], ["name", "like", f"%{txt}%"]] if txt else None
	return frappe.get_all(
		"Employee",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "employee_name", "designation", "department"],
		order_by="employee_name asc",
		limit_page_length=int(limit),
		ignore_permissions=True,
	)


@frappe.whitelist()
def mine() -> dict:
	"""For the home tile and the app: what I raised, and what waits for me."""
	employee = my_employee()
	if not employee:
		return {"raised": [], "waiting": []}
	fields = [
		"name",
		"subject",
		"status",
		"current_holder",
		"holder_name",
		"requested_by",
		"employee_name",
		"modified",
	]
	return {
		"raised": frappe.get_all(
			DT,
			filters={"requested_by": employee},
			fields=fields,
			order_by="modified desc",
			limit_page_length=50,
			ignore_permissions=True,
		),
		"waiting": frappe.get_all(
			DT,
			filters={"current_holder": employee, "status": "Open"},
			fields=fields,
			order_by="modified desc",
			limit_page_length=50,
			ignore_permissions=True,
		),
	}
