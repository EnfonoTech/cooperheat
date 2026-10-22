"""Who may see and change what on the Employee record (client request 2026-10-22).

Before: the stock "Employee Self Service" role could WRITE every field of any Employee it could
read (its own record, or a supervisor's team through the team scope), and no field was
protected: CTC, bank details, joining date, compensation were visible and editable by all.

Now (three levels, set once by ``ensure_employee_field_security`` from after_migrate):

* level 0 - name, contact, department, reporting line, schedule ... : everybody who may read
  the employee sees it; only HR User, HR Manager (and System Manager) may change it.
  Employee, Employee Self Service, Supervisor and Manager are read-only.
* level 1 - HR-sensitive: joining / confirmation / contract / retirement / exit dates,
  employment type, grade, identity documents (Iqama, passport), family and health data,
  date of birth: HR User, HR Manager, System Manager. Invisible to everybody else.
* level 2 - pay: CTC, salary currency and mode, bank details, payroll cost centre, Pay Batch,
  the Salary Compensation tab: HR Manager and System Manager only (like Employee
  Compensation itself). Invisible to everybody else, HR User included.

Fields at level 1 and 2 are not rendered and are stripped from API reads for users without
the role at that level. Roles are only ADDED at levels 1 and 2; the one reduction is the
"Employee Self Service" write right at level 0.
"""

import frappe

LEVEL_1 = [
	"date_of_birth", "date_of_joining", "scheduled_confirmation_date", "final_confirmation_date",
	"contract_end_date", "notice_number_of_days", "date_of_retirement", "employment_type", "grade",
	"job_applicant", "marital_status", "family_background", "blood_group", "health_details",
	"passport_number", "valid_upto", "date_of_issue", "place_of_issue", "custom_iqama_number",
	"custom_id_type", "custom_expairy_date", "bio", "resignation_letter_date", "relieving_date",
	"held_on", "new_workplace", "leave_encashed", "encashment_date", "reason_for_leaving",
	"feedback", "health_insurance_provider", "health_insurance_no",
]  # fmt: skip

LEVEL_2 = [
	"ctc", "salary_currency", "salary_mode", "bank_details_section", "bank_name", "bank_ac_no", "iban",
	"payroll_cost_center", "custom_pay_batch", "salary_information", "custom_compensation_tab",
	"custom_compensation_html",
]  # fmt: skip

# role -> (read, write) at each level (rows are added only when that role has no row at the level yet)
LEVEL_ROLES = {
	1: {"HR User": (1, 1), "HR Manager": (1, 1), "System Manager": (1, 1)},
	2: {"HR Manager": (1, 1), "System Manager": (1, 1)},
}

# level-0 roles that must not write (their read right stays)
READ_ONLY_AT_LEVEL_0 = ("Employee Self Service", "Employee", "Supervisor", "Manager")


def _fields_present(doctype_fields: list[str]) -> list[str]:
	existing = {f.fieldname for f in frappe.get_meta("Employee", cached=False).fields}
	return [f for f in doctype_fields if f in existing]


def ensure_employee_field_security():
	"""Idempotent. Returns what it changed (for the production log)."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists("DocType", "Employee"):
		return {}
	changed = {"fields": 0, "roles_added": [], "write_removed": []}
	for level, fields in ((1, LEVEL_1), (2, LEVEL_2)):
		for fieldname in _fields_present(fields):
			if frappe.db.get_value(
				"Property Setter",
				{"doc_type": "Employee", "field_name": fieldname, "property": "permlevel"},
				"value",
			) != str(level):
				make_property_setter("Employee", fieldname, "permlevel", level, "Int")
				changed["fields"] += 1
	for level, roles in LEVEL_ROLES.items():
		for role, (read, write) in roles.items():
			if not frappe.db.exists("Role", role):
				continue
			if frappe.db.exists("Custom DocPerm", {"parent": "Employee", "role": role, "permlevel": level}):
				continue
			add_permission("Employee", role, level)
			for ptype, value in (("read", read), ("write", write)):
				update_permission_property("Employee", role, level, ptype, value)
			changed["roles_added"].append(f"{role}@{level}")
	for name, role in frappe.get_all(
		"Custom DocPerm",
		filters={
			"parent": "Employee",
			"permlevel": 0,
			"role": ["in", list(READ_ONLY_AT_LEVEL_0)],
			"write": 1,
		},
		fields=["name", "role"],
		as_list=True,
	):
		frappe.db.set_value("Custom DocPerm", name, {"write": 0, "create": 0, "delete": 0})
		changed["write_removed"].append(role)
	# the stock (non-custom) permission table is only used while the doctype has no Custom DocPerm
	# rows of its own; this site has them, so nothing to change there.
	frappe.clear_cache(doctype="Employee")
	return changed
