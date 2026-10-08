frappe.query_reports["Employee Approver Exceptions"] = {
	filters: [
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{
			fieldname: "issue",
			label: __("Issue"),
			fieldtype: "Select",
			options: [
				"",
				"No Reports To",
				"No User account",
				"No Department",
				"Department has no Level 1 approver",
				"Level 1 approver has no User account",
			],
		},
	],
};
