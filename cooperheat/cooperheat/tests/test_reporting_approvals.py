# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Approvals from the employee's own reporting line.

Direct / Immediate Reporting = Employee.reports_to (level 1), Secondary Reporting (level 2,
field staff only), Payroll Approver from Pay Sheet Settings (level 3).

Runs against the DEV seed (cooperheat.cooperheat.dev_seed):
    bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_reporting_approvals
"""

import frappe
from frappe.utils import add_days, today

from cooperheat.cooperheat import dev_seed, org
from cooperheat.cooperheat.api import api, attendance_gen, supervisor
from cooperheat.cooperheat.tests.test_hr_scope import HRTestCase, emp_of
from cooperheat.cooperheat.tests.test_org_structure import make_employee

FIELD, OFFICE = "Field Staff", "Office Staff"


def set_payroll(approver):
	settings = frappe.get_single("Pay Sheet Settings")
	settings.payroll_approver = approver
	settings.flags.ignore_permissions = True
	settings.save()
	org.clear_cache()


def new_attendance(employee):
	doc = frappe.get_doc(
		{
			"doctype": "Attendance",
			"employee": employee,
			"attendance_date": today(),
			"status": "Present",
			"company": dev_seed.COMPANY,
			"department": frappe.db.get_value("Employee", employee, "department"),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	return doc.name


def state(name):
	return frappe.db.get_value("Attendance", name, "workflow_state")


def cleanup_debris():
	"""Several approval paths commit (level 3 approve, generation), so the employees these
	tests create outlive the test transaction. Remove them and what hangs on them (dev site only)."""
	if not frappe.conf.get("developer_mode"):
		return
	emps = frappe.get_all("Employee", filters={"last_name": "OrgTest"}, pluck="name")
	if not emps:
		return
	atts = frappe.get_all("Attendance", filters={"employee": ["in", emps]}, pluck="name")
	if atts:
		frappe.db.delete("Attendance Site Hours", {"parent": ["in", atts]})
		frappe.db.delete("Attendance", {"name": ["in", atts]})
	frappe.db.delete("Employee Checkin", {"employee": ["in", emps]})
	frappe.db.delete("Shift Assignment", {"employee": ["in", emps]})
	for name in emps:
		frappe.delete_doc("Employee", name, force=True, ignore_permissions=True)
	frappe.db.commit()


class ReportingTestCase(HRTestCase):
	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cleanup_debris()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		set_payroll(emp_of("irtaza"))
		org.clear_cache()

	def tearDown(self):
		set_payroll(emp_of("irtaza"))
		super().tearDown()

	def people(self):
		return emp_of("anil"), emp_of("khalid"), emp_of("irtaza")


class TestApprovalChain(ReportingTestCase):
	def test_field_staff_chain_and_windows(self):
		anil, khalid, irtaza = self.people()
		emp = make_employee("FieldA", custom_staff_category=FIELD, reports_to=anil, custom_secondary_reporting=khalid)
		chain = org.approval_chain(emp.name)
		self.assertEqual([(r.approval_level, r.approver) for r in chain], [(1, anil), (2, khalid), (3, irtaza)])
		self.assertEqual([r.approval_window_hours for r in chain], [48, 72, 48])

	def test_office_staff_have_no_secondary_step(self):
		anil, khalid, irtaza = self.people()
		emp = make_employee("OfficeA", custom_staff_category=OFFICE, reports_to=khalid, custom_secondary_reporting=anil)
		self.assertEqual([(r.approval_level, r.approver) for r in org.approval_chain(emp.name)], [(1, khalid), (3, irtaza)])

	def test_without_a_payroll_approver_the_chain_ends_at_the_reporting_line(self):
		anil, khalid, _ = self.people()
		set_payroll(None)
		emp = make_employee("FieldB", custom_staff_category=FIELD, reports_to=anil, custom_secondary_reporting=khalid)
		self.assertEqual([r.approval_level for r in org.approval_chain(emp.name)], [1, 2])

	def test_nobody_approves_their_own_or_twice(self):
		anil, khalid, irtaza = self.people()
		emp = make_employee("FieldC", custom_staff_category=FIELD, reports_to=khalid, custom_secondary_reporting=khalid)
		self.assertEqual([(r.approval_level, r.approver) for r in org.approval_chain(emp.name)], [(1, khalid), (3, irtaza)])
		boss = make_employee("PayrollSelf", custom_staff_category=OFFICE, reports_to=anil)
		set_payroll(boss.name)
		self.assertEqual([r.approval_level for r in org.approval_chain(boss.name)], [1])

	def test_support_reporting_approves_first_then_immediate(self):
		# client call 2026-10-25: coordinator (support) -> operations manager (immediate) -> payroll
		anil, khalid, irtaza = self.people()
		saleh = emp_of("saleh")
		emp = make_employee(
			"SupportA", custom_staff_category=FIELD, reports_to=anil, custom_secondary_reporting=khalid,
			custom_support_reporting=saleh,
		)
		chain = org.approval_chain(emp.name)
		self.assertEqual([(r.approval_level, r.approver) for r in chain], [(1, saleh), (2, anil), (3, irtaza)])
		self.assertEqual(org.first_approver(emp.name), saleh)

	def test_support_reporting_same_as_immediate_is_not_asked_twice(self):
		anil, _, irtaza = self.people()
		emp = make_employee("SupportB", custom_staff_category=FIELD, reports_to=anil, custom_support_reporting=anil)
		self.assertEqual([(r.approval_level, r.approver) for r in org.approval_chain(emp.name)], [(1, anil), (3, irtaza)])

	def test_no_reporting_person_means_no_first_approver(self):
		emp = make_employee("Loose", custom_staff_category=FIELD)
		self.assertIsNone(org.first_approver(emp.name))

	def test_secondary_defaults_to_the_supervisors_own_boss(self):
		anil, khalid, _ = self.people()
		emp = make_employee("FieldD", custom_staff_category=FIELD, reports_to=anil)
		self.assertEqual(emp.custom_secondary_reporting, khalid)  # Anil reports to Khalid
		office = make_employee("OfficeB", custom_staff_category=OFFICE, reports_to=anil)
		self.assertFalse(office.custom_secondary_reporting)

	def test_secondary_is_filled_when_the_category_is_set_later(self):
		anil, khalid, _ = self.people()
		emp = make_employee("FieldLate", reports_to=anil)  # no category yet: still gets the default
		self.assertEqual(emp.custom_secondary_reporting, khalid)
		frappe.db.set_value("Employee", emp.name, "custom_secondary_reporting", None)
		doc = frappe.get_doc("Employee", emp.name)
		doc.custom_staff_category = FIELD
		doc.save()
		self.assertEqual(doc.custom_secondary_reporting, khalid)

	def test_backfill_fills_existing_employees_and_skips_office_staff(self):
		anil, khalid, _ = self.people()
		field = make_employee("BackField", custom_staff_category=FIELD, reports_to=anil)
		office = make_employee("BackOffice", custom_staff_category=OFFICE, reports_to=anil)
		for e in (field, office):
			frappe.db.set_value("Employee", e.name, "custom_secondary_reporting", None)
		dry = org.backfill_secondary_reporting(dry_run=True)
		self.assertTrue(dry["dry_run"])
		self.assertIsNone(frappe.db.get_value("Employee", field.name, "custom_secondary_reporting"))
		org.backfill_secondary_reporting(dry_run=False)
		self.assertEqual(frappe.db.get_value("Employee", field.name, "custom_secondary_reporting"), khalid)
		self.assertIsNone(frappe.db.get_value("Employee", office.name, "custom_secondary_reporting"))

	def test_a_secondary_set_by_hand_is_kept(self):
		anil, khalid, irtaza = self.people()
		emp = make_employee("FieldE", custom_staff_category=FIELD, reports_to=anil, custom_secondary_reporting=irtaza)
		self.assertEqual(emp.custom_secondary_reporting, irtaza)

	def test_leave_expense_shift_approvers_follow_reports_to(self):
		anil, khalid, _ = self.people()
		emp = make_employee("FieldF", custom_staff_category=FIELD, reports_to=anil)
		anil_user = dev_seed.email("anil")
		for field in org.APPROVER_FIELDS:
			self.assertEqual(emp.get(field), anil_user)
		emp.reports_to = khalid
		emp.save()
		for field in org.APPROVER_FIELDS:
			self.assertEqual(emp.get(field), dev_seed.email("khalid"))


class TestAttendanceFlow(ReportingTestCase):
	def test_field_staff_go_supervisor_then_manager_then_payroll(self):
		anil, khalid, irtaza = self.people()
		emp = make_employee("FlowField", custom_staff_category=FIELD, reports_to=anil, custom_secondary_reporting=khalid)
		name = new_attendance(emp.name)
		self.assertEqual((state(name), frappe.db.get_value("Attendance", name, "current_approver")), ("Pending Level 1 Approval", anil))
		self.assertEqual(frappe.db.get_value("Attendance", name, "approval_window_hours"), 48)

		frappe.set_user(dev_seed.email("khalid"))
		with self.assertRaises(frappe.PermissionError):
			supervisor.approve_attendance(name)  # not his turn

		frappe.set_user(dev_seed.email("anil"))
		self.assertEqual(supervisor.approve_attendance(name)["state"], "Pending Level 2 Approval")
		self.assertEqual(frappe.db.get_value("Attendance", name, "current_approver"), khalid)
		self.assertEqual(frappe.db.get_value("Attendance", name, "approval_window_hours"), 72)

		frappe.set_user(dev_seed.email("khalid"))
		self.assertEqual(supervisor.approve_attendance(name)["state"], "Pending Level 3 Approval")
		self.assertEqual(frappe.db.get_value("Attendance", name, "current_approver"), irtaza)

		frappe.set_user(dev_seed.email("irtaza"))
		api.level3_approve_attendance(name)
		self.assertEqual(state(name), "Approved")

	def test_office_staff_skip_the_secondary_step(self):
		anil, khalid, irtaza = self.people()
		emp = make_employee("FlowOffice", custom_staff_category=OFFICE, reports_to=khalid)
		name = new_attendance(emp.name)
		frappe.set_user(dev_seed.email("khalid"))
		supervisor.approve_attendance(name)
		self.assertEqual(state(name), "Pending Level 3 Approval")
		self.assertEqual(frappe.db.get_value("Attendance", name, "current_approver"), irtaza)

	def test_without_payroll_approver_the_reporting_line_is_final(self):
		anil, khalid, _ = self.people()
		set_payroll(None)
		emp = make_employee("FlowNoPayroll", custom_staff_category=OFFICE, reports_to=khalid)
		name = new_attendance(emp.name)
		frappe.set_user(dev_seed.email("khalid"))
		supervisor.approve_attendance(name)
		self.assertEqual(state(name), "Approved")

	def test_only_the_payroll_approver_gives_the_final_approval(self):
		anil, khalid, irtaza = self.people()
		emp = make_employee("FlowPayroll", custom_staff_category=OFFICE, reports_to=khalid)
		name = new_attendance(emp.name)
		frappe.set_user(dev_seed.email("khalid"))
		supervisor.approve_attendance(name)
		with self.assertRaises(frappe.ValidationError):
			api.level3_approve_attendance(name)  # Khalid is not the Payroll Approver
		self.assertEqual(api.get_pending_level3_records(), [])
		frappe.set_user(dev_seed.email("irtaza"))
		self.assertIn(name, [r["name"] for r in api.get_pending_level3_records()])

	def test_changing_reports_to_moves_waiting_records(self):
		anil, khalid, _ = self.people()
		emp = make_employee("FlowMove", custom_staff_category=FIELD, reports_to=anil, custom_secondary_reporting=khalid)
		name = new_attendance(emp.name)
		doc = frappe.get_doc("Employee", emp.name)
		doc.reports_to = emp_of("saleh")
		doc.save()
		self.assertEqual(frappe.db.get_value("Attendance", name, "current_approver"), emp_of("saleh"))

	def test_changing_the_payroll_approver_moves_records_waiting_for_payroll(self):
		anil, khalid, irtaza = self.people()
		emp = make_employee("FlowPayrollMove", custom_staff_category=OFFICE, reports_to=khalid)
		name = new_attendance(emp.name)
		frappe.set_user(dev_seed.email("khalid"))
		supervisor.approve_attendance(name)
		frappe.set_user("Administrator")
		set_payroll(emp_of("mustafa"))
		self.assertEqual(frappe.db.get_value("Attendance", name, "current_approver"), emp_of("mustafa"))


class TestGenerationAndReports(ReportingTestCase):
	def test_employee_without_a_reporting_person_is_skipped_and_counted(self):
		emp = make_employee("NoBoss", custom_staff_category=FIELD)
		frappe.get_doc(
			{"doctype": "Employee Checkin", "employee": emp.name, "log_type": "IN", "time": today() + " 06:00:00"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "Employee Checkin", "employee": emp.name, "log_type": "OUT", "time": today() + " 07:00:00"}
		).insert(ignore_permissions=True)
		res = attendance_gen.generate(today(), today())
		self.assertGreaterEqual(res["no_approver"], 1)
		self.assertGreaterEqual(res["no_approver_employees"], 1)
		self.assertFalse(frappe.db.exists("Attendance", {"employee": emp.name, "docstatus": 1}))

	def test_generated_attendance_routes_to_reports_to(self):
		res = attendance_gen.generate(add_days(today(), -3), today())
		self.assertIsInstance(res["no_approver_employees"], int)
		rows = frappe.get_all(
			"Attendance",
			filters={
				"docstatus": 1,
				"workflow_state": "Pending Level 1 Approval",
				"employee": ["in", frappe.get_all("Employee", filters={"reports_to": emp_of("anil")}, pluck="name")],
			},
			fields=["current_approver"],
		)
		self.assertTrue(rows)
		for r in rows:
			self.assertEqual(r.current_approver, emp_of("anil"))

	def test_exceptions_report_lists_the_reporting_gaps(self):
		from cooperheat.cooperheat.report.employee_approver_exceptions.employee_approver_exceptions import get_data

		make_employee("GapNoBoss", custom_staff_category=FIELD)
		anil = emp_of("anil")
		lone = make_employee("GapNoSecondary", custom_staff_category=FIELD, reports_to=anil)
		frappe.db.set_value("Employee", lone.name, "custom_secondary_reporting", None)
		issues = {r["issue"] for r in get_data(frappe._dict())}
		self.assertIn("No Direct / Immediate Reporting", issues)
		self.assertIn("Field staff without Secondary Reporting", issues)


class TestScopeFollowsReporting(ReportingTestCase):
	def test_secondary_reporting_gives_sight_of_the_employee(self):
		anil, khalid, _ = self.people()
		emp = make_employee("ScopeSecondary", custom_staff_category=FIELD, reports_to=emp_of("saleh"), custom_secondary_reporting=anil)
		frappe.set_user(dev_seed.email("anil"))
		self.assertIn(emp.name, frappe.get_list("Employee", pluck="name", limit_page_length=1000))

	def test_support_reporting_gives_sight_of_the_employee(self):
		emp = make_employee("ScopeSupport", custom_staff_category=FIELD, reports_to=emp_of("saleh"), custom_support_reporting=emp_of("anil"))
		frappe.set_user(dev_seed.email("anil"))
		self.assertIn(emp.name, frappe.get_list("Employee", pluck="name", limit_page_length=1000))

	def test_department_approver_rows_no_longer_widen_scope(self):
		# Anil may still be listed in an old matrix; only the reporting line counts now
		frappe.set_user(dev_seed.email("saleh"))
		seen = set(frappe.get_list("Employee", pluck="name", limit_page_length=1000))
		self.assertNotIn(emp_of("anil"), seen)

	def test_payroll_approver_is_not_scoped(self):
		from cooperheat.cooperheat.permissions import scope

		self.assertFalse(scope.is_scoped(dev_seed.email("irtaza")))
		set_payroll(emp_of("saleh"))
		scope.clear_cache()
		self.assertFalse(scope.is_scoped(dev_seed.email("saleh")))
		self.assertTrue(scope.is_scoped(dev_seed.email("anil")))
