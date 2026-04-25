// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

frappe.query_reports["Pay Sheet Detail"] = {
	filters: [
		{
			fieldname: "company", label: __("Company"), fieldtype: "Link",
			options: "Company", default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "month", label: __("Month"), fieldtype: "Select",
			options: ["", "January","February","March","April","May","June",
				"July","August","September","October","November","December"].join("\n"),
		},
		{
			fieldname: "year", label: __("Year"), fieldtype: "Int",
			default: new Date().getFullYear(),
		},
		{
			fieldname: "pay_batch", label: __("Pay Batch"), fieldtype: "Link",
			options: "Pay Batch",
		},
		{
			fieldname: "employee", label: __("Employee"), fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "status", label: __("Status"), fieldtype: "Select",
			options: "\nDraft\nSubmitted\nPaid\nCancelled",
		},
		{ fieldname: "from_date", label: __("From Posting Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Posting Date"), fieldtype: "Date" },
		{
			fieldname: "include_draft", label: __("Include Drafts"),
			fieldtype: "Check", default: 0,
		},
	],
};
