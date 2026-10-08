import frappe


def execute():
	"""Give every Employee a Pay Batch: keep the one on their active
	compensation record, otherwise the default "Main" batch."""
	from cooperheat.setup import setup_custom_fields

	setup_custom_fields()  # the custom_pay_batch column must exist before we fill it
	frappe.clear_cache(doctype="Employee")

	if not frappe.db.exists("Pay Batch", "Main"):
		frappe.get_doc({"doctype": "Pay Batch", "batch_name": "Main", "description": "Default batch"}).insert(
			ignore_permissions=True
		)

	for emp in frappe.get_all("Employee", filters={"custom_pay_batch": ["in", ["", None]]}, pluck="name"):
		batch = frappe.db.get_value(
			"Employee Compensation", {"employee": emp, "is_active": 1}, "pay_batch", order_by="from_date desc"
		)
		frappe.db.set_value("Employee", emp, "custom_pay_batch", batch or "Main", update_modified=False)
