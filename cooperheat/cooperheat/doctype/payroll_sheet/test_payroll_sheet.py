# Copyright (c) 2026, enfonotechnology and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

SETTINGS = frappe._dict(
	monthly_working_hours=240,
	normal_ot_multiplier=1.5,
	holiday_ot_multiplier=2.0,
	travel_ot_multiplier=1.5,
	round_amounts=1,
	gosi_applicable_category="Saudi",
	gosi_rate_percent=0,
)

COMPENSATION = frappe._dict(basic=3000, housing_allowance=750)


def fake_cached_doc(doctype, name=None):
	if doctype == "Pay Sheet Settings":
		return SETTINGS
	if doctype == "Employee Compensation":
		return COMPENSATION
	raise frappe.DoesNotExistError


def make_sheet(**values):
	"""An unsaved Payroll Sheet for September 2026 (30 days)."""
	doc = frappe.get_doc({"doctype": "Payroll Sheet", "year": 2026, "month": "September", **values})
	with patch("frappe.get_cached_doc", side_effect=fake_cached_doc):
		doc.validate()
	return doc


class TestPayrollSheetOvertime(FrappeTestCase):
	def test_full_month_uses_basic(self):
		doc = make_sheet(compensation="EC-TEST", worked_days=30, normal_ot_hours=10)
		self.assertEqual(doc.basic, 3000)
		self.assertEqual(doc.normal_ot_amount, 187.5)  # 3000 / 240 * 1.5 * 10

	def test_unpaid_leave_does_not_reduce_ot_rate(self):
		# 5 unpaid days: basic is prorated, OT still uses the full 3000.
		doc = make_sheet(
			compensation="EC-TEST",
			worked_days=25,
			normal_ot_hours=10,
			holiday_ot_hours=8,
			travel_ot_hours=4,
		)
		self.assertEqual(doc.basic, 2500)
		self.assertEqual(doc.normal_ot_amount, 187.5)  # 3000 / 240 * 1.5 * 10
		self.assertEqual(doc.holiday_ot_amount, 200)  # 3000 / 240 * 2 * 8
		self.assertEqual(doc.travel_ot_amount, 75)  # 3000 / 240 * 1.5 * 4
		self.assertEqual(doc.total_ot_amount, 462.5)

	def test_without_compensation_uses_sheet_basic(self):
		doc = make_sheet(basic=2400, worked_days=20, normal_ot_hours=10)
		self.assertEqual(doc.normal_ot_amount, 150)  # 2400 / 240 * 1.5 * 10

	def test_zero_worked_days_pays_no_ot(self):
		doc = make_sheet(compensation="EC-TEST", worked_days=0, normal_ot_hours=10)
		self.assertEqual(doc.normal_ot_amount, 0)
		self.assertEqual(doc.total_ot_amount, 0)
