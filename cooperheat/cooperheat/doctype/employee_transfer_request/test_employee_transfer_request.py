"""Employee transfer between Business Lines, approved by the receiving manager (client, 2026-10-28).

    bench --site <dev-site> run-tests --module cooperheat.cooperheat.doctype.employee_transfer_request.test_employee_transfer_request
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat import dev_seed, org
from cooperheat.cooperheat.doctype.employee_transfer_request import employee_transfer_request as etr
from cooperheat.cooperheat.tests.test_org_structure import emp_of, make_employee, make_unit


class TestEmployeeTransfer(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.from_bl = make_unit("ETR From BL", org.BUSINESS_LINE)
		cls.to_bl = make_unit("ETR To BL", org.BUSINESS_LINE)
		cls.to_pl = make_unit("ETR To PL", org.PRODUCT_LINE, parent=cls.to_bl, is_group=0)
		org.clear_cache()
		cls.anil, cls.khalid = emp_of("anil"), emp_of("khalid")
		# Khalid is the head of the receiving Business Line (placed on it, no Product Line)
		cls.khalid_before = frappe.db.get_value("Employee", cls.khalid, ["custom_business_line", "custom_product_line", "department"])
		frappe.db.set_value("Employee", cls.khalid, {"custom_business_line": cls.to_bl, "custom_product_line": None}, update_modified=False)

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		bl, pl, dept = cls.khalid_before
		frappe.db.set_value("Employee", cls.khalid, {"custom_business_line": bl, "custom_product_line": pl, "department": dept}, update_modified=False)
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self.emp = make_employee("ETRTech", custom_business_line=self.from_bl, reports_to=self.anil)

	def tearDown(self):
		frappe.set_user("Administrator")

	def request(self, **kw):
		doc = frappe.get_doc(
			{
				"doctype": "Employee Transfer Request",
				"employee": self.emp.name,
				"reason": "Needed on the new project",
				"to_business_line": self.to_bl,
				"to_product_line": self.to_pl,
				**kw,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_receiving_business_line_head_is_suggested_and_request_waits(self):
		doc = self.request()
		self.assertEqual(doc.approver, self.khalid)
		self.assertEqual(doc.status, "Pending Approval")
		self.assertEqual(doc.from_business_line, self.from_bl)

	def test_only_the_receiving_manager_approves(self):
		doc = self.request()
		frappe.set_user(dev_seed.email("anil"))
		with self.assertRaises(frappe.PermissionError):
			etr.approve(doc.name)
		self.assertEqual(frappe.db.get_value("Employee", self.emp.name, "custom_business_line"), self.from_bl)

	def test_approval_moves_the_employee(self):
		doc = self.request(new_reports_to=self.khalid)
		frappe.set_user(dev_seed.email("khalid"))
		etr.approve(doc.name)
		frappe.set_user("Administrator")
		emp = frappe.db.get_value("Employee", self.emp.name, ["custom_business_line", "custom_product_line", "department", "reports_to"], as_dict=True)
		self.assertEqual((emp.custom_business_line, emp.custom_product_line, emp.department, emp.reports_to), (self.to_bl, self.to_pl, self.to_pl, self.khalid))
		self.assertEqual(frappe.db.get_value("Employee Transfer Request", doc.name, "status"), "Approved")

	def test_rejection_keeps_the_employee_and_needs_a_reason(self):
		doc = self.request()
		frappe.set_user(dev_seed.email("khalid"))
		with self.assertRaises(frappe.ValidationError):
			etr.reject(doc.name, " ")
		etr.reject(doc.name, "No place in the team")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Employee Transfer Request", doc.name, ["status", "rejection_reason"]), ("Rejected", "No place in the team"))
		self.assertEqual(frappe.db.get_value("Employee", self.emp.name, "custom_business_line"), self.from_bl)

	def test_a_decided_transfer_cannot_be_edited_or_decided_again(self):
		doc = self.request()
		frappe.set_user(dev_seed.email("khalid"))
		etr.approve(doc.name)
		with self.assertRaises(frappe.ValidationError):
			etr.approve(doc.name)
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Employee Transfer Request", doc.name)
		doc.reason = "changed"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def supervisor_request(self, employee, **kw):
		frappe.set_user(dev_seed.email("anil"))
		doc = frappe.get_doc(
			{
				"doctype": "Employee Transfer Request",
				"employee": employee,
				"reason": "Raised by the supervisor",
				"to_business_line": self.to_bl,
				"to_product_line": self.to_pl,
				**kw,
			}
		)
		return doc.insert()  # with permission checks, as from the form

	def test_supervisor_raises_a_transfer_for_their_own_team(self):
		doc = self.supervisor_request(self.emp.name)
		self.assertEqual((doc.status, doc.approver), ("Pending Approval", self.khalid))
		self.assertTrue(frappe.has_permission("Employee Transfer Request", "read", doc=doc.name))
		frappe.set_user(dev_seed.email("khalid"))
		etr.approve(doc.name)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Employee", self.emp.name, "custom_business_line"), self.to_bl)

	def test_supervisor_cannot_raise_for_someone_outside_the_team(self):
		frappe.set_user("Administrator")
		other = make_employee("ETROther", custom_business_line=self.from_bl)
		with self.assertRaises(frappe.PermissionError):
			self.supervisor_request(other.name)

	def test_requester_cannot_approve_their_own_request(self):
		with self.assertRaises(frappe.ValidationError):
			self.supervisor_request(self.emp.name, approver=self.anil)

	def test_supervisor_cannot_edit_a_decided_transfer(self):
		doc = self.supervisor_request(self.emp.name)
		frappe.set_user(dev_seed.email("khalid"))
		etr.reject(doc.name, "Not now")
		frappe.set_user(dev_seed.email("anil"))
		self.assertFalse(frappe.has_permission("Employee Transfer Request", "write", doc=doc.name))

	def test_moving_to_where_the_employee_already_is_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.request(to_business_line=self.from_bl, to_product_line=None)
