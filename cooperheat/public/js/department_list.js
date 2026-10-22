// The Department list shows names only. Everyone who opens "Department" from a menu lands on
// the Division screen instead; System Managers can still reach the plain list from there by
// coming back with the browser's Back button, or by setting frappe.cooperheat_department_list.
frappe.listview_settings["Department"] = {
	onload: function () {
		const history = frappe.route_history || [];
		const previous = (history[history.length - 2] || [])[0];
		if (frappe.cooperheat_department_list || previous === "division-screen" || previous === "Tree") {
			frappe.cooperheat_department_list = false;
			return;
		}
		setTimeout(() => frappe.set_route("division-screen"), 0);
	},
};
