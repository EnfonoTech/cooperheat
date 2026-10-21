// Division: one plain drill-down for the whole organisation.
// Top level has three tabs (support Divisions, Business Lines, old departments that still
// have no type). Click a name to see what is under it; the last level lists its employees.
// Route: /app/division/<tab>/<department>
frappe.pages["division"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Division"),
		single_column: true,
	});
	wrapper._dv = new DivisionScreen(page);
};

frappe.pages["division"].on_page_show = function (wrapper) {
	wrapper._dv && wrapper._dv.show();
};

const DV_API = "cooperheat.cooperheat.org.";
const dv_plural = (n, one, many) => `${cint(n)} ${cint(n) === 1 ? one : many}`;
const DV_TABS = [
	{ key: "Division", label: __("Division") },
	{ key: "Business Line", label: __("Business Line") },
	{ key: "Other", label: __("Old departments") },
];

class DivisionScreen {
	constructor(page) {
		this.page = page;
		this.company = null;
		this.inject_style();
		this.$root = $(`<div class="dv"></div>`).appendTo(page.main);
		this.company_field = page.add_field({
			fieldtype: "Link",
			fieldname: "company",
			label: __("Company"),
			options: "Company",
			hidden: 1,
			change: () => {
				const value = this.company_field.get_value();
				if (value && value !== this.company) {
					this.company = value;
					this.go(this.kind, null);
				}
			},
		});
	}

	show() {
		const route = frappe.get_route();
		this.kind = route[1] || "Division";
		this.node = route[2] || null;
		this.refresh();
	}

	go(kind, node) {
		frappe.set_route(...["division", kind, node].filter(Boolean));
	}

	refresh() {
		frappe
			.xcall(DV_API + "division_view", { node: this.node, kind: this.kind, company: this.company })
			.then((data) => this.render(data));
	}

	render(d) {
		this.company = d.company;
		this.kind = d.kind || this.kind;
		this.company_field.df.hidden = d.companies.length ? 0 : 1;
		this.company_field.refresh();
		if (d.companies.length) this.company_field.set_value(d.company);

		const $root = this.$root.empty();
		this.set_action(d);
		$root.append(this.crumbs(d));
		if (!d.node) $root.append(this.tabs(d));
		else $root.append(this.heading(d));

		const $children = $(`<div class="dv-grid"></div>`);
		d.children.forEach((c) => $children.append(this.card(c)));
		if (d.children.length) {
			$root.append(`<div class="dv-h">${d.node ? __("Inside {0}", [frappe.utils.escape_html(d.node.label)]) : ""}</div>`);
			$root.append($children);
		}
		if (d.node) $root.append(this.employees(d));
		if (!d.children.length && !d.node) {
			$root.append(`<div class="dv-empty">${__("Nothing here yet.")}</div>`);
		}
	}

	set_action(d) {
		this.page.clear_primary_action();
		if (!d.can_create || !d.add_type) return;
		this.page.set_primary_action(__("Add {0}", [__(d.add_type)]), () => {
			frappe.cooperheat_return_to_division = { kind: this.kind, node: this.node };
			frappe.new_doc("Department", {
				parent_department: d.node ? d.node.name : d.root,
				company: d.company,
				custom_unit_type: d.add_type,
			});
		});
	}

	crumbs(d) {
		const $c = $(`<div class="dv-crumbs"></div>`);
		const add = (label, fn) => $(`<a>${frappe.utils.escape_html(label)}</a>`).on("click", fn).appendTo($c);
		add(__("Division"), () => this.go(this.kind, null));
		d.breadcrumb.forEach((b, i) => {
			$c.append(`<span class="sep">›</span>`);
			if (i === d.breadcrumb.length - 1) $c.append(`<span class="cur">${frappe.utils.escape_html(b.label)}</span>`);
			else add(b.label, () => this.go(this.kind, b.name));
		});
		return $c;
	}

	tabs(d) {
		const $t = $(`<div class="dv-tabs"></div>`);
		DV_TABS.forEach((t) => {
			if (t.key === "Other" && !d.old_departments && this.kind !== "Other") return;
			const extra = t.key === "Other" && d.old_departments ? `<span class="cnt">${d.old_departments}</span>` : "";
			$(`<a class="dv-tab ${t.key === this.kind ? "active" : ""}">${t.label}${extra}</a>`)
				.on("click", () => this.go(t.key, null))
				.appendTo($t);
		});
		return $t;
	}

	heading(d) {
		const n = d.node;
		return $(`<div class="dv-head">
			<div class="dv-title">${frappe.utils.escape_html(n.label)}</div>
			<div class="dv-sub">${frappe.utils.escape_html(__(n.unit_type || ""))}
				· ${dv_plural(n.employees, __("employee"), __("employees"))} ${__("in total")}</div>
		</div>`);
	}

	card(c) {
		const sub = c.sub_units ? ` · ${dv_plural(c.sub_units, __("sub-unit"), __("sub-units"))}` : "";
		return $(`<div class="dv-card">
			<div class="dv-name">${frappe.utils.escape_html(c.label)}</div>
			<div class="dv-meta">${frappe.utils.escape_html(__(c.unit_type || ""))}</div>
			<div class="dv-meta"><b>${dv_plural(c.employees, __("employee"), __("employees"))}</b>${sub}</div>
		</div>`).on("click", () => this.go(this.kind, c.name));
	}

	employees(d) {
		const $s = $(`<div></div>`);
		$s.append(`<div class="dv-h">${__("Employees placed here")} (${d.employees.length})</div>`);
		if (!d.employees.length) {
			$s.append(`<div class="dv-empty small">${__("No employee is placed directly on {0}.", [frappe.utils.escape_html(d.node.label)])}</div>`);
			return $s;
		}
		const rows = d.employees
			.map(
				(e) => `<tr data-emp="${frappe.utils.escape_html(e.name)}">
					<td><a>${frappe.utils.escape_html(e.employee_name || e.name)}</a></td>
					<td>${frappe.utils.escape_html(e.designation || "")}</td>
					<td>${frappe.utils.escape_html(e.custom_staff_category || "")}</td>
					<td>${frappe.utils.escape_html(e.reports_to_name || "")}</td>
				</tr>`
			)
			.join("");
		const $table = $(`<table class="table table-bordered dv-table">
			<thead><tr><th>${__("Employee")}</th><th>${__("Designation")}</th><th>${__("Staff Category")}</th><th>${__("Reports To")}</th></tr></thead>
			<tbody>${rows}</tbody></table>`);
		$table.find("tr[data-emp]").on("click", function () {
			frappe.set_route("Form", "Employee", $(this).data("emp"));
		});
		$s.append($table);
		return $s;
	}

	inject_style() {
		if ($("#dv-style").length) return;
		$(`<style id="dv-style">
			.dv{padding-bottom:40px}
			.dv-crumbs{margin:2px 0 14px;color:var(--text-muted)}
			.dv-crumbs a{cursor:pointer;color:var(--text-color)}
			.dv-crumbs .sep{margin:0 8px}
			.dv-crumbs .cur{font-weight:600;color:var(--text-color)}
			.dv-tabs{display:flex;gap:4px;border-bottom:1px solid var(--border-color);margin-bottom:18px}
			.dv-tab{padding:8px 18px;cursor:pointer;border-bottom:2px solid transparent;color:var(--text-muted);font-weight:500}
			.dv-tab.active{color:var(--text-color);border-bottom-color:var(--primary)}
			.dv-tab .cnt{background:var(--orange-100,#fde8d0);color:var(--orange-600,#b45309);border-radius:10px;padding:0 7px;font-size:var(--text-xs);margin-left:6px}
			.dv-head{margin-bottom:16px}
			.dv-title{font-size:22px;font-weight:700}
			.dv-sub{color:var(--text-muted)}
			.dv-h{font-weight:600;margin:18px 0 10px}
			.dv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
			.dv-card{background:var(--card-bg);border:1px solid var(--border-color);border-radius:var(--border-radius-lg,10px);padding:14px 16px;cursor:pointer;transition:box-shadow .15s,border-color .15s}
			.dv-card:hover{box-shadow:var(--shadow-sm);border-color:var(--gray-400)}
			.dv-name{font-weight:600;font-size:15px}
			.dv-meta{color:var(--text-muted);font-size:var(--text-sm);margin-top:2px}
			.dv-table{background:var(--card-bg)}
			.dv-table tr[data-emp]{cursor:pointer}
			.dv-table tr[data-emp]:hover{background:var(--control-bg)}
			.dv-empty{padding:36px;text-align:center;color:var(--text-muted);background:var(--card-bg);border:1px dashed var(--border-color);border-radius:var(--border-radius-lg,10px)}
			.dv-empty.small{padding:18px}
		</style>`).appendTo(document.head);
	}
}
