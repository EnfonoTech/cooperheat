from datetime import date

import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat.setup_calendars import create_work_calendars, holiday_list_name

YEAR = 2031


def weekly_off_weekdays(holiday_list):
	rows = frappe.get_all("Holiday", filters={"parent": holiday_list, "weekly_off": 1}, pluck="holiday_date")
	return {d.weekday() for d in rows}, len(rows)


class TestWorkCalendars(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_office_is_friday_and_saturday_field_is_friday(self):
		create_work_calendars(YEAR)

		office_days, office_count = weekly_off_weekdays(holiday_list_name("Office", YEAR))
		field_days, field_count = weekly_off_weekdays(holiday_list_name("Field", YEAR))
		self.assertEqual(office_days, {4, 5})  # Friday, Saturday
		self.assertEqual(field_days, {4})
		self.assertGreater(office_count, field_count)

	def test_national_day_is_a_holiday(self):
		create_work_calendars(YEAR)
		self.assertTrue(
			frappe.db.exists(
				"Holiday", {"parent": holiday_list_name("Field", YEAR), "holiday_date": date(YEAR, 9, 23)}
			)
		)

	def test_shift_types_point_at_their_lists(self):
		create_work_calendars(YEAR)
		for kind in ("Office", "Field"):
			shift = frappe.get_doc("Shift Type", f"{kind} Shift")
			self.assertEqual(shift.enable_auto_attendance, 0)

	def test_rerun_creates_nothing(self):
		create_work_calendars(YEAR)
		self.assertEqual(create_work_calendars(YEAR), [])
