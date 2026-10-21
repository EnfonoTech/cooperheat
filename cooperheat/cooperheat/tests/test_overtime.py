"""Overtime rules (pure) and attendance wiring.

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_overtime
"""

from datetime import datetime

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from cooperheat.cooperheat import dev_seed
from cooperheat.cooperheat.overtime import FIELD, OFFICE, split_hours


class TestSplitHours(FrappeTestCase):
	def test_field_day_within_8_hours_has_no_ot(self):
		self.assertEqual(split_hours(8, FIELD, False)["ot"], 0)

	def test_field_day_over_8_hours(self):
		out = split_hours(11.5, FIELD, False)
		self.assertEqual((out["regular"], out["ot"], out["holiday_ot"]), (8, 3.5, 0))

	def test_field_day_capped_at_16_hours(self):
		out = split_hours(20, FIELD, False)
		self.assertEqual((out["regular"], out["ot"]), (8, 8))

	def test_field_weekend_or_public_holiday_is_all_holiday_ot(self):
		out = split_hours(10, FIELD, True)
		self.assertEqual((out["regular"], out["ot"], out["holiday_ot"]), (0, 0, 10))

	def test_field_holiday_capped_at_16_hours(self):
		self.assertEqual(split_hours(18, FIELD, True)["holiday_ot"], 16)

	def test_office_never_gets_ot_even_on_a_holiday_or_long_day(self):
		for holiday in (False, True):
			out = split_hours(15, OFFICE, holiday)
			self.assertEqual((out["ot"], out["holiday_ot"]), (0, 0))
			self.assertEqual(out["regular"], 15)

	def test_unknown_category_gets_no_ot(self):
		out = split_hours(12, None, False)
		self.assertEqual((out["ot"], out["holiday_ot"]), (0, 0))
		self.assertIn("not set", out["basis"])

	def test_zero_and_negative_hours(self):
		self.assertEqual(split_hours(0, FIELD, False)["regular"], 0)
		self.assertEqual(split_hours(-3, FIELD, False)["regular"], 0)


class TestAttendanceOvertime(FrappeTestCase):
	"""Attendance rows pick up the overtime fields through validate."""

	def setUp(self):
		frappe.set_user("Administrator")

	def _attendance(self, category, hours, day):
		emp = frappe.db.get_value("Employee", {"user_id": dev_seed.email("sandbox119")})
		frappe.db.set_value(
			"Employee",
			emp,
			{
				"custom_staff_category": category,
				"holiday_list": "Field Staff 2026" if category == FIELD else "Office Staff 2026",
			},
			update_modified=False,
		)
		doc = frappe.get_doc(
			{
				"doctype": "Attendance",
				"employee": emp,
				"attendance_date": day,
				"status": "Present",
				"working_hours": hours,
				"company": dev_seed.COMPANY,
			}
		)
		from cooperheat.cooperheat.overtime import apply_to_doc

		apply_to_doc(doc)
		return doc

	def test_office_staff_attendance_has_no_ot(self):
		doc = self._attendance(OFFICE, 12, "2026-10-07")  # Wednesday
		self.assertEqual(doc.custom_ot_hours, 0)
		self.assertEqual(doc.custom_regular_hours, 12)

	def test_field_staff_wednesday_overtime(self):
		doc = self._attendance(FIELD, 11, "2026-10-07")
		self.assertEqual((doc.custom_regular_hours, doc.custom_ot_hours), (8, 3))

	def test_field_staff_friday_is_holiday_overtime(self):
		doc = self._attendance(FIELD, 9, "2026-10-09")  # a Friday: weekly off in the Field calendar
		self.assertEqual(
			(doc.custom_regular_hours, doc.custom_ot_hours, doc.custom_holiday_ot_hours), (0, 0, 9)
		)

	def test_field_staff_saturday_is_a_normal_day(self):
		doc = self._attendance(FIELD, 9, "2026-10-10")  # Saturday: only the office is off
		self.assertEqual(
			(doc.custom_regular_hours, doc.custom_ot_hours, doc.custom_holiday_ot_hours), (8, 1, 0)
		)
