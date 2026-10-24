// Service Request: the holder forwards it to the right person, or completes / rejects it.
frappe.ui.form.on("Service Request", {
	refresh(frm) {
		if (frm.is_new()) {
			frm.set_intro(
				__(
					"Your request goes to your reporting person first. They can send it on until it reaches the right person."
				),
				"blue"
			);
			return;
		}
		const holder = frm.doc.holder_name || __("nobody (HR will route it)");
		const color =
			{ Open: "orange", Completed: "green", Rejected: "red" }[frm.doc.status] || "blue";
		frm.set_intro(
			frm.doc.status === "Open"
				? __("With {0}", [holder])
				: __("{0} by {1}", [__(frm.doc.status), holder]),
			color
		);
		if (!(frm.doc.__onload && frm.doc.__onload.can_act)) return;
		const call = (method, args) =>
			frappe
				.xcall("cooperheat.cooperheat.service_request_tools." + method, {
					name: frm.doc.name,
					...args,
				})
				.then(() => frm.reload_doc());
		frm.add_custom_button(__("Forward"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Forward to"),
				fields: [
					{
						fieldname: "to_employee",
						label: __("Person who can do this"),
						fieldtype: "Link",
						options: "Employee",
						reqd: 1,
						get_query: () => ({ filters: { status: "Active" } }),
					},
					{ fieldname: "comment", label: __("Note"), fieldtype: "Small Text" },
				],
				primary_action_label: __("Forward"),
				primary_action(v) {
					d.hide();
					call("forward", v);
				},
			});
			d.show();
		}).addClass("btn-primary");
		for (const [label, method] of [
			[__("Complete"), "complete"],
			[__("Reject"), "reject"],
		]) {
			frm.add_custom_button(label, () => {
				frappe.prompt(
					{ fieldname: "comment", label: __("Note"), fieldtype: "Small Text" },
					(v) => call(method, v),
					label,
					label
				);
			});
		}
	},
});
