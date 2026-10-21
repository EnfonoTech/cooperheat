// Department form: show what sits under this node and add children from here.
frappe.ui.form.on("Department", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.parent_department) return;
		frm.add_custom_button(__("Open in Division"), () => {
			const kind = cooperheat_kind_of(frm.doc.custom_unit_type);
			frappe.set_route(
				...["division", kind, kind === "Other" ? null : frm.doc.name].filter(Boolean)
			);
		});
		cooperheat_department_overview(frm);
	},
	after_save(frm) {
		// Created from the Division screen: go back to where it was added.
		const back = frappe.cooperheat_return_to_division;
		if (back) {
			frappe.cooperheat_return_to_division = null;
			frappe.set_route(...["division", back.kind, back.node].filter(Boolean));
			return;
		}
		// Created from the tree: go back to it.
		if (frappe.cooperheat_return_to_tree) {
			frappe.cooperheat_return_to_tree = false;
			frappe.set_route("Tree", "Department");
		}
	},
	parent_department(frm) {
		if (!frm.doc.parent_department || frm.doc.custom_unit_type) return;
		frappe.db
			.get_value("Department", frm.doc.parent_department, "custom_unit_type")
			.then((r) => {
				const child = cooperheat_child_type((r.message || {}).custom_unit_type);
				if (child && !frm.doc.custom_unit_type) frm.set_value("custom_unit_type", child);
			});
	},
});

const COOPERHEAT_CHILD_TYPE = {
	Division: "Department",
	Department: "Sub-Department",
	"Sub-Department": "Sub-Department",
	"Business Line": "Product Line",
	"Product Line": "Sub-Product Line",
	"Sub-Product Line": "Sub-Product Line",
};

function cooperheat_kind_of(unit_type) {
	if (["Division", "Department", "Sub-Department"].includes(unit_type)) return "Division";
	if (["Business Line", "Product Line", "Sub-Product Line"].includes(unit_type))
		return "Business Line";
	return "Other";
}

function cooperheat_child_type(parent_type) {
	return COOPERHEAT_CHILD_TYPE[parent_type] || null;
}

function cooperheat_department_overview(frm) {
	frappe.call({
		method: "cooperheat.cooperheat.org.department_overview",
		args: { department: frm.doc.name },
		callback(r) {
			const data = r.message;
			if (!data) return;
			const child_type = data.child_type;
			if (child_type && frm.doc.docstatus < 1 && frappe.model.can_create("Department")) {
				frm.add_custom_button(__("Add {0}", [__(child_type)]), () => {
					frappe.cooperheat_return_to_tree = false;
					frappe.cooperheat_return_to_division = {
						kind: cooperheat_kind_of(child_type),
						node: frm.doc.name,
					};
					frappe.new_doc("Department", {
						parent_department: frm.doc.name,
						company: frm.doc.company,
						custom_unit_type: child_type,
					});
				});
			}
			let html;
			if (!data.children.length) {
				html = `<div class="text-muted">${__("Nothing under {0} yet.", [
					frappe.utils.escape_html(frm.doc.department_name),
				])}</div>`;
			} else {
				const rows = data.children
					.map(
						(c) => `<tr>
							<td><a href="/app/department/${encodeURIComponent(c.name)}">${frappe.utils.escape_html(
							c.department_name
						)}</a></td>
							<td class="text-muted">${frappe.utils.escape_html(__(c.custom_unit_type || ""))}</td>
							<td class="text-right">${cint(c.employees)}</td>
						</tr>`
					)
					.join("");
				html = `<table class="table table-sm" style="margin:0">
					<thead><tr><th>${__("Name")}</th><th>${__("Type")}</th><th class="text-right">${__(
					"Employees"
				)}</th></tr></thead>
					<tbody>${rows}</tbody></table>`;
			}
			frm.dashboard.add_section(html, __("Contains ({0})", [data.children.length]));
			frm.dashboard.show();
		},
	});
}
