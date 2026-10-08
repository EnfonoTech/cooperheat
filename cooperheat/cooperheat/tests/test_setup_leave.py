import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat.setup_leave import create_leave_setup

YEAR = 2031


def company():
	return frappe.db.get_value("Employee", {"status": "Active"}, "company")


class TestLeaveSetup(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_every_active_employee_gets_privilege_leave(self):
		comp = company()
		create_leave_setup(YEAR, comp)
		active = frappe.get_all("Employee", filters={"company": comp, "status": "Active"}, pluck="name")
		allocated = frappe.get_all(
			"Leave Allocation",
			filters={
				"employee": ["in", active],
				"leave_type": "Privilege Leave",
				"from_date": f"{YEAR}-01-01",
				"docstatus": 1,
			},
			fields=["employee", "new_leaves_allocated"],
		)
		self.assertEqual({a.employee for a in allocated}, set(active))
		self.assertTrue(all(a.new_leaves_allocated == 21 for a in allocated))

	def test_rerun_assigns_nobody_new(self):
		comp = company()
		create_leave_setup(YEAR, comp)
		self.assertEqual(create_leave_setup(YEAR, comp)["assigned"], [])
