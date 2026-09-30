// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

frappe.query_reports["Approver Technician Summary"] = {
	// rows carry "indent" (0 = approver, 1 = technician) so this renders as a tree;
	// depth 1 opens it with every technician visible
	initial_depth: 1,
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.indent === 0) {
			value = `<b>${value}</b>`;
		}
		return value;
	},
	filters: [
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "approval_level",
			label: __("Approval Level"),
			fieldtype: "Select",
			options: ["", "1", "2", "3"],
		},
		{
			fieldname: "approver",
			label: __("Approver"),
			fieldtype: "Link",
			options: "Employee",
		},
	],
};
