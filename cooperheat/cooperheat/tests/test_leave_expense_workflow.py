"""Leave and expense: reporting person approves, then the Payroll Approver.

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_leave_expense_workflow
"""

import unittest

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, today

from cooperheat.cooperheat import approval_workflows as aw
from cooperheat.cooperheat import dev_seed, org
from cooperheat.cooperheat.tests.test_hr_scope import HRTestCase, emp_of
from cooperheat.cooperheat.tests.test_org_structure import make_employee
from cooperheat.cooperheat.tests.test_reporting_approvals import cleanup_debris, set_payroll

_next_day = [60]


def new_leave(employee):
	_next_day[0] += 3
	start = add_days(today(), _next_day[0])
	doc = frappe.get_doc(
		{
			"doctype": "Leave Application",
			"employee": employee,
			"leave_type": "Leave Without Pay",
			"from_date": start,
			"to_date": start,
			"status": "Open",
			"description": "workflow test",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def act(name, action, user):
	frappe.set_user(dev_seed.email(user) if "@" not in user else user)
	try:
		doc = frappe.get_doc("Leave Application", name)
		apply_workflow(doc, action)
	finally:
		frappe.set_user("Administrator")


def row(name):
	return frappe.db.get_value(
		"Leave Application",
		name,
		["workflow_state", "status", "docstatus", "leave_approver", aw.FINAL_APPROVER_FIELD],
		as_dict=True,
	)


class TestLeaveWorkflow(HRTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Leave Type", "Leave Without Pay"):
			raise unittest.SkipTest("Leave Without Pay is not set up on this site")
		cls.anil, cls.khalid, cls.irtaza = emp_of("anil"), emp_of("khalid"), emp_of("irtaza")

	@classmethod
	def tearDownClass(cls):
		for name in frappe.get_all(
			"Leave Application", filters={"description": "workflow test"}, pluck="name"
		):
			frappe.db.delete("Leave Application", {"name": name})
		cleanup_debris()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		set_payroll(self.irtaza)

	def tearDown(self):
		set_payroll(self.irtaza)
		super().tearDown()

	def test_definition_exists_and_is_active(self):
		wf = frappe.get_doc("Workflow", "Leave Approval")
		self.assertEqual((wf.document_type, wf.is_active), ("Leave Application", 1))
		self.assertEqual([s.state for s in wf.states][:2], [aw.PENDING_1, aw.PENDING_2])

	def test_request_starts_with_the_reporting_person_and_a_final_approver(self):
		emp = make_employee("LvStart", reports_to=self.anil)
		leave = row(new_leave(emp.name))
		self.assertEqual(leave.workflow_state, aw.PENDING_1)
		self.assertEqual(leave.leave_approver, dev_seed.email("anil"))
		self.assertEqual(leave[aw.FINAL_APPROVER_FIELD], dev_seed.email("irtaza"))

	def test_reporting_person_then_payroll_approver(self):
		emp = make_employee("LvFlow", reports_to=self.anil)
		name = new_leave(emp.name)
		with self.assertRaises(frappe.ValidationError):
			act(name, "Approve", "khalid")  # not the reporting person
		act(name, "Approve", "anil")
		self.assertEqual(row(name).workflow_state, aw.PENDING_2)
		with self.assertRaises(frappe.ValidationError):
			act(name, "Approve", "anil")  # the final step is Irtaza's
		act(name, "Approve", "irtaza")
		done = row(name)
		self.assertEqual((done.workflow_state, done.status, done.docstatus), (aw.APPROVED, "Approved", 1))

	def test_reject_at_the_first_step_ends_it(self):
		emp = make_employee("LvReject", reports_to=self.anil)
		name = new_leave(emp.name)
		act(name, "Reject", "anil")
		done = row(name)
		self.assertEqual((done.workflow_state, done.status), (aw.REJECTED, "Rejected"))

	def test_without_a_payroll_approver_the_reporting_person_is_final(self):
		set_payroll(None)
		emp = make_employee("LvNoPayroll", reports_to=self.anil)
		name = new_leave(emp.name)
		act(name, "Approve", "anil")
		done = row(name)
		self.assertEqual((done.workflow_state, done.status, done.docstatus), (aw.APPROVED, "Approved", 1))

	def test_when_the_reporting_person_is_the_payroll_approver_there_is_one_step(self):
		emp = make_employee("LvSame", reports_to=self.irtaza)
		name = new_leave(emp.name)
		self.assertIsNone(row(name)[aw.FINAL_APPROVER_FIELD])
		act(name, "Approve", "irtaza")
		self.assertEqual(row(name).workflow_state, aw.APPROVED)

	def test_hr_manager_can_step_in_at_the_first_step(self):
		emp = make_employee("LvHr", reports_to=self.anil)
		name = new_leave(emp.name)
		act(name, "Approve", "mustafa")
		self.assertEqual(row(name).workflow_state, aw.PENDING_2)

	def test_existing_open_requests_are_picked_up(self):
		emp = make_employee("LvOld", reports_to=self.anil)
		name = new_leave(emp.name)
		frappe.db.set_value(
			"Leave Application",
			name,
			{"workflow_state": None, "leave_approver": None, aw.FINAL_APPROVER_FIELD: None},
		)
		aw._backfill_open_requests("Leave Application")
		leave = row(name)
		self.assertEqual(leave.workflow_state, aw.PENDING_1)
		self.assertEqual(leave.leave_approver, dev_seed.email("anil"))
		self.assertEqual(leave[aw.FINAL_APPROVER_FIELD], dev_seed.email("irtaza"))


class TestExpenseWorkflow(HRTestCase):
	def test_definition_exists_and_is_active(self):
		wf = frappe.get_doc("Workflow", "Expense Approval")
		self.assertEqual((wf.document_type, wf.is_active), ("Expense Claim", 1))
		approve = [t for t in wf.transitions if t.action == "Approve" and t.allowed == "All"]
		self.assertEqual(
			[(t.state, t.next_state) for t in approve],
			[(aw.PENDING_1, aw.PENDING_2), (aw.PENDING_2, aw.APPROVED)],
		)
		self.assertIn("expense_approver", approve[0].condition)
		self.assertIn(aw.FINAL_APPROVER_FIELD, approve[1].condition)
		self.assertEqual(
			{s.state: s.update_value for s in wf.states if s.update_field}[aw.APPROVED], "Approved"
		)

	def test_approver_and_final_approver_are_filled(self):
		doc = frappe.new_doc("Expense Claim")
		doc.employee = make_employee("ExpStart", reports_to=emp_of("anil")).name
		aw.before_validate(doc)
		self.assertEqual(doc.expense_approver, dev_seed.email("anil"))
		self.assertEqual(doc.get(aw.FINAL_APPROVER_FIELD), dev_seed.email("irtaza"))

	@classmethod
	def tearDownClass(cls):
		cleanup_debris()
		super().tearDownClass()
