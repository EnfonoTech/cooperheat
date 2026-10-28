// Cost Center of the shift follows the employee's Product Line, else Business Line
// (cooperheat.cooperheat.cost_center.employee_cost_center_query; client, 2026-10-28).
frappe.ui.form.on("Shift Assignment", {
	setup(frm) {
		frm.set_query("custom_cost_center", () => ({
			query: "cooperheat.cooperheat.cost_center.employee_cost_center_query",
			filters: { employee: frm.doc.employee || "", company: frm.doc.company || "" },
		}));
	},
	employee(frm) {
		if (frm.doc.custom_cost_center) frm.set_value("custom_cost_center", "");
	},
});
