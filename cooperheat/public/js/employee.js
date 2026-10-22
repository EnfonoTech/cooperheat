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
		cooperheat_compensation_tab(frm);
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


// Salary Compensation tab: the current package and its history, changed from here instead of
// creating an Employee Compensation record in the Payroll section. Only System Manager and
// HR Manager see the tab; the server refuses everybody else (cooperheat.cooperheat.compensation).
function cooperheat_compensation_tab(frm) {
	const allowed = frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");
	// For anybody else the server does not even send the tab (field level 2: HR Manager / System Manager).
	if (frm.fields_dict.custom_compensation_tab) frm.set_df_property("custom_compensation_tab", "hidden", allowed ? 0 : 1);
	if (!allowed) return;
	const $box = frm.fields_dict.custom_compensation_html && frm.fields_dict.custom_compensation_html.$wrapper;
	if (!$box) return;
	if (frm.is_new()) {
		$box.html(`<p class="text-muted">${__("Save the employee first, then add the salary compensation here.")}</p>`);
		return;
	}
	$box.html(`<p class="text-muted">${__("Loading...")}</p>`);
	frappe.xcall("cooperheat.cooperheat.compensation.get_for_employee", { employee: frm.doc.name }).then((data) => {
		cooperheat_render_compensation(frm, $box, data);
	});
}

function cooperheat_money(value, currency) {
	return format_currency(value || 0, currency);
}

function cooperheat_render_compensation(frm, $box, data) {
	const esc = frappe.utils.escape_html;
	const label = Object.fromEntries(data.fields.map((f) => [f.fieldname, f.label]));
	const part = (group) => data.fields.filter((f) => f.group === group);
	let html = "";
	if (data.needs_nationality) {
		html += `<div class="alert alert-warning">${__("Set the Nationality on the Overview tab first: it decides the Saudi / Expat category used for GOSI.")}</div>`;
	}
	const cur = data.current;
	if (cur) {
		const rows = (group) =>
			part(group)
				.filter((f) => cur.values[f.fieldname])
				.map((f) => `<tr><td>${esc(f.label)}</td><td class="text-right">${cooperheat_money(cur.values[f.fieldname], cur.currency)}</td></tr>`)
				.join("") || `<tr><td class="text-muted" colspan="2">${__("none")}</td></tr>`;
		html += `<div class="ch-comp-head">
			<b>${__("Current package")}</b> · ${__("effective from")} ${frappe.datetime.str_to_user(cur.from_date)}
			· ${esc(cur.employee_category || "")} · ${esc(cur.pay_batch || "")}
			· <a href="/app/employee-compensation/${encodeURIComponent(cur.name)}">${esc(cur.name)}</a>
		</div>
		<div class="row"><div class="col-md-6"><table class="table table-sm"><thead><tr><th colspan="2">${__("Earnings / Allowances (monthly)")}</th></tr></thead><tbody>${rows("earning")}
			<tr><td><b>${__("Total earnings")}</b></td><td class="text-right"><b>${cooperheat_money(cur.total_earnings, cur.currency)}</b></td></tr></tbody></table></div>
		<div class="col-md-6"><table class="table table-sm"><thead><tr><th colspan="2">${__("Fixed monthly deductions")}</th></tr></thead><tbody>${rows("deduction")}
			<tr><td><b>${__("Total deductions")}</b></td><td class="text-right"><b>${cooperheat_money(cur.total_deductions, cur.currency)}</b></td></tr></tbody></table></div></div>`;
	} else {
		html += `<p class="text-muted">${__("No salary compensation is in force for this employee yet.")}</p>`;
	}
	if (data.history.length) {
		html += `<h6 style="margin-top:14px">${__("History")}</h6><table class="table table-sm table-bordered"><thead><tr>
			<th>${__("Effective from")}</th><th class="text-right">${__("Basic")}</th><th class="text-right">${__("Total earnings")}</th>
			<th class="text-right">${__("Deductions")}</th><th>${__("Status")}</th><th></th></tr></thead><tbody>${data.history
				.map(
					(h) => `<tr><td>${frappe.datetime.str_to_user(h.from_date)}</td>
					<td class="text-right">${cooperheat_money(h.values.basic, h.currency)}</td>
					<td class="text-right">${cooperheat_money(h.total_earnings, h.currency)}</td>
					<td class="text-right">${cooperheat_money(h.total_deductions, h.currency)}</td>
					<td>${h.is_active ? __("Active") : __("Inactive")}${cur && h.name === cur.name ? " · " + __("in force today") : ""}</td>
					<td><a href="/app/employee-compensation/${encodeURIComponent(h.name)}">${__("Open")}</a></td></tr>`
				)
				.join("")}</tbody></table>`;
	}
	$box.html(html);
	if (!data.can_write) return;
	const $bar = $(`<div style="margin-top:10px"></div>`).appendTo($box);
	$(`<button class="btn btn-primary btn-sm">${cur ? __("Change compensation") : __("Add compensation")}</button>`)
		.on("click", () => cooperheat_compensation_dialog(frm, data, null))
		.appendTo($bar);
	if (cur) {
		$(`<button class="btn btn-default btn-sm" style="margin-left:8px">${__("Correct this record")}</button>`)
			.on("click", () => cooperheat_compensation_dialog(frm, data, cur))
			.appendTo($bar);
		$bar.append(`<span class="text-muted small" style="margin-left:10px">${__("Change = a new package from a date (a raise); Correct = fix a mistake in the current one.")}</span>`);
	}
}

function cooperheat_compensation_dialog(frm, data, record) {
	const base = record || data.current || { values: {}, notes: "" };
	const field = (f) => ({ fieldtype: "Currency", fieldname: f.fieldname, label: f.label, default: base.values[f.fieldname] || 0 });
	const earnings = data.fields.filter((f) => f.group === "earning");
	const deductions = data.fields.filter((f) => f.group === "deduction");
	const half = Math.ceil(earnings.length / 2);
	const dialog = new frappe.ui.Dialog({
		title: record ? __("Correct current compensation") : base.name ? __("Change compensation") : __("Add compensation"),
		size: "large",
		fields: [
			{
				fieldtype: "Date",
				fieldname: "from_date",
				label: __("Effective from"),
				reqd: 1,
				default: record ? record.from_date : frappe.datetime.get_today(),
				description: record ? __("Date this package started.") : __("The Payroll Sheet uses the latest package whose date is on or before the posting date."),
			},
			{ fieldtype: "Section Break", label: __("Earnings / Allowances (full monthly amounts)") },
			...earnings.slice(0, half).map(field),
			{ fieldtype: "Column Break" },
			...earnings.slice(half).map(field),
			{ fieldtype: "Section Break", label: __("Fixed monthly deductions") },
			...deductions.slice(0, Math.ceil(deductions.length / 2)).map(field),
			{ fieldtype: "Column Break" },
			...deductions.slice(Math.ceil(deductions.length / 2)).map(field),
			{ fieldtype: "Section Break" },
			{ fieldtype: "Small Text", fieldname: "notes", label: __("Notes"), default: base.notes || "" },
		],
		primary_action_label: __("Save"),
		primary_action(values) {
			const amounts = {};
			data.fields.forEach((f) => (amounts[f.fieldname] = flt(values[f.fieldname])));
			frappe
				.xcall("cooperheat.cooperheat.compensation.save", {
					employee: frm.doc.name,
					values: amounts,
					from_date: values.from_date,
					record: record ? record.name : null,
					notes: values.notes || "",
				})
				.then(() => {
					dialog.hide();
					frappe.show_alert({ message: __("Compensation saved"), indicator: "green" });
					cooperheat_compensation_tab(frm);
				});
		},
	});
	dialog.show();
}
