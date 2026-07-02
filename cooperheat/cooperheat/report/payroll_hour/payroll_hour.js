// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

frappe.query_reports["Payroll Hour"] = {
	formatter: function (value, row, column, data, default_formatter) {
		if (column.fieldname === "employee" && value) {
			return `<a href="/app/employee/${value}">${value}</a>`;
		}
		return default_formatter(value, row, column, data);
	},
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_end(),
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
	],
};
