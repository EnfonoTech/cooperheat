import frappe
from frappe import _
from frappe.utils import cint, cstr, now


_LAYOUT_FIELDTYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}


def before_validate(doc, method=None):
	"""Adding a node under a parent from the Division tree or the parent's own page.

	* The Unit Type follows the parent when left empty (Division -> Department ->
	  Sub-Department, Business Line -> Product Line -> Sub-Product Line).
	* A parent that was a leaf becomes a group, so a Department can be given
	  Sub-Departments straight from its own page.
	"""
	from cooperheat.cooperheat import org

	parent = doc.get("parent_department")
	if not parent:
		return
	if not doc.get("custom_unit_type"):
		doc.custom_unit_type = org.child_unit_type(parent)
	if (doc.is_new() or doc.has_value_changed("parent_department")) and not frappe.db.get_value(
		"Department", parent, "is_group"
	):
		frappe.db.set_value("Department", parent, "is_group", 1)


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
