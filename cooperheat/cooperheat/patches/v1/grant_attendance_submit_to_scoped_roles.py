import frappe


def execute():
	"""Approving an Attendance through the workflow needs the `submit` right. Rows
	made before this was added (and a missing row) get it; rows that already have
	it are untouched."""
	from cooperheat.setup import SCOPED_ROLE_NAMES, ensure_roles, _grant

	ensure_roles()
	for role in SCOPED_ROLE_NAMES:
		row = frappe.db.get_value("Custom DocPerm", {"parent": "Attendance", "role": role, "permlevel": 0}, "name")
		if row:
			frappe.db.set_value("Custom DocPerm", row, "submit", 1)
		else:
			_grant("Attendance", role, 0, ("read", "write", "submit"))
	frappe.clear_cache(doctype="Attendance")
