"""Salary Compensation inside the Employee form (tab "Salary Compensation").

HR no longer has to open the Payroll section and create an Employee Compensation record
by hand: the Employee form shows the current package and the history and lets HR change it.
The data stays in Employee Compensation (date-versioned, as Payroll Sheet and Payroll Import
expect: the latest active record with Effective From on or before the posting date wins):

* "Change compensation" creates a NEW record from a chosen date (a raise keeps the old
  record for the earlier months);
* "Correct this record" edits the current record in place (a typing error).

Salary figures are only ever returned to users who may read Employee Compensation (System
Manager, HR Manager, Payroll); a supervisor opening the same employee gets nothing.

``get_salary_view`` is the read-only "Salary" tab for everybody else: an employee sees his OWN
package, a Manager sees the package of the people in his team (never bank details), nobody else
gets anything.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet import COMP_DEDUCTION_FIELDS, EARNING_FIELDS

DT = "Employee Compensation"
COMPONENTS = EARNING_FIELDS + COMP_DEDUCTION_FIELDS


def _check_access(ptype="read"):
	if not frappe.has_permission(DT, ptype):
		frappe.throw(_("You are not allowed to see or change salary compensation."), frappe.PermissionError)


def _fields_spec() -> list[dict]:
	meta = frappe.get_meta(DT)
	return [
		{
			"fieldname": f,
			"label": _(meta.get_label(f)),
			"group": "earning" if f in EARNING_FIELDS else "deduction",
		}
		for f in COMPONENTS
	]


def _summary(doc) -> dict:
	earnings = sum(flt(doc.get(f)) for f in EARNING_FIELDS)
	deductions = sum(flt(doc.get(f)) for f in COMP_DEDUCTION_FIELDS)
	return {
		"name": doc.name,
		"from_date": str(doc.from_date),
		"is_active": cint(doc.is_active),
		"pay_batch": doc.pay_batch,
		"employee_category": doc.employee_category,
		"currency": doc.currency,
		"notes": doc.notes,
		"values": {f: flt(doc.get(f)) for f in COMPONENTS},
		"total_earnings": flt(earnings, 2),
		"total_deductions": flt(deductions, 2),
		"net_fixed": flt(earnings - deductions, 2),
	}


@frappe.whitelist()
def get_for_employee(employee: str) -> dict:
	"""The Salary Compensation tab: current package (the one Payroll uses today) and history."""
	_check_access("read")
	if not frappe.db.exists("Employee", employee):
		frappe.throw(_("Employee {0} was not found.").format(employee))
	records = frappe.get_all(DT, filters={"employee": employee}, pluck="name", order_by="from_date desc, creation desc")
	docs = [frappe.get_doc(DT, name) for name in records]
	current = next((d for d in docs if cint(d.is_active) and getdate(d.from_date) <= getdate(today())), None)
	return {
		"fields": _fields_spec(),
		"can_write": bool(frappe.has_permission(DT, "write")),
		"needs_nationality": not frappe.db.get_value("Employee", employee, "nationality"),
		"currency": (current.currency if current else None) or "SAR",
		"current": _summary(current) if current else None,
		"history": [_summary(d) for d in docs],
	}


@frappe.whitelist()
def save(employee: str, values, from_date=None, record=None, notes=None) -> dict:
	"""Create a new compensation record (from_date) or, with ``record``, correct that one."""
	if isinstance(values, str):
		values = frappe.parse_json(values)
	values = {f: flt(values.get(f)) for f in COMPONENTS}
	if record:
		_check_access("write")
		doc = frappe.get_doc(DT, record)
		if doc.employee != employee:
			frappe.throw(_("{0} does not belong to {1}.").format(record, employee))
		if from_date and getdate(from_date) != getdate(doc.from_date):
			clash = frappe.db.get_value(DT, {"employee": employee, "from_date": getdate(from_date), "name": ["!=", record]})
			if clash:
				frappe.throw(_("Another compensation record exists for {0} from {1}: {2}").format(employee, from_date, clash))
			doc.from_date = from_date
	else:
		_check_access("create")
		if not from_date:
			frappe.throw(_("Effective From is required."))
		clash = frappe.db.get_value(DT, {"employee": employee, "from_date": getdate(from_date)})
		if clash:
			frappe.throw(
				_("A compensation record already exists for {0} from {1}: {2}. Use Correct this record to change it.").format(
					employee, from_date, clash
				)
			)
		latest = frappe.get_all(DT, filters={"employee": employee}, fields=["currency"], order_by="from_date desc", limit=1)
		doc = frappe.new_doc(DT)
		doc.update({"employee": employee, "from_date": from_date, "is_active": 1, "currency": latest[0].currency if latest else "SAR"})
	if not frappe.db.get_value("Employee", employee, "nationality"):
		frappe.throw(_("Set the Nationality on the Overview tab first: it decides the Saudi / Expat category used for GOSI."))
	doc.update(values)
	if notes is not None:
		doc.notes = notes
	doc.save()
	return {"name": doc.name}


def _view_scope(employee: str) -> str | None:
	"""Why the session user may see ``employee``'s salary read-only: "own", "team" or None."""
	user = frappe.session.user
	if frappe.db.get_value("Employee", {"user_id": user}, "name") == employee:
		return "own"
	if "Manager" in frappe.get_roles(user):
		from cooperheat.cooperheat.permissions.scope import get_scope

		if employee in get_scope(user).employees:
			return "team"
	return None


@frappe.whitelist()
def get_salary_view(employee: str) -> dict:
	"""The read-only Salary tab: the current package (no bank details, no history).

	HR Manager, Payroll and System Manager use the editable Salary Compensation tab instead, so
	they get ``allowed: False`` here and the tab stays hidden for them.
	"""
	if frappe.has_permission(DT, "read"):
		return {"allowed": False, "reason": "editable tab"}
	scope = _view_scope(employee)
	if not scope:
		return {"allowed": False, "reason": "not your salary"}
	today_ = getdate(today())
	docs = frappe.get_all(
		DT,
		filters={"employee": employee, "is_active": 1},
		pluck="name",
		order_by="from_date desc, creation desc",
	)
	current = None
	for name in docs:
		doc = frappe.get_doc(DT, name)
		if getdate(doc.from_date) <= today_:
			current = doc
			break
	label = {f["fieldname"]: f["label"] for f in _fields_spec()}
	out = {
		"allowed": True,
		"scope": scope,
		"employee_name": frappe.db.get_value("Employee", employee, "employee_name"),
		"ctc": flt(frappe.db.get_value("Employee", employee, "ctc")),
		"current": None,
	}
	if current:
		summary = _summary(current)
		out["current"] = {
			"from_date": summary["from_date"],
			"currency": summary["currency"],
			"earnings": [
				{"label": label[f], "value": v}
				for f, v in summary["values"].items()
				if v and f in EARNING_FIELDS
			],
			"deductions": [
				{"label": label[f], "value": v}
				for f, v in summary["values"].items()
				if v and f in COMP_DEDUCTION_FIELDS
			],
			"total_earnings": summary["total_earnings"],
			"total_deductions": summary["total_deductions"],
			"net_fixed": summary["net_fixed"],
		}
	return out
