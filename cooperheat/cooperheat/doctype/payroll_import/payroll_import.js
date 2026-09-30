// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

const SLIP_API = "cooperheat.cooperheat.doctype.payroll_import.slip_dispatch";

frappe.ui.form.on("Payroll Import", {
	setup(frm) {
		// the grid renders before refresh runs, so the cell formatters must exist by now
		style_row_columns(frm);
	},

	refresh(frm) {
		if (frm.is_new()) return;

		if (["Draft", "Failed", "Completed"].includes(frm.doc.status)) {
			const label = frm.doc.status === "Completed"
				? __("Re-run Import")
				: frm.doc.status === "Failed"
					? __("Retry Import")
					: __("Start Import");
			const $btn = frm.add_custom_button(label, () => {
				const proceed = () => {
					frappe.call({
						method: "cooperheat.cooperheat.doctype.payroll_import.payroll_import.start_import",
						args: { name: frm.doc.name },
						freeze: true,
						freeze_message: frm.doc.file
							? __("Processing Excel...")
							: __("Generating from Attendance..."),
					}).then(() => frm.reload_doc());
				};
				if (frm.is_dirty()) {
					frm.save().then(proceed);
				} else {
					proceed();
				}
			});
			// once the import is done the next step is the salary slips, so Re-run stays secondary
			if (frm.doc.status !== "Completed") $btn.removeClass("btn-default").addClass("btn-primary");
		}

		if (["Queued", "Running"].includes(frm.doc.status)) {
			frm.disable_save();
			frm.add_custom_button(__("Refresh"), () => frm.reload_doc());
		}

		style_row_columns(frm);
		render_headline(frm);
		render_not_imported_panel(frm);
		setup_slip_pipeline(frm);
		bind_row_buttons(frm);
		watch_grid(frm);
		highlight_log_rows(frm);
	},

	rows_on_form_rendered(frm) {
		highlight_log_rows(frm);
	},
});

frappe.ui.form.on("Payroll Import Row", {
	// the Send button inside the expanded row form
	resend_email(frm, cdt, cdn) {
		resend_one(frm, locals[cdt][cdn]);
	},
});

// ---------------------------------------------------------------------------
// Import headline / errors (unchanged behaviour)
// ---------------------------------------------------------------------------

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
			if (child.row_status === "Error" || child.email_status === "Failed") {
				$row.addClass("row-error").css("background-color", "#fff5f5");
			} else if (child.row_status === "Created") {
				$row.css("background-color", "");
			} else if (child.row_status === "Skipped") {
				$row.css("background-color", "#fffbea");
			}
		});
	}, 50);
}

// ---------------------------------------------------------------------------
// Slip + Email columns in the table
// ---------------------------------------------------------------------------

const SLIP_COLOR = {
	"Submitted": "green", "Draft": "orange", "Not Created": "gray",
	"Sheet Draft": "gray", "Sheet Cancelled": "red", "Cancelled": "red",
};
const SLIP_LABEL = {
	"Not Created": "No slip", "Sheet Draft": "Sheet draft", "Sheet Cancelled": "Sheet cancelled",
};
const MAIL_COLOR = { "Sent": "green", "Queued": "blue", "Failed": "red", "Skipped": "orange" };

function pill(label, color, title) {
	const text = frappe.utils.escape_html(__(label));
	return `<span class="indicator-pill no-indicator-dot ${color} ellipsis" style="padding:1px 6px;" title="${frappe.utils.escape_html(title || "")}">`
		+ `<span class="ellipsis">${text}</span></span>`;
}

// Grid cells are static text, so the status columns and the Send button get a formatter.
// The grid keeps its own copies of the docfields, so set it on those as well as on the meta.
function row_formatters() {
	return {
		slip_status: (value, _df, _opts, doc) => {
			if (!value) return "";
			const badge = pill(SLIP_LABEL[value] || value, SLIP_COLOR[value] || "gray", (doc && doc.slip_error) || value);
			// the pill doubles as the way into the salary slip
			return doc && doc.salary_slip
				? `<a href="${frappe.utils.get_form_link("Salary Slip", doc.salary_slip)}">${badge}</a>`
				: badge;
		},
		email_status: (value, _df, _opts, doc) =>
			value ? pill(value, MAIL_COLOR[value] || "gray", (doc && doc.email_error) || "") : "",
		resend_email: (value, _df, _opts, doc) => {
			if (!doc || doc.slip_status !== "Submitted") return "";
			if (doc.email_status === "Queued") return `<span class="text-muted">${__("Queued")}</span>`;
			if (!doc.email_to) return "";
			const label = doc.email_status === "Sent" ? __("Resend") : doc.email_status === "Failed" ? __("Retry") : __("Send");
			return `<button class="btn btn-xs btn-default slip-mail-btn" data-row="${frappe.utils.escape_html(doc.name)}">${label}</button>`;
		},
	};
}

function style_row_columns(frm) {
	const formatters = row_formatters();
	// frappe.meta.docfield_map holds the originals that every grid row copies from;
	// (frappe.meta.get_docfield returns a throw-away copy, so a formatter set there is lost)
	const originals = (frappe.meta.docfield_map || {})["Payroll Import Row"] || {};
	const grid = frm && frm.fields_dict && frm.fields_dict.rows && frm.fields_dict.rows.grid;
	Object.keys(formatters).forEach((fieldname) => {
		if (originals[fieldname]) originals[fieldname].formatter = formatters[fieldname];
		((grid && grid.docfields) || [])
			.filter((d) => d.fieldname === fieldname)
			.forEach((d) => (d.formatter = formatters[fieldname]));
	});
}

// The grid re-renders its rows on paging and refresh and can drop the formatters above, so the
// cells are also painted straight from the row data after every render. It only writes a cell
// when its HTML differs, so the observer settles instead of looping.
function paint_row_cells(frm) {
	const grid = frm.fields_dict.rows && frm.fields_dict.rows.grid;
	if (!grid) return;
	const formatters = row_formatters();
	grid.wrapper.find(".grid-row").each(function () {
		const $row = $(this);
		const child = (frm.doc.rows || []).find((c) => c.name === $row.attr("data-name"));
		if (!child) return;
		Object.keys(formatters).forEach((fieldname) => {
			const cell = $row.find(`[data-fieldname="${fieldname}"] .static-area`).get(0);
			if (!cell) return;
			const html = formatters[fieldname](child[fieldname], null, null, child);
			if (cell.innerHTML !== html) cell.innerHTML = html;
		});
	});
}

function watch_grid(frm) {
	const grid = frm.fields_dict.rows && frm.fields_dict.rows.grid;
	if (!grid || frm.__grid_observer) return;
	let timer = null;
	frm.__grid_observer = new MutationObserver(() => {
		clearTimeout(timer);
		timer = setTimeout(() => {
			paint_row_cells(frm);
			highlight_log_rows(frm);
		}, 40);
	});
	frm.__grid_observer.observe(grid.wrapper.get(0), { childList: true, subtree: true });
	paint_row_cells(frm);
}

function bind_row_buttons(frm) {
	const grid = frm.fields_dict.rows && frm.fields_dict.rows.grid;
	if (!grid || frm.__send_click_bound) return;
	frm.__send_click_bound = true;
	// Capture phase: the grid's own cell click handler (which opens the row form) runs first
	// in the bubble phase and would swallow the click.
	grid.wrapper.get(0).addEventListener("click", (e) => {
		const btn = e.target.closest && e.target.closest(".slip-mail-btn");
		if (!btn) return;
		e.preventDefault();
		e.stopPropagation();
		const row = (frm.doc.rows || []).find((r) => r.name === btn.getAttribute("data-row"));
		if (row) resend_one(frm, row);
	}, true);
}

function resend_one(frm, row) {
	if (!row) return;
	const who = row.employee_name || row.employee || row.code;
	const go = () => {
		frappe.call({
			method: `${SLIP_API}.resend_email`,
			args: { name: frm.doc.name, row: row.name },
			freeze: true,
			freeze_message: __("Preparing the email for {0}...", [who]),
		}).then((r) => {
			const res = r.message || {};
			if (res.outcome === "ok") {
				frappe.show_alert({ message: __("Email for {0} is queued.", [who]), indicator: "green" });
			} else {
				frappe.msgprint({
					title: __("Email not queued"),
					indicator: "red",
					message: frappe.utils.escape_html(res.email_error || __("Nothing was queued.")),
				});
			}
			frm.reload_doc();
		});
	};
	if (row.email_status === "Sent") {
		frappe.confirm(
			__("{0} was already emailed{1}. Send the salary slip again?", [
				frappe.utils.escape_html(who),
				row.email_sent_on ? " " + __("on {0}", [frappe.datetime.str_to_user(row.email_sent_on)]) : "",
			]),
			go
		);
	} else {
		go();
	}
}

// ---------------------------------------------------------------------------
// Salary slip pipeline: Create -> Submit -> Send emails
// ---------------------------------------------------------------------------

function setup_slip_pipeline(frm) {
	if (frm.is_new() || frm.doc.status !== "Completed") return;

	const group = __("Salary Slips");
	frm.add_custom_button(__("Create Salary Slips"), () => open_bulk(frm, "create_slips"), group);
	frm.add_custom_button(__("Submit Salary Slips"), () => open_bulk(frm, "submit_slips"), group);
	frm.add_custom_button(__("Send Salary Slip Emails"), () => open_bulk(frm, "send_emails"), group);
	frm.add_custom_button(__("Refresh Slip & Email Status"), () => {
		frappe.call({
			method: `${SLIP_API}.refresh_status`,
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message: __("Reading slips and mail status..."),
		}).then(() => frm.reload_doc());
	}, group);
	frm.add_custom_button(__("Dispatch Report"), () => {
		frappe.set_route("query-report", "Salary Slip Dispatch Status", { payroll_import: frm.doc.name });
	}, group);
	frm.page.set_inner_btn_group_as_primary(group);

	load_pipeline(frm);
}

function on_this_form(frm) {
	const route = frappe.get_route();
	return route[0] === "Form" && route[1] === "Payroll Import" && frm.doc && route[2] === frm.doc.name;
}

function stop_watching(frm) {
	if (frm.__pipeline_timer) {
		clearTimeout(frm.__pipeline_timer);
		frm.__pipeline_timer = null;
	}
}

function load_pipeline(frm) {
	stop_watching(frm);
	frappe.call({
		method: `${SLIP_API}.get_summary`,
		args: { name: frm.doc.name },
	}).then((r) => {
		const s = r.message;
		if (!s || !on_this_form(frm)) return;
		render_pipeline_panel(frm, s);

		const running = s.bulk && ["Queued", "Running"].includes(s.bulk.status) && !s.bulk.stale;
		if (running) {
			watch(frm, 3000, "bulk");
		} else if (s.needs_sync && !frm.__synced_recently) {
			// slips or mail changed behind our back (or the import predates this feature)
			frm.__synced_recently = true;
			setTimeout(() => (frm.__synced_recently = false), 15000);
			sync_now(frm);
		}
	});
}

function sync_now(frm) {
	frappe.call({
		method: `${SLIP_API}.refresh_status`,
		args: { name: frm.doc.name },
	}).then((r) => {
		const res = r.message || {};
		if (!on_this_form(frm)) return;
		if (res.changed) {
			frm.reload_doc();
		} else if (res.summary) {
			render_pipeline_panel(frm, res.summary);
		}
		if (res.summary && res.summary.mail_queued > 0) watch(frm, 8000, "mail", 0);
	});
}

// Poll while an action runs ("bulk"), then while queued mails leave the server ("mail").
function watch(frm, interval, mode, ticks) {
	stop_watching(frm);
	ticks = ticks || 0;
	const max_ticks = mode === "mail" ? 90 : 4000;
	frm.__pipeline_timer = setTimeout(() => {
		if (!on_this_form(frm) || ticks > max_ticks) return stop_watching(frm);

		const method = mode === "mail" ? "refresh_status" : "get_summary";
		frappe.call({ method: `${SLIP_API}.${method}`, args: { name: frm.doc.name } }).then((r) => {
			if (!on_this_form(frm)) return;
			const res = r.message || {};
			const s = mode === "mail" ? res.summary : res;
			if (!s) return;
			render_pipeline_panel(frm, s);

			if (mode === "bulk") {
				const active = s.bulk && ["Queued", "Running"].includes(s.bulk.status) && !s.bulk.stale;
				if (active) return watch(frm, interval, mode, ticks + 1);
				announce_result(s.bulk);
				frm.reload_doc();
				return;
			}
			if (res.changed) frm.reload_doc();
			if (s.mail_queued > 0) watch(frm, interval, mode, ticks + 1);
		});
	}, interval);
}

function announce_result(bulk) {
	if (!bulk || !bulk.message) return;
	frappe.show_alert({
		message: `<b>${frappe.utils.escape_html(bulk.action || "")}</b>: ${frappe.utils.escape_html(bulk.message)}`,
		indicator: bulk.status === "Failed" ? "red" : "green",
	}, 12);
}

function chip(label, count, color) {
	return `<span class="indicator-pill ${count ? color : "gray"}" style="margin-right:8px;">`
		+ `${frappe.utils.escape_html(label)} <b>${count}</b></span>`;
}

function render_pipeline_panel(frm, s) {
	const id = "slip-pipeline-panel";
	frm.$wrapper.find(`#${id}`).remove();
	if (!s || !s.with_sheet) return;

	const bulk = s.bulk || {};
	const running = ["Queued", "Running"].includes(bulk.status) && !bulk.stale;

	let progress = "";
	if (running) {
		const m = (bulk.message || "").match(/(\d+) of (\d+)/);
		const pct = m && +m[2] ? Math.round((100 * +m[1]) / +m[2]) : 5;
		progress = `
			<div style="margin:10px 0 4px;"><b>${frappe.utils.escape_html(bulk.action || "")}</b>
				<span class="text-muted">— ${frappe.utils.escape_html(bulk.message || "")}</span></div>
			<div class="progress" style="height:8px;margin-bottom:6px;">
				<div class="progress-bar progress-bar-striped active" style="width:${pct}%"></div>
			</div>`;
	} else if (bulk.stale) {
		progress = `<div class="text-warning" style="margin-top:8px;">${__("The last action ({0}) stopped responding. You can start it again.", [frappe.utils.escape_html(bulk.action || "")])}</div>`;
	}

	const slips = chip(__("No slip yet"), s.not_created + s.sheet_draft, "gray")
		+ chip(__("Draft"), s.slip_draft, "orange")
		+ chip(__("Submitted"), s.slip_submitted, "green")
		+ (s.slip_cancelled ? chip(__("Cancelled"), s.slip_cancelled, "red") : "");
	const mails = chip(__("Not sent"), s.mail_pending, "gray")
		+ chip(__("Queued"), s.mail_queued, "blue")
		+ chip(__("Sent"), s.mail_sent, "green")
		+ chip(__("Failed"), s.mail_failed, "red")
		+ chip(__("No email address"), s.no_address, "orange");

	const html = `
		<div id="${id}" class="form-section" style="margin-top:15px;">
			<div class="section-body">
				<div style="margin-bottom:6px;"><b>${__("Salary slips")}</b> <span class="text-muted">(${s.with_sheet} ${__("employees")})</span></div>
				<div style="margin-bottom:10px;">${slips}</div>
				<div style="margin-bottom:6px;"><b>${__("Emails")}</b>
					<span class="text-muted">— ${__("only submitted slips are emailed")}</span></div>
				<div>${mails}</div>
				${progress}
				${mail_issues_html(frm)}
			</div>
		</div>`;

	const $anchor = frm.fields_dict.error_count && frm.fields_dict.error_count.$wrapper
		? frm.fields_dict.error_count.$wrapper.closest(".section-body, .form-section")
		: null;
	if ($anchor && $anchor.length) {
		$anchor.after(html);
	} else {
		frm.fields_dict.rows.$wrapper.before(html);
	}
}

// Who was skipped and who failed, straight from the table, so HR can chase them.
function mail_issues_html(frm) {
	const rows = frm.doc.rows || [];
	const missing = rows.filter(r => r.payroll_sheet && !r.email_to && !r.email_queue
		&& ["Sheet Draft", "Not Created", "Draft", "Submitted"].includes(r.slip_status));
	const failed = rows.filter(r => r.email_status === "Failed");
	const line = (r) => `<li>${frappe.utils.escape_html(r.employee_name || r.employee || r.code || "")}`
		+ ` <span class="text-muted">(${frappe.utils.escape_html(r.employee || r.code || "")})</span>`
		+ (r.email_error ? ` — <span class="text-danger">${frappe.utils.escape_html(r.email_error)}</span>` : "") + "</li>";
	let html = "";
	if (failed.length) {
		html += `<details style="margin-top:10px;" open><summary class="text-danger"><b>${failed.length}</b> ${__("email(s) failed")}</summary>`
			+ `<ul style="margin:6px 0 0 18px;">${failed.map(line).join("")}</ul></details>`;
	}
	if (missing.length) {
		html += `<details style="margin-top:10px;"><summary class="text-warning"><b>${missing.length}</b> ${__("employee(s) have no email address - their emails are skipped until one is added")}</summary>`
			+ `<ul style="margin:6px 0 0 18px;">${missing.map(line).join("")}</ul></details>`;
	}
	return html;
}

const BULK_ACTIONS = {
	create_slips: (s) => {
		const fields = [];
		if (s.sheet_draft) {
			fields.push({
				fieldtype: "Check", fieldname: "submit_sheets",
				label: __("Also submit the {0} draft Payroll Sheet(s) first", [s.sheet_draft]),
			});
		}
		return {
			title: __("Create Salary Slips"),
			count: s.not_created,
			html: `<p>${__("{0} employee(s) have a submitted Payroll Sheet but no salary slip. A <b>draft</b> Salary Slip is created for each.", [s.not_created])}</p>`
				+ `<p class="text-muted">${__("A missing Salary Structure Assignment is created automatically from the default structure.")}</p>`
				+ (s.sheet_draft ? `<p class="text-warning">${__("{0} Payroll Sheet(s) are still Draft and are skipped unless you tick the box below.", [s.sheet_draft])}</p>` : "")
				+ (s.no_address ? `<p class="text-warning">${__("{0} employee(s) have no email address. Their slips are created, but their emails are skipped until an address is added on the Employee.", [s.no_address])}</p>` : "")
				+ (s.slip_cancelled ? `<p class="text-muted">${__("{0} cancelled slip(s) are not re-created here; use Create Salary Slip on the Payroll Sheet.", [s.slip_cancelled])}</p>` : ""),
			fields,
			ok: __("Create"),
			nothing: __("Every submitted Payroll Sheet already has a salary slip."),
			also: s.sheet_draft,
		};
	},
	submit_slips: (s) => ({
		title: __("Submit Salary Slips"),
		count: s.slip_draft,
		html: `<p>${__("{0} draft Salary Slip(s) will be submitted.", [s.slip_draft])}</p>`
			+ `<p class="text-muted">${__("Submitting does not email anyone. Use Send Salary Slip Emails for that.")}</p>`
			+ `<p class="text-muted">${__("If one slip fails to submit, the rest still go through.")}</p>`,
		fields: [],
		ok: __("Submit"),
		nothing: __("There are no draft salary slips to submit."),
	}),
	send_emails: (s) => {
		const fields = [];
		if (s.mail_sent) {
			fields.push({
				fieldtype: "Check", fieldname: "resend_all",
				label: __("Also send again to the {0} employee(s) already emailed", [s.mail_sent]),
			});
		}
		const todo = s.mail_pending + s.mail_failed;
		return {
			title: __("Send Salary Slip Emails"),
			count: todo,
			html: `<p>${todo
					? __("{0} email(s) with the salary slip PDF will be queued.", [todo])
					: __("No new emails to send.")}`
				+ (s.mail_failed ? ` ${__("This includes {0} that failed before.", [s.mail_failed])}` : "") + `</p>`
				+ (s.no_address ? `<p class="text-warning">${__("{0} employee(s) have no email address and are skipped.", [s.no_address])}</p>` : "")
				+ (s.mail_queued ? `<p class="text-muted">${__("{0} email(s) are still waiting in the queue and are not queued twice.", [s.mail_queued])}</p>` : "")
				+ (s.slip_draft ? `<p class="text-muted">${__("{0} slip(s) are still Draft - submit them to email them.", [s.slip_draft])}</p>` : "")
				+ `<p class="text-muted">${__("A problem with one employee never stops the others. Status shows per employee in the table.")}</p>`,
			fields,
			ok: __("Send"),
			nothing: s.slip_submitted
				? __("Nothing to send: every submitted slip has been emailed or has no email address.")
				: __("Submit the salary slips first - only submitted slips are emailed."),
			also: s.mail_sent,
		};
	},
};

function open_bulk(frm, action) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the document first."));
		return;
	}
	frappe.call({
		method: `${SLIP_API}.refresh_status`,
		args: { name: frm.doc.name },
		freeze: true,
		freeze_message: __("Checking the salary slips..."),
	}).then((r) => {
		const s = (r.message || {}).summary;
		if (!s) return;
		if (s.bulk && ["Queued", "Running"].includes(s.bulk.status) && !s.bulk.stale) {
			frappe.msgprint(__("Another action is still running: {0}", [frappe.utils.escape_html(s.bulk.message || s.bulk.action || "")]));
			return;
		}
		const cfg = BULK_ACTIONS[action](s);
		if (!cfg.count && !cfg.also) {
			frappe.msgprint({ title: cfg.title, message: cfg.nothing, indicator: "blue" });
			return;
		}
		const d = new frappe.ui.Dialog({
			title: cfg.title,
			fields: [{ fieldtype: "HTML", fieldname: "info", options: cfg.html }, ...cfg.fields],
			primary_action_label: cfg.ok,
			primary_action(values) {
				d.hide();
				frappe.call({
					method: `${SLIP_API}.start_bulk`,
					args: { name: frm.doc.name, action, options: values || {} },
				}).then(() => {
					frappe.show_alert({ message: __("{0} started - you can keep working.", [cfg.title]), indicator: "blue" });
					frm.reload_doc();
				});
			},
		});
		d.show();
	});
}
