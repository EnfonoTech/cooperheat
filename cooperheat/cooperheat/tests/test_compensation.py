"""Salary Compensation tab of the Employee form (data layer).

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_compensation
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from cooperheat.cooperheat import compensation as comp
from cooperheat.cooperheat import dev_seed
from cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet import get_employee_compensation
from cooperheat.cooperheat.tests.test_org_structure import make_employee
from cooperheat.cooperheat.tests.test_reporting_approvals import cleanup_debris


def amounts(**kw):
	return {f: kw.get(f, 0) for f in comp.COMPONENTS}


class TestCompensationTab(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"Employee Compensation",
			filters={
				"employee": ["in", frappe.get_all("Employee", filters={"last_name": "OrgTest"}, pluck="name")]
			},
			pluck="name",
		):
			frappe.delete_doc("Employee Compensation", name, force=True, ignore_permissions=True)
		cleanup_debris()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")

	def employee(self, first, nationality="Saudi"):
		return make_employee(first, nationality=nationality)

	def test_new_employee_has_no_package_yet(self):
		emp = self.employee("CpNone")
		data = comp.get_for_employee(emp.name)
		self.assertIsNone(data["current"])
		self.assertEqual(data["history"], [])
		self.assertFalse(data["needs_nationality"])
		self.assertIn("basic", [f["fieldname"] for f in data["fields"]])

	def test_first_package_is_created_from_the_form(self):
		emp = self.employee("CpFirst")
		comp.save(
			emp.name, amounts(basic=3000, housing_allowance=750, general_advance=100), add_days(today(), -10)
		)
		data = comp.get_for_employee(emp.name)
		cur = data["current"]
		self.assertEqual(
			(cur["values"]["basic"], cur["total_earnings"], cur["total_deductions"], cur["net_fixed"]),
			(3000, 3750, 100, 3650),
		)
		self.assertEqual(cur["employee_category"], "Saudi")  # derived from the nationality, as before

	def test_a_raise_is_a_new_record_and_payroll_picks_by_date(self):
		emp = self.employee("CpRaise")
		old_from, new_from = add_days(today(), -60), add_days(today(), -5)
		first = comp.save(emp.name, amounts(basic=3000), old_from)["name"]
		second = comp.save(emp.name, amounts(basic=3500), new_from)["name"]
		self.assertNotEqual(first, second)
		self.assertEqual(get_employee_compensation(emp.name, add_days(today(), -30))["values"]["basic"], 3000)
		self.assertEqual(get_employee_compensation(emp.name, today())["values"]["basic"], 3500)
		data = comp.get_for_employee(emp.name)
		self.assertEqual([h["name"] for h in data["history"]], [second, first])
		self.assertEqual(data["current"]["name"], second)

	def test_correct_edits_the_record_in_place(self):
		emp = self.employee("CpFix")
		name = comp.save(emp.name, amounts(basic=2000), add_days(today(), -3))["name"]
		comp.save(emp.name, amounts(basic=2200), add_days(today(), -3), record=name)
		self.assertEqual(frappe.db.count("Employee Compensation", {"employee": emp.name}), 1)
		self.assertEqual(frappe.db.get_value("Employee Compensation", name, "basic"), 2200)

	def test_two_packages_cannot_start_on_the_same_day(self):
		emp = self.employee("CpDup")
		day = add_days(today(), -2)
		comp.save(emp.name, amounts(basic=1000), day)
		with self.assertRaises(frappe.ValidationError):
			comp.save(emp.name, amounts(basic=1100), day)

	def test_a_record_of_another_employee_cannot_be_edited(self):
		a, b = self.employee("CpA"), self.employee("CpB")
		name = comp.save(a.name, amounts(basic=1000), add_days(today(), -2))["name"]
		with self.assertRaises(frappe.ValidationError):
			comp.save(b.name, amounts(basic=1), add_days(today(), -2), record=name)

	def test_nationality_is_needed_for_the_category(self):
		emp = make_employee("CpNoNat")
		self.assertTrue(comp.get_for_employee(emp.name)["needs_nationality"])
		with self.assertRaises(frappe.ValidationError):
			comp.save(emp.name, amounts(basic=1000), add_days(today(), -1))

	def test_supervisors_never_see_salary_figures(self):
		emp = self.employee("CpSecret")
		comp.save(emp.name, amounts(basic=4000), add_days(today(), -1))
		frappe.set_user(dev_seed.email("anil"))
		with self.assertRaises(frappe.PermissionError):
			comp.get_for_employee(emp.name)
		with self.assertRaises(frappe.PermissionError):
			comp.save(emp.name, amounts(basic=1), add_days(today(), -9))

	def test_hr_manager_can_use_it(self):
		emp = self.employee("CpHr")
		frappe.set_user(dev_seed.email("mustafa"))
		comp.save(emp.name, amounts(basic=1500), add_days(today(), -1))
		self.assertEqual(comp.get_for_employee(emp.name)["current"]["values"]["basic"], 1500)
