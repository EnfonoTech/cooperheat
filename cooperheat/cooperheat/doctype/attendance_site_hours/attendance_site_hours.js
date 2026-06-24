// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

frappe.ui.form.on("Attendance Site Hours", {
	check_in_time(frm, cdt, cdn) {
		recalc_hours(cdt, cdn);
	},
	check_out_time(frm, cdt, cdn) {
		recalc_hours(cdt, cdn);
	},
});

function recalc_hours(cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.check_in_time || !row.check_out_time) return;

	const diff = moment(row.check_out_time, "YYYY-MM-DD HH:mm:ss").diff(
		moment(row.check_in_time, "YYYY-MM-DD HH:mm:ss"),
		"hours",
		true
	);
	frappe.model.set_value(cdt, cdn, "hours", diff > 0 ? flt(diff, 2) : 0);
}
