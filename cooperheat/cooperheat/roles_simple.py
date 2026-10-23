"""A short, named set of roles for Cooperheat (client request, meeting of 2026-10-22).

The client's HR Manager found the roles list of a user ("too many roles", most of them ERP modules
the site does not use: Agriculture, Manufacturing, Sales, Blogger ...) impossible to reason about.
This sets up eight Role Profiles, each one a single choice on the User form:

    Employee, Supervisor, Manager, HR, HR Manager, Payroll, Store, IT

``apply`` (run by hand, never from migrate - it removes roles from users):

1. creates the two roles the site did not have: ``Payroll`` and ``Store``, with their rights
   (Payroll = the HR Manager's rights on the payroll doctypes + the pay fields of the Employee;
   Store = full rights on Assets + Employee read; the Stock rights come from the stock roles in the
   profile),
2. creates the eight Role Profiles,
3. switches off every other role (``Role.disabled``): they disappear from the roles list of the
   User form and from every user. The removed assignments are written to a snapshot file first,
4. marks each user whose roles are exactly those of one profile with that profile (nothing else on
   the user changes).

    bench --site <site> execute cooperheat.cooperheat.roles_simple.apply            # dry run: only reports
    bench --site <site> execute cooperheat.cooperheat.roles_simple.apply --kwargs "{'dry_run': 0}"
    bench --site <site> execute cooperheat.cooperheat.roles_simple.revert           # roles back from the snapshot

Doctype permission rows are never deleted, so re-enabling a role brings its rights back.
"""

import json
import os

import frappe
from frappe.core.doctype.role.role import STANDARD_ROLES

NEW_ROLES = ("Payroll", "Store")

# Roles that stay on (besides the ones the profiles use): site features that run on them.
KEEP = {
	"Employee",
	"Employee Self Service",
	"Leave Approver",
	"Expense Approver",
	"Supervisor",
	"Manager",
	"HR User",
	"HR Manager",
	"Payroll",
	"Store",
	"Stock User",
	"Stock Manager",
	"Item Manager",
	"Projects User",
	"Projects Manager",
	"Accounts User",
	"Accounts Manager",
	"Report Manager",
	"Dashboard Manager",
	"Workspace Manager",
	"Prepared Report User",
	"Customer",
	"Supplier",
} | set(STANDARD_ROLES)

_EMPLOYEE = ["Employee", "Employee Self Service"]
_APPROVER = ["Leave Approver", "Expense Approver"]

PROFILES = {
	"Employee": _EMPLOYEE,
	"Supervisor": [*_EMPLOYEE, "Supervisor", *_APPROVER],
	"Manager": [*_EMPLOYEE, "Manager", *_APPROVER],
	"HR": [*_EMPLOYEE, "HR User", *_APPROVER],
	"HR Manager": [*_EMPLOYEE, "HR User", "HR Manager", *_APPROVER],
	"Payroll": [*_EMPLOYEE, "Payroll"],
	"Store": [*_EMPLOYEE, "Store", "Stock User", "Stock Manager", "Item Manager"],
	"IT": [*_EMPLOYEE, "System Manager"],
}

PAYROLL_DOCTYPES = (
	"Salary Slip",
	"Payroll Entry",
	"Salary Structure",
	"Salary Structure Assignment",
	"Salary Component",
	"Additional Salary",
	"Payroll Period",
	"Payroll Settings",
	"Employee Incentive",
	"Retention Bonus",
	"Gratuity",
	"Gratuity Rule",
	"Salary Withholding",
	"Employee Compensation",
	"Pay Batch",
	"Pay Sheet Settings",
	"Payroll Sheet",
	"Payroll Import",
)

PTYPES = (
	"read", "write", "create", "delete", "submit", "cancel", "amend",
	"report", "export", "import", "share", "print", "email",
)  # fmt: skip


def snapshot_file() -> str:
	return frappe.get_site_path("private", "roles_cleanup_snapshot.json")


def apply(dry_run=1, snapshot_path=None) -> dict:
	"""Idempotent. ``dry_run`` (default) only reports what would be done."""
	dry_run = int(dry_run)
	out = {"dry_run": dry_run, "disable": roles_to_disable()}
	if dry_run:
		out["users_affected"] = _assignments(out["disable"], count_only=True)
		return out

	for role in NEW_ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)
	out["perms"] = ensure_role_permissions()
	from cooperheat.cooperheat.employee_security import ensure_employee_field_security

	ensure_employee_field_security()  # adds Payroll at the pay level
	out["profiles"] = ensure_profiles()
	out["removed_assignments"] = disable_roles(out["disable"], snapshot_path)
	out["users_with_profile"] = mark_users()
	frappe.clear_cache()
	return out


def revert(snapshot_path=None) -> dict:
	"""Re-enables the switched-off roles and gives every user back what the snapshot recorded."""
	path = snapshot_path or snapshot_file()
	if not os.path.exists(path):
		return {"restored": 0, "error": "no snapshot"}
	with open(path) as handle:
		snap = json.load(handle)
	for role in snap["roles"]:
		if frappe.db.exists("Role", role):
			frappe.db.set_value("Role", role, "disabled", 0)
	restored = 0
	for parent, parenttype, role in snap["assignments"]:
		if not frappe.db.exists("Has Role", {"parent": parent, "parenttype": parenttype, "role": role}):
			frappe.get_doc(
				{
					"doctype": "Has Role",
					"parent": parent,
					"parenttype": parenttype,
					"parentfield": "roles",
					"role": role,
				}
			).db_insert()
			restored += 1
	frappe.clear_cache()
	return {"restored": restored, "roles": len(snap["roles"])}


def roles_to_disable() -> list[str]:
	enabled = frappe.get_all("Role", filters={"disabled": 0}, pluck="name")
	keep = KEEP | {r for roles in PROFILES.values() for r in roles}
	automatic = set(frappe.permissions.AUTOMATIC_ROLES)
	return sorted(r for r in enabled if r not in keep and r not in automatic)


def _assignments(roles: list[str], count_only=False):
	if not roles:
		return 0 if count_only else []
	rows = frappe.get_all(
		"Has Role",
		filters={"role": ["in", roles], "parenttype": ["in", ["User", "Role Profile"]]},
		fields=["parent", "parenttype", "role"],
		as_list=True,
	)
	return len({r[0] for r in rows}) if count_only else [list(r) for r in rows]


def disable_roles(roles: list[str], snapshot_path=None) -> int:
	assignments = _assignments(roles)
	path = snapshot_path or snapshot_file()
	merged = {"roles": [], "assignments": []}
	if os.path.exists(path):
		with open(path) as handle:
			merged = json.load(handle)
	merged["roles"] = sorted(set(merged["roles"]) | set(roles))
	known = {tuple(a) for a in merged["assignments"]}
	merged["assignments"] += [a for a in assignments if tuple(a) not in known]
	with open(path, "w") as handle:
		json.dump(merged, handle)
	for role in roles:
		doc = frappe.get_doc("Role", role)
		doc.disabled = 1
		doc.flags.ignore_permissions = True
		doc.save()  # Role.validate removes it from every user
	return len(assignments)


def ensure_profiles() -> dict:
	made = {"created": [], "updated": []}
	for name, roles in PROFILES.items():
		roles = [r for r in roles if frappe.db.exists("Role", r)]
		if frappe.db.exists("Role Profile", name):
			doc = frappe.get_doc("Role Profile", name)
			if {r.role for r in doc.roles} == set(roles):
				continue
			doc.roles = []
			made["updated"].append(name)
		else:
			doc = frappe.new_doc("Role Profile")
			doc.role_profile = name
			made["created"].append(name)
		for role in roles:
			doc.append("roles", {"role": role})
		doc.flags.ignore_permissions = True
		doc.save()
	return made


def mark_users() -> int:
	"""A user whose roles are exactly those of one profile gets that profile (no role changes)."""
	automatic = set(frappe.permissions.AUTOMATIC_ROLES)
	by_roles = {frozenset(roles): name for name, roles in PROFILES.items()}
	rows = frappe.get_all("Has Role", filters={"parenttype": "User"}, fields=["parent", "role"], as_list=True)
	roles_of: dict[str, set] = {}
	for user, role in rows:
		if role not in automatic:
			roles_of.setdefault(user, set()).add(role)
	count = 0
	for user, roles in roles_of.items():
		profile = by_roles.get(frozenset(roles))
		if profile and frappe.db.get_value("User", user, "role_profile_name") != profile:
			frappe.db.set_value("User", user, "role_profile_name", profile, update_modified=False)
			count += 1
	return count


def _rows(doctype: str, role: str) -> list[dict]:
	"""The permission rows a role has on a doctype (custom ones once the doctype has any)."""
	fields = ["permlevel", *PTYPES]
	table = "Custom DocPerm" if frappe.db.exists("Custom DocPerm", {"parent": doctype}) else "DocPerm"
	return frappe.get_all(
		table, filters={"parent": doctype, "role": role}, fields=fields, order_by="permlevel"
	)


def _give(doctype: str, role: str, rows: list[dict]) -> int:
	"""Add-only: a (doctype, role, permlevel) that already has a row is left as it is."""
	from frappe.permissions import add_permission, update_permission_property

	added = 0
	for row in rows:
		level = row.get("permlevel") or 0
		if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": level}):
			continue
		add_permission(doctype, role, level)
		for ptype in PTYPES:
			if row.get(ptype):
				update_permission_property(doctype, role, level, ptype, 1)
		added += 1
	return added


def ensure_role_permissions() -> dict:
	"""Idempotent and add-only. Returns {role: rows added}."""
	from cooperheat.setup import _grant

	added = {"Payroll": 0, "Store": 0}
	for doctype in PAYROLL_DOCTYPES:
		if frappe.db.exists("DocType", doctype):
			added["Payroll"] += _give(doctype, "Payroll", _rows(doctype, "HR Manager"))
	for role in ("Payroll", "Store"):
		if frappe.db.exists("DocType", "Employee"):
			_grant("Employee", role, 0, ("read",))
	if frappe.db.exists("DocType", "Asset"):
		for doctype in frappe.get_all("DocType", filters={"module": "Assets", "istable": 0}, pluck="name"):
			submittable = frappe.get_meta(doctype).is_submittable
			full = {p: 1 for p in PTYPES if submittable or p not in ("submit", "cancel", "amend")}
			full["permlevel"] = 0
			added["Store"] += _give(doctype, "Store", [full])
	return added
