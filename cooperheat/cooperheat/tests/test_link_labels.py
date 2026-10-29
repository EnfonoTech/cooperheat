"""Link pickers show the record's title, not a parent / type / description (client, 2026-10-29).

Department and Cost Center have "show title field in link" on, so Frappe takes the 2nd
column of a custom link query as the label shown in the field.

    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_link_labels
"""

import frappe
from frappe.desk.search import build_for_autosuggest
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat import cost_center, org
from cooperheat.cooperheat.tests.test_org_structure import make_unit


class TestLinkLabels(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.bl = make_unit("LBL Business Line", org.BUSINESS_LINE)
		cls.pl = make_unit("LBL Product", org.PRODUCT_LINE, parent=cls.bl, is_group=0)
		org.clear_cache()

	def labels(self, doctype, rows):
		return {r["value"]: r.get("label") for r in build_for_autosuggest(rows, doctype)}

	def test_product_line_shows_its_own_name_not_the_business_line(self):
		rows = org.product_line_query("Department", "", "name", 0, 20, {"business_line": self.bl})
		self.assertEqual(self.labels("Department", rows)[self.pl], "LBL Product")

	def test_product_line_found_by_its_name(self):
		rows = org.product_line_query("Department", "LBL Prod", "name", 0, 20, {"business_line": self.bl})
		self.assertIn(self.pl, [r[0] for r in rows])

	def test_department_picker_shows_the_department_name(self):
		rows = org.departments_in_division("Department", "LBL", "name", 0, 20, {})
		self.assertEqual(self.labels("Department", rows).get(self.pl), "LBL Product")

	def test_cost_center_picker_shows_the_cost_center_name(self):
		rows = cost_center.cost_center_query("Cost Center", "", "name", 0, 5, {})
		for name, label in self.labels("Cost Center", rows).items():
			self.assertEqual(label, frappe.db.get_value("Cost Center", name, "cost_center_name"))
