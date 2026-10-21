"""Assign Shift from the Employee form and the staff-category importer.

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_shift_tools
"""

import csv
import tempfile

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from cooperheat.cooperheat import shift_tools, staff_import
from cooperheat.cooperheat.setup_calendars import create_work_calendars, setup_shifts
from cooperheat.cooperheat.tests.test_work_schedule import make_employee


class TestShiftTools(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		create_work_calendars(frappe.utils.getdate(today()).year)
		setup_shifts()

	def test_assign_shift_creates_submitted_assignment(self):
		e = make_employee("Assign")
		name = shift_tools.assign_shift(e.name, "Office Shift 2", today(), add_days(today(), 6))
		row = frappe.db.get_value(
			"Shift Assignment", name, ["docstatus", "status", "shift_type"], as_dict=True
		)
		self.assertEqual((row.docstatus, row.status, row.shift_type), (1, "Active", "Office Shift 2"))
		self.assertEqual(shift_tools.get_employee_shifts(e.name)[0].name, name)

	def test_end_before_start_is_refused(self):
		e = make_employee("BadDates")
		with self.assertRaises(frappe.ValidationError):
			shift_tools.assign_shift(e.name, "Office Shift", today(), add_days(today(), -1))

	def test_non_hr_cannot_assign(self):
		e = make_employee("NoHr")
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				shift_tools.assign_shift(e.name, "Office Shift", today())
		finally:
			frappe.set_user("Administrator")

	def test_staff_import_dry_run_then_apply(self):
		e = make_employee("Imp")
		with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
			w = csv.writer(f)
			w.writerow(["employee", "category"])
			w.writerow([e.name, "Field"])
			w.writerow(["NO-SUCH-EMP", "Office"])
			w.writerow([e.name, "Bogus"])
		report = staff_import.load(f.name)
		self.assertEqual(len(report["updated"]), 1)
		self.assertEqual(len(report["problems"]), 2)
		self.assertFalse(frappe.db.get_value("Employee", e.name, "custom_staff_category"))
		staff_import.load(f.name, dry_run=0)
		self.assertEqual(frappe.db.get_value("Employee", e.name, "custom_staff_category"), "Field Staff")
		self.assertEqual(frappe.db.get_value("Employee", e.name, "default_shift"), "Field Shift")
