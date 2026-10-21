"""Division tree / Department form: unit types follow the parent, sub-levels, head counts.

Runs against the DEV seed (cooperheat.cooperheat.dev_seed):
    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_org_hierarchy
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat import dev_seed, org
from cooperheat.cooperheat.tests.test_org_structure import make_employee


def add_node(name, parent, unit_type=None, is_group=0):
	doc = frappe.get_doc(
		{
			"doctype": "Department",
			"department_name": name,
			"company": dev_seed.COMPANY,
			"parent_department": parent,
			"is_group": is_group,
			"custom_unit_type": unit_type,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


class TestOrgHierarchy(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.division = add_node("HT Division", "All Departments", org.DIVISION, 1)
		cls.bl = add_node("HT Business Line", "All Departments", org.BUSINESS_LINE, 1)

	def test_child_type_follows_the_parent(self):
		dept = add_node("HT Finance", self.division)
		sub = add_node("HT Payables", dept)
		self.assertEqual(org.unit_type(dept), org.DEPARTMENT)
		self.assertEqual(org.unit_type(sub), org.SUB_DEPARTMENT)
		subsub = add_node("HT Vendors", sub)
		self.assertEqual(org.unit_type(subsub), org.SUB_DEPARTMENT)

	def test_operations_side_gets_product_and_sub_product_lines(self):
		pl = add_node("HT TPI", self.bl)
		sub = add_node("HT TPI Team", pl)
		self.assertEqual(org.unit_type(pl), org.PRODUCT_LINE)
		self.assertEqual(org.unit_type(sub), org.SUB_PRODUCT_LINE)

	def test_a_chosen_type_is_kept(self):
		name = add_node("HT Odd Unit", self.division, org.DIVISION, 1)
		self.assertEqual(org.unit_type(name), org.DIVISION)

	def test_root_children_are_not_guessed(self):
		name = add_node("HT Untyped", "All Departments")
		self.assertIsNone(org.unit_type(name))

	def test_a_leaf_parent_becomes_a_group(self):
		leaf = add_node("HT Leaf", self.division)
		self.assertFalse(frappe.db.get_value("Department", leaf, "is_group"))
		add_node("HT Leaf Child", leaf)
		self.assertEqual(frappe.db.get_value("Department", leaf, "is_group"), 1)

	def test_employee_can_sit_on_a_sub_product_line(self):
		pl = add_node("HT NDT", self.bl, is_group=1)
		sub = add_node("HT NDT Crew", pl)
		emp = make_employee("SubPL", custom_product_line=sub)
		self.assertEqual(emp.department, sub)
		self.assertEqual(emp.custom_business_line, self.bl)

	def test_product_line_picker_offers_sub_product_lines(self):
		pl = add_node("HT Picker PL", self.bl, is_group=1)
		sub = add_node("HT Picker Sub", pl)
		rows = org.product_line_query("Department", "HT Picker", "name", 0, 20, {"business_line": self.bl})
		self.assertCountEqual([r[0] for r in rows], [pl, sub])

	def test_a_division_is_not_a_product_line(self):
		with self.assertRaises(frappe.ValidationError):
			make_employee("NotPL", custom_product_line=self.division)

	def test_tree_rows_carry_type_and_head_count(self):
		pl = add_node("HT Count PL", self.bl)
		make_employee("Counted", department=pl, custom_business_line=self.bl, custom_product_line=pl)
		rows = {r["value"]: r for r in org.department_children("Department", self.bl)}
		self.assertEqual(rows[pl]["unit_type"], org.PRODUCT_LINE)
		self.assertEqual(rows[pl]["employees"], 1)

	def test_overview_lists_children_with_totals_below_each(self):
		pl = add_node("HT Over PL", self.bl, is_group=1)
		sub = add_node("HT Over Sub", pl)
		make_employee("Under", custom_product_line=sub)
		data = org.department_overview(self.bl)
		self.assertEqual(data["child_type"], org.PRODUCT_LINE)
		row = next(c for c in data["children"] if c.name == pl)
		self.assertEqual(row["employees"], 1)
		self.assertEqual(org.department_overview(pl)["child_type"], org.SUB_PRODUCT_LINE)
