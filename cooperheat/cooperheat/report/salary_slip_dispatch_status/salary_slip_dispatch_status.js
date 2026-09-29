// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

const DISPATCH_MONTHS = [
	"", "January", "February", "March", "April", "May", "June",
	"July", "August", "September", "October", "November", "December",
];

const DISPATCH_COLORS = {
	// slip status
	"Submitted": "green", "Draft": "orange", "Not Created": "gray", "Sheet Draft": "gray",
	"Cancelled": "red", "Sheet Cancelled": "red", "Not Imported": "red",
	// email status
	"Sent": "green", "Queued": "blue", "Failed": "red", "Skipped": "orange", "Not Sent": "gray",
};

frappe.query_reports["Salary Slip Dispatch Status"] = {
	filters: [
		{
			fieldname: "payroll_import",
			label: __("Payroll Import"),
			fieldtype: "Link",
			options: "Payroll Import",
			get_query: () => ({ filters: { status: "Completed" } }),
		},
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "month", label: __("Month"), fieldtype: "Select", options: DISPATCH_MONTHS },
		{ fieldname: "year", label: __("Year"), fieldtype: "Int" },
		{
			fieldname: "slip_status",
			label: __("Slip Status"),
			fieldtype: "Select",
			options: ["", "Not Imported", "Sheet Draft", "Not Created", "Draft", "Submitted", "Cancelled"],
		},
		{
			fieldname: "email_status",
			label: __("Email Status"),
			fieldtype: "Select",
			options: ["", "Not Sent", "Queued", "Sent", "Failed", "Skipped"],
		},
		{ fieldname: "needs_attention", label: __("Needs attention only"), fieldtype: "Check" },
	],

	onload(report) {
		// open on the latest completed import
		frappe.db.get_list("Payroll Import", {
			filters: { status: "Completed" },
			fields: ["name"],
			order_by: "creation desc",
			limit: 1,
		}).then((rows) => {
			if (rows.length && !report.get_filter_value("payroll_import")) {
				report.set_filter_value("payroll_import", rows[0].name);
			}
		});
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data || !["slip_status", "email_status"].includes(column.fieldname)) return value;
		const color = DISPATCH_COLORS[data[column.fieldname]];
		if (!color) return value;
		return `<span class="indicator-pill ${color} ellipsis"><span class="ellipsis">${value}</span></span>`;
	},
};
