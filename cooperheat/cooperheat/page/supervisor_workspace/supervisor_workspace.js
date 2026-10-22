frappe.pages["supervisor-workspace"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Supervisor Workspace"),
		single_column: true,
	});
	wrapper._sw = new SupervisorWorkspace(wrapper, page);
};

frappe.pages["supervisor-workspace"].on_page_show = function (wrapper) {
	wrapper._sw && wrapper._sw.refresh();
};

const SW_API = "cooperheat.cooperheat.api.supervisor.";

const SW_FILTERS = [
	{ key: "all", label: __("All") },
	{ key: "in", label: __("On site") },
	{ key: "out", label: __("Checked out") },
	{ key: "none", label: __("No check-in") },
	{ key: "approve", label: __("Needs approval") },
];

class SupervisorWorkspace {
	constructor(wrapper, page) {
		this.page = page;
		this.team = [];
		this.groups = [];
		this.tab = "team";
		this.filter = "all";
		this.search = "";
		this.scope = "day";
		this.date = frappe.datetime.get_today();
		this.selected = null;

		this.date_field = page.add_field({
			fieldtype: "Date",
			fieldname: "date",
			label: __("Day"),
			default: this.date,
			change: () => {
				this.date = this.date_field.get_value() || frappe.datetime.get_today();
				this.refresh();
			},
		});
		page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.add_menu();

		this.inject_style();
		this.$root = $(`<div class="sw"></div>`).appendTo(page.main);
		this.refresh();
	}

	add_menu() {
		const page = this.page;
		if (frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager") || frappe.user.has_role("HR User")) {
			page.add_menu_item(__("All check-ins (plain list)"), () => {
				frappe.cooperheat_checkin_list = true;
				frappe.set_route("List", "Employee Checkin");
			});
		}
		if (frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager")) {
			page.add_menu_item(__("Recalculate overtime"), () => this.recalculate_overtime());
			page.add_menu_item(__("Generate attendance from check-ins"), () => {
				frappe.xcall("cooperheat.cooperheat.api.attendance_gen.run_now").then((r) => {
					frappe.msgprint(
						__("Created {0} attendance record(s). Skipped {1}; {2} waiting for a Level 1 approver in their department.", [
							r.created, r.skipped, r.no_approver,
						])
					);
					this.refresh();
				});
			});
		}
		if (frappe.boot.developer_mode && frappe.user.has_role("System Manager")) {
			page.add_menu_item(__("Reset demo data (dev site)"), () => {
				frappe.confirm(__("Wipe the demo users' check-ins and attendance and recreate the two seeded days?"), () => {
					frappe.xcall("cooperheat.cooperheat.dev_seed.reset_demo").then(() => {
						frappe.show_alert({ message: __("Demo data restored"), indicator: "green" });
						this.refresh();
					});
				});
			});
		}
	}

	recalculate_overtime() {
		const call = (values, dry_run) =>
			frappe.xcall("cooperheat.cooperheat.overtime.recalculate_overtime", {
				from_date: values.from_date,
				to_date: values.to_date,
				employee: values.employee || null,
				dry_run: dry_run,
			});
		const dialog = new frappe.ui.Dialog({
			title: __("Recalculate overtime"),
			fields: [
				{ fieldtype: "Date", fieldname: "from_date", label: __("From"), reqd: 1, default: frappe.datetime.add_days(frappe.datetime.get_today(), -30) },
				{ fieldtype: "Date", fieldname: "to_date", label: __("To"), reqd: 1, default: frappe.datetime.get_today() },
				{ fieldtype: "Link", fieldname: "employee", label: __("Employee (optional)"), options: "Employee" },
				{ fieldtype: "HTML", fieldname: "note", options: `<p class="text-muted">${__("Re-derives regular and overtime hours from each day's working hours and the employee's Staff Category (Field: over 8 h is overtime; Office: none). First shows how many records would change.")}</p>` },
			],
			primary_action_label: __("Check"),
			primary_action: (values) => {
				call(values, 1).then((r) => {
					dialog.hide();
					if (!r.changed) {
						frappe.msgprint(__("{0} records checked: nothing to change.", [r.checked]));
						return;
					}
					frappe.confirm(
						__("{0} of {1} records would change. Apply now?", [r.changed, r.checked]),
						() => call(values, 0).then((done) => frappe.show_alert({ message: __("{0} records updated", [done.changed]), indicator: "green" }))
					);
				});
			},
		});
		dialog.show();
	}

	inject_style() {
		if ($("#sw-style").length) return;
		$(`<style id="sw-style">
			.sw{padding-bottom:40px}
			.sw-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:4px 0 16px}
			.sw-stat{background:var(--card-bg);border:1px solid var(--border-color);border-radius:var(--border-radius-lg,10px);padding:12px 14px;cursor:pointer;transition:box-shadow .15s,border-color .15s}
			.sw-stat:hover{box-shadow:var(--shadow-sm);border-color:var(--gray-400)}
			.sw-stat.active{border-color:var(--primary);box-shadow:0 0 0 1px var(--primary)}
			.sw-stat .n{font-size:26px;font-weight:700;line-height:1.1}
			.sw-stat .l{color:var(--text-muted);font-size:var(--text-sm);margin-top:2px}
			.sw-stat.warn .n{color:var(--orange-600,#c2410c)}
			.sw-stat.ok .n{color:var(--green-600,#15803d)}
			.sw-bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
			.sw-search{flex:1 1 240px;max-width:360px}
			.sw-chips{display:flex;gap:6px;flex-wrap:wrap}
			.sw-chip{border:1px solid var(--border-color);background:var(--card-bg);border-radius:999px;padding:3px 12px;font-size:var(--text-sm);cursor:pointer;color:var(--text-color)}
			.sw-chip.active{background:var(--primary);border-color:var(--primary);color:#fff}
			.sw-tabs{display:flex;gap:4px;border-bottom:1px solid var(--border-color);margin-bottom:16px}
			.sw-tab{padding:8px 16px;cursor:pointer;border-bottom:2px solid transparent;color:var(--text-muted);font-weight:500}
			.sw-tab.active{color:var(--text-color);border-bottom-color:var(--primary)}
			.sw-tab .cnt{background:var(--orange-100,#fde8d0);color:var(--orange-600,#b45309);border-radius:10px;padding:0 7px;font-size:var(--text-xs);margin-left:6px}
			.sw-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px}
			.sw-card{background:var(--card-bg);border:1px solid var(--border-color);border-radius:var(--border-radius-lg,10px);padding:14px;cursor:pointer;display:flex;gap:12px;align-items:flex-start;transition:box-shadow .15s,border-color .15s}
			.sw-card:hover{box-shadow:var(--shadow-sm);border-color:var(--gray-400)}
			.sw-av{flex:0 0 40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;background:var(--gray-500)}
			.sw-av.in{background:var(--green-500,#22a06b)}
			.sw-av.out{background:var(--blue-500,#2d7ff9)}
			.sw-main{flex:1;min-width:0}
			.sw-name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
			.sw-sub{color:var(--text-muted);font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
			.sw-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;align-items:center}
			.sw-b{display:inline-block;padding:2px 8px;border-radius:10px;font-size:var(--text-xs);background:var(--control-bg);color:var(--text-color)}
			.sw-b.in{background:var(--green-100,#d6f5e1);color:var(--green-700,#166534)}
			.sw-b.pend{background:var(--orange-100,#fde8d0);color:var(--orange-700,#9a3412)}
			.sw-b.done{background:var(--green-100,#d6f5e1);color:var(--green-700,#166534)}
			.sw-empty{padding:36px;text-align:center;color:var(--text-muted);background:var(--card-bg);border:1px dashed var(--border-color);border-radius:var(--border-radius-lg,10px)}
			.sw-seg{display:inline-flex;border:1px solid var(--border-color);border-radius:8px;overflow:hidden;margin-bottom:14px}
			.sw-seg a{padding:5px 14px;cursor:pointer;color:var(--text-color);background:var(--card-bg);border-right:1px solid var(--border-color)}
			.sw-seg a:last-child{border-right:0}
			.sw-seg a.active{background:var(--primary);color:#fff}
			.sw-group{background:var(--card-bg);border:1px solid var(--border-color);border-radius:var(--border-radius-lg,10px);margin-bottom:12px;overflow:hidden}
			.sw-group-h{display:flex;align-items:center;gap:12px;padding:10px 14px;background:var(--control-bg)}
			.sw-group-h .sw-name{flex:1}
			.sw-row{display:flex;align-items:center;gap:14px;padding:9px 14px;border-top:1px solid var(--border-color);flex-wrap:wrap}
			.sw-row .d{width:120px;font-weight:600}
			.sw-row .t{flex:1;min-width:160px;color:var(--text-muted)}
			.sw-row .h{width:70px;text-align:right}
			.sw-row .act{display:flex;gap:8px;align-items:center;min-width:150px;justify-content:flex-end}
			.sw-back{cursor:pointer;color:var(--text-muted);display:inline-block;margin-bottom:10px}
			.sw-detail-h{display:flex;gap:14px;align-items:center;margin-bottom:6px}
			.sw-sum{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 16px}
			.sw-sum .sw-stat{cursor:default;min-width:130px}
			.sw-logs{background:var(--control-bg);padding:6px 14px 8px 134px;border-top:1px solid var(--border-color)}
			.sw-log{display:flex;gap:12px;align-items:center;padding:4px 0}
			.sw-link{cursor:pointer;color:var(--primary)}
			@media (max-width:640px){.sw-row .d{width:100%}.sw-logs{padding-left:14px}.sw-row .act{justify-content:flex-start}}
		</style>`).appendTo("head");
	}

	esc(v) {
		return frappe.utils.escape_html(v == null ? "" : String(v));
	}

	initials(name) {
		const parts = (name || "?").trim().split(/\s+/);
		return ((parts[0] || "?")[0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
	}

	hm(ts) {
		return ts ? String(ts).slice(11, 16) : "—";
	}

	// ── data ───────────────────────────────────────────────────────────────
	refresh() {
		this.selected = null;
		this.$root.html(`<div class="sw-empty">${__("Loading...")}</div>`);
		return Promise.all([
			frappe.xcall(SW_API + "get_team", { date: this.date }),
			frappe.xcall(SW_API + "get_pending_grouped", { date: this.date, scope: this.scope }),
		]).then(([team, groups]) => {
			this.team = team;
			this.groups = groups;
			this.render();
		});
	}

	totals() {
		const t = { all: this.team.length, in: 0, out: 0, none: 0, approve: 0, pending: 0 };
		for (const m of this.team) {
			t[m.state] = (t[m.state] || 0) + 1;
			t.pending += m.pending;
			if (m.pending) t.approve += 1;
		}
		return t;
	}

	render() {
		const t = this.totals();
		const tile = (key, n, label, cls) =>
			`<div class="sw-stat ${cls || ""} ${this.filter === key && this.tab === "team" ? "active" : ""}" data-filter="${key}">
				<div class="n">${n}</div><div class="l">${label}</div></div>`;
		this.$root.html(`
			<div class="sw-stats">
				${tile("all", t.all, __("Team members"))}
				${tile("in", t.in, __("On site now"), "ok")}
				${tile("out", t.out, __("Checked out"))}
				${tile("none", t.none, __("No check-in"))}
				${tile("approve", t.pending, __("Awaiting your approval"), t.pending ? "warn" : "")}
			</div>
			<div class="sw-tabs">
				<div class="sw-tab ${this.tab === "team" ? "active" : ""}" data-tab="team">${__("Team")}</div>
				<div class="sw-tab ${this.tab === "approvals" ? "active" : ""}" data-tab="approvals">${__("Approvals")}${
					t.pending ? `<span class="cnt">${t.pending}</span>` : ""
				}</div>
			</div>
			<div class="sw-body"></div>`);
		this.$body = this.$root.find(".sw-body");
		this.$root.find(".sw-stat[data-filter]").on("click", (e) => {
			this.filter = $(e.currentTarget).data("filter");
			this.tab = "team";
			this.render();
		});
		this.$root.find(".sw-tab").on("click", (e) => {
			this.tab = $(e.currentTarget).data("tab");
			this.render();
		});
		this.tab === "team" ? this.render_team() : this.render_approvals();
	}

	// ── team tab ───────────────────────────────────────────────────────────
	visible_team() {
		const q = this.search.trim().toLowerCase();
		return this.team.filter((m) => {
			if (this.filter === "approve" && !m.pending) return false;
			if (["in", "out", "none"].includes(this.filter) && m.state !== this.filter) return false;
			if (q && !((m.employee_name || "") + " " + (m.designation || "") + " " + (m.department || "") + " " + m.employee).toLowerCase().includes(q)) return false;
			return true;
		});
	}

	render_team() {
		const chips = SW_FILTERS.map(
			(f) => `<span class="sw-chip ${this.filter === f.key ? "active" : ""}" data-f="${f.key}">${f.label}</span>`
		).join("");
		this.$body.html(`
			<div class="sw-bar">
				<input type="search" class="form-control sw-search" placeholder="${__("Search name, designation or department")}" value="${this.esc(this.search)}">
				<div class="sw-chips">${chips}</div>
			</div>
			<div class="sw-grid"></div>`);
		this.$body.find(".sw-search").on("input", (e) => {
			this.search = e.target.value;
			this.paint_cards();
		});
		this.$body.find(".sw-chip").on("click", (e) => {
			this.filter = $(e.currentTarget).data("f");
			this.render();
		});
		this.paint_cards();
	}

	paint_cards() {
		const list = this.visible_team();
		const $grid = this.$body.find(".sw-grid");
		if (!list.length) {
			$grid.replaceWith(`<div class="sw-grid"><div class="sw-empty" style="grid-column:1/-1">${
				this.team.length ? __("Nobody matches this filter.") : __("No technicians are linked to you yet. Ask HR to set your technicians' Reports To, or add you as approver in their Department.")
			}</div></div>`);
			return;
		}
		const cards = list.map((m) => {
			const state =
				m.state === "in"
					? `<span class="sw-b in">${__("On site since {0}", [this.hm(m.first_in)])}</span>`
					: m.state === "out"
					? `<span class="sw-b">${__("Out {0}", [this.hm(m.last_log)])}</span>`
					: `<span class="sw-b">${__("No check-in")}</span>`;
			const hrs = m.hours_today ? `<span class="sw-b">${this.esc(m.hours_today)} ${__("h")}</span>` : "";
			const pend = m.pending ? `<span class="sw-b pend">${__("{0} to approve", [m.pending])}</span>` : "";
			return `<div class="sw-card" data-emp="${this.esc(m.employee)}">
				<div class="sw-av ${m.state}">${this.esc(this.initials(m.employee_name))}</div>
				<div class="sw-main">
					<div class="sw-name">${this.esc(m.employee_name)}</div>
					<div class="sw-sub">${this.esc([m.designation, m.department].filter(Boolean).join(" · "))}</div>
					<div class="sw-meta">${state}${hrs}${pend}</div>
				</div></div>`;
		});
		$grid.html(cards.join(""));
		$grid.find(".sw-card").on("click", (e) => this.open_employee($(e.currentTarget).attr("data-emp")));
	}

	// ── approvals tab ──────────────────────────────────────────────────────
	render_approvals() {
		const seg = [
			["day", __("Selected day")],
			["earlier", __("Earlier")],
			["all", __("All pending")],
		]
			.map(([k, l]) => `<a class="${this.scope === k ? "active" : ""}" data-scope="${k}">${l}</a>`)
			.join("");
		const total = this.groups.reduce((n, g) => n + g.items.length, 0);
		let html = `<div class="sw-bar"><div class="sw-seg">${seg}</div>
			<span class="sw-sub">${__("{0} record(s) for {1} technician(s)", [total, this.groups.length])}</span>
			${total ? `<button class="btn btn-primary btn-sm sw-all" style="margin-left:auto">${__("Approve all ({0})", [total])}</button>` : ""}</div>`;
		if (!this.groups.length) {
			html += `<div class="sw-empty">${this.scope === "day" ? __("Nothing waiting for you on this day.") : __("Nothing waiting for you.")}
				${this.scope === "day" ? `<div style="margin-top:6px"><a class="sw-link sw-showall">${__("Show all pending")}</a></div>` : ""}</div>`;
		}
		for (const g of this.groups) {
			html += `<div class="sw-group" data-emp="${this.esc(g.employee)}">
				<div class="sw-group-h">
					<div class="sw-av" style="width:32px;height:32px;flex-basis:32px;font-size:12px">${this.esc(this.initials(g.employee_name))}</div>
					<div class="sw-name sw-open" style="cursor:pointer">${this.esc(g.employee_name)}</div>
					<span class="sw-b pend">${__("{0} pending", [g.items.length])}</span>
					<button class="btn btn-default btn-xs sw-grp-all">${__("Approve all")}</button>
				</div>
				${g.items
					.map(
						(i) => `<div class="sw-row" data-att="${this.esc(i.attendance)}">
							<div class="d">${this.esc(moment(i.date).format("ddd D MMM"))}</div>
							<div class="t">${this.esc(this.hm(i.in_time))} – ${this.esc(this.hm(i.out_time))} · ${this.esc(i.state)}</div>
							<div class="h"><b>${this.esc(i.hours)}</b> ${__("h")}</div>
							<div class="act"><a class="sw-link sw-open-att">${__("Open")}</a>
								<button class="btn btn-primary btn-xs sw-approve">${__("Approve")}</button></div>
						</div>`
					)
					.join("")}</div>`;
		}
		this.$body.html(html);
		this.$body.find(".sw-seg a").on("click", (e) => {
			this.scope = $(e.currentTarget).data("scope");
			this.refresh().then(() => { this.tab = "approvals"; this.render(); });
		});
		this.$body.find(".sw-showall").on("click", () => {
			this.scope = "all";
			this.refresh().then(() => { this.tab = "approvals"; this.render(); });
		});
		this.$body.find(".sw-open").on("click", (e) => this.open_employee($(e.currentTarget).closest(".sw-group").attr("data-emp")));
		this.$body.find(".sw-open-att").on("click", (e) => frappe.set_route("Form", "Attendance", $(e.currentTarget).closest(".sw-row").data("att")));
		this.$body.find(".sw-approve").on("click", (e) => this.approve([$(e.currentTarget).closest(".sw-row").data("att")]));
		this.$body.find(".sw-grp-all").on("click", (e) => {
			const names = $(e.currentTarget).closest(".sw-group").find(".sw-row").map((_, r) => $(r).data("att")).get();
			this.confirm_approve(names);
		});
		this.$body.find(".sw-all").on("click", () => {
			this.confirm_approve(this.groups.flatMap((g) => g.items.map((i) => i.attendance)));
		});
	}

	confirm_approve(names) {
		frappe.confirm(__("Approve {0} record(s)?", [names.length]), () => this.approve(names));
	}

	approve(names) {
		const call = names.length === 1
			? frappe.xcall(SW_API + "approve_attendance", { attendance: names[0] }).then((r) => ({ approved: [r.attendance], failed: [] }))
			: frappe.xcall(SW_API + "approve_many", { attendances: names });
		return call.then((r) => {
			if (r.approved.length) frappe.show_alert({ message: __("Approved {0} record(s)", [r.approved.length]), indicator: "green" });
			if (r.failed.length) {
				frappe.msgprint({
					title: __("Some records could not be approved"),
					indicator: "orange",
					message: r.failed.map((f) => `<div><b>${this.esc(f.attendance)}</b>: ${this.esc(f.error)}</div>`).join(""),
				});
			}
			const keep = this.selected;
			return this.refresh().then(() => {
				if (keep) this.open_employee(keep);
				else { this.tab = "approvals"; this.render(); }
			});
		});
	}

	// ── one technician ─────────────────────────────────────────────────────
	open_employee(emp) {
		this.selected = emp;
		const m = this.team.find((x) => x.employee === emp) || { employee_name: emp };
		this.$root.html(`<div class="sw-empty">${__("Loading...")}</div>`);
		// attr(), not data(): jQuery turns an all-digit id (production employee ids are numbers like
		// 3044307) into a Number and the server then refuses it as a non-string.
		frappe.xcall(SW_API + "get_employee_days", { employee: String(emp) }).catch((err) => {
			this.selected = null;
			this.refresh();
			throw err;
		}).then((days) => {
			const worked = days.filter((d) => d.total_hours > 0);
			const hours = worked.reduce((n, d) => n + d.total_hours, 0);
			const pending = days.filter((d) => d.can_approve).length;
			let html = `<a class="sw-back">&larr; ${__("Back to team")}</a>
				<div class="sw-detail-h">
					<div class="sw-av ${m.state || ""}" style="width:48px;height:48px;flex-basis:48px">${this.esc(this.initials(m.employee_name))}</div>
					<div><div class="sw-name" style="font-size:var(--text-xl)">${this.esc(m.employee_name)}</div>
					<div class="sw-sub">${this.esc([m.designation, m.department, m.cell_number].filter(Boolean).join(" · "))}</div></div>
				</div>
				<div class="sw-sum">
					<div class="sw-stat"><div class="n">${worked.length}</div><div class="l">${__("Days worked (14 d)")}</div></div>
					<div class="sw-stat"><div class="n">${Math.round(hours * 10) / 10}</div><div class="l">${__("Total hours")}</div></div>
					<div class="sw-stat ${pending ? "warn" : ""}"><div class="n">${pending}</div><div class="l">${__("To approve")}</div></div>
				</div>
				<div class="sw-sub" style="margin-bottom:6px">${__("Click a date to see every check-in and check-out.")}</div>
				<div class="sw-group">`;
			if (!days.length) html += `<div class="sw-empty" style="border:0">${__("No attendance in this period.")}</div>`;
			for (const d of days) {
				const att = d.attendance;
				const st = att ? att.workflow_state || att.status : __("No attendance yet");
				const cls = att && /Pending/.test(att.workflow_state || "") ? "pend" : att && att.workflow_state === "Approved" ? "done" : "";
				html += `<div class="sw-day" data-date="${this.esc(d.date)}">
					<div class="sw-row sw-day-head" style="cursor:pointer">
						<div class="d">${this.esc(moment(d.date).format("ddd D MMM"))}</div>
						<div class="t">${this.esc(this.hm(d.first_in))} – ${this.esc(this.hm(d.last_out))}
							${d.complete ? "" : `<span class="sw-b pend">${__("Open check-in")}</span>`}
							<span class="sw-b ${cls}">${this.esc(st)}</span></div>
						<div class="h"><b>${this.esc(d.total_hours)}</b> ${__("h")}</div>
						<div class="act">${att ? `<a class="sw-link sw-open-att" data-att="${this.esc(att.name)}">${__("Open")}</a>` : ""}
							${d.can_approve ? `<button class="btn btn-primary btn-xs sw-approve" data-att="${this.esc(att.name)}">${__("Approve")}</button>` : ""}</div>
					</div>
					<div class="sw-logs" style="display:none">${d.checkins
						.map(
							(c) => `<div class="sw-log">
								<span class="sw-b ${c.log_type === "IN" ? "in" : ""}">${this.esc(c.log_type)}</span>
								<b>${this.esc(this.hm(c.time))}</b>
								<span class="sw-sub">${this.esc(c.project_label || "")}</span>
								${c.editable
									? `<a class="sw-link sw-edit" data-name="${this.esc(c.name)}" data-time="${this.esc(c.time)}">${__("Edit time")}</a>`
									: `<span class="sw-sub">${__("locked (over 48h or approved)")}</span>`}
							</div>`
						)
						.join("") || `<div class="sw-sub">${__("No check-ins")}</div>`}</div></div>`;
			}
			html += `</div>`;
			this.$root.html(html);
			this.$root.find(".sw-back").on("click", () => { this.selected = null; this.refresh(); });
			this.$root.find(".sw-day-head").on("click", (e) => {
				if ($(e.target).closest("a,button").length) return;
				$(e.currentTarget).siblings(".sw-logs").slideToggle(120);
			});
			this.$root.find(".sw-open-att").on("click", (e) => frappe.set_route("Form", "Attendance", $(e.currentTarget).data("att")));
			this.$root.find(".sw-approve").on("click", (e) => this.approve([$(e.currentTarget).data("att")]));
			this.$root.find(".sw-edit").on("click", (e) => {
				const $a = $(e.currentTarget);
				this.edit_time($a.data("name"), $a.data("time"), emp);
			});
		});
	}

	edit_time(name, current, emp) {
		frappe.prompt(
			[{ fieldname: "time", fieldtype: "Datetime", label: __("New time"), default: current, reqd: 1 }],
			(v) => {
				frappe.xcall(SW_API + "set_checkin_time", { checkin: name, time: v.time }).then(() => {
					frappe.show_alert({ message: __("Time updated"), indicator: "green" });
					this.refresh().then(() => this.open_employee(emp));
				});
			},
			__("Edit check-in time"),
			__("Save")
		);
	}
}
