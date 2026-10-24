"""The short, named set of roles (Role Profiles Employee ... IT) and the clean-up of the other roles.

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_roles_simple
"""

import json
import os
import tempfile

import frappe
from frappe.core.doctype.user.user import get_all_roles
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat import roles_simple
from cooperheat.cooperheat.employee_security import ensure_employee_field_security

PAYROLL_USER = "payroll.test@cooperheat-dev.test"
STORE_USER = "store.test@cooperheat-dev.test"
SUPERVISOR_USER = "supervisor.exact@cooperheat-dev.test"
UNUSED = (
	"Zz Unused Role A",
	"Zz Unused Role B",
)  # fresh roles: the real clean-up may already have run on the site


def make_user(email, roles):
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
	)
	user.flags.ignore_permissions = True
	user.insert()
	user.add_roles(*roles)
	# User.save drops roles a bare test user has no business with (Employee, Employee Self Service);
	# real staff have them through their Employee record, so put them back for the exact-match test
	for role in roles:
		if not frappe.db.exists("Has Role", {"parent": email, "parenttype": "User", "role": role}):
			frappe.get_doc(
				{
					"doctype": "Has Role",
					"parent": email,
					"parenttype": "User",
					"parentfield": "roles",
					"role": role,
				}
			).db_insert()
	return user


class TestRolesSimple(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for role in UNUSED:
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()
		make_user(SUPERVISOR_USER, roles_simple.PROFILES["Supervisor"])
		cls.snapshot = os.path.join(tempfile.mkdtemp(), "snapshot.json")
		cls.result = roles_simple.apply(dry_run=0, snapshot_path=cls.snapshot)
		make_user(PAYROLL_USER, ["Employee", "Employee Self Service", "Payroll"])
		make_user(STORE_USER, roles_simple.PROFILES["Store"])

	def can(self, user, ptype, doctype):
		return frappe.has_permission(doctype, ptype, user=user)

	def test_dry_run_changes_nothing(self):
		before = frappe.db.count("Role", {"disabled": 1})
		result = roles_simple.apply()
		self.assertEqual(result["dry_run"], 1)
		self.assertEqual(frappe.db.count("Role", {"disabled": 1}), before)

	def test_profiles_exist_with_their_roles(self):
		for name, roles in roles_simple.PROFILES.items():
			doc = frappe.get_doc("Role Profile", name)
			self.assertEqual({r.role for r in doc.roles}, set(roles), name)
		self.assertEqual(set(roles_simple.PROFILES), {
			"Employee", "Supervisor", "Manager", "HR Staff", "HR Manager", "Payroll", "Payroll and HR Manager",
			"Store", "Full Access", "IT",
		})  # fmt: skip

	def test_it_profile_carries_what_an_administrator_needs(self):
		it = {r.role for r in frappe.get_doc("Role Profile", "IT").roles}
		self.assertTrue({"System Manager", "HR Manager", "Payroll", "Store", "Accounts Manager"} <= it)
		self.assertFalse({"Supervisor", "Manager"} & it)  # those two limit a person to a team
		self.assertIn("Script Manager", it)
		self.assertNotIn(
			"Script Manager", {r.role for r in frappe.get_doc("Role Profile", "Full Access").roles}
		)

	def test_the_stock_hr_profile_and_its_user_are_left_alone(self):
		self.assertEqual(
			{r.role for r in frappe.get_doc("Role Profile", "HR").roles},
			{"HR Manager", "HR User", "Leave Approver", "Expense Approver"},
		)
		for name in roles_simple.UNUSED_PROFILES:
			self.assertFalse(frappe.db.exists("Role Profile", name), name)

	def test_payroll_works_on_payroll_not_on_stock(self):
		self.assertTrue(self.can(PAYROLL_USER, "read", "Salary Slip"))
		self.assertTrue(self.can(PAYROLL_USER, "write", "Salary Slip"))
		self.assertTrue(self.can(PAYROLL_USER, "read", "Employee Compensation"))
		self.assertTrue(self.can(PAYROLL_USER, "read", "Employee"))
		self.assertFalse(self.can(PAYROLL_USER, "write", "Employee"))
		self.assertFalse(self.can(PAYROLL_USER, "read", "Stock Entry"))
		self.assertFalse(self.can(PAYROLL_USER, "read", "Asset"))

	def test_payroll_sees_the_pay_fields_store_does_not(self):
		meta = frappe.get_meta("Employee")
		self.assertIn(2, meta.get_permlevel_access("read", "Employee", user=PAYROLL_USER) or [])
		self.assertNotIn(1, meta.get_permlevel_access("read", "Employee", user=PAYROLL_USER) or [])
		for level in (1, 2):
			self.assertNotIn(level, meta.get_permlevel_access("read", "Employee", user=STORE_USER) or [])

	def test_store_works_on_assets_and_stock_not_on_payroll(self):
		self.assertTrue(self.can(STORE_USER, "write", "Asset"))
		self.assertTrue(self.can(STORE_USER, "create", "Asset Movement"))
		self.assertTrue(self.can(STORE_USER, "read", "Stock Entry"))
		self.assertTrue(self.can(STORE_USER, "read", "Employee"))
		self.assertFalse(self.can(STORE_USER, "write", "Employee"))
		# every employee may open the Salary Slip list (the rows are limited to their own); store staff
		# must not change or create payroll documents
		self.assertFalse(self.can(STORE_USER, "write", "Salary Slip"))
		self.assertFalse(self.can(STORE_USER, "create", "Payroll Entry"))

	def test_unused_roles_are_gone_from_the_picker_and_from_users(self):
		picker = set(get_all_roles())
		for role in UNUSED:
			self.assertNotIn(role, picker)
			self.assertFalse(frappe.db.exists("Has Role", {"role": role}))
		for role in ("Supervisor", "Manager", "HR User", "HR Manager", "Payroll", "Store", "Employee"):
			self.assertIn(role, picker)
		self.assertTrue(frappe.db.exists("Role", "System Manager"))
		self.assertEqual(frappe.db.get_value("Role", "System Manager", "disabled"), 0)

	def test_user_with_exactly_a_profiles_roles_gets_marked_and_keeps_roles(self):
		self.assertEqual(frappe.db.get_value("User", SUPERVISOR_USER, "role_profile_name"), "Supervisor")
		roles = set(frappe.get_roles(SUPERVISOR_USER)) - {"All", "Guest", "Desk User"}
		self.assertEqual(roles, set(roles_simple.PROFILES["Supervisor"]))

	def test_the_second_run_changes_nothing(self):
		again = roles_simple.apply(dry_run=0, snapshot_path=self.snapshot)
		self.assertEqual(again["perms"], {"Payroll": 0, "Store": 0})
		self.assertEqual(again["profiles"], {"created": [], "updated": [], "kept": [], "dropped": []})
		self.assertEqual(again["disable"], [])
		self.assertEqual(again["removed_assignments"], 0)

	def test_revert_brings_the_roles_back(self):
		with open(self.snapshot) as handle:
			snap = json.load(handle)
		self.assertIn(UNUSED[0], snap["roles"])
		roles_simple.revert(snapshot_path=self.snapshot)
		self.assertIn(UNUSED[0], get_all_roles())
		self.assertEqual(frappe.db.get_value("Role", UNUSED[0], "disabled"), 0)
		# and a second apply puts the clean-up back
		roles_simple.apply(dry_run=0, snapshot_path=self.snapshot)
		self.assertNotIn(UNUSED[0], get_all_roles())

	def test_pay_level_keeps_hr_manager(self):
		ensure_employee_field_security()
		self.assertTrue(
			frappe.db.exists(
				"Custom DocPerm", {"parent": "Employee", "role": "HR Manager", "permlevel": 2, "read": 1}
			)
		)
