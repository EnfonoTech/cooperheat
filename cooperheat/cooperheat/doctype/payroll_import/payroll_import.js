// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payroll Import", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (["Draft", "Failed", "Completed"].includes(frm.doc.status)) {
			const label = frm.doc.status === "Completed"
				? __("Re-run Import")
				: frm.doc.status === "Failed"
					? __("Retry Import")
					: __("Start Import");
			frm.add_custom_button(label, () => {
				if (!frm.doc.file) {
					frappe.msgprint(__("Attach an Excel file first."));
					return;
				}
				const proceed = () => {
					frappe.call({
						method: "cooperheat.cooperheat.doctype.payroll_import.payroll_import.start_import",
						args: { name: frm.doc.name },
						freeze: true,
						freeze_message: __("Processing Excel..."),
					}).then(() => frm.reload_doc());
				};
				if (frm.is_dirty()) {
					frm.save().then(proceed);
				} else {
					proceed();
				}
			}).removeClass("btn-default").addClass("btn-primary");
		}

		if (["Queued", "Running"].includes(frm.doc.status)) {
			frm.disable_save();
			frm.add_custom_button(__("Refresh"), () => frm.reload_doc());
		}

		render_headline(frm);
		render_not_imported_panel(frm);
		highlight_log_rows(frm);
	},

	rows_on_form_rendered(frm) {
		highlight_log_rows(frm);
	},
});

function render_headline(frm) {
	if (frm.doc.status === "Failed" && frm.doc.error_message) {
		frm.dashboard.set_headline_alert(
			`<div class="text-danger"><b>${__("Import failed")}:</b> ${frappe.utils.escape_html(frm.doc.error_message)}</div>`
		);
		return;
	}
	if (frm.doc.error_count > 0) {
		frm.dashboard.set_headline_alert(
			`<div class="text-danger"><b>${frm.doc.error_count}</b> ${__("row(s) not imported")} — ${__("see details below")}. ${__("Created")}: ${frm.doc.created_count}, ${__("Skipped")}: ${frm.doc.skipped_count}.</div>`
		);
	} else if (frm.doc.status === "Completed") {
		frm.dashboard.set_headline_alert(
			`<div class="text-success">${__("Imported")} <b>${frm.doc.created_count}</b> ${__("row(s)")}${frm.doc.skipped_count ? ", " + frm.doc.skipped_count + " " + __("skipped") : ""}.</div>`
		);
	}
}

function render_not_imported_panel(frm) {
	const wrap_id = "not-imported-panel";
	// Prefer showing after the stats section
	const $anchor = frm.fields_dict.error_count && frm.fields_dict.error_count.$wrapper
		? frm.fields_dict.error_count.$wrapper.closest(".section-body, .form-section")
		: null;

	frm.$wrapper.find(`#${wrap_id}`).remove();

	const errors = (frm.doc.rows || []).filter(r => r.row_status === "Error");
	if (!errors.length) return;

	const items = errors.map(r => `
		<tr class="text-danger">
			<td>${frappe.utils.escape_html(r.doc_no || "")}</td>
			<td>${frappe.utils.escape_html(r.code || "-")}</td>
			<td>${frappe.utils.escape_html(r.employee || "-")}</td>
			<td>${frappe.utils.escape_html(r.message || "")}</td>
		</tr>
	`).join("");

	const html = `
		<div id="${wrap_id}" class="form-section" style="margin-top:15px;">
			<div class="section-body">
				<div class="alert alert-danger" style="margin-bottom:10px;">
					<b>${errors.length} ${__("row(s) not imported")}</b>
					${__("— review the reasons below and either fix the source data or create the missing Employee Compensation, then Re-run Import.")}
				</div>
				<table class="table table-sm table-bordered" style="margin-bottom:0;">
					<thead>
						<tr><th style="width:70px;">${__("Doc No")}</th>
						<th style="width:140px;">${__("Code")}</th>
						<th style="width:180px;">${__("Employee")}</th>
						<th>${__("Reason")}</th></tr>
					</thead>
					<tbody>${items}</tbody>
				</table>
			</div>
		</div>
	`;

	if ($anchor && $anchor.length) {
		$anchor.after(html);
	} else {
		frm.fields_dict.rows.$wrapper.before(html);
	}
}

function highlight_log_rows(frm) {
	if (!frm.fields_dict.rows || !frm.fields_dict.rows.grid) return;
	const grid = frm.fields_dict.rows.grid;
	// Run after the grid renders
	setTimeout(() => {
		grid.wrapper.find(".grid-row").each(function() {
			const $row = $(this);
			const docname = $row.attr("data-name");
			if (!docname) return;
			const child = (frm.doc.rows || []).find(c => c.name === docname);
			if (!child) return;
			$row.removeClass("row-error row-created row-skipped");
			if (child.row_status === "Error") {
				$row.addClass("row-error").css("background-color", "#fff5f5");
			} else if (child.row_status === "Created") {
				$row.css("background-color", "");
			} else if (child.row_status === "Skipped") {
				$row.css("background-color", "#fffbea");
			}
		});
	}, 50);
}
