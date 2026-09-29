# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Tests for the Payroll Import salary slip pipeline (create -> submit -> email).

Run on a dev site that has ERPNext + HRMS:

	bench --site <site> run-tests --module cooperheat.cooperheat.doctype.payroll_import.test_slip_dispatch

Nothing here sends mail (Email Queue.send is a no-op under tests) and nothing renders a PDF
(frappe.attach_print is patched: printing writes an Access Log and commits). The integration
tests patch frappe.db.commit so the whole class rolls back at the end.
"""

import unittest
import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, now_datetime

from cooperheat.cooperheat.doctype.payroll_import import slip_dispatch as sd
from cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet import MONTHS

FAKE_PDF = {"fname": "Payslip-test.pdf", "fcontent": b"%PDF-1.4 test"}


def _d(**kw):
	return frappe._dict(**kw)


def _ctx(**kw):
	base = dict(
		sheets={}, slips={}, by_period={}, employees={}, queues={}, latest_queue={}, recipient={}, row_slip={},
	)
	base.update(kw)
	return frappe._dict(base)


def _row(**kw):
	base = dict(
		name="row1", employee="E1", code="C1", employee_name="Emp One", payroll_sheet="PS1", row_status="Created",
		message="", salary_slip="", slip_status="", slip_error="", email_status="", email_to="",
		email_sent_on=None, email_error="", email_queue="",
	)
	base.update(kw)
	return frappe._dict(base)


class TestEmployeeEmail(FrappeTestCase):
	def test_preferred_then_company_then_personal_then_login(self):
		emp = _d(prefered_email="pref@x.com", company_email="co@x.com", personal_email="me@x.com", user_id="u@x.com")
		self.assertEqual(sd.employee_email(emp), "pref@x.com")
		emp.prefered_email = ""
		self.assertEqual(sd.employee_email(emp), "co@x.com")
		emp.company_email = None
		self.assertEqual(sd.employee_email(emp), "me@x.com")
		emp.personal_email = ""
		self.assertEqual(sd.employee_email(emp), "u@x.com")

	def test_invalid_addresses_are_skipped_not_used(self):
		emp = _d(prefered_email="not-an-email", company_email="", personal_email="ok@x.com", user_id="Administrator")
		self.assertEqual(sd.employee_email(emp), "ok@x.com")
		self.assertEqual(sd.employee_email(_d(user_id="Administrator", personal_email="nope")), "")
		self.assertEqual(sd.employee_email(_d()), "")


class TestRowState(FrappeTestCase):
	"""_state() derives the row from Payroll Sheet / Salary Slip / Email Queue - no database needed."""

	def sheet(self, docstatus=1, slip=None):
		return _d(name="PS1", docstatus=docstatus, salary_slip=slip, employee="E1", month="September", year=2026,
			net_payable=100, currency="SAR")

	def slip(self, name="SS1", docstatus=1):
		return _d(name=name, docstatus=docstatus, employee="E1", net_pay=100)

	def emp(self, **kw):
		base = dict(name="E1", employee_name="Emp One", department=None, prefered_email="e1@x.com")
		base.update(kw)
		return _d(**base)

	def state(self, row, **ctx_kw):
		return sd._state(row, _ctx(**ctx_kw))

	def test_import_error_row_has_nothing(self):
		st = self.state(_row(payroll_sheet="", row_status="Error"))
		self.assertEqual(st["slip_status"], "")
		self.assertEqual(st["email_status"], "")

	def test_slip_status_follows_the_documents(self):
		row = _row()
		cases = [
			(self.sheet(docstatus=0), None, "Sheet Draft"),
			(self.sheet(docstatus=2), None, "Sheet Cancelled"),
			(self.sheet(docstatus=1), None, "Not Created"),
			(self.sheet(docstatus=1, slip="SS1"), self.slip(docstatus=0), "Draft"),
			(self.sheet(docstatus=1, slip="SS1"), self.slip(docstatus=1), "Submitted"),
			(self.sheet(docstatus=1, slip="SS1"), self.slip(docstatus=2), "Cancelled"),
		]
		for sheet, slip, expected in cases:
			ctx = dict(sheets={"PS1": sheet}, employees={"E1": self.emp()}, row_slip={"row1": slip} if slip else {})
			self.assertEqual(self.state(row, **ctx)["slip_status"], expected, expected)

	def test_missing_address_shows_as_skipped_once_a_slip_exists(self):
		ctx = dict(sheets={"PS1": self.sheet(slip="SS1")}, row_slip={"row1": self.slip(docstatus=0)},
			employees={"E1": self.emp(prefered_email="")})
		st = self.state(_row(), **ctx)
		self.assertEqual((st["email_status"], st["email_to"]), ("Skipped", ""))
		self.assertIn("No email address", st["email_error"])
		# fix the address and the skip goes away by itself
		ctx["employees"]["E1"].company_email = "fixed@x.com"
		st = self.state(_row(email_status="Skipped"), **ctx)
		self.assertEqual((st["email_status"], st["email_to"]), ("", "fixed@x.com"))

	def test_address_is_shown_before_any_slip_exists(self):
		ctx = dict(sheets={"PS1": self.sheet()}, employees={"E1": self.emp()})
		st = self.state(_row(), **ctx)
		self.assertEqual((st["slip_status"], st["email_to"], st["email_status"]), ("Not Created", "e1@x.com", ""))
		ctx["employees"]["E1"] = self.emp(prefered_email="")
		st = self.state(_row(), **ctx)
		self.assertEqual((st["email_to"], st["email_status"]), ("", ""))  # flagged in the summary, not as Skipped

	def submitted_ctx(self, **extra):
		ctx = dict(sheets={"PS1": self.sheet(slip="SS1")}, row_slip={"row1": self.slip()},
			employees={"E1": self.emp()})
		ctx.update(extra)
		return ctx

	def test_email_queue_status_is_mirrored(self):
		modified = now_datetime()
		row = _row(email_queue="Q1", email_to="e1@x.com", email_status="Queued")
		q = lambda **kw: _d(name="Q1", status="Not Sent", error="", modified=modified, retry=0, **kw)  # noqa: E731

		st = self.state(row, **self.submitted_ctx(queues={"Q1": q()}))
		self.assertEqual((st["email_status"], st["email_error"]), ("Queued", ""))

		st = self.state(row, **self.submitted_ctx(queues={"Q1": q()}))
		self.assertEqual(st["email_status"], "Queued")

		retrying = _d(name="Q1", status="Not Sent", error="Traceback\nSMTPServerDisconnected: gone", modified=modified, retry=2)
		st = self.state(row, **self.submitted_ctx(queues={"Q1": retrying}))
		self.assertEqual(st["email_status"], "Queued")
		self.assertIn("Retry 2", st["email_error"])
		self.assertIn("SMTPServerDisconnected: gone", st["email_error"])

		sent = _d(name="Q1", status="Sent", error="", modified=modified, retry=0)
		st = self.state(row, **self.submitted_ctx(queues={"Q1": sent}))
		self.assertEqual((st["email_status"], st["email_sent_on"], st["email_to"]), ("Sent", modified, "e1@x.com"))

		failed = _d(name="Q1", status="Error", error="Traceback\nsmtplib.SMTPRecipientsRefused: bad", modified=modified, retry=3)
		st = self.state(row, **self.submitted_ctx(queues={"Q1": failed}))
		self.assertEqual(st["email_status"], "Failed")
		self.assertEqual(st["email_error"], "smtplib.SMTPRecipientsRefused: bad")

	def test_mail_sent_by_hrms_on_submit_is_adopted(self):
		modified = now_datetime()
		hrms_mail = _d(name="Q9", status="Sent", error="", modified=modified, retry=0)
		st = self.state(
			_row(),
			**self.submitted_ctx(queues={"Q9": hrms_mail}, latest_queue={"SS1": hrms_mail}, recipient={"Q9": "sent-to@x.com"}),
		)
		self.assertEqual((st["email_status"], st["email_queue"], st["email_to"]), ("Sent", "Q9", "sent-to@x.com"))

	def test_a_failed_attempt_is_not_overwritten_by_an_older_queue_entry(self):
		old = _d(name="Q1", status="Sent", error="", modified=now_datetime(), retry=0)
		row = _row(email_status="Failed", email_error="PDF failed", email_to="e1@x.com")
		st = self.state(row, **self.submitted_ctx(latest_queue={"SS1": old}, queues={"Q1": old}))
		self.assertEqual((st["email_status"], st["email_error"]), ("Failed", "PDF failed"))

	def test_purged_queue_entries(self):
		sent_row = _row(email_queue="GONE", email_status="Sent", email_to="e1@x.com", email_sent_on=now_datetime())
		self.assertEqual(self.state(sent_row, **self.submitted_ctx())["email_status"], "Sent")
		queued_row = _row(email_queue="GONE", email_status="Queued", email_to="e1@x.com")
		st = self.state(queued_row, **self.submitted_ctx())
		self.assertEqual(st["email_status"], "Failed")
		self.assertEqual(st["email_queue"], "")  # cleared, so it can be sent again

	def test_slip_error_only_while_the_step_is_pending(self):
		ctx = dict(sheets={"PS1": self.sheet()}, employees={"E1": self.emp()})
		self.assertEqual(self.state(_row(slip_error="boom"), **ctx)["slip_error"], "boom")
		ctx = self.submitted_ctx()
		self.assertEqual(self.state(_row(slip_error="boom"), **ctx)["slip_error"], "")


class TestEligibility(FrappeTestCase):
	def test_each_step_only_takes_what_it_should(self):
		E = sd._eligible
		st = lambda slip, mail="": {"slip_status": slip, "email_status": mail}  # noqa: E731
		none, resend = _d(), _d(resend_all=1)

		self.assertTrue(E("create_slips", st("Not Created"), none))
		self.assertFalse(E("create_slips", st("Sheet Draft"), none))
		self.assertTrue(E("create_slips", st("Sheet Draft"), _d(submit_sheets=1)))
		self.assertFalse(E("create_slips", st("Cancelled"), _d(submit_sheets=1)))
		self.assertFalse(E("create_slips", st("Draft"), none))

		self.assertTrue(E("submit_slips", st("Draft"), none))
		self.assertFalse(E("submit_slips", st("Submitted"), none))
		self.assertFalse(E("submit_slips", st("Not Created"), none))

		self.assertFalse(E("send_emails", st("Draft"), none))
		for mail in ("", "Failed", "Skipped"):
			self.assertTrue(E("send_emails", st("Submitted", mail), none), mail)
		self.assertFalse(E("send_emails", st("Submitted", "Sent"), none))
		self.assertTrue(E("send_emails", st("Submitted", "Sent"), resend))
		self.assertFalse(E("send_emails", st("Submitted", "Queued"), resend))  # never double-queued


class TestMailingSwitch(FrappeTestCase):
	def test_flag_is_set_inside_and_restored_after(self):
		frappe.flags.pop("via_payroll_entry", None)
		with sd._mailing_is_separate():
			self.assertTrue(frappe.flags.via_payroll_entry)
		self.assertFalse(frappe.flags.via_payroll_entry)

		frappe.flags.via_payroll_entry = "before"
		try:
			with sd._mailing_is_separate():
				pass
			self.assertEqual(frappe.flags.via_payroll_entry, "before")
			with self.assertRaises(ValueError), sd._mailing_is_separate():
				raise ValueError
			self.assertEqual(frappe.flags.via_payroll_entry, "before")
		finally:
			frappe.flags.pop("via_payroll_entry", None)


class TestPipeline(FrappeTestCase):
	"""create -> submit -> email against real documents (one transaction, rolled back)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.commit_patch = patch.object(frappe.db, "commit")
		cls.commit_patch.start()
		cls.addClassCleanup(cls.commit_patch.stop)

		# the current month, in a company that has a Fiscal Year for it (HRMS needs one to build a slip)
		cls.today = getdate()
		cls.month, cls.year = MONTHS[cls.today.month - 1], cls.today.year
		cls.company = next((c for c in frappe.get_all("Company", pluck="name") if cls.has_fiscal_year(c)), None)
		if not cls.company:
			raise unittest.SkipTest("needs a Company with a Fiscal Year covering this month")
		cls.currency = frappe.get_cached_value("Company", cls.company, "default_currency")

		# HRMS refuses to build a slip for an employee with no holiday list (own or the company's)
		cls.holiday_list = f"ZZ Test Holidays {uuid.uuid4().hex[:6]}"
		frappe.get_doc({
			"doctype": "Holiday List", "holiday_list_name": cls.holiday_list,
			"from_date": f"{cls.year}-01-01", "to_date": f"{cls.year}-12-31",
		}).insert(ignore_permissions=True)

		structure = f"ZZ Test Structure {uuid.uuid4().hex[:6]}"
		ss = frappe.new_doc("Salary Structure")
		ss.name = structure
		ss.is_active = "Yes"
		ss.company = cls.company
		ss.payroll_frequency = "Monthly"
		ss.currency = cls.currency
		ss.flags.ignore_permissions = True
		ss.insert()
		ss.submit()

		settings = frappe.get_single("Pay Sheet Settings")
		settings.default_salary_structure = structure
		settings.flags.ignore_permissions = True
		settings.save()
		from cooperheat.cooperheat.doctype.pay_sheet_settings.pay_sheet_settings import setup_defaults

		setup_defaults()

		# HRMS mails a slip on submit when this is on - the bulk step must keep it quiet
		frappe.db.set_single_value("Payroll Settings", "email_salary_slip_to_employee", 1)

		cls.emp_ok = cls.make_employee("Ok", company_email=f"ok.{uuid.uuid4().hex[:5]}@example.com")
		cls.emp_none = cls.make_employee("NoMail")
		cls.emp_plain = cls.make_employee("Plain", company_email=f"plain.{uuid.uuid4().hex[:5]}@example.com")
		cls.sheets = {e.name: cls.make_sheet(e) for e in (cls.emp_ok, cls.emp_none, cls.emp_plain)}

		imp = frappe.get_doc({
			"doctype": "Payroll Import", "company": cls.company, "month": cls.month, "year": cls.year,
			"posting_date": cls.today, "file": "/files/zz-test.xlsx", "status": "Completed",
		})
		for i, e in enumerate((cls.emp_ok, cls.emp_none, cls.emp_plain), 1):
			imp.append("rows", {
				"doc_no": str(i), "code": e.employee_number, "employee": e.name, "employee_name": e.employee_name,
				"payroll_sheet": cls.sheets[e.name], "row_status": "Created",
			})
		imp.flags.ignore_permissions = True
		imp.insert()
		cls.imp = imp.name

	@classmethod
	def has_fiscal_year(cls, company):
		from erpnext.accounts.utils import FiscalYearError, get_fiscal_year

		try:
			get_fiscal_year(cls.today.replace(day=1), company=company)
			return True
		except FiscalYearError:
			return False

	@classmethod
	def make_employee(cls, first_name, **extra):
		code = f"ZZT{uuid.uuid4().hex[:6]}"
		emp = frappe.get_doc({
			"doctype": "Employee", "employee_number": code, "first_name": first_name, "last_name": code,
			"gender": "Male", "date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01",
			"company": cls.company, "status": "Active", "prefered_contact_email": "Company Email",
			"holiday_list": cls.holiday_list, **extra,
		})
		emp.flags.ignore_permissions = True
		emp.insert()
		frappe.get_doc({
			"doctype": "Employee Compensation", "employee": emp.name, "from_date": "2010-01-01", "is_active": 1,
			"currency": cls.currency, "employee_category": "Expat", "basic": 5000, "housing_allowance": 1000,
		}).insert(ignore_permissions=True)
		return emp

	@classmethod
	def make_sheet(cls, emp):
		from cooperheat.cooperheat.doctype.payroll_import.payroll_import import _make_payroll_sheet
		from cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet import get_employee_compensation

		ps = _make_payroll_sheet(
			company=cls.company, employee=emp.name, month=cls.month, year=cls.year, posting_date=cls.today,
			row={"days": 30}, comp_data=get_employee_compensation(emp.name, cls.today),
		)
		ps.submit()
		return ps.name

	def rows(self):
		return {r.employee: r for r in sd._rows(self.imp)}

	def test_pipeline_end_to_end(self):
		# 0. straight after the import every sheet has no slip; the missing address is not flagged yet
		sd.sync_rows(self.imp)
		rows = self.rows()
		self.assertEqual({r.slip_status for r in rows.values()}, {"Not Created"})

		# 1. create
		with patch.object(sd, "_set_bulk"):
			sd.run_bulk(self.imp, "create_slips", {})
		rows = self.rows()
		self.assertEqual(
			{r.slip_status for r in rows.values()}, {"Draft"}, {r.employee: r.slip_error for r in rows.values()}
		)
		self.assertTrue(all(r.salary_slip for r in rows.values()))
		self.assertEqual(rows[self.emp_none.name].email_status, "Skipped")
		self.assertEqual(rows[self.emp_ok.name].email_to, self.emp_ok.company_email)

		# 2. submit: HRMS's own on-submit email must stay quiet
		with patch("hrms.payroll.doctype.salary_slip.salary_slip.SalarySlip.email_salary_slip") as hrms_mail:
			control = frappe.get_doc("Salary Slip", rows[self.emp_plain.name].salary_slip)
			control.flags.ignore_permissions = True
			control.submit()
			self.assertEqual(hrms_mail.call_count, 1)  # control: an ordinary submit does mail
			with patch.object(sd, "_set_bulk"):
				sd.run_bulk(self.imp, "submit_slips", {})
			self.assertEqual(hrms_mail.call_count, 1)  # the bulk step added none
		rows = self.rows()
		self.assertEqual({r.slip_status for r in rows.values()}, {"Submitted"})

		# 3. email: one queued, one skipped, PDF attached, nothing sent yet
		with patch.object(sd, "_set_bulk"), patch("frappe.attach_print", return_value=FAKE_PDF):
			sd.run_bulk(self.imp, "send_emails", {})
		rows = self.rows()
		ok, none, plain = rows[self.emp_ok.name], rows[self.emp_none.name], rows[self.emp_plain.name]
		self.assertEqual(ok.email_status, "Queued")
		self.assertEqual(plain.email_status, "Queued")
		self.assertEqual(none.email_status, "Skipped")
		self.assertFalse(none.email_queue)
		queue = frappe.get_doc("Email Queue", ok.email_queue)
		self.assertEqual(queue.reference_doctype, "Salary Slip")
		self.assertEqual(queue.reference_name, ok.salary_slip)
		self.assertEqual([r.recipient for r in queue.recipients], [self.emp_ok.company_email])
		self.assertIn("Payslip-test.pdf", queue.message)  # the queue keeps the full MIME message, PDF included

		# 4. the row follows the queue: retry -> sent -> error, and a rerun never double-queues
		frappe.db.set_value("Email Queue", ok.email_queue, {"status": "Not Sent", "retry": 1, "error": "x\nSMTP hiccup"})
		sd.sync_rows(self.imp)
		row = self.rows()[self.emp_ok.name]
		self.assertEqual(row.email_status, "Queued")
		self.assertIn("SMTP hiccup", row.email_error)

		frappe.db.set_value("Email Queue", ok.email_queue, {"status": "Sent", "error": ""})
		frappe.db.set_value("Email Queue", plain.email_queue, {"status": "Error", "error": "x\nsmtplib.SMTPDataError: 550"})
		sd.sync_rows(self.imp)
		rows = self.rows()
		self.assertEqual(rows[self.emp_ok.name].email_status, "Sent")
		self.assertTrue(rows[self.emp_ok.name].email_sent_on)
		self.assertEqual(rows[self.emp_plain.name].email_status, "Failed")
		self.assertEqual(rows[self.emp_plain.name].email_error, "smtplib.SMTPDataError: 550")

		before = frappe.db.count("Email Queue")
		with patch.object(sd, "_set_bulk"), patch("frappe.attach_print", return_value=FAKE_PDF):
			sd.run_bulk(self.imp, "send_emails", {})  # only the failed one is retried
		self.assertEqual(frappe.db.count("Email Queue") - before, 1)
		self.assertEqual(self.rows()[self.emp_ok.name].email_queue, ok.email_queue)  # sent row untouched

		# 5. single resend from the row button
		with patch.object(sd, "_assert_outgoing_email"), patch("frappe.attach_print", return_value=FAKE_PDF):
			out = sd.resend_email(self.imp, ok.name)
			self.assertEqual(out["outcome"], "ok")
			self.assertNotEqual(self.rows()[self.emp_ok.name].email_queue, ok.email_queue)
			with self.assertRaises(frappe.ValidationError):  # now queued: refuse a double send
				sd.resend_email(self.imp, ok.name)
			with self.assertRaises(frappe.ValidationError):  # no address
				sd.resend_email(self.imp, none.name)

		# 6. the report reads the same story
		from cooperheat.cooperheat.report.salary_slip_dispatch_status.salary_slip_dispatch_status import (
			execute,
		)

		_cols, data, _msg, _chart, summary = execute({"payroll_import": self.imp})
		self.assertEqual(len(data), 3)
		by_emp = {d["employee"]: d for d in data}
		self.assertEqual(by_emp[self.emp_none.name]["email_status"], "Skipped")
		self.assertEqual(by_emp[self.emp_ok.name]["slip_status"], "Submitted")
		self.assertEqual(dict((s["label"], s["value"]) for s in summary)["Employees"], 3)

	def test_a_slip_that_disagrees_with_its_sheet_is_refused(self):
		emp = self.make_employee("Mismatch", company_email="mismatch@example.com")
		sheet = self.make_sheet(emp)
		sheet_net = frappe.db.get_value("Payroll Sheet", sheet, "net_payable")
		slip = frappe.get_attr("cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet.create_salary_slip")(sheet)

		sd.assert_slip_matches_sheet(slip, sheet)  # equal: fine
		frappe.db.set_value("Salary Slip", slip, "net_pay", sheet_net + 1700)
		with self.assertRaises(frappe.ValidationError) as ctx:
			sd.assert_slip_matches_sheet(slip, sheet)
		self.assertIn("does not match", str(ctx.exception))
		frappe.db.set_value("Salary Slip", slip, "net_pay", sheet_net + 0.004)  # rounding noise is tolerated
		sd.assert_slip_matches_sheet(slip, sheet)

	def test_the_error_names_the_unmapped_field(self):
		# a field with an amount but no Component Mapping row is left off the slip - say so
		settings = frappe.get_single("Pay Sheet Settings")
		settings.component_mapping = [m for m in settings.component_mapping if m.payroll_field != "service_allowance"]
		settings.flags.ignore_permissions = True
		settings.save()

		emp = self.make_employee("Unmapped", company_email="unmapped@example.com")
		frappe.db.set_value("Employee Compensation", {"employee": emp.name}, "service_allowance", 300)
		sheet = self.make_sheet(emp)
		self.assertEqual(frappe.db.get_value("Payroll Sheet", sheet, "service_allowance"), 300)
		slip = frappe.get_attr("cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet.create_salary_slip")(sheet)
		with self.assertRaises(frappe.ValidationError) as ctx:
			sd.assert_slip_matches_sheet(slip, sheet)
		message = str(ctx.exception)
		self.assertIn("not in the Component Mapping", message)
		self.assertIn("Service Allowance 300.00", message)

	def test_two_sheet_fields_feeding_one_component_are_not_a_false_alarm(self):
		settings = frappe.get_single("Pay Sheet Settings")
		for m in settings.component_mapping:
			if m.payroll_field == "others":
				m.salary_component = "Other Allowance"  # same component as other_allowance
		settings.flags.ignore_permissions = True
		settings.save()

		emp = self.make_employee("Shared", company_email="shared@example.com")
		frappe.db.set_value("Employee Compensation", {"employee": emp.name}, "other_allowance", 100)
		sheet = self.make_sheet(emp)
		slip = frappe.get_attr("cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet.create_salary_slip")(sheet)
		frappe.db.set_value("Salary Slip", slip, "net_pay", 1)  # force a disagreement that has no component cause
		with self.assertRaises(frappe.ValidationError) as ctx:
			sd.assert_slip_matches_sheet(slip, sheet)
		self.assertNotIn("Other Allowance:", str(ctx.exception))

	def test_bulk_submit_leaves_a_mismatched_draft_alone(self):
		emp = self.make_employee("Drift", company_email="drift@example.com")
		sheet = self.make_sheet(emp)
		slip = frappe.get_attr("cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet.create_salary_slip")(sheet)
		frappe.db.set_value("Salary Slip", slip, "net_pay", 999)  # someone edited the draft after it was made

		imp = frappe.get_doc({
			"doctype": "Payroll Import", "company": self.company, "month": self.month, "year": self.year,
			"posting_date": self.today, "file": "/files/zz-test3.xlsx", "status": "Completed",
		})
		imp.append("rows", {
			"doc_no": "1", "code": emp.employee_number, "employee": emp.name, "employee_name": emp.employee_name,
			"payroll_sheet": sheet, "row_status": "Created",
		})
		imp.flags.ignore_permissions = True
		imp.insert()
		with patch.object(sd, "_set_bulk"):
			sd.run_bulk(imp.name, "submit_slips", {})
		row = sd._rows(imp.name)[0]
		self.assertEqual(row.slip_status, "Draft")
		self.assertIn("does not match", row.slip_error)
		self.assertEqual(frappe.db.get_value("Salary Slip", slip, "docstatus"), 0)

	def test_a_failing_employee_does_not_stop_the_others(self):
		# an employee who joins after the period cannot get a salary slip; the good one must still get one
		late = self.make_employee("Late", company_email="late@example.com")
		late_sheet = self.make_sheet(late)
		frappe.db.set_value("Employee", late.name, "date_of_joining", add_days(self.today, 90))
		good = self.make_employee("Good", company_email="good@example.com")
		good_sheet = self.make_sheet(good)

		imp = frappe.get_doc({
			"doctype": "Payroll Import", "company": self.company, "month": self.month, "year": self.year,
			"posting_date": self.today, "file": "/files/zz-test2.xlsx", "status": "Completed",
		})
		for i, (e, sheet) in enumerate(((late, late_sheet), (good, good_sheet)), 1):
			imp.append("rows", {
				"doc_no": str(i), "code": e.employee_number, "employee": e.name, "employee_name": e.employee_name,
				"payroll_sheet": sheet, "row_status": "Created",
			})
		imp.flags.ignore_permissions = True
		imp.insert()

		with patch.object(sd, "_set_bulk"):
			sd.run_bulk(imp.name, "create_slips", {})
		rows = {r.employee: r for r in sd._rows(imp.name)}
		self.assertEqual(rows[late.name].slip_status, "Not Created")
		self.assertIn("joining", rows[late.name].slip_error.lower())
		self.assertEqual(rows[good.name].slip_status, "Draft", rows[good.name].slip_error)
		self.assertFalse(rows[good.name].slip_error)
