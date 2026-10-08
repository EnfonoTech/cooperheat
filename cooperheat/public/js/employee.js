// Business Line / Product Line placement. The server derives `department`
// from these (cooperheat.cooperheat.org.sync_employee_org).
frappe.ui.form.on("Employee", {
	setup(frm) {
		frm.set_query("custom_business_line", () => ({ filters: { custom_unit_type: "Business Line", disabled: 0 } }));
		frm.set_query("custom_product_line", () => ({
			query: "cooperheat.cooperheat.org.product_line_query",
			filters: { business_line: frm.doc.custom_business_line || "" },
		}));
	},
	refresh(frm) {
		frm.toggle_enable("department", !frm.doc.custom_business_line);
	},
	custom_business_line(frm) {
		frm.toggle_enable("department", !frm.doc.custom_business_line);
		if (!frm.doc.custom_business_line) {
			frm.set_value("custom_product_line", "");
			return;
		}
		frm.set_value("department", frm.doc.custom_product_line || frm.doc.custom_business_line);
	},
	custom_product_line(frm) {
		if (frm.doc.custom_business_line) {
			frm.set_value("department", frm.doc.custom_product_line || frm.doc.custom_business_line);
		}
	},
});
