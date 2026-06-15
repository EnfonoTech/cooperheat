import frappe


def execute():
	# Deactivate the Shift Assignment Approval workflow
	if frappe.db.exists("Workflow", "Shift Assignment Approval"):
		frappe.db.set_value("Workflow", "Shift Assignment Approval", "is_active", 0)
		frappe.clear_cache(doctype="Shift Assignment")

	# Remove cooperheat-added custom fields from Shift Assignment
	sa_fields = [
		"Shift Assignment-approval_details_section",
		"Shift Assignment-current_approval_level",
		"Shift Assignment-current_approver",
		"Shift Assignment-current_approver_name",
	]
	for cf_name in sa_fields:
		if frappe.db.exists("Custom Field", cf_name):
			frappe.delete_doc("Custom Field", cf_name, ignore_permissions=True, force=True)

	frappe.clear_cache(doctype="Shift Assignment")
