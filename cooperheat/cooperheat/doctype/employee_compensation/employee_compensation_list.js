// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

frappe.listview_settings["Employee Compensation"] = {
	add_fields: ["is_active"],
	get_indicator(doc) {
		if (cint(doc.is_active)) return [__("Active"), "green", "is_active,=,1"];
		return [__("Inactive"), "gray", "is_active,=,0"];
	},
};
