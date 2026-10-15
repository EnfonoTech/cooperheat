frappe.query_reports["Overtime Comparison"] = {
	filters: [
		{ fieldname: "year", label: __("Year"), fieldtype: "Int", default: new Date().getFullYear(), reqd: 1 },
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: "January\nFebruary\nMarch\nApril\nMay\nJune\nJuly\nAugust\nSeptember\nOctober\nNovember\nDecember",
			default: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"][new Date().getMonth()],
			reqd: 1,
		},
		{ fieldname: "staff_category", label: __("Staff Category"), fieldtype: "Select", options: "\nOffice Staff\nField Staff" },
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{ fieldname: "only_differences", label: __("Only differences"), fieldtype: "Check" },
	],
};
