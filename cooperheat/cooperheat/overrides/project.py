# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def autoname(doc, method=None):
	"""Name a Project after the client's own job code instead of ``PROJ-####``.

	Uses ``custom_project_code`` first, then the CRM number. When neither is
	filled in the standard naming series applies unchanged."""
	code = (doc.get("custom_project_code") or doc.get("custom_crm_no") or "").strip()
	if not code:
		return
	if frappe.db.exists("Project", code):
		frappe.throw(
			_("A Project with the code {0} already exists.").format(code), frappe.DuplicateEntryError
		)
	doc.name = code
