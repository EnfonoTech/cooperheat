# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import calendar
from datetime import date

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

MONTHS = [
	"January", "February", "March", "April", "May", "June",
	"July", "August", "September", "October", "November", "December",
]

EARNING_FIELDS = [
	"basic", "housing_allowance", "transport_allowance", "living_allowance",
	"service_allowance", "driving_allowance", "merit_award", "aramco_certification",
	"supervisor_allowance", "education_allowance", "rso_allowance", "rpp_allowance",
	"other_allowance",
]

PRORATED_EARNING_FIELDS = [f for f in EARNING_FIELDS if f != "basic"]

DEDUCTION_FIELDS = [
	"general_advance", "housing_advance", "housing_deduction",
	"transport_deduction", "education_deduction", "retention_deduction",
	"other_deduction",
]

SPECIAL_EARNINGS = [
	"others", "bonus", "expenses", "air_fare",
	"vacation_pay", "gratuity", "retention",
]

# Fields copied from the Compensation record to the Payroll Sheet.
COMPENSATION_COPY_FIELDS = EARNING_FIELDS + DEDUCTION_FIELDS + [
	"pay_batch", "employee_category", "currency",
]


def month_index(month_name):
	try:
		return MONTHS.index(month_name) + 1
	except ValueError:
		return None


def days_in_month(year, month_name):
	m = month_index(month_name)
	if not (year and m):
		return 30
	return calendar.monthrange(int(year), m)[1]


class PayrollSheet(Document):
	def validate(self):
		self.set_days_in_month()
		self.apply_proration()
		self.calculate_overtime()
		self.calculate_gosi()
		self.calculate_totals()

	def apply_proration(self):
		"""Re-prorate earnings from the linked Compensation based on worked_days.

		Idempotent: always reads full values from Compensation and writes
		prorated values, so editing worked_days (or anything else) and saving
		always produces consistent amounts. Deductions are NOT touched here —
		they're a mix of Compensation fixed amounts and Excel overrides.
		"""
		if not self.compensation:
			return
		try:
			comp = frappe.get_cached_doc("Employee Compensation", self.compensation)
		except frappe.DoesNotExistError:
			return

		worked = flt(self.worked_days)
		dim = flt(self.days_in_month) or 30
		factor = min(worked, dim) / dim if worked > 0 and dim > 0 else 0.0

		# Basic is fixed (not prorated)
		self.basic = self.round_amount(flt(comp.basic))
		for f in PRORATED_EARNING_FIELDS:
			self.set(f, self.round_amount(flt(comp.get(f)) * factor))

	def before_save(self):
		self.validate()

	def on_submit(self):
		if self.status == "Draft":
			self.db_set("status", "Submitted")

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	# --- helpers -----------------------------------------------------------

	def get_settings(self):
		return frappe.get_cached_doc("Pay Sheet Settings")

	def set_days_in_month(self):
		self.days_in_month = days_in_month(self.year, self.month)

	def round_amount(self, value):
		settings = self.get_settings()
		v = flt(value)
		return flt(v, 2) if settings.round_amounts else v

	# --- calculations ------------------------------------------------------

	def calculate_overtime(self):
		settings = self.get_settings()
		mwh = flt(settings.monthly_working_hours) or 240.0
		basic = flt(self.basic)
		hourly = basic / mwh if mwh else 0.0

		self.normal_ot_amount = self.round_amount(
			hourly * flt(settings.normal_ot_multiplier) * flt(self.normal_ot_hours)
		)
		self.holiday_ot_amount = self.round_amount(
			hourly * flt(settings.holiday_ot_multiplier) * flt(self.holiday_ot_hours)
		)
		self.travel_ot_amount = self.round_amount(
			hourly * flt(settings.travel_ot_multiplier) * flt(self.travel_ot_hours)
		)
		self.total_ot_amount = self.round_amount(
			flt(self.normal_ot_amount)
			+ flt(self.holiday_ot_amount)
			+ flt(self.travel_ot_amount)
		)

	def calculate_gosi(self):
		settings = self.get_settings()
		applicable = (settings.gosi_applicable_category or "Saudi").strip()
		if (self.employee_category or "").strip() != applicable:
			self.gosi = 0
			return
		base = flt(self.basic) + flt(self.housing_allowance)
		self.gosi = self.round_amount(base * flt(settings.gosi_rate_percent) / 100.0)

	def calculate_totals(self):
		earnings_total = sum(flt(self.get(f)) for f in EARNING_FIELDS)
		special_total = sum(flt(self.get(f)) for f in SPECIAL_EARNINGS)
		self.total_earnings = self.round_amount(
			earnings_total + flt(self.total_ot_amount) + special_total
		)
		self.total_deduction = self.round_amount(
			flt(self.gosi) + sum(flt(self.get(f)) for f in DEDUCTION_FIELDS)
		)
		self.net_payable = self.round_amount(
			flt(self.total_earnings) - flt(self.total_deduction)
		)


# ---------------------------------------------------------------------------
# Whitelisted helpers used by the bulk import page and the JS form
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_employee_compensation(employee, posting_date=None):
	"""Return the Employee Compensation that applies for an employee on a date.

	Picks the latest active record with ``from_date <= posting_date``.

	Shape:
	    {
	      "compensation": "<name>",
	      "values": {fieldname: value, ...},
	    }
	"""
	if not employee:
		return {}
	pd = getdate(posting_date) if posting_date else getdate()
	comp_name = frappe.db.get_value(
		"Employee Compensation",
		filters={
			"employee": employee,
			"is_active": 1,
			"from_date": ["<=", pd],
		},
		fieldname="name",
		order_by="from_date desc",
	)
	if not comp_name:
		return {}

	comp = frappe.get_doc("Employee Compensation", comp_name)
	values = {f: flt(comp.get(f)) for f in EARNING_FIELDS + DEDUCTION_FIELDS}
	values["pay_batch"] = comp.pay_batch
	values["employee_category"] = comp.employee_category
	values["currency"] = comp.currency
	return {"compensation": comp.name, "values": values}


@frappe.whitelist()
def create_salary_slip(payroll_sheet):
	"""Create an ERPNext Salary Slip from a submitted Payroll Sheet.

	Uses the Salary Component mapping from Pay Sheet Settings. Auto-creates
	a Salary Structure Assignment for the employee if none exists yet, so
	ERPNext's 'Please assign a Salary Structure first' error doesn't block.
	"""
	doc = frappe.get_doc("Payroll Sheet", payroll_sheet)
	if doc.docstatus != 1:
		frappe.throw(_("Payroll Sheet must be submitted first."))

	month_num = month_index(doc.month)
	if not month_num:
		frappe.throw(_("Invalid month."))
	dim = days_in_month(doc.year, doc.month)
	start_date = date(int(doc.year), month_num, 1)
	end_date = date(int(doc.year), month_num, dim)

	settings = frappe.get_cached_doc("Pay Sheet Settings")
	mapping = _mapping_from_settings(settings)
	if not mapping:
		frappe.throw(_(
			"No Salary Component mapping configured. Open Pay Sheet Settings and "
			"click 'Actions → Setup Defaults' first."
		))

	ssa_name = _ensure_salary_structure_assignment(
		employee=doc.employee,
		company=doc.company,
		start_date=start_date,
		settings=settings,
	)
	slip_structure = frappe.db.get_value("Salary Structure Assignment", ssa_name, "salary_structure")

	slip = frappe.new_doc("Salary Slip")
	slip.employee = doc.employee
	slip.salary_structure = slip_structure
	slip.payroll_frequency = "Monthly"
	slip.posting_date = doc.posting_date or end_date
	slip.start_date = start_date
	slip.end_date = end_date
	slip.company = doc.company
	# We've already prorated amounts ourselves based on worked_days. Setting
	# payment_days = total_working_days prevents ERPNext from prorating again.
	slip.payment_days = dim
	slip.total_working_days = dim
	slip.leave_without_pay = 0
	slip.absent_days = 0
	slip.currency = doc.currency
	slip.remark = (doc.remarks or "") + f"\nGenerated from Payroll Sheet {doc.name}"

	for field, (component, ctype) in mapping.items():
		amount = flt(doc.get(field))
		if not amount:
			continue
		_ensure_salary_component(component, ctype)
		table = "earnings" if ctype == "Earning" else "deductions"
		slip.append(table, {
			"salary_component": component,
			"amount": amount,
		})

	slip.flags.ignore_permissions = True
	slip.insert()
	return slip.name


def _mapping_from_settings(settings):
	"""Return {payroll_field: (salary_component, component_type)} from settings."""
	result = {}
	for row in (settings.component_mapping or []):
		if row.payroll_field and row.salary_component and row.component_type:
			result[row.payroll_field] = (row.salary_component, row.component_type)
	return result


def _ensure_salary_component(name, component_type):
	if frappe.db.exists("Salary Component", name):
		return
	sc = frappe.new_doc("Salary Component")
	sc.salary_component = name
	sc.salary_component_abbr = "".join(w[0] for w in name.split() if w).upper()[:10]
	sc.type = component_type
	# depends_on_payment_days=0 so HRMS does not re-scale our amounts.
	# Proration is already applied on the Payroll Sheet based on worked_days.
	sc.depends_on_payment_days = 0
	sc.flags.ignore_permissions = True
	sc.insert()


def _ensure_salary_structure_assignment(employee, company, start_date, settings):
	"""Make sure the employee has a submitted Salary Structure Assignment
	with from_date <= start_date. Auto-create one using the default structure
	if needed."""
	existing = frappe.db.get_value(
		"Salary Structure Assignment",
		filters={
			"employee": employee,
			"docstatus": 1,
			"from_date": ["<=", start_date],
		},
		fieldname="name",
		order_by="from_date desc",
	)
	if existing:
		return existing

	structure = settings.default_salary_structure
	if not structure:
		frappe.throw(_(
			"No Default Salary Structure set in Pay Sheet Settings. "
			"Open Pay Sheet Settings and click 'Actions → Setup Defaults'."
		))

	ssa = frappe.new_doc("Salary Structure Assignment")
	ssa.employee = employee
	ssa.salary_structure = structure
	ssa.company = company
	ssa.from_date = start_date
	ssa.base = flt(frappe.db.get_value("Payroll Sheet", {
		"employee": employee, "docstatus": 1,
	}, "basic")) or 0
	ssa.flags.ignore_permissions = True
	ssa.insert()
	ssa.submit()
	return ssa.name
