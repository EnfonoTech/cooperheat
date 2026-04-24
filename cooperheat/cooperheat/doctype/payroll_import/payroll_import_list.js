// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

frappe.listview_settings["Payroll Import"] = {
	get_indicator(doc) {
		const map = {
			"Draft": ["Draft", "gray", "status,=,Draft"],
			"Queued": ["Queued", "blue", "status,=,Queued"],
			"Running": ["Running", "blue", "status,=,Running"],
			"Completed": ["Completed", "green", "status,=,Completed"],
			"Failed": ["Failed", "red", "status,=,Failed"],
		};
		return map[doc.status];
	},
};
