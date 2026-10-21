// Employee Checkin: one entry per employee -> that employee's dates -> that day's check-ins.
// The drill-down lives in the Supervisor Workspace (HR Manager / HR User see everyone there), so
// the plain list of every punch is only shown when asked for: coming from a filtered link (an
// Employee's connections, a report), the "All check-ins" button, or the Back button.
// HRMS defines its own onload (Fetch Shifts); keep it and add ours.
(function () {
	const settings = (frappe.listview_settings["Employee Checkin"] =
		frappe.listview_settings["Employee Checkin"] || {});
	const hrms_onload = settings.onload;
	settings.onload = function (listview) {
		if (hrms_onload) hrms_onload.call(this, listview);
		const history = frappe.route_history || [];
		const previous = (history[history.length - 2] || [])[0];
		const filtered = frappe.route_options && Object.keys(frappe.route_options).length;
		if (!frappe.cooperheat_checkin_list && !filtered && previous !== "supervisor-workspace") {
			setTimeout(() => frappe.set_route("supervisor-workspace"), 0);
			return;
		}
		frappe.cooperheat_checkin_list = false;
		listview.page.add_inner_button(__("By employee"), () =>
			frappe.set_route("supervisor-workspace")
		);
	};
})();
