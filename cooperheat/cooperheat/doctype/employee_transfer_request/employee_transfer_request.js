// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

const ETR = "cooperheat.cooperheat.doctype.employee_transfer_request.employee_transfer_request";

frappe.ui.form.on("Employee Transfer Request", {
	setup(frm) {
		frm.set_query("to_business_line", () => ({ filters: { custom_unit_type: "Business Line", disabled: 0 } }));
		frm.set_query("to_product_line", () => ({
			query: "cooperheat.cooperheat.org.product_line_query",
			filters: { business_line: frm.doc.to_business_line || "" },
		}));
	},
	refresh(frm) {
		const decided = ["Approved", "Rejected"].includes(frm.doc.status);
		frm.set_read_only(decided);
		if (frm.doc.status !== "Pending Approval" || frm.is_new()) return;
		const me = frappe.session.user;
		if (me !== frm.doc.approver_user && me !== "Administrator") {
			frm.dashboard.set_headline(__("Waiting for {0} to approve.", [frm.doc.approver_name]));
			return;
		}
		frm.add_custom_button(__("Approve"), () => {
			frappe.confirm(__("Move {0} now?", [frm.doc.employee_name]), () =>
				frappe.xcall(`${ETR}.approve`, { name: frm.doc.name }).then(() => frm.reload_doc())
			);
		}).addClass("btn-primary");
		frm.add_custom_button(__("Reject"), () => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
				(v) => frappe.xcall(`${ETR}.reject`, { name: frm.doc.name, reason: v.reason }).then(() => frm.reload_doc()),
				__("Reject transfer")
			);
		});
	},
	to_business_line(frm) {
		if (frm.doc.to_product_line) frm.set_value("to_product_line", "");
		suggest(frm);
	},
	to_department(frm) {
		suggest(frm);
	},
});

function suggest(frm) {
	frappe
		.xcall(`${ETR}.suggest_approver`, {
			business_line: frm.doc.to_business_line || null,
			department: frm.doc.to_business_line ? null : frm.doc.to_department || null,
		})
		.then((boss) => boss && frm.set_value("approver", boss));
}
