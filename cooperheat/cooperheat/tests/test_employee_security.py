"""Role-based and field-level access to the Employee record.

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_employee_security
"""

import frappe
import frappe.desk.form.load
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat import dev_seed
from cooperheat.cooperheat.employee_security import LEVEL_1, LEVEL_2, ensure_employee_field_security
from cooperheat.cooperheat.tests.test_hr_scope import emp_of

HR_USER_ONLY = "hr.user.only@cooperheat-dev.test"


def visible_keys(user, employee):
	frappe.set_user(user)
	frappe.response["docs"] = []  # getdoc appends: do not read a document left by an earlier call
	try:
		frappe.desk.form.load.getdoc("Employee", employee)
		doc = next(d for d in frappe.response.docs if d.get("name") == employee)
		return {k for k, v in doc.as_dict().items() if v not in (None, "", 0)}
	finally:
		frappe.set_user("Administrator")


class TestEmployeeSecurity(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		ensure_employee_field_security()
		cls.tech = frappe.db.get_value("Employee", {"user_id": dev_seed.email("tech101")}, "name")
		frappe.db.set_value(
			"Employee",
			cls.tech,
			{
				"ctc": 9999,
				"bank_ac_no": "SECRET-ACCOUNT",
				"iban": "SA00SECRET",
				"date_of_joining": "2020-01-01",
				"passport_number": "P123",
			},
		)
		if not frappe.db.exists("User", HR_USER_ONLY):
			user = frappe.get_doc(
				{"doctype": "User", "email": HR_USER_ONLY, "first_name": "HRonly", "send_welcome_email": 0}
			)
			user.flags.no_welcome_mail = True
			user.insert(ignore_permissions=True)
		frappe.get_doc("User", HR_USER_ONLY).add_roles("HR User")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		if frappe.db.exists("User", HR_USER_ONLY):
			frappe.delete_doc("User", HR_USER_ONLY, force=True, ignore_permissions=True)
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")

	def test_supervisor_cannot_edit_a_team_members_record(self):
		frappe.set_user(dev_seed.email("anil"))
		self.assertTrue(frappe.has_permission("Employee", "read", doc=self.tech))
		self.assertFalse(frappe.has_permission("Employee", "write", doc=self.tech))
		doc = frappe.get_doc("Employee", self.tech)
		doc.cell_number = "0500000000"
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_manager_cannot_edit_either(self):
		frappe.set_user(dev_seed.email("khalid"))
		self.assertFalse(frappe.has_permission("Employee", "write", doc=self.tech))

	def test_employee_self_service_is_read_only_now(self):
		rows = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": "Employee", "role": "Employee Self Service", "permlevel": 0},
			fields=["read", "write"],
		)
		self.assertTrue(rows)
		self.assertTrue(all(r.read == 1 and r.write == 0 for r in rows))

	def test_supervisor_sees_the_teams_hr_details_but_no_pay(self):
		# client 2026-10-23: supervisors and managers see all details of their people except salary
		keys = visible_keys(dev_seed.email("anil"), self.tech)
		self.assertIn("employee_name", keys)
		self.assertIn("department", keys)
		self.assertIn("reports_to", keys)
		for field in ("date_of_joining", "passport_number", "date_of_birth"):
			self.assertIn(field, keys)
		for field in ("ctc", "bank_ac_no", "iban", "salary_mode"):
			self.assertNotIn(field, keys)

	def test_supervisor_gets_hr_columns_but_no_pay_columns_from_the_list_api(self):
		frappe.set_user(dev_seed.email("anil"))
		rows = frappe.get_list(
			"Employee", fields=["name", "ctc", "bank_ac_no", "date_of_joining"], limit_page_length=5
		)
		self.assertTrue(rows)
		for row in rows:
			self.assertIn("date_of_joining", row)
			for field in ("ctc", "bank_ac_no"):
				self.assertNotIn(field, row)

	def test_hr_user_sees_hr_fields_but_not_pay(self):
		keys = visible_keys(HR_USER_ONLY, self.tech)
		self.assertIn("date_of_joining", keys)
		self.assertIn("passport_number", keys)
		for field in ("ctc", "bank_ac_no", "iban"):
			self.assertNotIn(field, keys)

	def test_hr_user_can_edit_basic_fields(self):
		frappe.set_user(HR_USER_ONLY)
		self.assertTrue(frappe.has_permission("Employee", "write", doc=self.tech))

	def test_hr_manager_sees_everything(self):
		keys = visible_keys(dev_seed.email("mustafa"), self.tech)
		for field in ("ctc", "bank_ac_no", "iban", "date_of_joining", "passport_number"):
			self.assertIn(field, keys)

	def test_pay_fields_are_level_two_and_hr_fields_level_one(self):
		meta = frappe.get_meta("Employee", cached=False)
		levels = {f.fieldname: f.permlevel for f in meta.fields}
		for field in LEVEL_2:
			if field in levels:
				self.assertEqual(levels[field], 2, field)
		for field in LEVEL_1:
			if field in levels:
				self.assertEqual(levels[field], 1, field)

	def test_running_it_twice_changes_nothing(self):
		again = ensure_employee_field_security()
		self.assertEqual(again["fields"], 0)
		self.assertEqual(again["roles_added"], [])
		self.assertEqual(again["write_removed"], [])

	def test_the_employee_form_work_still_saves_for_hr(self):
		frappe.set_user(dev_seed.email("mustafa"))
		doc = frappe.get_doc("Employee", emp_of("mustafa"))
		doc.save()  # no permission error on a record with level 1 and 2 fields
