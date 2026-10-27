"""Cost Center follows Business Line > Product Line on the Employee (client request 2026-10-26).

    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_cost_center
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat import cost_center, dev_seed, org
from cooperheat.cooperheat.tests.test_org_structure import make_employee, make_unit


def make_cc(code, bl=None, pl=None):
	abbr = frappe.get_cached_value("Company", dev_seed.COMPANY, "abbr")
	name = code + " - " + abbr
	if not frappe.db.exists("Cost Center", name):
		frappe.get_doc(
			{
				"doctype": "Cost Center",
				"cost_center_name": code,
				"company": dev_seed.COMPANY,
				"parent_cost_center": cost_center._company_root(dev_seed.COMPANY),
				"custom_business_line": bl,
				"custom_product_line": pl,
			}
		).insert(ignore_permissions=True)
	return name


def query(**filters):
	return [r[0] for r in cost_center.cost_center_query("Cost Center", "", "name", 0, 100, filters)]


class TestCostCenter(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.bl = make_unit("CC Inspection", org.BUSINESS_LINE)
		cls.pl = make_unit("CC NDT", org.PRODUCT_LINE, parent=cls.bl)
		cls.sub = make_unit("CC NDT Team", org.SUB_PRODUCT_LINE, parent=cls.pl, is_group=0)
		cls.other_pl = make_unit("CC TPI", org.PRODUCT_LINE, parent=cls.bl, is_group=0)
		org.clear_cache()
		cls.cc_ndt = make_cc("CCT-NUT", cls.bl, cls.pl)
		cls.cc_tpi = make_cc("CCT-TPI", cls.bl, cls.other_pl)
		cls.cc_admin = make_cc("CCT-ADM")

	def test_product_line_shows_only_its_cost_centers(self):
		got = query(business_line=self.bl, product_line=self.pl)
		self.assertIn(self.cc_ndt, got)
		self.assertNotIn(self.cc_tpi, got)
		self.assertNotIn(self.cc_admin, got)

	def test_sub_product_line_uses_its_product_lines_cost_centers(self):
		self.assertIn(self.cc_ndt, query(business_line=self.bl, product_line=self.sub))

	def test_business_line_only_shows_all_of_the_business_line(self):
		got = query(business_line=self.bl)
		self.assertIn(self.cc_ndt, got)
		self.assertIn(self.cc_tpi, got)

	def test_office_staff_see_the_general_cost_centers(self):
		got = query()
		self.assertIn(self.cc_admin, got)
		self.assertNotIn(self.cc_ndt, got)

	def test_employee_with_another_product_lines_cost_center_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_employee("CCWrong", custom_business_line=self.bl, custom_product_line=self.pl, custom_job_code=self.cc_tpi)

	def test_general_cost_center_is_allowed_for_anyone(self):
		emp = make_employee("CCGeneral", custom_business_line=self.bl, custom_product_line=self.pl, custom_job_code=self.cc_admin)
		self.assertEqual(emp.custom_job_code, self.cc_admin)
