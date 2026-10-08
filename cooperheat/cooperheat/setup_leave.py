"""Leave period, policy and allocations for a year.

Without a submitted Leave Allocation, HRMS rejects every paid leave with
"Application period cannot be outside leave allocation period".

Default days follow the Saudi Labour Law minimums (annual 21 days, sick 30
days at full pay). The client must confirm them; pass `days` to override.

	bench --site <site> execute cooperheat.cooperheat.setup_leave.create_leave_setup \
		--kwargs "{'year': 2026, 'company': 'COOPERHEAT Saudi Arabia Co. Ltd'}"

Opening balances (days already used or carried) are a separate import.
"""

from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, flt

DEFAULT_DAYS = {
	"Privilege Leave": 21,
	"Sick Leave": 30,
}


def policy_title(year):
	return "Cooperheat Standard " + str(year)


def year_bounds(year):
	return date(year, 1, 1), date(year, 12, 31)


@frappe.whitelist()
def create_leave_setup(year, company, days=None, holiday_list=None):
	"""Create the leave period + policy for `year` and assign it to every
	active employee of `company` that has no assignment for that period yet.

	Idempotent. Returns a summary dict.
	"""
	frappe.only_for(("System Manager", "HR Manager"))
	year = cint(year)
	if year < 2000:
		frappe.throw(_("Enter a valid year."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company not found: {0}", [company]))
	days = frappe.parse_json(days) if isinstance(days, str) else (days or DEFAULT_DAYS)

	period = get_or_create_leave_period(year, company)
	policy = get_or_create_policy(year, days)
	assigned = assign_policy(policy, period, company)
	if holiday_list:
		frappe.db.set_value("Company", company, "default_holiday_list", holiday_list)
	return {"leave_period": period.name, "leave_policy": policy.name, "assigned": assigned}


def get_or_create_leave_period(year, company):
	start, end = year_bounds(year)
	name = frappe.db.get_value("Leave Period", {"company": company, "from_date": start, "to_date": end})
	if name:
		return frappe.get_doc("Leave Period", name)
	doc = frappe.get_doc(
		{"doctype": "Leave Period", "company": company, "from_date": start, "to_date": end, "is_active": 1}
	)
	doc.insert()
	return doc


def get_or_create_policy(year, days):
	name = frappe.db.get_value("Leave Policy", {"title": policy_title(year), "docstatus": 1})
	if name:
		return frappe.get_doc("Leave Policy", name)
	missing = [lt for lt in days if not frappe.db.exists("Leave Type", lt)]
	if missing:
		frappe.throw(_("Leave Type not found: {0}", [", ".join(missing)]))
	doc = frappe.get_doc(
		{
			"doctype": "Leave Policy",
			"title": policy_title(year),
			"leave_policy_details": [
				{"leave_type": lt, "annual_allocation": flt(n)} for lt, n in days.items()
			],
		}
	)
	doc.insert()
	doc.submit()
	return doc


def assign_policy(policy, period, company):
	employees = frappe.get_all("Employee", filters={"company": company, "status": "Active"}, pluck="name")
	already = set(
		frappe.get_all(
			"Leave Policy Assignment",
			filters={"leave_period": period.name, "docstatus": 1},
			pluck="employee",
		)
	)
	assigned = []
	for employee in employees:
		if employee in already:
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Leave Policy Assignment",
				"employee": employee,
				"leave_policy": policy.name,
				"assignment_based_on": "Leave Period",
				"leave_period": period.name,
				"effective_from": period.from_date,
				"effective_to": period.to_date,
			}
		)
		doc.insert()
		doc.submit()
		assigned.append(employee)
	return assigned
