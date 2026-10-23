"""The Employee form lists the assets the employee is custodian of.

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_employee_assets
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestEmployeeAssets(FrappeTestCase):
	def test_assets_connection_is_on_the_employee_form(self):
		data = frappe.get_meta("Employee", cached=False).get_dashboard_data()
		cards = {card["label"]: card["items"] for card in data.transactions}
		self.assertEqual(cards.get("Assets"), ["Asset"])
		self.assertEqual(data.non_standard_fieldnames["Asset"], "custodian")

	def test_other_connections_are_kept(self):
		data = frappe.get_meta("Employee", cached=False).get_dashboard_data()
		labels = {card["label"] for card in data.transactions}
		self.assertTrue({"Attendance", "Leave", "Payroll"} <= labels)
		self.assertEqual(data.non_standard_fieldnames["Bank Account"], "party")
