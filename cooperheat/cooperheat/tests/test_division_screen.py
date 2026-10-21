"""The Division screen: plain drill-down data (tabs, sub-units, employees, breadcrumb).

    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_division_screen
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat import dev_seed, org
from cooperheat.cooperheat.tests.test_hr_scope import emp_of
from cooperheat.cooperheat.tests.test_org_hierarchy import add_node
from cooperheat.cooperheat.tests.test_org_structure import make_employee


class TestDivisionScreen(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.division = add_node("DV Division", "All Departments", org.DIVISION, 1)
		cls.dept = add_node("DV Finance", cls.division)
		cls.sub = add_node("DV Payables", cls.dept)
		cls.bl = add_node("DV Business Line", "All Departments", org.BUSINESS_LINE, 1)
		cls.pl = add_node("DV Product", cls.bl)
		cls.sub_pl = add_node("DV Product Team", cls.pl)
		cls.old = add_node("DV Old Flat Department", "All Departments")
		cls.boss = emp_of("khalid")
		cls.e1 = make_employee("DvOne", custom_product_line=cls.sub_pl, reports_to=cls.boss)
		cls.e2 = make_employee("DvTwo", department=cls.dept)

	def view(self, node=None, kind="Division"):
		return org.division_view(node=node, kind=kind, company=dev_seed.COMPANY)

	def test_top_level_of_each_tab(self):
		divisions = {c["name"] for c in self.view()["children"]}
		lines = {c["name"] for c in self.view(kind="Business Line")["children"]}
		old = {c["name"] for c in self.view(kind="Other")["children"]}
		self.assertIn(self.division, divisions)
		self.assertNotIn(self.bl, divisions)
		self.assertIn(self.bl, lines)
		self.assertIn(self.old, old)
		self.assertNotIn(self.division, old)

	def test_top_level_offers_the_right_add_button_and_counts_old_departments(self):
		self.assertEqual(self.view()["add_type"], org.DIVISION)
		self.assertEqual(self.view(kind="Business Line")["add_type"], org.BUSINESS_LINE)
		self.assertIsNone(self.view(kind="Other")["add_type"])
		self.assertGreaterEqual(self.view()["old_departments"], 1)

	def test_division_shows_its_departments_and_what_a_new_child_would_be(self):
		data = self.view(self.division)
		self.assertEqual([c["name"] for c in data["children"]], [self.dept])
		self.assertEqual(data["add_type"], org.DEPARTMENT)
		self.assertEqual(data["children"][0]["sub_units"], 1)
		self.assertEqual(self.view(self.dept)["add_type"], org.SUB_DEPARTMENT)

	def test_business_line_drills_down_to_sub_product_line_with_employees(self):
		self.assertEqual([c["name"] for c in self.view(self.bl, "Business Line")["children"]], [self.pl])
		self.assertEqual([c["name"] for c in self.view(self.pl, "Business Line")["children"]], [self.sub_pl])
		leaf = self.view(self.sub_pl, "Business Line")
		self.assertEqual([e["name"] for e in leaf["employees"]], [self.e1.name])
		self.assertEqual(leaf["employees"][0]["reports_to_name"], frappe.db.get_value("Employee", self.boss, "employee_name"))
		self.assertEqual(leaf["add_type"], org.SUB_PRODUCT_LINE)

	def test_counts_include_everything_below(self):
		top = {c["name"]: c for c in self.view(kind="Business Line")["children"]}[self.bl]
		self.assertEqual(top["employees"], 1)
		mid = {c["name"]: c for c in self.view(self.bl, "Business Line")["children"]}[self.pl]
		self.assertEqual(mid["employees"], 1)

	def test_employees_placed_on_a_department_are_listed_there(self):
		data = self.view(self.dept)
		self.assertEqual([e["name"] for e in data["employees"]], [self.e2.name])

	def test_breadcrumb_runs_from_the_top(self):
		data = self.view(self.sub_pl, "Business Line")
		self.assertEqual([b["name"] for b in data["breadcrumb"]], [self.bl, self.pl, self.sub_pl])

	def test_kind_follows_the_node(self):
		self.assertEqual(self.view(self.sub, "Business Line")["kind"], "Division")
		self.assertEqual(self.view(self.pl, "Division")["kind"], "Business Line")

	def test_unknown_node_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.view("No Such Department")
