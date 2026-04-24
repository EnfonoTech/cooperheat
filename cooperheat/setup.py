# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


# Field names owned by this app on the Employee doctype.
# (Previously we also owned pay_batch and employee_category; these now live on
# Employee Compensation, so we clean them up on migrate.)
EMPLOYEE_CUSTOM_FIELD_OWNED = {
	"employee_category",
	"pay_batch",
	"cooperheat_payroll_section",
}


def setup_custom_fields():
	# Currently nothing to install on Employee — kept as a hook point for future additions.
	custom_fields = {}
	if custom_fields:
		create_custom_fields(custom_fields, update=True)


def cleanup_legacy_employee_fields():
	for fn in EMPLOYEE_CUSTOM_FIELD_OWNED:
		name = f"Employee-{fn}"
		if frappe.db.exists("Custom Field", name):
			try:
				frappe.delete_doc("Custom Field", name, ignore_permissions=True)
			except Exception:
				frappe.log_error(
					title="failed to delete legacy custom field",
					message=f"{name}",
				)


DEFAULT_SETTINGS = {
	"monthly_working_hours": 240,
	"normal_ot_multiplier": 1.5,
	"holiday_ot_multiplier": 2.0,
	"travel_ot_multiplier": 1.5,
	"gosi_rate_percent": 9.75,
	"gosi_applicable_category": "Saudi",
	"round_amounts": 1,
}


def seed_settings():
	if not frappe.db.exists("DocType", "Pay Sheet Settings"):
		return
	doc = frappe.get_single("Pay Sheet Settings")
	changed = False
	for k, v in DEFAULT_SETTINGS.items():
		if not doc.get(k):
			doc.set(k, v)
			changed = True
	if changed:
		doc.flags.ignore_permissions = True
		doc.save()


def after_install():
	setup_custom_fields()
	seed_settings()


def backfill_compensation_from_date():
	if not frappe.db.exists("DocType", "Employee Compensation"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabEmployee Compensation`
		SET from_date = COALESCE(from_date, DATE(creation), CURDATE())
		WHERE from_date IS NULL OR from_date = '0000-00-00'
		"""
	)


def after_migrate():
	cleanup_legacy_employee_fields()
	setup_custom_fields()
	seed_settings()
	backfill_compensation_from_date()
