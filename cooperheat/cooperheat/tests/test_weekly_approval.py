"""Weekly Attendance Approval (client, 2026-10-30): the Direct / Immediate Reporting person of a
ticked employee approves once a week: no daily e-mail, a weekly summary, a window from the review.

    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_weekly_approval
"""

from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.utils import get_datetime, now_datetime

from cooperheat.cooperheat import dev_seed, org, weekly_approval
from cooperheat.cooperheat.api import supervisor
from cooperheat.cooperheat.tests.test_hr_scope import emp_of
from cooperheat.cooperheat.tests.test_org_structure import make_employee
from cooperheat.cooperheat.tests.test_reporting_approvals import FIELD, ReportingTestCase, new_attendance


class TestNextReview(ReportingTestCase):
	def test_next_sunday_8am(self):
		self.assertEqual(weekly_approval.next_review(datetime(2026, 10, 30, 15, 0)), datetime(2026, 11, 1, 8, 0))  # Fri
		self.assertEqual(weekly_approval.next_review(datetime(2026, 11, 1, 7, 0)), datetime(2026, 11, 1, 8, 0))  # Sun early
		self.assertEqual(weekly_approval.next_review(datetime(2026, 11, 1, 8, 0)), datetime(2026, 11, 8, 8, 0))  # at review
		self.assertEqual(weekly_approval.next_review(datetime(2026, 11, 2, 9, 0)), datetime(2026, 11, 8, 8, 0))  # Mon


class TestWeeklyApproval(ReportingTestCase):
	def test_chain_marks_only_the_immediate_reporting_level_weekly(self):
		anil, khalid, irtaza = self.people()
		saleh = emp_of("saleh")
		emp = make_employee(
			"WeeklyA", custom_staff_category=FIELD, reports_to=anil, custom_secondary_reporting=khalid,
			custom_support_reporting=saleh, custom_weekly_attendance_approval=1,
		)
		chain = [(r.approval_level, r.approver, r.weekly) for r in org.approval_chain(emp.name)]
		self.assertEqual(chain, [(1, saleh, False), (2, anil, True), (3, irtaza, False)])

	def test_unticked_stays_daily(self):
		anil, khalid, _ = self.people()
		emp = make_employee("WeeklyOff", custom_staff_category=FIELD, reports_to=anil, custom_secondary_reporting=khalid)
		self.assertFalse(any(r.weekly for r in org.approval_chain(emp.name)))
		with patch("frappe.sendmail") as mail:
			name = new_attendance(emp.name)
		self.assertEqual(mail.call_count, 1)  # daily: one e-mail for this attendance, as before
		self.assertEqual(frappe.db.get_value("Attendance", name, "approval_window_hours"), 48)

	def test_weekly_level_waits_for_the_review_and_sends_no_daily_mail(self):
		anil, khalid, _ = self.people()
		emp = make_employee(
			"WeeklyB", custom_staff_category=FIELD, reports_to=anil, custom_secondary_reporting=khalid,
			custom_weekly_attendance_approval=1,
		)
		since = now_datetime()
		with patch("frappe.sendmail") as mail:
			name = new_attendance(emp.name)  # level 1 is Anil (Immediate Reporting), weekly
		self.assertEqual(mail.call_count, 0)  # no e-mail per attendance
		expires = get_datetime(frappe.db.get_value("Attendance", name, "window_expires_at"))
		self.assertEqual(expires, weekly_approval.window_expiry(1, since))

		summary = weekly_approval.pending_for_weekly_review()
		self.assertIn(name, [r.name for r in summary.get(anil, [])])
		with patch("frappe.sendmail") as mail:
			self.assertEqual(weekly_approval.send_weekly_summaries().get(anil, 0), len(summary[anil]))
		to_anil = [c for c in mail.call_args_list if "Anil" in c.kwargs["message"]]
		self.assertEqual(len(to_anil), 1)  # one summary, not one per record
		self.assertIn("WeeklyB", to_anil[0].kwargs["message"])

		# approving is as usual; the next level (Khalid) is daily again and gets its e-mail
		frappe.set_user(dev_seed.email("anil"))
		self.assertEqual(supervisor.approve_attendance(name)["state"], "Pending Level 2 Approval")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Attendance", name, "approval_window_hours"), 72)
		self.assertNotIn(name, [r.name for r in weekly_approval.pending_for_weekly_review().get(anil, [])])

	def test_approve_all_only_touches_records_assigned_to_me(self):
		from fatehhr.api import approvals as app_approvals

		anil, khalid, _ = self.people()
		mine = make_employee("WeeklyMine", custom_staff_category=FIELD, reports_to=anil, custom_secondary_reporting=khalid,
			custom_weekly_attendance_approval=1)
		other = make_employee("WeeklyOther", custom_staff_category=FIELD, reports_to=khalid)
		a, b = new_attendance(mine.name), new_attendance(other.name)
		frappe.set_user(dev_seed.email("anil"))
		self.assertEqual(app_approvals.approve_all([]), {"approved": [], "failed": []})
		res = app_approvals.approve_all([a, b])
		frappe.set_user("Administrator")
		self.assertEqual(res["approved"], [a])
		self.assertEqual(frappe.db.get_value("Attendance", a, "workflow_state"), "Pending Level 2 Approval")
		self.assertEqual(frappe.db.get_value("Attendance", b, "workflow_state"), "Pending Level 1 Approval")
