frappe.query_reports["Employee Approver Exceptions"] = {
	filters: [
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "issue",
			label: __("Issue"),
			fieldtype: "Select",
			options: [
				"",
				"No Direct / Immediate Reporting",
				"Direct / Immediate Reporting person has no User account",
				"Field staff without Secondary Reporting",
				"Secondary Reporting person has no User account",
				"No Staff Category",
				"No User account",
			],
		},
	],
};
