// "Division" tree: one expandable hierarchy for the support side
// (Division > Department > Sub-Department) and the operations side
// (Business Line > Product Line > Sub-Product Line). Loaded after ERPNext's own
// department_tree.js, so this extends its settings.
(function () {
	const ADD_BUTTONS = [
		// [button label, new node's Unit Type, parent Unit Types it appears on]
		[__("Add Department"), "Department", ["Division"]],
		[__("Add Sub-Department"), "Sub-Department", ["Department", "Sub-Department"]],
		[__("Add Product Line"), "Product Line", ["Business Line"]],
		[__("Add Sub-Product Line"), "Sub-Product Line", ["Product Line", "Sub-Product Line"]],
	];
	const ROOT_BUTTONS = [
		[__("Add Division"), "Division"],
		[__("Add Business Line"), "Business Line"],
	];

	function add_under(node, unit_type) {
		const company =
			(node.data && node.data.company) ||
			(window.cur_tree && cur_tree.args && cur_tree.args.company) ||
			frappe.defaults.get_user_default("Company");
		frappe.cooperheat_return_to_tree = true;
		frappe.new_doc("Department", {
			parent_department: node.is_root ? "All Departments" : node.label,
			company: company,
			custom_unit_type: unit_type,
		});
	}

	const toolbar = [
		// Replaces the stock "Add Child" (same label) with typed buttons below.
		{ label: __("Add Child"), condition: () => false, click: () => {} },
	];
	ADD_BUTTONS.forEach(([label, unit_type, parents]) => {
		toolbar.push({
			label: label,
			condition: (node) =>
				!node.is_root && parents.includes(node.data && node.data.unit_type),
			click: (node) => add_under(node, unit_type),
		});
	});
	ROOT_BUTTONS.forEach(([label, unit_type]) => {
		toolbar.push({
			label: label,
			condition: (node) => !!node.is_root,
			click: (node) => add_under(node, unit_type),
		});
	});
	// A node without a Unit Type (old data): plain child, the server fills what it can.
	toolbar.push({
		label: __("Add Sub-unit"),
		condition: (node) => !node.is_root && !(node.data && node.data.unit_type),
		click: (node) => add_under(node, null),
	});

	const settings = frappe.treeview_settings["Department"] || {};
	frappe.treeview_settings["Department"] = Object.assign(settings, {
		title: __("Division"),
		get_tree_nodes: "cooperheat.cooperheat.org.department_children",
		extend_toolbar: true,
		toolbar: toolbar,
		// Unit Type and head count next to each name.
		onrender: function (node) {
			if (node.is_root || !node.data) return;
			const $link = node.$tree_link;
			if (!$link || $link.find(".ch-unit").length) return;
			const type = node.data.unit_type
				? frappe.utils.escape_html(__(node.data.unit_type))
				: "";
			const count = node.data.employees ? ` · ${cint(node.data.employees)}` : "";
			if (type || count) {
				$link.append(
					`<span class="ch-unit text-muted" style="margin-left:8px;font-size:11px;">${type}${count}</span>`
				);
			}
		},
		menu_items: (settings.menu_items || []).concat([
			{
				label: __("Division screen"),
				action: function () {
					frappe.set_route("division");
				},
			},
		]),
	});
})();
