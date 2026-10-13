// Employee -> dates -> that day's check-ins, for HR across all employees.
// The drill-down lives in the Supervisor Workspace (HR Manager / HR User see everyone there).
// HRMS defines its own onload (Fetch Shifts); keep it and add ours.
(function () {
	const settings = (frappe.listview_settings["Employee Checkin"] = frappe.listview_settings["Employee Checkin"] || {});
	const hrms_onload = settings.onload;
	settings.onload = function (listview) {
		if (hrms_onload) hrms_onload.call(this, listview);
		listview.page.add_inner_button(__("View by Employee"), () => frappe.set_route("supervisor-workspace"));
	};
})();
