"""Site Hours: Payable from the check-ins, Billable by tick box or by hand (client call 2026-10-25).

    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_billable_hours
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat.overrides.attendance import _apply_billable, _recalculate_site_hours_from_times


def row(**kw):
	base = dict(idx=1, payroll_hours=0, hours=0, is_billable=0, check_in_time=None, check_out_time=None)
	base.update(kw)
	return frappe._dict(base)


def att(*rows):
	return frappe._dict(docstatus=1, custom_site_hours=list(rows), working_hours=0, in_time=None, out_time=None)


class TestBillableTickBox(FrappeTestCase):
	def test_ticked_copies_payable(self):
		r = row(payroll_hours=14.95, hours=3, is_billable=1)
		_apply_billable(r)
		self.assertEqual((r.payroll_hours, r.hours), (14, 14))  # whole hours (client, 28 Oct)

	def test_not_ticked_keeps_typed_billable(self):
		r = row(payroll_hours=14.95, hours=10)
		_apply_billable(r)
		self.assertEqual(r.hours, 10)

	def test_negative_billable_refused(self):
		with self.assertRaises(frappe.ValidationError):
			_apply_billable(row(payroll_hours=8, hours=-1))


class TestPayableFromCheckins(FrappeTestCase):
	def test_checkin_hours_go_to_payable_not_billable(self):
		r = row(check_in_time="2026-10-25 17:55:10", check_out_time="2026-10-26 06:15:01")
		doc = att(r)
		_recalculate_site_hours_from_times(doc)
		self.assertEqual(r.payroll_hours, 12)  # 12.33 h worked counts as 12
		self.assertEqual(r.hours, 0)
		self.assertEqual(doc.working_hours, 12)

	def test_approver_payable_correction_is_kept_on_save(self):
		# the supervisor's case of 26 Oct: 12.33 from check-ins, corrected to 14
		r = row(check_in_time="2026-10-25 17:55:10", check_out_time="2026-10-26 06:15:01", payroll_hours=14, is_billable=1)
		doc = att(r)
		_recalculate_site_hours_from_times(doc)
		self.assertEqual(r.payroll_hours, 14)
		self.assertEqual(r.hours, 14)
		self.assertEqual(doc.working_hours, 14)

	def test_payable_above_billable_allowed_on_any_site(self):
		r = row(check_in_time="2026-10-25 08:00:00", check_out_time="2026-10-25 18:00:00", payroll_hours=10, hours=6)
		doc = att(r)
		_recalculate_site_hours_from_times(doc)  # the old "Payable cannot exceed Billable" rule is gone
		self.assertEqual((r.payroll_hours, r.hours, doc.working_hours), (10, 6, 10))


class TestWholeHours(FrappeTestCase):
	def test_decimals_are_dropped_not_rounded(self):
		from cooperheat.cooperheat.overrides.attendance import whole_hours

		self.assertEqual([whole_hours(h) for h in (12.7, 12.3, 12.0, 11.999999, 0.4)], [12, 12, 12, 12, 0])
