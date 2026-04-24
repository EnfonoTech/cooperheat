# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PaySheetSettings(Document):
	def validate(self):
		if self.monthly_working_hours and self.monthly_working_hours <= 0:
			frappe.throw(_("Monthly Working Hours must be greater than zero."))
		if self.gosi_rate_percent is not None and self.gosi_rate_percent < 0:
			frappe.throw(_("GOSI Rate cannot be negative."))

		seen = set()
		for row in self.component_mapping or []:
			if not row.payroll_field or not row.salary_component:
				continue
			if row.payroll_field in seen:
				frappe.throw(
					_("Payroll field {0} is mapped more than once.").format(row.payroll_field)
				)
			seen.add(row.payroll_field)


DEFAULT_MAPPING = [
	("basic", "Basic", "Earning"),
	("housing_allowance", "Housing Allowance", "Earning"),
	("transport_allowance", "Transport Allowance", "Earning"),
	("living_allowance", "Living Allowance", "Earning"),
	("service_allowance", "Service Allowance", "Earning"),
	("driving_allowance", "Driving Allowance", "Earning"),
	("merit_award", "Merit Award", "Earning"),
	("aramco_certification", "Aramco Certification", "Earning"),
	("supervisor_allowance", "Supervisor Allowance", "Earning"),
	("education_allowance", "Education Allowance", "Earning"),
	("rso_allowance", "RSO Allowance", "Earning"),
	("rpp_allowance", "RPP Allowance", "Earning"),
	("other_allowance", "Other Allowance", "Earning"),
	("total_ot_amount", "Overtime", "Earning"),
	("others", "Others", "Earning"),
	("bonus", "Bonus", "Earning"),
	("expenses", "Expenses", "Earning"),
	("air_fare", "Air Fare", "Earning"),
	("vacation_pay", "Vacation Pay", "Earning"),
	("gratuity", "Gratuity", "Earning"),
	("retention", "Retention", "Earning"),
	("gosi", "GOSI", "Deduction"),
	("general_advance", "General Advance", "Deduction"),
	("housing_advance", "Housing Advance", "Deduction"),
	("housing_deduction", "Housing Deduction", "Deduction"),
	("transport_deduction", "Transport Deduction", "Deduction"),
	("education_deduction", "Education Deduction", "Deduction"),
	("retention_deduction", "Retention Deduction", "Deduction"),
	("other_deduction", "Other Deduction", "Deduction"),
]


@frappe.whitelist()
def setup_defaults():
	"""Seed default mapping, create missing Salary Components, ensure default Salary Structure."""
	frappe.only_for(["System Manager", "HR Manager"])
	settings = frappe.get_single("Pay Sheet Settings")

	components_created = []
	for _field, comp, ctype in DEFAULT_MAPPING:
		if frappe.db.exists("Salary Component", comp):
			# Ensure existing component won't re-scale our amounts
			if frappe.db.get_value("Salary Component", comp, "depends_on_payment_days") != 0:
				frappe.db.set_value("Salary Component", comp, "depends_on_payment_days", 0)
		else:
			sc = frappe.new_doc("Salary Component")
			sc.salary_component = comp
			sc.salary_component_abbr = _abbr(comp)
			sc.type = ctype
			sc.depends_on_payment_days = 0
			sc.flags.ignore_permissions = True
			sc.insert()
			components_created.append(comp)

	mapping_added = 0
	if not settings.component_mapping:
		for field, comp, ctype in DEFAULT_MAPPING:
			settings.append("component_mapping", {
				"payroll_field": field,
				"salary_component": comp,
				"component_type": ctype,
			})
			mapping_added += 1

	structure_created = False
	if not settings.default_salary_structure:
		name = "Cooperheat Default"
		if not frappe.db.exists("Salary Structure", name):
			ss = frappe.new_doc("Salary Structure")
			ss.name = name
			ss.is_active = "Yes"
			ss.company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
			ss.payroll_frequency = "Monthly"
			ss.currency = frappe.defaults.get_global_default("currency") or "SAR"
			ss.flags.ignore_permissions = True
			ss.insert()
			ss.submit()
			structure_created = True
		settings.default_salary_structure = name

	settings.flags.ignore_permissions = True
	settings.save()

	return {
		"components_created": components_created,
		"mapping_added": mapping_added,
		"structure_created": structure_created,
		"default_structure": settings.default_salary_structure,
	}


def _abbr(name):
	return "".join(w[0] for w in name.split() if w).upper()[:10]
