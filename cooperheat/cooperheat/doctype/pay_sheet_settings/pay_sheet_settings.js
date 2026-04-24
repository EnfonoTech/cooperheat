// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

frappe.ui.form.on("Pay Sheet Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Setup Defaults"), () => {
			frappe.confirm(
				__("This will:<br>") +
				__("1. Create missing Salary Components referenced by defaults") + "<br>" +
				__("2. Populate the Component Mapping if empty") + "<br>" +
				__("3. Create a <b>Cooperheat Default</b> Salary Structure and link it here") + "<br><br>" +
				__("Existing rows and already-created records are left untouched. Proceed?"),
				() => {
					frappe.call({
						method: "cooperheat.cooperheat.doctype.pay_sheet_settings.pay_sheet_settings.setup_defaults",
						freeze: true,
						freeze_message: __("Setting up..."),
					}).then(r => {
						const res = r.message || {};
						frappe.msgprint({
							title: __("Setup complete"),
							indicator: "green",
							message: `
								${__("Components created")}: <b>${(res.components_created || []).length}</b><br>
								${__("Mapping rows added")}: <b>${res.mapping_added || 0}</b><br>
								${__("Default Structure")}: <b>${res.default_structure || "-"}</b>
							`,
						});
						frm.reload_doc();
					});
				}
			);
		}, __("Actions"));
	},
});
