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
	const hours = diff > 0 ? flt(diff, 2) : 0;

	// Billable Hours is set once, from the first calculation, and then stays
	// constant - later check-in/check-out edits only affect Payable Hours.
	if (!row.hours) {
		frappe.model.set_value(cdt, cdn, "hours", hours);
	}
	frappe.model.set_value(cdt, cdn, "payroll_hours", hours);
}
