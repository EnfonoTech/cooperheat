"""Timesheet Reviewer: reads every Business Line's attendance, writes nothing outside the team
(client call 2026-10-25).

    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_timesheet_reviewer
"""

import frappe

from cooperheat.cooperheat import dev_seed
from cooperheat.cooperheat.permissions import scope
from cooperheat.cooperheat.roles_simple import ensure_timesheet_reviewer
from cooperheat.cooperheat.tests.test_hr_scope import HRTestCase, CT, team_of


class TestTimesheetReviewer(HRTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_timesheet_reviewer()
		cls.user = dev_seed.email("anil")  # a Supervisor: scoped to the LS team
		cls.outsider = sorted(team_of(CT, True))[0]
		frappe.get_doc("User", cls.user).add_roles("Timesheet Reviewer")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.get_doc("User", cls.user).remove_roles("Timesheet Reviewer")
		super().tearDownClass()

	def test_query_conditions_open_for_attendance_and_checkins_only(self):
		self.assertEqual(scope.attendance_query(self.user), "")
		self.assertEqual(scope.employee_checkin_query(self.user), "")
		self.assertNotEqual(scope.employee_query(self.user), "")  # Employee list stays the team

	def test_reads_but_cannot_write_outside_the_team(self):
		doc = frappe._dict(doctype="Attendance", employee=self.outsider)
		self.assertIsNone(scope.employee_doc_has_permission(doc, "read", self.user))
		self.assertFalse(scope.employee_doc_has_permission(doc, "write", self.user))
		self.assertFalse(scope.employee_doc_has_permission(doc, "submit", self.user))

	def test_shift_assignment_is_not_widened(self):
		doc = frappe._dict(doctype="Shift Assignment", employee=self.outsider)
		self.assertFalse(scope.employee_doc_has_permission(doc, "read", self.user))
