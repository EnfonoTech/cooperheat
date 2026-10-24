"""The AI assistant of the Grey Theme app ("Fateh AI", shown here as "Cooperheat AI") is IT-only.

Why: its backend (``grey_theme.chat_handler.handle_ai_query``) lets an outside AI service write a
database query and runs it with ``frappe.db.sql`` WITHOUT checking who is asking, and can create
Customers and Items with ``ignore_permissions``. On an HR system that would sidestep every
permission rule (salary, bank and ID data). No AI key is set on this site today, so it only answers
a few canned sales / stock questions, but the door must not stay open for the day somebody adds one.

* the whitelisted method is replaced (``override_whitelisted_methods`` in hooks.py) by the guard below;
* the Page and the Workspace are limited to System Manager by ``setup.ensure_ai_restricted``.
"""

import frappe
from frappe import _

ALLOWED_ROLE = "System Manager"


@frappe.whitelist()
def handle_ai_query(question):
	if ALLOWED_ROLE not in frappe.get_roles():
		frappe.throw(_("The AI assistant is available to IT only."), frappe.PermissionError)
	from grey_theme.chat_handler import handle_ai_query as original

	return original(question)
