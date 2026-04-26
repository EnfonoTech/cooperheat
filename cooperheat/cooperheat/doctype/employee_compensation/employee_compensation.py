# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class EmployeeCompensation(Document):
	def validate(self):
		self.derive_employee_category()
		if not self.employee_category:
			frappe.throw(_("Employee Category is required."))
		if not self.from_date:
			frappe.throw(_("Effective From is required."))

	def derive_employee_category(self):
		"""Set employee_category from the linked Employee's Nationality:
		   nationality.is_local → Saudi, otherwise → Expat. Always overrides
		   any manual value to keep it consistent with the Employee record."""
		if not self.employee:
			return
		nationality = frappe.db.get_value("Employee", self.employee, "nationality")
		if not nationality:
			return
		is_local = frappe.db.get_value("Nationality", nationality, "is_local")
		self.employee_category = "Saudi" if is_local else "Expat"

		dup = frappe.db.get_value(
			"Employee Compensation",
			filters={
				"employee": self.employee,
				"from_date": self.from_date,
				"name": ["!=", self.name or ""],
			},
			fieldname="name",
		)
		if dup:
			frappe.throw(
				_("Another compensation record exists for {0} from {1}: {2}").format(
					self.employee, self.from_date, dup
				)
			)
