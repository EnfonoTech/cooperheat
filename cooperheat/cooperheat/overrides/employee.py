# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from cooperheat.cooperheat.permissions.scope import on_employee_update as _sync_user_permissions


def before_validate(doc, method=None):
	from cooperheat.cooperheat.org import fill_default_approvers, fill_secondary_reporting, sync_employee_org

	from cooperheat.cooperheat.work_schedule import sync_work_schedule

	sync_employee_org(doc)
	sync_work_schedule(doc)
	_default_pay_batch(doc)
	fill_secondary_reporting(doc)
	fill_default_approvers(doc)


def on_update(doc, method=None):
	_sync_user_permissions(doc, method)
	_propagate_pay_batch(doc)
	_restamp_pending_approvals(doc)
	_recompute_overtime_for_category(doc)


def _recompute_overtime_for_category(doc):
	"""Staff Category set or changed: overtime already stored on this person's recent
	attendance (last 60 days) is re-derived, so nothing has to be run by hand."""
	if doc.flags.in_insert or not doc.has_value_changed("custom_staff_category"):
		return
	from frappe.utils import add_days, today

	from cooperheat.cooperheat.overtime import recompute_range

	recompute_range(add_days(today(), -60), today(), employee=doc.name, dry_run=False)


def _restamp_pending_approvals(doc):
	"""Reporting line changed: Attendance still waiting on the old approver moves with it."""
	if doc.flags.in_insert:
		return
	if doc.has_value_changed("reports_to") or doc.has_value_changed("custom_secondary_reporting"):
		from cooperheat.cooperheat.org import restamp_pending_attendance

		restamp_pending_attendance(doc.name)


def _default_pay_batch(doc):
	"""New joiners go into the Main batch. Without a batch, a payroll run for
	Main silently leaves them out."""
	if doc.meta.has_field("custom_pay_batch") and not doc.get("custom_pay_batch") and frappe.db.exists("Pay Batch", "Main"):
		doc.custom_pay_batch = "Main"


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
