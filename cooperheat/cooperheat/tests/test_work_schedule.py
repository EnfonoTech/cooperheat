"""Office / Field staff category drives holiday list and default shift.

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_work_schedule
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate, nowdate, today

from cooperheat.cooperheat import dev_seed
from cooperheat.cooperheat.setup_calendars import create_work_calendars, holiday_list_name
from cooperheat.cooperheat.work_schedule import roll_over_calendars


def make_employee(first, **values):
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": first,
			"last_name": "WsTest",
			"gender": "Male",
			"date_of_birth": "1995-05-05",
			"date_of_joining": today(),
			"company": dev_seed.COMPANY,
			"status": "Active",
			**values,
		}
	).insert(ignore_permissions=True)


class TestWorkSchedule(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.year = getdate(nowdate()).year
		create_work_calendars(cls.year)

	def test_office_staff_gets_office_calendar_and_shift(self):
		e = make_employee("Office", custom_staff_category="Office Staff")
		self.assertEqual(e.holiday_list, holiday_list_name("Office", self.year))
		self.assertEqual(e.default_shift, "Office Shift")

	def test_field_staff_gets_field_calendar_and_shift(self):
		e = make_employee("Field", custom_staff_category="Field Staff")
		self.assertEqual(e.holiday_list, holiday_list_name("Field", self.year))
		self.assertEqual(e.default_shift, "Field Shift")

	def test_chosen_shift_is_kept(self):
		e = make_employee("Day", custom_staff_category="Field Staff", default_shift="Day Shift")
		self.assertEqual(e.default_shift, "Day Shift")
		self.assertEqual(e.holiday_list, holiday_list_name("Field", self.year))

	def test_office_shift_without_category_sets_category(self):
		e = make_employee("ShiftOnly", default_shift="Office Shift")
		self.assertEqual(e.custom_staff_category, "Office Staff")
		self.assertEqual(e.holiday_list, holiday_list_name("Office", self.year))

	def test_rollover_moves_stale_calendar(self):
		e = make_employee("Stale", custom_staff_category="Field Staff")
		frappe.db.set_value("Employee", e.name, "holiday_list", None)
		roll_over_calendars()
		self.assertEqual(
			frappe.db.get_value("Employee", e.name, "holiday_list"), holiday_list_name("Field", self.year)
		)

	def test_new_employee_defaults_to_main_pay_batch(self):
		if not frappe.db.exists("Pay Batch", "Main"):
			frappe.get_doc({"doctype": "Pay Batch", "batch_name": "Main"}).insert(ignore_permissions=True)
		e = make_employee("Batch")
		self.assertEqual(e.custom_pay_batch, "Main")
