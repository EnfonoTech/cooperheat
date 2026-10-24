"""A request starts with the reporting person and is forwarded, completed or rejected by its holder.

bench --site <dev-site> run-tests --module cooperheat.cooperheat.tests.test_service_request
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from cooperheat.cooperheat import dev_seed
from cooperheat.cooperheat import service_request_tools as srt
from cooperheat.cooperheat.tests.test_hr_scope import emp_of


def new_request(user, subject="Laptop will not start"):
	frappe.set_user(user)
	try:
		doc = frappe.get_doc(
			{"doctype": "Service Request", "subject": subject, "details": "It shows a black screen."}
		)
		doc.insert()
		return doc
	finally:
		frappe.set_user("Administrator")


class TestServiceRequest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.tech_user = dev_seed.email("tech101")
		cls.tech = frappe.db.get_value("Employee", {"user_id": cls.tech_user}, "name")
		cls.boss = frappe.db.get_value("Employee", cls.tech, "reports_to")
		cls.boss_user = frappe.db.get_value("Employee", cls.boss, "user_id")
		cls.khalid_user = dev_seed.email("khalid")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_it_starts_with_the_reporting_person(self):
		doc = new_request(self.tech_user)
		self.assertEqual(doc.requested_by, self.tech)
		self.assertEqual(doc.current_holder, self.boss)
		self.assertEqual(doc.status, "Open")
		self.assertEqual([s.action for s in doc.trail], ["Created"])
		self.assertEqual(doc.holder_name, frappe.db.get_value("Employee", self.boss, "employee_name"))
		self.assertTrue(doc.employee_name)

	def test_the_holder_forwards_it_on_and_the_requester_sees_the_trail(self):
		doc = new_request(self.tech_user)
		frappe.set_user(self.boss_user)
		srt.forward(doc.name, emp_of("khalid"), "Please look at this")
		frappe.set_user(self.tech_user)
		mine = frappe.get_doc("Service Request", doc.name)
		self.assertEqual(mine.current_holder, emp_of("khalid"))
		self.assertEqual(mine.holder_name, frappe.db.get_value("Employee", emp_of("khalid"), "employee_name"))
		self.assertEqual([s.action for s in mine.trail], ["Created", "Forwarded"])
		self.assertEqual(mine.trail[1].comment, "Please look at this")

	def test_only_the_holder_can_act(self):
		doc = new_request(self.tech_user)
		frappe.set_user(self.tech_user)  # the requester is not the holder
		with self.assertRaises(frappe.PermissionError):
			srt.complete(doc.name, "done by myself")
		frappe.set_user(self.khalid_user)  # somebody who was never part of it
		with self.assertRaises(frappe.PermissionError):
			srt.forward(doc.name, emp_of("khalid"))

	def test_complete_and_reject_close_it(self):
		doc = new_request(self.tech_user)
		frappe.set_user(self.boss_user)
		srt.forward(doc.name, emp_of("khalid"))
		frappe.set_user(self.khalid_user)
		out = srt.complete(doc.name, "Replaced the battery")
		self.assertEqual(out["status"], "Completed")
		frappe.set_user(self.boss_user)  # a closed request cannot be forwarded again
		with self.assertRaises(frappe.PermissionError):
			srt.forward(doc.name, emp_of("khalid"))
		other = new_request(self.tech_user, "Parking space")
		frappe.set_user(self.boss_user)
		self.assertEqual(srt.reject(other.name, "Not possible")["status"], "Rejected")

	def test_visibility(self):
		doc = new_request(self.tech_user)
		frappe.set_user(self.khalid_user)
		self.assertNotIn(doc.name, [r.name for r in frappe.get_list("Service Request")])
		frappe.set_user(self.boss_user)
		self.assertIn(doc.name, [r.name for r in frappe.get_list("Service Request")])
		frappe.set_user("Administrator")
		self.assertIn(doc.name, [r.name for r in frappe.get_list("Service Request")])

	def test_status_and_holder_cannot_be_edited_directly(self):
		doc = new_request(self.tech_user)
		frappe.set_user(self.boss_user)
		edit = frappe.get_doc("Service Request", doc.name)
		edit.current_holder = emp_of("khalid")
		# refused either by the field rule (holder with the Employee role) or by the permission check
		with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
			edit.save()

	def test_mine_lists_raised_and_waiting(self):
		doc = new_request(self.tech_user)
		frappe.set_user(self.tech_user)
		self.assertIn(doc.name, [r["name"] for r in srt.mine()["raised"]])
		frappe.set_user(self.boss_user)
		self.assertIn(doc.name, [r["name"] for r in srt.mine()["waiting"]])

	def test_forward_target_must_be_an_active_employee(self):
		doc = new_request(self.tech_user)
		frappe.set_user(self.boss_user)
		with self.assertRaises(frappe.ValidationError):
			srt.forward(doc.name, "HR-EMP-NOPE")
		self.assertTrue(srt.people("Khalid"))
