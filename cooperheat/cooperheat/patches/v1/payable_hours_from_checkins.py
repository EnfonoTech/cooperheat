"""Site Hours swap (client call 2026-10-25): check-in hours are now Payable Hours,
Billable is a tick box or typed by the supervisor.

Rows where nobody entered Payable Hours get the check-in hours (until now kept in
Billable Hours). Billable Hours stay as they are; the new Billable tick box starts
unticked. Pay does not change: the payroll reports read Payable from now on and
fell back to these same hours before.
"""

import frappe


def execute():
	ash = frappe.qb.DocType("Attendance Site Hours")
	(
		frappe.qb.update(ash)
		.set(ash.payroll_hours, ash.hours)
		.where(ash.parentfield == "custom_site_hours")
		.where((ash.payroll_hours.isnull()) | (ash.payroll_hours == 0))
		.where(ash.hours > 0)
	).run()
