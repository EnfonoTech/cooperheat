"""Who sees which pay and HR data, the payroll person's attendance and leave rights, the IT-only AI
assistant, and the Department list that follows the Division.

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_pay_visibility
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat import ai_guard, compensation, dev_seed, org, roles_simple
from cooperheat.cooperheat.employee_security import LEVEL_1, ensure_employee_field_security
from cooperheat.cooperheat.tests.test_employee_security import visible_keys
from cooperheat.cooperheat.tests.test_hr_scope import emp_of


class TestPayVisibility(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		ensure_employee_field_security()
		cls.anil = dev_seed.email("anil")
		cls.tech = frappe.db.get_value("Employee", {"user_id": dev_seed.email("tech101")}, "name")
		cls.anil_emp = emp_of("anil")
		frappe.db.set_value(
			"Employee", cls.tech, {"date_of_birth": "1990-01-01", "passport_number": "P123456", "ctc": 9000}
		)
		frappe.get_doc(
			{
				"doctype": "Employee Compensation",
				"employee": cls.tech,
				"from_date": "2026-01-01",
				"is_active": 1,
				"currency": "SAR",
				"basic": 5000,
			}
		).insert(ignore_permissions=True) if not frappe.db.exists(
			"Employee Compensation", {"employee": cls.tech, "from_date": "2026-01-01"}
		) else None

	def tearDown(self):
		frappe.set_user("Administrator")

	# --- HR details: supervisors and managers read their team's, nobody but HR writes ---
	def test_supervisor_reads_hr_details_of_the_team_but_not_pay(self):
		seen = visible_keys(self.anil, self.tech)
		self.assertIn("date_of_birth", seen)
		self.assertIn("passport_number", seen)
		self.assertNotIn("ctc", seen)
		self.assertNotIn("bank_ac_no", seen)

	def test_level_1_rows_for_supervisor_and_manager_are_read_only(self):
		for role in ("Supervisor", "Manager"):
			row = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": "Employee", "role": role, "permlevel": 1},
				["read", "write"],
				as_dict=True,
			)
			self.assertEqual((row.read, row.write), (1, 0), role)
		self.assertTrue(set(LEVEL_1) >= {"date_of_birth", "passport_number"})

	# --- the read-only salary tab ---
	def test_own_salary_is_visible_to_the_employee_only(self):
		frappe.set_user(dev_seed.email("tech101"))
		mine = compensation.get_salary_view(self.tech)
		self.assertTrue(mine["allowed"])
		self.assertEqual(mine["scope"], "own")
		expected = compensation._summary(
			frappe.get_doc(
				"Employee Compensation",
				frappe.get_all(
					"Employee Compensation",
					filters={"employee": self.tech, "is_active": 1},
					pluck="name",
					order_by="from_date desc",
				)[0],
			)
		)["total_earnings"]
		self.assertEqual(mine["current"]["total_earnings"], expected)
		other = frappe.db.get_value("Employee", {"user_id": dev_seed.email("tech102")}, "name")
		if other:
			self.assertFalse(compensation.get_salary_view(other)["allowed"])

	def test_own_salary_for_the_app_works_for_any_role(self):
		frappe.set_user(dev_seed.email("tech101"))
		own = compensation.get_own_salary()
		self.assertTrue(own["allowed"])
		self.assertEqual(own["scope"], "own")
		frappe.set_user("Administrator")  # no employee linked to Administrator
		self.assertFalse(compensation.get_own_salary()["allowed"])

	def test_supervisor_gets_no_salary_view_of_the_team(self):
		frappe.set_user(self.anil)
		self.assertFalse(compensation.get_salary_view(self.tech)["allowed"])

	def test_manager_sees_the_team_package_without_bank_data(self):
		from cooperheat.cooperheat.permissions import scope

		manager_emp = emp_of("khalid")
		old = frappe.db.get_value("Employee", self.tech, "reports_to")
		frappe.db.set_value("Employee", self.tech, "reports_to", manager_emp)
		scope.clear_cache()
		try:
			frappe.set_user(dev_seed.email("khalid"))
			view = compensation.get_salary_view(self.tech)
			self.assertTrue(view["allowed"])
			self.assertEqual(view["scope"], "team")
			self.assertNotIn("bank", " ".join(view).lower())
			self.assertNotIn("iban", " ".join(view).lower())
			# a manager does not see the pay of somebody outside his team
			stranger = frappe.db.get_value("Employee", {"user_id": dev_seed.email("anil")}, "name")
			frappe.db.set_value("Employee", stranger, "reports_to", None)
			scope.clear_cache()
			self.assertFalse(compensation.get_salary_view(stranger)["allowed"])
		finally:
			frappe.set_user("Administrator")
			frappe.db.set_value("Employee", self.tech, "reports_to", old)
			scope.clear_cache()

	def test_hr_manager_uses_the_editable_tab_instead(self):
		frappe.set_user("Administrator")
		self.assertFalse(compensation.get_salary_view(self.tech)["allowed"])

	# --- payroll person: attendance and leave ---
	def test_payroll_role_can_edit_attendance_and_leave(self):
		roles_simple.apply(dry_run=0, snapshot_path="/tmp/test_pay_visibility_snapshot.json")
		user = "payroll.vis@cooperheat-dev.test"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{"doctype": "User", "email": user, "first_name": "PayVis", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parent": user,
				"parenttype": "User",
				"parentfield": "roles",
				"role": "Payroll",
			}
		).db_insert() if not frappe.db.exists("Has Role", {"parent": user, "role": "Payroll"}) else None
		frappe.clear_cache(user=user)
		for dt in ("Attendance", "Leave Application", "Leave Allocation", "Attendance Request"):
			self.assertTrue(frappe.has_permission(dt, "read", user=user), dt)
			self.assertTrue(frappe.has_permission(dt, "write", user=user), dt)

	# --- profiles for the named people ---
	def test_profiles_full_access_is_it_minus_system_manager(self):
		it, full = set(roles_simple.PROFILES["IT"]), set(roles_simple.PROFILES["Full Access"])
		self.assertEqual(it - full, {"System Manager", "Script Manager"})
		both = set(roles_simple.PROFILES["Payroll and HR Manager"])
		self.assertTrue({"HR Manager", "Payroll"} <= both)

	def test_assign_profiles_is_a_dry_run_by_default_and_reversible(self):
		user = "assign.test@cooperheat-dev.test"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{"doctype": "User", "email": user, "first_name": "Assign", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parent": user,
				"parenttype": "User",
				"parentfield": "roles",
				"role": "Accounts Manager",
			}
		).db_insert() if not frappe.db.exists(
			"Has Role", {"parent": user, "role": "Accounts Manager"}
		) else None
		snap = "/tmp/test_assign_snapshot.json"
		dry = roles_simple.assign_profiles({user: "HR Manager"})
		self.assertEqual(dry["dry_run"], 1)
		self.assertIn("Accounts Manager", dry["plan"][user]["loses"])
		self.assertTrue(frappe.db.exists("Has Role", {"parent": user, "role": "Accounts Manager"}))
		roles_simple.assign_profiles({user: "HR Manager"}, dry_run=0, snapshot_path=snap)
		self.assertFalse(frappe.db.exists("Has Role", {"parent": user, "role": "Accounts Manager"}))
		self.assertTrue(frappe.db.exists("Has Role", {"parent": user, "role": "HR Manager"}))
		self.assertEqual(frappe.db.get_value("User", user, "role_profile_name"), "HR Manager")
		roles_simple.revert_users(snapshot_path=snap)
		self.assertTrue(frappe.db.exists("Has Role", {"parent": user, "role": "Accounts Manager"}))
		self.assertFalse(frappe.db.exists("Has Role", {"parent": user, "role": "HR Manager"}))

	# --- the AI assistant is IT-only ---
	def test_ai_assistant_refuses_everybody_but_system_manager(self):
		frappe.set_user(self.anil)
		with self.assertRaises(frappe.PermissionError):
			ai_guard.handle_ai_query("show every salary")
		frappe.set_user("Administrator")
		result = ai_guard.handle_ai_query(
			"show every salary"
		)  # no AI key on the dev site: an error dict, no query run
		self.assertIsInstance(result, dict)

	def test_ai_page_and_workspace_are_system_manager_only(self):
		from cooperheat.setup import ensure_ai_restricted

		ensure_ai_restricted()
		for doctype, name in (("Page", "ai-chat"), ("Workspace", "FATEH AI")):
			if frappe.db.exists(doctype, name):
				self.assertEqual(
					frappe.get_all("Has Role", filters={"parent": name, "parenttype": doctype}, pluck="role"),
					["System Manager"],
				)

	# --- Department follows the Division ---
	def test_departments_follow_the_division(self):
		company = frappe.db.get_value("Department", {"custom_unit_type": "Division"}, "company")
		division_node = frappe.db.get_value(
			"Department", {"custom_unit_type": "Division", "is_group": 1}, "name"
		)
		if not division_node:
			self.skipTest("no Division node on this site")
		legacy = (
			division_node.split(" Division - ")[0]
			if " Division - " in division_node
			else division_node.split(" - ")[0]
		)
		below = org.descendants([division_node]) - {division_node}
		rows = org.departments_in_division(
			"Department", "", "name", 0, 100, {"division": legacy, "company": company}
		)
		self.assertEqual({r[0] for r in rows}, below)
		everything = org.departments_in_division(
			"Department", "", "name", 0, 500, {"division": "No Such Division", "company": company}
		)
		self.assertGreater(len(everything), len(below))
		self.assertIsNone(org.department_in_division("No Such Division", "x"))
		if below:
			self.assertTrue(org.department_in_division(legacy, sorted(below)[0]))
		self.assertFalse(org.department_in_division(legacy, "Not A Department"))
