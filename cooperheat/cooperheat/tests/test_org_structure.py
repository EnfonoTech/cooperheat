"""Business Line / Product Line structure and inherited approvers.

Runs against the DEV seed (cooperheat.cooperheat.dev_seed):
    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_org_structure
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from cooperheat.cooperheat import dev_seed, org
from cooperheat.cooperheat.permissions import scope


def emp_of(key):
	return frappe.db.get_value("Employee", {"user_id": dev_seed.email(key)}, "name")


def make_unit(name, unit_type, parent=None, is_group=1, matrix=()):
	doc = frappe.get_doc(
		{
			"doctype": "Department",
			"department_name": name,
			"company": dev_seed.COMPANY,
			"parent_department": parent or "All Departments",
			"is_group": is_group,
			"custom_unit_type": unit_type,
			"approval_matrix": [
				{"approval_level": lvl, "approver": approver, "approval_window_hours": 24, "location": loc}
				for lvl, approver, loc in matrix
			],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def make_location(name):
	if not frappe.db.exists("Location", name):
		frappe.get_doc({"doctype": "Location", "location_name": name}).insert(ignore_permissions=True)
	return name


def make_employee(first, **values):
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": first,
			"last_name": "OrgTest",
			"gender": "Male",
			"date_of_birth": "1995-05-05",
			"date_of_joining": today(),
			"company": dev_seed.COMPANY,
			"status": "Active",
			**values,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


class TestOrgStructure(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.anil, cls.saleh, cls.khalid, cls.irtaza = (emp_of(k) for k in ("anil", "saleh", "khalid", "irtaza"))
		cls.jubail, cls.yanbu = make_location("OT-Jubail"), make_location("OT-Yanbu")
		# Inspection (L2 Khalid, L3 Irtaza) > CNDT (no approvers) > NDT Team (L1 per location)
		cls.bl = make_unit("OT Inspection", org.BUSINESS_LINE, matrix=[(2, cls.khalid, None), (3, cls.irtaza, None)])
		cls.cndt = make_unit("OT CNDT", org.PRODUCT_LINE, parent=cls.bl)
		cls.ndt = make_unit(
			"OT NDT Team",
			org.PRODUCT_LINE,
			parent=cls.cndt,
			is_group=0,
			matrix=[(1, cls.anil, cls.jubail), (1, cls.saleh, cls.yanbu)],
		)
		cls.other_bl = make_unit("OT Fabrication", org.BUSINESS_LINE)
		cls.other_pl = make_unit("OT Welding", org.PRODUCT_LINE, parent=cls.other_bl, is_group=0)
		org.clear_cache()

	def setUp(self):
		frappe.set_user("Administrator")
		org.clear_cache()
		scope.clear_cache()

	# --- inherited approvers -------------------------------------------------

	def test_levels_inherit_from_the_business_line(self):
		levels = {r.approval_level: r for r in org.effective_matrix(self.ndt, location=self.jubail)}
		self.assertEqual(levels[1].approver, self.anil)
		self.assertEqual(levels[1].source, self.ndt)
		self.assertEqual(levels[2].approver, self.khalid)
		self.assertEqual(levels[2].source, self.bl)
		self.assertEqual(levels[3].approver, self.irtaza)

	def test_location_picks_the_local_supervisor(self):
		levels = {r.approval_level: r.approver for r in org.effective_matrix(self.ndt, location=self.yanbu)}
		self.assertEqual(levels[1], self.saleh)

	def test_product_line_without_rows_uses_parent(self):
		levels = {r.approval_level: r.approver for r in org.effective_matrix(self.cndt)}
		self.assertEqual(levels, {2: self.khalid, 3: self.irtaza})

	def test_root_departments_are_unchanged(self):
		# Flat departments under All Departments (production today) resolve only their own rows.
		ls = dev_seed.dept_name("Leak Sealing")
		own = {
			r.approval_level: r.approver
			for r in frappe.get_all(
				"Department Approval Matrix", filters={"parent": ls, "parentfield": "approval_matrix"}, fields=["approval_level", "approver"]
			)
		}
		self.assertEqual({r.approval_level: r.approver for r in org.effective_matrix(ls)}, own)

	# --- employee placement --------------------------------------------------

	def test_product_line_sets_business_line_and_department(self):
		e = make_employee("Tech", custom_product_line=self.ndt, custom_assigned_location=self.jubail)
		self.assertEqual(e.custom_business_line, self.bl)
		self.assertEqual(e.department, self.ndt)
		self.assertEqual(e.reports_to, self.anil)

	def test_business_line_head_sits_on_the_business_line(self):
		e = make_employee("Head", custom_business_line=self.bl)
		self.assertEqual(e.department, self.bl)
		self.assertFalse(e.custom_product_line)

	def test_product_line_of_another_business_line_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_employee("Wrong", custom_business_line=self.bl, custom_product_line=self.other_pl)

	def test_business_line_field_rejects_a_product_line(self):
		with self.assertRaises(frappe.ValidationError):
			make_employee("Wrong2", custom_business_line=self.cndt)

	def test_picking_an_operations_department_fills_the_fields(self):
		e = make_employee("Direct", department=self.ndt)
		self.assertEqual(e.custom_product_line, self.ndt)
		self.assertEqual(e.custom_business_line, self.bl)

	def test_leave_approver_filled_from_level_1(self):
		e = make_employee("Leave", custom_product_line=self.ndt, custom_assigned_location=self.yanbu)
		saleh_user = frappe.db.get_value("Employee", self.saleh, "user_id")
		self.assertEqual(e.leave_approver, saleh_user)
		self.assertEqual(e.shift_request_approver, saleh_user)

	def test_support_department_untouched(self):
		ct = dev_seed.dept_name("Contracting")
		e = make_employee("Support", department=ct)
		self.assertEqual(e.department, ct)
		self.assertFalse(e.custom_business_line)

	# --- scope ---------------------------------------------------------------

	def test_business_line_manager_sees_all_product_lines(self):
		e = make_employee("Seen", custom_product_line=self.ndt, custom_assigned_location=self.jubail)
		khalid_user = frappe.db.get_value("Employee", self.khalid, "user_id")
		visible = scope.get_scope(khalid_user)
		self.assertIn(self.ndt, visible.departments)
		self.assertIn(e.name, visible.employees)

	def test_product_line_query_lists_only_its_lines(self):
		rows = org.product_line_query("Department", "", "name", 0, 50, {"business_line": self.bl})
		names = {r[0] for r in rows}
		self.assertEqual(names, {self.cndt, self.ndt})
