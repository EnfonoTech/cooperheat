"""Shift-date grouping (pure logic, no database).

    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_work_day
"""

from datetime import date, datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat.work_day import group_by_work_date


def log(kind, when):
	return frappe._dict(log_type=kind, time=datetime.strptime(when, "%Y-%m-%d %H:%M"))


class TestGroupByWorkDate(FrappeTestCase):
	def test_ordinary_day(self):
		g = group_by_work_date([log("IN", "2026-10-07 08:00"), log("OUT", "2026-10-07 17:00")])
		self.assertEqual(list(g), [date(2026, 10, 7)])
		self.assertEqual(len(g[date(2026, 10, 7)]), 2)

	def test_thursday_night_shift_ends_friday_morning_belongs_to_thursday(self):
		# 2026-10-08 is a Thursday
		g = group_by_work_date([log("IN", "2026-10-08 20:00"), log("OUT", "2026-10-09 04:00")])
		self.assertEqual(list(g), [date(2026, 10, 8)])

	def test_friday_night_shift_belongs_to_friday(self):
		g = group_by_work_date([log("IN", "2026-10-09 20:00"), log("OUT", "2026-10-10 04:00")])
		self.assertEqual(list(g), [date(2026, 10, 9)])

	def test_out_after_more_than_16_hours_is_its_own_day(self):
		g = group_by_work_date([log("IN", "2026-10-07 06:00"), log("OUT", "2026-10-08 06:00")])
		self.assertEqual(set(g), {date(2026, 10, 7), date(2026, 10, 8)})

	def test_exactly_16_hours_still_pairs(self):
		g = group_by_work_date([log("IN", "2026-10-07 20:00"), log("OUT", "2026-10-08 12:00")])
		self.assertEqual(list(g), [date(2026, 10, 7)])

	def test_night_shift_then_next_evening_shift(self):
		g = group_by_work_date(
			[
				log("IN", "2026-10-07 20:00"),
				log("OUT", "2026-10-08 04:00"),
				log("IN", "2026-10-08 20:00"),
				log("OUT", "2026-10-09 04:00"),
			]
		)
		self.assertEqual(set(g), {date(2026, 10, 7), date(2026, 10, 8)})
		self.assertEqual(len(g[date(2026, 10, 8)]), 2)

	def test_open_night_shift_has_no_out_yet(self):
		g = group_by_work_date([log("IN", "2026-10-08 20:00")])
		self.assertEqual(list(g), [date(2026, 10, 8)])
		self.assertEqual(g[date(2026, 10, 8)][-1].log_type, "IN")

	def test_several_sites_in_a_day(self):
		g = group_by_work_date(
			[
				log("IN", "2026-10-07 07:00"),
				log("OUT", "2026-10-07 10:00"),
				log("IN", "2026-10-07 11:00"),
				log("OUT", "2026-10-07 14:00"),
				log("IN", "2026-10-07 15:00"),
				log("OUT", "2026-10-07 18:00"),
			]
		)
		self.assertEqual(list(g), [date(2026, 10, 7)])
		self.assertEqual(len(g[date(2026, 10, 7)]), 6)


class TestNightShiftAttendance(FrappeTestCase):
	"""Check-ins -> attendance for shifts that cross midnight (database)."""

	THU, FRI, SAT = "2026-09-24", "2026-09-25", "2026-09-26"  # Thursday, Friday, Saturday

	def setUp(self):
		frappe.set_user("Administrator")
		from cooperheat.cooperheat import dev_seed

		self.emp = frappe.db.get_value("Employee", {"user_id": dev_seed.email("sandbox120")})
		frappe.db.set_value(
			"Employee",
			self.emp,
			{"custom_staff_category": "Field Staff", "holiday_list": "Field Staff 2026"},
			update_modified=False,
		)
		self._wipe()

	def tearDown(self):
		self._wipe()

	def _wipe(self):
		atts = frappe.get_all("Attendance", filters={"employee": self.emp, "attendance_date": ["between", [self.THU, self.SAT]]}, pluck="name")
		if atts:
			frappe.db.delete("Attendance Site Hours", {"parent": ["in", atts]})
			frappe.db.delete("Attendance", {"name": ["in", atts]})
		frappe.db.delete(
			"Employee Checkin",
			{"employee": self.emp, "time": ["between", [self.THU + " 00:00:00", self.SAT + " 23:59:59"]]},
		)
		frappe.db.commit()

	def _punch(self, kind, when):
		frappe.get_doc(
			{"doctype": "Employee Checkin", "employee": self.emp, "log_type": kind, "time": when, "skip_auto_attendance": 0}
		).insert(ignore_permissions=True)

	def _generate(self):
		from cooperheat.cooperheat.api.attendance_gen import generate

		generate(self.THU, self.SAT)
		return {
			a.attendance_date.isoformat(): a
			for a in frappe.get_all(
				"Attendance",
				filters={"employee": self.emp, "attendance_date": ["between", [self.THU, self.SAT]], "docstatus": 1},
				fields=["attendance_date", "working_hours", "custom_regular_hours", "custom_ot_hours", "custom_holiday_ot_hours"],
			)
		}

	def test_thursday_night_into_friday_is_one_thursday_shift_without_weekend_ot(self):
		self._punch("IN", self.THU + " 20:00:00")
		self._punch("OUT", self.FRI + " 04:00:00")
		atts = self._generate()
		self.assertEqual(list(atts), [self.THU])  # no Friday attendance
		a = atts[self.THU]
		self.assertEqual(a.working_hours, 8)
		self.assertEqual((a.custom_regular_hours, a.custom_ot_hours, a.custom_holiday_ot_hours), (8, 0, 0))

	def test_friday_night_shift_is_weekend_overtime(self):
		self._punch("IN", self.FRI + " 20:00:00")
		self._punch("OUT", self.SAT + " 04:00:00")
		atts = self._generate()
		self.assertEqual(list(atts), [self.FRI])
		a = atts[self.FRI]
		self.assertEqual((a.custom_regular_hours, a.custom_ot_hours, a.custom_holiday_ot_hours), (0, 0, 8))

	def test_night_shift_over_8_hours_has_ot_but_no_holiday_ot_when_started_thursday(self):
		self._punch("IN", self.THU + " 18:00:00")
		self._punch("OUT", self.FRI + " 06:00:00")  # 12 hours
		a = self._generate()[self.THU]
		self.assertEqual((a.custom_regular_hours, a.custom_ot_hours, a.custom_holiday_ot_hours), (8, 4, 0))

	def test_open_check_in_before_midnight_blocks_a_second_in(self):
		self._punch("IN", self.THU + " 20:00:00")
		with self.assertRaises(frappe.ValidationError):
			self._punch("IN", self.FRI + " 01:00:00")

	def test_out_after_midnight_needs_no_same_day_in(self):
		self._punch("IN", self.THU + " 22:00:00")
		self._punch("OUT", self.FRI + " 02:00:00")  # would have been refused as an OUT with no IN today
		self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.emp, "time": ["between", [self.THU + " 00:00:00", self.SAT + " 23:59:59"]]}), 2)


class TestAutoCheckout(TestNightShiftAttendance):
	"""A check-in left open for 24 h is closed by the system after 8 h (client, 2026-10-28)."""

	def test_open_check_in_is_closed_after_8_hours_with_a_note(self):
		from cooperheat.cooperheat.auto_checkout import NOTE, close_forgotten_checkins

		self._punch("IN", self.THU + " 07:30:00")
		res = close_forgotten_checkins(now=self.FRI + " 08:00:00", employees=[self.emp])
		self.assertEqual(res["closed"], [self.emp])
		out = frappe.get_all(
			"Employee Checkin",
			filters={"employee": self.emp, "log_type": "OUT", "time": ["between", [self.THU + " 00:00:00", self.SAT + " 23:59:59"]]},
			fields=["time", "activity_log"],
		)
		self.assertEqual([(str(o.time), o.activity_log) for o in out], [(self.THU + " 15:30:00", NOTE)])

	def test_a_check_in_from_this_morning_is_left_open(self):
		from cooperheat.cooperheat.auto_checkout import close_forgotten_checkins

		self._punch("IN", self.THU + " 07:30:00")
		self.assertEqual(close_forgotten_checkins(now=self.THU + " 20:00:00", employees=[self.emp])["closed"], [])

	def test_a_second_tap_seconds_after_the_check_in_is_refused(self):
		self._punch("IN", self.THU + " 07:30:00")
		with self.assertRaises(frappe.ValidationError):
			self._punch("OUT", self.THU + " 07:30:40")

	def test_a_check_in_a_second_after_the_check_out_is_refused(self):
		# production 29 Oct: OUT 19:30:29 + IN 19:30:30 made a 12-hour day count 23 hours
		self._punch("IN", self.THU + " 07:30:00")
		self._punch("OUT", self.THU + " 19:30:29")
		with self.assertRaises(frappe.ValidationError):
			self._punch("IN", self.THU + " 19:30:30")

	def test_closing_yesterday_then_starting_today_still_works(self):
		# the real pattern: forgot to check out, so OUT then IN about 15 seconds apart
		self._punch("IN", self.THU + " 07:30:00")
		self._punch("OUT", self.FRI + " 06:00:00")
		self._punch("IN", self.FRI + " 06:00:15")
		self.assertEqual(
			frappe.db.count("Employee Checkin", {"employee": self.emp, "time": [">=", self.FRI + " 00:00:00"]}), 2
		)
