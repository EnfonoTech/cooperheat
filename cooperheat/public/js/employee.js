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
		cooperheat_shift_section(frm);
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

// Shift Assignments on the Employee: recent assignments + an "Assign Shift" button
// (HR only; server side re-checks in cooperheat.cooperheat.shift_tools).
function cooperheat_shift_section(frm) {
	if (frm.is_new()) return;
	const hr = ["HR Manager", "HR User", "System Manager"].some((r) => frappe.user.has_role(r));
	if (hr) {
		frm.add_custom_button(__("Assign Shift"), () => cooperheat_assign_shift(frm), __("Actions"));
	}
	frappe.call({
		method: "cooperheat.cooperheat.shift_tools.get_employee_shifts",
		args: { employee: frm.doc.name },
		callback(r) {
			const rows = r.message || [];
			const esc = frappe.utils.escape_html;
			const body = rows.length
				? rows
						.map(
							(d) =>
								`<tr><td><a href="/app/shift-assignment/${encodeURIComponent(d.name)}">${esc(d.shift_type)}</a></td>` +
								`<td>${frappe.datetime.str_to_user(d.start_date)}</td>` +
								`<td>${d.end_date ? frappe.datetime.str_to_user(d.end_date) : __("open-ended")}</td>` +
								`<td>${esc(d.status)}</td></tr>`
						)
						.join("")
				: `<tr><td colspan="4" class="text-muted">${__("No shift assignments. The Default Shift applies.")}</td></tr>`;
			frm.dashboard.clear_headline();
			frm.dashboard.add_section(
				`<div class="cooperheat-shifts"><table class="table table-sm"><thead><tr><th>${__("Shift")}</th>` +
					`<th>${__("From")}</th><th>${__("To")}</th><th>${__("Status")}</th></tr></thead><tbody>${body}</tbody></table></div>`,
				__("Shift Assignments")
			);
		},
	});
}

function cooperheat_assign_shift(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Assign Shift to {0}", [frm.doc.employee_name]),
		fields: [
			{ fieldname: "shift_type", label: __("Shift Type"), fieldtype: "Link", options: "Shift Type", reqd: 1 },
			{ fieldname: "start_date", label: __("Start Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
			{ fieldname: "end_date", label: __("End Date (empty = open-ended)"), fieldtype: "Date" },
		],
		primary_action_label: __("Assign"),
		primary_action(values) {
			frappe.call({
				method: "cooperheat.cooperheat.shift_tools.assign_shift",
				args: { employee: frm.doc.name, ...values },
				freeze: true,
				callback() {
					d.hide();
					frappe.show_alert({ message: __("Shift assigned"), indicator: "green" });
					frm.reload_doc();
				},
			});
		},
	});
	d.show();
}
