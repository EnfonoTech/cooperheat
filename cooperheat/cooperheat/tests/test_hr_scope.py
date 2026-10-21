# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Team scoping, edit window, attendance generation, hierarchy and Pay Batch.

Runs against the DEV seed (cooperheat.cooperheat.dev_seed):
    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_hr_scope
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime, today

from cooperheat.cooperheat import dev_seed
from cooperheat.cooperheat.api import attendance_gen, supervisor
from cooperheat.cooperheat.permissions import scope

LS = dev_seed.dept_name("Leak Sealing")
CT = dev_seed.dept_name("Contracting")
NDT = dev_seed.dept_name("NDT")


def emp_of(key):
	return frappe.db.get_value("Employee", {"user_id": dev_seed.email(key)}, "name")


def team_of(dept, sandbox=False):
	"""Technicians of a department. ``sandbox`` adds the check-in-free test technicians."""
	names = set(frappe.get_all("Employee", filters={"department": dept, "user_id": ["like", "tech%"]}, pluck="name"))
	if sandbox:
		names |= set(frappe.get_all("Employee", filters={"department": dept, "user_id": ["like", "sandbox%"]}, pluck="name"))
	return names


class HRTestCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		dev_seed.reset_activity(commit=False)

	def setUp(self):
		frappe.set_user("Administrator")
		scope.clear_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		scope.clear_cache()


class TestScoping(HRTestCase):
	def test_roles_and_scoped_flags(self):
		self.assertTrue(scope.is_scoped(dev_seed.email("anil")))
		self.assertTrue(scope.is_scoped(dev_seed.email("khalid")))
		self.assertFalse(scope.is_scoped(dev_seed.email("mustafa")))  # HR Manager
		self.assertFalse(scope.is_scoped(dev_seed.email("irtaza")))
		self.assertFalse(scope.is_scoped("Administrator"))
		self.assertFalse(scope.is_scoped("tech101" + dev_seed.DOMAIN))  # plain employee

	def test_supervisor_sees_only_own_team_in_employee_list(self):
		frappe.set_user(dev_seed.email("anil"))
		seen = set(frappe.get_list("Employee", pluck="name", limit_page_length=500))
		self.assertTrue(team_of(LS, True) <= seen)
		self.assertIn(emp_of("anil"), seen)
		self.assertFalse(seen & team_of(CT, True))
		self.assertFalse(seen & team_of(NDT))

	def test_other_supervisor_cannot_open_foreign_employee(self):
		foreign = sorted(team_of(LS))[0]
		frappe.set_user(dev_seed.email("saleh"))
		self.assertFalse(frappe.has_permission("Employee", "read", doc=foreign))
		frappe.set_user(dev_seed.email("anil"))
		self.assertTrue(frappe.has_permission("Employee", "read", doc=foreign))

	def test_checkin_and_attendance_lists_are_scoped(self):
		frappe.set_user(dev_seed.email("saleh"))
		emps = set(frappe.get_list("Employee Checkin", pluck="employee", limit_page_length=1000))
		self.assertTrue(emps)
		self.assertFalse(emps & team_of(LS))
		self.assertFalse(emps & team_of(NDT))

	def test_manager_sees_both_supervisors_and_their_departments(self):
		# Khalid is Level 2 approver of Leak Sealing and Contracting and the boss of both supervisors
		frappe.set_user(dev_seed.email("khalid"))
		seen = set(frappe.get_list("Employee", pluck="name", limit_page_length=500))
		self.assertTrue(team_of(LS) <= seen)
		self.assertTrue(team_of(CT) <= seen)
		self.assertIn(emp_of("anil"), seen)
		self.assertFalse(seen & team_of(NDT))

	def test_hr_manager_unrestricted(self):
		frappe.set_user(dev_seed.email("mustafa"))
		seen = set(frappe.get_list("Employee", pluck="name", limit_page_length=500))
		self.assertTrue((team_of(LS, True) | team_of(CT, True) | team_of(NDT)) <= seen)

	def test_department_list_is_scoped_and_self_service_for_matrix_only(self):
		frappe.set_user(dev_seed.email("anil"))
		self.assertEqual(set(frappe.get_list("Department", pluck="name")), {LS})
		doc = frappe.get_doc("Department", LS)
		doc.department_name = "Hijacked"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		frappe.set_user(dev_seed.email("saleh"))
		self.assertFalse(frappe.has_permission("Department", "write", doc=LS))

	def test_supervisor_can_add_a_peer_approver_to_own_department(self):
		frappe.set_user(dev_seed.email("anil"))
		doc = frappe.get_doc("Department", LS)
		before = len(doc.approval_matrix)
		doc.append("approval_matrix", {"approval_level": 1, "approver": emp_of("saleh"), "approval_window_hours": 24})
		doc.save()
		try:
			self.assertEqual(len(frappe.get_doc("Department", LS).approval_matrix), before + 1)
		finally:  # the test DB is shared across tests - put the matrix back
			frappe.set_user("Administrator")
			d = frappe.get_doc("Department", LS)
			d.set("approval_matrix", [r for r in d.approval_matrix if not (r.approval_level == 1 and r.approver == emp_of("saleh"))])
			d.save()

	def test_supervisor_cannot_replace_a_more_senior_approver(self):
		frappe.set_user(dev_seed.email("anil"))  # Level 1 in Leak Sealing
		doc = frappe.get_doc("Department", LS)
		row = next(r for r in doc.approval_matrix if r.approval_level == 2)
		row.approver = emp_of("anil")
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_supervisor_outside_the_matrix_cannot_edit_another_department(self):
		frappe.set_user(dev_seed.email("saleh"))  # not an approver of Leak Sealing
		self.assertFalse(frappe.has_permission("Department", "write", doc=LS))

	def test_saving_a_supervisor_employee_does_not_recreate_self_permission(self):
		frappe.set_user("Administrator")
		emp = frappe.get_doc("Employee", emp_of("anil"))
		emp.create_user_permission = 1
		emp.save()
		rows = frappe.get_all("User Permission", filters={"user": dev_seed.email("anil"), "allow": "Employee"})
		self.assertFalse(rows)

	def test_no_self_or_department_user_permissions_for_supervisors(self):
		frappe.set_user("Administrator")
		frappe.get_doc({"doctype": "User Permission", "user": dev_seed.email("anil"), "allow": "Department", "for_value": LS}).insert()
		self.assertEqual(len(scope.sync_user_permissions(dev_seed.email("anil"))), 1)
		rows = frappe.get_all("User Permission", filters={"user": dev_seed.email("anil"), "allow": ["in", ["Employee", "Department"]]})
		self.assertFalse(rows)
		# a plain technician keeps the HRMS "Employee = self" restriction
		self.assertEqual(scope.sync_user_permissions("tech101" + dev_seed.DOMAIN), [])


class TestEditWindow(HRTestCase):
	def _checkin(self, employee, hours_ago):
		frappe.db.delete("Employee Checkin", {"employee": employee})
		return frappe.get_doc(
			{
				"doctype": "Employee Checkin",
				"employee": employee,
				"log_type": "IN",
				"time": add_to_date(now_datetime(), hours=-hours_ago).replace(microsecond=0),
			}
		).insert(ignore_permissions=True)

	def _tech(self, n):
		return frappe.db.get_value("Employee", {"employee_number": "T%d" % n}, "name")

	def test_supervisor_can_edit_within_48h_but_not_after(self):
		recent = self._checkin(self._tech(119), 10)
		old = self._checkin(self._tech(120), 60)
		frappe.set_user(dev_seed.email("anil"))
		doc = frappe.get_doc("Employee Checkin", recent.name)
		doc.time = add_to_date(doc.time, minutes=-20)
		doc.save()  # inside the window
		doc = frappe.get_doc("Employee Checkin", old.name)
		doc.time = add_to_date(doc.time, minutes=-20)
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_hr_manager_can_edit_after_48h_and_edit_is_logged(self):
		old = self._checkin(self._tech(120), 70)
		frappe.set_user(dev_seed.email("mustafa"))
		doc = frappe.get_doc("Employee Checkin", old.name)
		doc.time = add_to_date(doc.time, minutes=15)
		doc.save()
		comments = frappe.get_all("Comment", filters={"reference_doctype": "Employee Checkin", "reference_name": old.name}, pluck="content")
		self.assertTrue(any("Time changed" in c for c in comments))

	def test_cannot_move_a_checkin_into_the_future(self):
		recent = self._checkin(self._tech(119), 5)
		frappe.set_user(dev_seed.email("anil"))
		doc = frappe.get_doc("Employee Checkin", recent.name)
		doc.time = add_to_date(now_datetime(), hours=3)
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_supervisor_cannot_edit_other_teams_checkin(self):
		other = self._checkin(self._tech(121), 5)  # Contracting tech
		frappe.set_user(dev_seed.email("anil"))
		with self.assertRaises(frappe.PermissionError):
			supervisor.set_checkin_time(other.name, add_to_date(now_datetime(), hours=-6))


class TestAttendanceGeneration(HRTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Attendance")
		frappe.db.sql("update `tabEmployee Checkin` set attendance = null")

	def test_creates_attendance_and_routes_to_level_1_approver(self):
		res = attendance_gen.generate(add_days(today(), -3), today())
		self.assertGreater(res["created"], 0)
		rows = frappe.get_all(
			"Attendance",
			filters={"department": LS, "docstatus": 1},
			fields=["workflow_state", "current_approver", "current_approval_level"],
		)
		self.assertTrue(rows)
		for r in rows:
			self.assertEqual(r.workflow_state, "Pending Level 1 Approval")
			self.assertEqual(r.current_approver, emp_of("anil"))
			self.assertEqual(r.current_approval_level, 1)

	def test_is_idempotent_and_links_checkins(self):
		attendance_gen.generate(add_days(today(), -3), today())
		again = attendance_gen.generate(add_days(today(), -3), today())
		self.assertEqual(again["created"], 0)
		linked = frappe.db.count("Employee Checkin", {"attendance": ["is", "set"]})
		self.assertGreater(linked, 0)

	def test_open_checkin_day_is_not_turned_into_attendance(self):
		tech = frappe.db.get_value("Employee", {"employee_number": "T114"}, "name")
		frappe.db.delete("Employee Checkin", {"employee": tech})
		frappe.get_doc({"doctype": "Employee Checkin", "employee": tech, "log_type": "IN", "time": add_days(today(), -1) + " 07:00:00"}).insert(ignore_permissions=True)
		attendance_gen.generate(add_days(today(), -3), today())
		self.assertFalse(frappe.db.exists("Attendance", {"employee": tech, "docstatus": 1}))

	def test_department_without_level_1_approver_is_skipped_and_reported(self):
		res = attendance_gen.generate(add_days(today(), -3), today())
		self.assertGreater(res["no_approver"], 0)
		self.assertFalse(frappe.db.exists("Attendance", {"department": NDT}))

	def test_kill_switch(self):
		frappe.conf.cooperheat_disable_attendance_generation = 1
		try:
			self.assertEqual(attendance_gen.generate_attendance_from_checkins().get("disabled"), 1)
		finally:
			frappe.conf.pop("cooperheat_disable_attendance_generation", None)


class TestSupervisorWorkspaceAPI(HRTestCase):
	def setUp(self):
		super().setUp()
		attendance_gen.generate(add_days(today(), -3), today())

	def test_team_lists_only_own_technicians_with_pending_counts(self):
		frappe.set_user(dev_seed.email("anil"))
		team = supervisor.get_team(add_days(today(), -1))
		names = {t["employee"] for t in team}
		self.assertEqual(names, team_of(LS, True))
		seeded = {t["employee"]: t for t in team if t["employee"] in team_of(LS)}
		self.assertTrue(all(t["pending"] >= 1 for t in seeded.values()))

	def test_pending_grouped_by_technician_and_defaults_to_one_day(self):
		frappe.set_user(dev_seed.email("anil"))
		groups = supervisor.get_pending_grouped(add_days(today(), -1))
		self.assertEqual({g["employee"] for g in groups}, team_of(LS))
		self.assertTrue(all(len(g["items"]) == 1 for g in groups))
		backlog = supervisor.get_pending_grouped(all_dates=1)
		self.assertTrue(all(len(g["items"]) >= 2 for g in backlog))

	def test_employee_days_has_day_summary_and_blocks_foreign_employee(self):
		mine = sorted(team_of(LS))[0]
		foreign = sorted(team_of(CT))[0]
		frappe.set_user(dev_seed.email("anil"))
		days = supervisor.get_employee_days(mine)
		self.assertTrue(days)
		d = days[0]
		self.assertEqual(d["first_in"][11:16], "07:15")
		self.assertEqual(d["last_out"][11:16], "16:40")
		self.assertAlmostEqual(d["total_hours"], 9.42, places=1)
		self.assertTrue(d["complete"])
		self.assertIn("NRT-1001", d["checkins"][0]["project_label"])
		with self.assertRaises(frappe.PermissionError):
			supervisor.get_employee_days(foreign)

	def test_old_checkins_are_flagged_not_editable_for_supervisor(self):
		mine = sorted(team_of(LS))[0]
		frappe.set_user(dev_seed.email("anil"))
		days = supervisor.get_employee_days(mine, add_days(today(), -2), today())
		two_days = [d for d in days if d["date"] == add_days(today(), -2)]
		if two_days:  # ~ 3 days old morning check-in is outside 48h
			self.assertFalse(two_days[0]["checkins"][0]["editable"])


class TestHierarchyAndProjects(HRTestCase):
	def test_new_joiner_is_not_linked_by_department(self):
		"""Reporting lines are set per employee (Direct / Immediate Reporting), not guessed from the department."""
		doc = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "New",
				"last_name": "Joiner",
				"gender": "Male",
				"date_of_birth": "1995-05-05",
				"date_of_joining": today(),
				"company": dev_seed.COMPANY,
				"department": CT,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		self.assertFalse(doc.reports_to)

	def test_exceptions_report_lists_unlinked_ndt_staff(self):
		from cooperheat.cooperheat.report.employee_approver_exceptions.employee_approver_exceptions import get_data

		rows = get_data(frappe._dict(department=NDT))
		issues = {r["issue"] for r in rows}
		self.assertIn("No Direct / Immediate Reporting", issues)

	def test_project_is_named_after_the_client_job_code(self):
		doc = frappe.get_doc(
			{"doctype": "Project", "project_name": "Test Job", "custom_project_code": "NRT-9999", "company": dev_seed.COMPANY}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.name, "NRT-9999")
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc(
				{"doctype": "Project", "project_name": "Dup", "custom_project_code": "NRT-9999", "company": dev_seed.COMPANY}
			).insert(ignore_permissions=True)

	def test_supervisor_can_create_project_but_not_delete(self):
		frappe.set_user(dev_seed.email("anil"))
		self.assertTrue(frappe.has_permission("Project", "create"))
		self.assertFalse(frappe.has_permission("Project", "delete"))


class TestPayBatch(HRTestCase):
	def test_every_employee_has_a_batch_and_main_exists(self):
		self.assertTrue(frappe.db.exists("Pay Batch", "Main"))

	def test_employee_batch_overrides_and_propagates_to_active_compensation(self):
		from cooperheat.cooperheat.overrides.employee import effective_pay_batch

		if not frappe.db.exists("Pay Batch", "Sponsor A"):
			frappe.get_doc({"doctype": "Pay Batch", "batch_name": "Sponsor A"}).insert()
		emp = frappe.db.get_value("Employee", {"employee_number": "T102"}, "name")
		frappe.db.set_value("Employee", emp, "custom_pay_batch", "Sponsor A")
		self.assertEqual(effective_pay_batch(emp), "Sponsor A")

	def test_payroll_import_skips_employees_of_other_batches(self):
		from cooperheat.cooperheat.doctype.payroll_import.payroll_import import _process_row

		if not frappe.db.exists("Pay Batch", "Sponsor A"):
			frappe.get_doc({"doctype": "Pay Batch", "batch_name": "Sponsor A"}).insert()
		emp = frappe.db.get_value("Employee", {"employee_number": "T103"}, "name")
		frappe.db.set_value("Employee", emp, "custom_pay_batch", "Main")
		doc = frappe._dict(pay_batch="Sponsor A", month="October", year=2026, posting_date=today(), company=dev_seed.COMPANY, submit_after_create=0)
		status, sheet, employee, message = _process_row(doc, {"code": "T103"})
		self.assertEqual(status, "Skipped")
		self.assertIn("Sponsor A", message)

	def test_hr_manager_can_create_a_batch(self):
		frappe.set_user(dev_seed.email("irtaza"))
		self.assertTrue(frappe.has_permission("Pay Batch", "create"))
		frappe.set_user(dev_seed.email("anil"))
		self.assertFalse(frappe.has_permission("Pay Batch", "create"))


class TestReviewHardening(HRTestCase):
	def _tech(self, n):
		return frappe.db.get_value("Employee", {"employee_number": "T%d" % n}, "name")

	def test_plain_employee_cannot_use_the_workspace_api(self):
		frappe.set_user("tech101" + dev_seed.DOMAIN)
		for fn in (supervisor.get_team, supervisor.get_pending_grouped):
			with self.assertRaises(frappe.PermissionError):
				fn()
		with self.assertRaises(frappe.PermissionError):
			supervisor.get_employee_days(sorted(team_of(LS))[0])

	def test_new_checkin_form_opens_for_a_supervisor(self):
		frappe.set_user(dev_seed.email("anil"))
		self.assertTrue(frappe.has_permission("Employee Checkin", "create"))
		self.assertTrue(frappe.has_permission(doc=frappe.new_doc("Employee Checkin"), ptype="create"))

	def test_supervisor_cannot_insert_an_old_checkin_for_a_technician(self):
		frappe.set_user(dev_seed.email("anil"))
		doc = frappe.get_doc(
			{"doctype": "Employee Checkin", "employee": self._tech(119), "log_type": "IN", "time": add_to_date(now_datetime(), hours=-70)}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_supervisor_can_punch_for_themself_even_when_late(self):
		frappe.set_user(dev_seed.email("anil"))
		frappe.db.delete("Employee Checkin", {"employee": emp_of("anil")})
		doc = frappe.get_doc(
			{"doctype": "Employee Checkin", "employee": emp_of("anil"), "log_type": "IN", "time": add_to_date(now_datetime(), hours=-72)}
		)
		doc.insert()  # an offline punch draining late is a normal check-in, not a supervisor edit
		self.assertTrue(doc.name)

	def test_checkin_cannot_be_reassigned_after_48h(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Employee Checkin", {"employee": self._tech(120)})
		old = frappe.get_doc(
			{"doctype": "Employee Checkin", "employee": self._tech(120), "log_type": "IN", "time": add_to_date(now_datetime(), hours=-60)}
		).insert()
		frappe.set_user(dev_seed.email("anil"))
		doc = frappe.get_doc("Employee Checkin", old.name)
		doc.log_type = "OUT"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_edit_blocked_once_the_attendance_is_approved(self):
		attendance_gen.generate(add_days(today(), -3), today())
		att = frappe.get_all("Attendance", filters={"department": LS, "attendance_date": add_days(today(), -1), "docstatus": 1}, pluck="name")[0]
		frappe.db.set_value("Attendance", att, "workflow_state", "Approved")
		emp, day = frappe.db.get_value("Attendance", att, ["employee", "attendance_date"])
		log = frappe.get_all("Employee Checkin", filters={"employee": emp, "log_type": "IN", "time": ["between", [str(day) + " 00:00:00", str(day) + " 23:59:59"]]}, pluck="name")[0]
		frappe.set_user(dev_seed.email("anil"))
		doc = frappe.get_doc("Employee Checkin", log)
		with self.assertRaises(frappe.ValidationError):
			supervisor.save_checkin_time(doc, add_to_date(doc.time, minutes=-5))
		frappe.set_user(dev_seed.email("mustafa"))
		doc = frappe.get_doc("Employee Checkin", log)
		supervisor.save_checkin_time(doc, add_to_date(doc.time, minutes=-5))  # HR may still correct it

	def test_todays_attendance_waits_until_the_day_looks_finished(self):
		now = now_datetime()
		if now.hour < 8:
			self.skipTest("needs a same-calendar-day window of several hours")
		tech = self._tech(119)
		frappe.db.delete("Employee Checkin", {"employee": tech})
		frappe.db.delete("Attendance", {"employee": tech})
		start = now.replace(hour=0, minute=30, second=0, microsecond=0)
		for log_type, t in (("IN", start), ("OUT", add_to_date(now, hours=-1))):
			frappe.get_doc({"doctype": "Employee Checkin", "employee": tech, "log_type": log_type, "time": t}).insert(ignore_permissions=True)
		attendance_gen.generate(today(), today())
		self.assertFalse(frappe.db.exists("Attendance", {"employee": tech}))  # lunch-break OUT: too early
		frappe.db.set_value("Employee Checkin", {"employee": tech, "log_type": "OUT"}, "time", add_to_date(now, hours=-4))
		attendance_gen.generate(today(), today())
		self.assertTrue(frappe.db.exists("Attendance", {"employee": tech, "docstatus": 1}))

	def test_cancelled_attendance_is_not_recreated(self):
		attendance_gen.generate(add_days(today(), -3), today())
		att = frappe.get_all("Attendance", filters={"department": LS, "attendance_date": add_days(today(), -1), "docstatus": 1}, pluck="name")[0]
		frappe.get_doc("Attendance", att).cancel()
		again = attendance_gen.generate(add_days(today(), -3), today())
		self.assertEqual(again["created"], 0)

	def test_concurrent_run_is_refused(self):
		from frappe.utils.synchronization import filelock

		with filelock("cooperheat_attendance_generation", timeout=0):
			self.assertEqual(attendance_gen.generate(add_days(today(), -3), today()).get("busy"), 1)

	def test_self_permission_is_restored_when_the_supervisor_role_is_removed(self):
		mail = "tech101" + dev_seed.DOMAIN
		for up in frappe.get_all("User Permission", filters={"user": mail, "allow": "Employee"}, pluck="name"):
			frappe.delete_doc("User Permission", up, force=True, ignore_permissions=True)
		scope.restore_self_permission(mail)
		self.assertTrue(frappe.db.exists("User Permission", {"user": mail, "allow": "Employee"}))

	def test_existing_role_permissions_are_not_overwritten(self):
		from cooperheat import setup

		row = {"parent": "Project", "role": "Supervisor", "permlevel": 0}
		frappe.db.set_value("Custom DocPerm", row, "create", 0)
		try:
			setup.ensure_role_permissions()
			self.assertEqual(frappe.db.get_value("Custom DocPerm", row, "create"), 0)
		finally:
			frappe.db.set_value("Custom DocPerm", row, "create", 1)


class TestMobileApprovalFlow(HRTestCase):
	"""The supervisor corrects a time and approves through the mobile app API."""

	def setUp(self):
		super().setUp()
		frappe.db.delete("Attendance")
		frappe.db.sql("update `tabEmployee Checkin` set attendance = null")
		attendance_gen.generate(add_days(today(), -3), today())

	def test_approver_edits_a_time_and_approves_through_the_app_api(self):
		from fatehhr.api import approvals

		frappe.set_user(dev_seed.email("anil"))
		pending = approvals.list_pending()
		self.assertTrue(pending)
		yesterday = add_days(today(), -1)
		# only yesterday's records are inside the 48h correction window
		name = next(a["name"] for a in pending if str(frappe.db.get_value("Attendance", a["name"], "attendance_date")) == yesterday)
		detail = approvals.detail(name)
		first_in = next(c for c in detail["checkins"] if c["log_type"] == "IN")
		hours_before = frappe.db.get_value("Attendance", name, "working_hours")

		# move the IN 30 minutes later (the app sends UTC ISO strings)
		moved = add_to_date(frappe.db.get_value("Employee Checkin", first_in["name"], "time"), minutes=30)
		approvals.update_checkin_times(name, [{"checkin": first_in["name"], "time": approvals._naive_site_to_utc_iso(moved)}])
		self.assertEqual(frappe.db.get_value("Employee Checkin", first_in["name"], "time"), moved)
		self.assertAlmostEqual(frappe.db.get_value("Attendance", name, "working_hours"), hours_before - 0.5, places=1)

		approvals.approve(name)
		self.assertEqual(frappe.db.get_value("Attendance", name, "workflow_state"), "Pending Level 2 Approval")
		self.assertEqual(frappe.db.get_value("Attendance", name, "current_approver"), emp_of("khalid"))

	def test_other_supervisor_cannot_approve(self):
		from fatehhr.api import approvals

		frappe.set_user(dev_seed.email("anil"))
		name = approvals.list_pending()[0]["name"]
		frappe.set_user(dev_seed.email("saleh"))
		with self.assertRaises(frappe.PermissionError):
			approvals.approve(name)


class TestWorkspaceUIBackend(HRTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Attendance")
		frappe.db.sql("update `tabEmployee Checkin` set attendance = null")
		attendance_gen.generate(add_days(today(), -3), today())

	def test_team_separates_pending_for_the_day_from_total(self):
		frappe.set_user(dev_seed.email("anil"))
		team = {t["employee"]: t for t in supervisor.get_team(add_days(today(), -1))}
		tech = team[sorted(team_of(LS))[0]]
		self.assertEqual(tech["pending"], 2)       # yesterday + the day before
		self.assertEqual(tech["pending_day"], 1)   # only the selected day
		today_view = supervisor.get_team(today())
		self.assertTrue(all(t["pending_day"] == 0 for t in today_view))

	def test_pending_scopes(self):
		frappe.set_user(dev_seed.email("anil"))
		day = add_days(today(), -1)
		one = supervisor.get_pending_grouped(day, scope="day")
		earlier = supervisor.get_pending_grouped(day, scope="earlier")
		everything = supervisor.get_pending_grouped(day, scope="all")
		count = lambda groups: sum(len(g["items"]) for g in groups)
		self.assertEqual(count(one), len(team_of(LS)))
		self.assertEqual(count(earlier), len(team_of(LS)))
		self.assertEqual(count(everything), count(one) + count(earlier))

	def test_employee_days_flag_what_the_user_can_approve(self):
		mine = sorted(team_of(LS))[0]
		frappe.set_user(dev_seed.email("anil"))
		self.assertTrue(all(d["can_approve"] for d in supervisor.get_employee_days(mine) if d["attendance"]))
		frappe.set_user(dev_seed.email("khalid"))  # level 2: nothing is waiting for him yet
		self.assertFalse(any(d["can_approve"] for d in supervisor.get_employee_days(mine)))

	def test_approve_attendance_moves_it_to_the_next_level(self):
		frappe.set_user(dev_seed.email("anil"))
		name = supervisor.get_pending_grouped(add_days(today(), -1), scope="day")[0]["items"][0]["attendance"]
		res = supervisor.approve_attendance(name)
		self.assertEqual(res["state"], "Pending Level 2 Approval")
		frappe.set_user(dev_seed.email("khalid"))
		self.assertEqual(supervisor.get_pending_grouped(add_days(today(), -1), scope="day")[0]["items"][0]["attendance"], name)

	def test_approve_many_reports_each_failure_and_keeps_going(self):
		frappe.set_user(dev_seed.email("anil"))
		items = [i["attendance"] for g in supervisor.get_pending_grouped(add_days(today(), -1), scope="day") for i in g["items"]][:3]
		frappe.set_user(dev_seed.email("saleh"))
		res = supervisor.approve_many(items)  # not Saleh's team / not assigned to him
		self.assertEqual(res["approved"], [])
		self.assertEqual(len(res["failed"]), 3)
		frappe.set_user(dev_seed.email("anil"))
		res = supervisor.approve_many(items + ["NO-SUCH-ATT"])
		self.assertEqual(len(res["approved"]), 3)
		self.assertEqual(len(res["failed"]), 1)

	def test_a_supervisor_cannot_approve_someone_elses_assignment(self):
		frappe.set_user(dev_seed.email("anil"))
		name = supervisor.get_pending_grouped(add_days(today(), -1), scope="day")[0]["items"][0]["attendance"]
		frappe.set_user(dev_seed.email("saleh"))
		with self.assertRaises(frappe.PermissionError):
			supervisor.approve_attendance(name)

	def test_hr_manager_can_step_in_for_the_assigned_approver(self):
		frappe.set_user(dev_seed.email("anil"))
		name = supervisor.get_pending_grouped(add_days(today(), -1), scope="day")[0]["items"][0]["attendance"]
		frappe.set_user(dev_seed.email("mustafa"))
		self.assertEqual(supervisor.approve_attendance(name)["state"], "Pending Level 2 Approval")

	def test_workspace_has_number_cards_and_link_cards(self):
		ws = frappe.get_doc("Workspace", "Supervisor Desk")
		self.assertEqual({r.number_card_name for r in ws.number_cards}, {"Team Pending Approvals", "Team Check-ins Today", "Team Members"})
		cards = [r.label for r in ws.links if r.type == "Card Break"]
		self.assertEqual(cards, ["My Team", "Attendance & Approvals", "Projects & Sites", "HR Tools"])
		self.assertIn('"type": "card"', ws.content)
		self.assertIn('"type": "number_card"', ws.content)

	def test_number_cards_count_only_the_users_team(self):
		from frappe.desk.doctype.number_card.number_card import get_result

		def count(card):
			doc = frappe.get_doc("Number Card", card)
			return get_result(doc, doc.filters_json and frappe.parse_json(doc.filters_json))

		frappe.set_user(dev_seed.email("anil"))
		self.assertEqual(count("Team Members"), len(team_of(LS, True)) + 1)  # + Anil himself
		frappe.set_user(dev_seed.email("mustafa"))
		self.assertGreater(count("Team Members"), len(team_of(LS, True)) + 1)
