"""Overtime follows the Staff Category, also for attendance stored before it was set.

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_overtime_recompute
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, today

from cooperheat.cooperheat import dev_seed
from cooperheat.cooperheat.overtime import recompute_range
from cooperheat.cooperheat.tests.test_org_structure import make_employee
from cooperheat.cooperheat.tests.test_reporting_approvals import cleanup_debris, new_attendance


def hours_of(name):
	return frappe.db.get_value(
		"Attendance",
		name,
		["working_hours", "custom_regular_hours", "custom_ot_hours", "custom_ot_basis"],
		as_dict=True,
	)


class TestOvertimeRecompute(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		cleanup_debris()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")

	def attendance_with_hours(self, first, category, hours=11.14):
		emp = make_employee(
			first,
			custom_staff_category=category,
			reports_to=frappe.db.get_value("Employee", {"user_id": dev_seed.email("anil")}),
		)
		name = new_attendance(emp.name)
		frappe.db.set_value("Attendance", name, "working_hours", hours, update_modified=False)
		return emp, name

	def test_without_a_category_everything_is_regular(self):
		emp, name = self.attendance_with_hours("OtNone", None)
		recompute_range(today(), today(), employee=emp.name, dry_run=False)
		row = hours_of(name)
		self.assertEqual((flt(row.custom_regular_hours), flt(row.custom_ot_hours)), (11.14, 0))
		self.assertEqual(row.custom_ot_basis, "Staff category not set")

	def test_setting_field_staff_moves_hours_above_eight_to_overtime(self):
		emp, name = self.attendance_with_hours("OtField", None)
		doc = frappe.get_doc("Employee", emp.name)
		doc.custom_staff_category = "Field Staff"
		doc.save()  # the category change re-derives the stored hours by itself
		row = hours_of(name)
		self.assertEqual((flt(row.custom_regular_hours), flt(row.custom_ot_hours)), (8.0, 3.14))

	def test_office_staff_never_get_overtime(self):
		emp, name = self.attendance_with_hours("OtOffice", None, 12.0)
		doc = frappe.get_doc("Employee", emp.name)
		doc.custom_staff_category = "Office Staff"
		doc.save()
		row = hours_of(name)
		self.assertEqual((flt(row.custom_regular_hours), flt(row.custom_ot_hours)), (12.0, 0))

	def test_dry_run_counts_without_writing(self):
		emp, name = self.attendance_with_hours("OtDry", "Field Staff", 10.0)
		frappe.db.set_value(
			"Attendance", name, {"custom_ot_hours": 0, "custom_regular_hours": 10.0}, update_modified=False
		)
		res = recompute_range(today(), today(), employee=emp.name, dry_run=True)
		self.assertEqual((res["changed"], res["dry_run"]), (1, True))
		self.assertEqual(flt(hours_of(name).custom_ot_hours), 0)
		res = recompute_range(today(), today(), employee=emp.name, dry_run=False)
		self.assertEqual(flt(hours_of(name).custom_ot_hours), 2.0)
		self.assertEqual(recompute_range(today(), today(), employee=emp.name, dry_run=True)["changed"], 0)
