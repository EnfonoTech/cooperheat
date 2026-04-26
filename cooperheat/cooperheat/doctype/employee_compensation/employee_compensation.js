// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

frappe.ui.form.on("Employee Compensation", {
	employee(frm) {
		if (!frm.doc.employee) return;
		frappe.db.get_value("Employee", frm.doc.employee, "nationality").then(r => {
			const nat = r && r.message && r.message.nationality;
			if (!nat) return;
			frappe.db.get_value("Nationality", nat, "is_local").then(rr => {
				const is_local = cint(rr && rr.message && rr.message.is_local);
				frm.set_value("employee_category", is_local ? "Saudi" : "Expat");
			});
		});
	},
});
