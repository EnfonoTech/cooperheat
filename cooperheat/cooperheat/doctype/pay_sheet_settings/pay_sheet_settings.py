# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PaySheetSettings(Document):
	def validate(self):
		if self.monthly_working_hours and self.monthly_working_hours <= 0:
			frappe.throw("Monthly Working Hours must be greater than zero.")
		if self.gosi_rate_percent is not None and self.gosi_rate_percent < 0:
			frappe.throw("GOSI Rate cannot be negative.")
