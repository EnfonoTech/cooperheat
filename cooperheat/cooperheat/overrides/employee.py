# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from cooperheat.cooperheat.permissions.scope import on_employee_update as _sync_user_permissions


def before_validate(doc, method=None):
	_auto_link_reports_to(doc)


def on_update(doc, method=None):
	_sync_user_permissions(doc, method)
	_propagate_pay_batch(doc)


def _auto_link_reports_to(doc):
	"""A new joiner (or anyone saved without a manager) is linked to the nearest
	approver of their Department's approval matrix: Level 1 first, then 2, 3.
	An employee is never linked to themself."""
	if doc.get("reports_to") or not doc.get("department"):
		return
	rows = frappe.get_all(
		"Department Approval Matrix",
		filters={"parent": doc.department, "parentfield": "approval_matrix"},
		fields=["approval_level", "approver"],
		order_by="approval_level asc",
	)
	for row in rows:
		if row.approver and row.approver != doc.name:
			doc.reports_to = row.approver
			return


def _propagate_pay_batch(doc):
	"""Employee.custom_pay_batch is the source of truth; keep the active
	Employee Compensation record (which the Payroll Sheet copies) in step."""
	batch = doc.get("custom_pay_batch")
	if not batch or not doc.has_value_changed("custom_pay_batch"):
		return
	for name in frappe.get_all("Employee Compensation", filters={"employee": doc.name, "is_active": 1}, pluck="name"):
		frappe.db.set_value("Employee Compensation", name, "pay_batch", batch, update_modified=False)


def effective_pay_batch(employee: str) -> str | None:
	"""The batch an employee is paid in: their own setting, else the active compensation record's."""
	batch = frappe.db.get_value("Employee", employee, "custom_pay_batch")
	if batch:
		return batch
	return frappe.db.get_value(
		"Employee Compensation", {"employee": employee, "is_active": 1}, "pay_batch", order_by="from_date desc"
	)
