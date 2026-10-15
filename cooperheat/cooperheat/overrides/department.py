import frappe
from frappe import _
from frappe.utils import cint, cstr, now


_LEVEL_STATE = {
	1: "Pending Level 1 Approval",
	2: "Pending Level 2 Approval",
	3: "Pending Level 3 Approval",
}


_LAYOUT_FIELDTYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}


def validate(doc, method=None):
	"""A supervisor may maintain the approvers of their own department, within limits:

	* only if they are ALREADY an approver of that department (otherwise anyone with
	  one report in a department could appoint themselves and widen their own scope);
	* only at their own level or below - never replace someone more senior;
	* nothing else on the Department record.
	"""
	from cooperheat.cooperheat.permissions.scope import is_scoped

	if doc.is_new() or not is_scoped(frappe.session.user):
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	for df in doc.meta.fields:
		if df.fieldtype in _LAYOUT_FIELDTYPES or df.fieldtype in frappe.model.table_fields:
			continue
		if cstr(doc.get(df.fieldname)) != cstr(before.get(df.fieldname)):
			frappe.throw(
				_("You can only change the Approval Matrix of a department. {0} is read-only for you.").format(
					_(df.label or df.fieldname)
				)
			)

	def rows(d):
		return {
			(cint(r.approval_level), cstr(r.approver), cint(r.approval_window_hours))
			for r in (d.get("approval_matrix") or [])
		}

	old_rows, new_rows = rows(before), rows(doc)
	changed_levels = {row[0] for row in old_rows ^ new_rows}
	if not changed_levels:
		return

	mine = set(frappe.get_all("Employee", filters={"user_id": frappe.session.user}, pluck="name"))
	my_levels = [lvl for (lvl, approver, _w) in old_rows if approver in mine]
	if not my_levels:
		frappe.throw(_("Only an approver of this department can change its Approval Matrix."))
	if max(changed_levels) > max(my_levels):
		frappe.throw(
			_("You can change approvers up to your own level ({0}). Ask HR to change more senior levels.").format(
				max(my_levels)
			)
		)


def on_update(doc, method):
	"""When the Department approval matrix changes, re-stamp current_approver
	on all pending Attendance records for this department so approvers are
	never locked out by a stale value."""
	_sync_pending_attendance(doc)


def _sync_pending_attendance(dept_doc):
	"""Re-stamp current_approver on pending Attendance of this department and of
	every department below it, since those inherit its approvers."""
	from cooperheat.cooperheat.org import clear_cache, descendants, effective_matrix

	clear_cache()
	pending_states = list(_LEVEL_STATE.values())
	records = frappe.get_all(
		"Attendance",
		filters={
			"department": ["in", list(descendants([dept_doc.name])) or [dept_doc.name]],
			"workflow_state": ["in", pending_states],
			"docstatus": 1,
		},
		fields=["name", "employee", "department", "workflow_state", "current_approver"],
	)
	if not records:
		return

	state_to_level = {v: k for k, v in _LEVEL_STATE.items()}

	for rec in records:
		level = state_to_level.get(rec.workflow_state)
		if not level:
			continue
		row = next((r for r in effective_matrix(rec.department, rec.employee) if r.approval_level == level), None)
		new_approver = row.approver if row else None
		if not new_approver or new_approver == rec.current_approver:
			continue
		approver_name = frappe.db.get_value("Employee", new_approver, "employee_name") or new_approver
		frappe.db.set_value(
			"Attendance",
			rec.name,
			{
				"current_approver": new_approver,
				"current_approver_name": approver_name,
			},
			update_modified=False,
		)
