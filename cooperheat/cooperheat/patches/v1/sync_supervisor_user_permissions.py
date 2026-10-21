import json

import frappe


def execute():
	"""Supervisors/Managers are now scoped by rule (permissions/scope.py). Drop the
	Employee-self and Department User Permissions they were given by hand, which
	would otherwise keep hiding their team. The removed rows are written to the
	log so they can be restored by hand if anyone objects."""
	from cooperheat.cooperheat.permissions.scope import sync_all_user_permissions

	removed = sync_all_user_permissions()
	frappe.logger("cooperheat").info("removed stale User Permissions of scoped users: " + json.dumps(removed))
	print(f"cooperheat: removed {len(removed)} User Permission row(s) of supervisors/managers")
	for row in removed:
		print("   ", row["user"], row["allow"], row["for_value"])
