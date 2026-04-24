// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

frappe.listview_settings["Payroll Sheet"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Import from Excel"), () => {
			frappe.new_doc("Payroll Import");
		}, __("Actions"));
		listview.page.add_inner_button(__("View Imports"), () => {
			frappe.set_route("List", "Payroll Import");
		}, __("Actions"));
	},
	get_indicator(doc) {
		const map = {
			"Draft": ["Draft", "gray", "status,=,Draft"],
			"Submitted": ["Submitted", "blue", "status,=,Submitted"],
			"Paid": ["Paid", "green", "status,=,Paid"],
			"Cancelled": ["Cancelled", "red", "status,=,Cancelled"],
		};
		return map[doc.status];
	},
};
