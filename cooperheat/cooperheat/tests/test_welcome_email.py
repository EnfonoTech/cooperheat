"""The new-user e-mail is titled with the platform name, not the legal Company name (client, 2026-10-29).

    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_welcome_email
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestWelcomeEmail(FrappeTestCase):
	def test_cooperheat_hook_wins_over_erpnext(self):
		self.assertEqual(frappe.get_hooks("welcome_email")[-1], "cooperheat.cooperheat.branding.welcome_email")

	def test_subject_uses_the_platform_name(self):
		from cooperheat.cooperheat.branding import welcome_email

		name = frappe.db.get_single_value("System Settings", "app_name") or "Cooperheat"
		self.assertEqual(welcome_email(), "Welcome to " + name)
		company = frappe.defaults.get_global_default("company")
		if company and company != name:
			self.assertNotIn(company, welcome_email())
