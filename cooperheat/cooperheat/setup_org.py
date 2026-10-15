"""Create the Cooperheat organisation tree (idempotent).

`create_structure(company)` builds the support divisions and the operations
business lines / product lines agreed in the 2026-10-05 meeting, plus the
locations. Existing departments are re-used by name; nothing is deleted.

`uat_demo()` additionally places the UAT test employees and approvers. It
refuses to run outside developer mode, so it can never touch production.

	bench --site <site> execute cooperheat.cooperheat.setup_org.create_structure --kwargs "{'company': '...'}"
"""

import frappe
from frappe import _

from cooperheat.cooperheat import org

# (name, unit type, parent name or None, is_group)
STRUCTURE = [
	("Management", "Division", None, 1),
	("HSEQ Division", "Division", None, 1),
	("HSEQ", "Department", "HSEQ Division", 0),
	("Operations Division", "Division", None, 1),
	("Operations Support", "Department", "Operations Division", 0),
	("Finance Division", "Division", None, 1),
	("Finance", "Department", "Finance Division", 0),
	("Procurement", "Department", "Finance Division", 1),
	("Logistics", "Department", "Procurement", 0),
	("Store", "Department", "Finance Division", 1),
	("Equipment, Tools & Assets", "Department", "Store", 0),
	("ICT", "Department", "Finance Division", 0),
	("Cost & Estimation", "Department", "Finance Division", 0),
	("Sales Division", "Division", None, 1),
	("Sales Team", "Department", "Sales Division", 0),
	("HR Division", "Division", None, 1),
	("HR", "Department", "HR Division", 0),
	("Admin", "Department", "HR Division", 0),
	("PRO", "Department", "HR Division", 0),
	("Recruitment", "Department", "HR Division", 0),
	("Inspection Business Line", org.BUSINESS_LINE, None, 1),
	("TPI", org.PRODUCT_LINE, "Inspection Business Line", 0),
	("ANDT", org.PRODUCT_LINE, "Inspection Business Line", 0),
	("CNDT", org.PRODUCT_LINE, "Inspection Business Line", 1),
	("RSO Team", org.PRODUCT_LINE, "CNDT", 0),
	("NDT Team", org.PRODUCT_LINE, "CNDT", 0),
	("Specialized Mechanical Services Business Line", org.BUSINESS_LINE, None, 1),
	("HTLS", org.PRODUCT_LINE, "Specialized Mechanical Services Business Line", 0),
	("Online Leak Sealing", org.PRODUCT_LINE, "Specialized Mechanical Services Business Line", 0),
	("Heat Treatment Business Line", org.BUSINESS_LINE, None, 1),
	("Fabrication Business Line", org.BUSINESS_LINE, None, 1),
]

# Business lines carry their full name (client request 2026-10-11).
RENAMES = {
	"Inspection": "Inspection Business Line",
	"Specialized Mechanical Services": "Specialized Mechanical Services Business Line",
	"Heat Treatment": "Heat Treatment Business Line",
	"Fabrication": "Fabrication Business Line",
}

# (location, parent group or None, is_group)
LOCATIONS = [
	("Eastern Province", None, 1),
	("Jubail", "Eastern Province", 0),
	("Dammam", "Eastern Province", 0),
	("Western Province", None, 1),
	("Yanbu", "Western Province", 0),
]


def dept(company, department_name):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	return department_name + " - " + abbr


@frappe.whitelist()
def create_structure(company):
	frappe.only_for(("System Manager", "HR Manager"))
	created = []
	for name, parent, is_group in LOCATIONS:
		if not frappe.db.exists("Location", name):
			frappe.get_doc(
				{"doctype": "Location", "location_name": name, "parent_location": parent, "is_group": is_group}
			).insert()
			created.append(name)

	for old, new in RENAMES.items():
		if frappe.db.exists("Department", dept(company, old)) and not frappe.db.exists("Department", dept(company, new)):
			frappe.rename_doc("Department", dept(company, old), dept(company, new), force=True)
			frappe.db.set_value("Department", dept(company, new), "department_name", new)
			created.append(dept(company, new))

	for name, unit_type, parent, is_group in STRUCTURE:
		full = dept(company, name)
		parent_full = dept(company, parent) if parent else "All Departments"
		if frappe.db.exists("Department", full):
			doc = frappe.get_doc("Department", full)
			changed = False
			for field, value in (("custom_unit_type", unit_type), ("parent_department", parent_full)):
				if doc.get(field) != value:
					doc.set(field, value)
					changed = True
			if is_group and not doc.is_group:
				doc.is_group, changed = 1, True
			if changed:
				doc.save()
			continue
		frappe.get_doc(
			{
				"doctype": "Department",
				"department_name": name,
				"company": company,
				"parent_department": parent_full,
				"is_group": is_group,
				"custom_unit_type": unit_type,
			}
		).insert()
		created.append(full)
	org.clear_cache()
	return created


@frappe.whitelist()
def remove_unlisted(company, keep=None, dry_run=1):
	"""Departments of `company` that are not in STRUCTURE (or `keep`):
	deleted when nothing points at them, otherwise disabled (history kept).

	`dry_run=1` only reports.
	"""
	frappe.only_for(("System Manager", "HR Manager"))
	from frappe.utils import cint

	keep = set(frappe.parse_json(keep) if isinstance(keep, str) else (keep or []))
	wanted = {dept(company, name) for name, *_ in STRUCTURE} | {dept(company, k) for k in keep}
	report = {"delete": [], "disable": [], "kept": sorted(wanted)}
	candidates = frappe.get_all(
		"Department", filters={"company": company, "name": ["not in", list(wanted)]}, fields=["name", "disabled"], order_by="rgt desc"
	)
	for row in candidates:
		in_use = any(
			frappe.db.exists(doctype, {"department": row.name})
			for doctype in ("Employee", "Attendance", "Leave Application", "Salary Slip", "Expense Claim", "Shift Assignment")
		) or frappe.db.exists("Department", {"parent_department": row.name})
		if in_use:
			if not row.disabled:
				report["disable"].append(row.name)
				if not cint(dry_run):
					frappe.db.set_value("Department", row.name, "disabled", 1)
		else:
			report["delete"].append(row.name)
			if not cint(dry_run):
				frappe.delete_doc("Department", row.name, ignore_permissions=True)
	org.clear_cache()
	return report


@frappe.whitelist()
def backfill_employees(company, dry_run=1):
	"""Fill Business Line / Product Line and empty approvers on existing employees.

	Writes with db.set_value (no save), so no other hooks run. `dry_run=1`
	only reports what would change.
	"""
	frappe.only_for(("System Manager", "HR Manager"))
	from frappe.utils import cint

	changes = []
	for name in frappe.get_all("Employee", filters={"company": company, "status": "Active"}, pluck="name"):
		doc = frappe.get_doc("Employee", name)
		before = {f: doc.get(f) for f in BACKFILL_FIELDS}
		org.sync_employee_org(doc)
		org.fill_default_approvers(doc)
		after = {f: doc.get(f) for f in BACKFILL_FIELDS}
		diff = {f: after[f] for f in BACKFILL_FIELDS if after[f] != before[f]}
		if diff:
			changes.append({"employee": name, **diff})
			if not cint(dry_run):
				frappe.db.set_value("Employee", name, diff, update_modified=False)
	return changes


BACKFILL_FIELDS = (
	"department",
	"custom_business_line",
	"custom_product_line",
	"leave_approver",
	"shift_request_approver",
	"expense_approver",
)


@frappe.whitelist()
def uat_demo():
	"""UAT only: place the test employees and approvers in the new tree."""
	frappe.only_for("System Manager")
	if not frappe.conf.developer_mode:
		frappe.throw(_("uat_demo only runs on a developer-mode (UAT) site."))
	from cooperheat.cooperheat import dev_seed

	company = dev_seed.COMPANY
	create_structure(company)

	def d(name):
		return dept(company, name)

	def emp(key):
		return frappe.db.get_value("Employee", {"user_id": dev_seed.email(key)}, "name")

	khalid, irtaza, mustafa = (emp(k) for k in ("khalid", "irtaza", "mustafa"))

	# The seeded Leak Sealing / Contracting teams become product lines of SMS.
	for seeded in ("Leak Sealing", "Contracting"):
		doc = frappe.get_doc("Department", dev_seed.dept_name(seeded))
		doc.parent_department = d("Specialized Mechanical Services Business Line")
		doc.custom_unit_type = org.PRODUCT_LINE
		doc.save()

	def demo_person(first, user_key, roles=("Employee", "Supervisor"), **values):
		email = dev_seed.email(user_key)
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": first, "send_welcome_email": 0, "user_type": "System User"}
			)
			user.flags.no_welcome_mail = True
			user.insert(ignore_permissions=True)
			user.add_roles(*roles)
		name = frappe.db.get_value("Employee", {"user_id": email})
		if name:
			return name
		return (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": first,
					"last_name": "Demo",
					"gender": "Male",
					"date_of_birth": "1988-01-01",
					"date_of_joining": "2026-01-01",
					"company": company,
					"status": "Active",
					"user_id": email,
					**values,
				}
			)
			.insert()
			.name
		)

	# Dedicated approvers, so the seeded supervisors' teams stay exactly as tested.
	insp_mgr = demo_person("Inspection Manager", "inspection.manager", custom_business_line=d("Inspection Business Line"))
	sup_jub = demo_person("NDT Supervisor Jubail", "ndt.jubail", custom_product_line=d("NDT Team"), custom_assigned_location="Jubail")
	sup_yan = demo_person("NDT Supervisor Yanbu", "ndt.yanbu", custom_product_line=d("NDT Team"), custom_assigned_location="Yanbu")

	def matrix(name, rows):
		doc = frappe.get_doc("Department", d(name))
		wanted = [(lvl, who, loc) for lvl, who, loc in rows]
		have = [(r.approval_level, r.approver, r.location) for r in doc.approval_matrix]
		if have == wanted:
			return
		doc.approval_matrix = []
		for level, approver, location in rows:
			doc.append(
				"approval_matrix",
				{"approval_level": level, "approver": approver, "approval_window_hours": 48, "location": location},
			)
		doc.save()

	matrix("Inspection Business Line", [(2, insp_mgr, None), (3, irtaza, None)])
	matrix("NDT Team", [(1, sup_jub, "Jubail"), (1, sup_yan, "Yanbu")])
	matrix("Specialized Mechanical Services Business Line", [(2, khalid, None), (3, irtaza, None)])
	matrix("Heat Treatment Business Line", [(3, irtaza, None)])
	matrix("Fabrication Business Line", [(3, irtaza, None)])
	matrix("Finance Division", [(1, mustafa, None), (3, irtaza, None)])
	matrix("HR Division", [(1, irtaza, None)])

	def place(employee, **values):
		doc = frappe.get_doc("Employee", employee)
		doc.update(values)
		doc.save()

	place(khalid, custom_business_line=d("Specialized Mechanical Services Business Line"), custom_product_line=None)
	place(mustafa, department=d("ICT"))
	place(irtaza, department=d("HR"))

	for first, location in (("NDT Jubail 1", "Jubail"), ("NDT Jubail 2", "Jubail"), ("NDT Yanbu 1", "Yanbu")):
		if frappe.db.exists("Employee", {"first_name": first, "company": company}):
			continue
		frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": first,
				"last_name": "Demo",
				"gender": "Male",
				"date_of_birth": "1994-01-01",
				"date_of_joining": "2026-01-01",
				"company": company,
				"status": "Active",
				"custom_product_line": d("NDT Team"),
				"custom_assigned_location": location,
			}
		).insert()
	# Re-resolve manager + approvers for the demo people now that every matrix exists.
	demo = set(frappe.get_all("Employee", filters={"department": d("NDT Team")}, pluck="name")) | {insp_mgr}
	for name in demo:
		frappe.db.set_value(
			"Employee",
			name,
			{"reports_to": None, "leave_approver": None, "shift_request_approver": None, "expense_approver": None},
			update_modified=False,
		)
		org.clear_cache()
		frappe.get_doc("Employee", name).save()

	# On UAT the seeded Leak Sealing team plays Online Leak Sealing; drop the empty twin.
	twin = d("Online Leak Sealing")
	if frappe.db.exists("Department", twin) and not frappe.db.exists("Employee", {"department": twin}):
		frappe.delete_doc("Department", twin)
	org.clear_cache()
	backfill_employees(company, dry_run=0)

	# Work schedule: office people vs field people.
	office = {mustafa, irtaza}
	for name in frappe.get_all("Employee", filters={"company": company, "status": "Active"}, pluck="name"):
		category = "Office Staff" if name in office else "Field Staff"
		if frappe.db.get_value("Employee", name, "custom_staff_category") != category:
			doc = frappe.get_doc("Employee", name)
			doc.custom_staff_category = category
			doc.default_shift = None
			doc.save()

	# Only the agreed structure (plus the seeded UAT test teams) stays.
	return remove_unlisted(company, keep=["Leak Sealing", "Contracting", "NDT"], dry_run=0)
