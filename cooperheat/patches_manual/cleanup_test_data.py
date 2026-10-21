"""Remove demo / testing attendance data from before go-live. MANUAL, never auto-run.

Scope (agreed with the client 2026-10-13: "delete only testing data"):
* Employee Checkin dated before `cutoff`;
* Attendance dated from `attendance_from` up to (not including) `cutoff`, any status;
* Attendance Request starting before `cutoff`.
Attendance before `attendance_from` (the March import used for payroll) is kept.

Deleted documents go to the Deleted Document list (restorable from the desk).
Take a database backup first. `dry_run=1` (the default) only counts.

	bench --site <site> execute cooperheat.patches_manual.cleanup_test_data.run \
		--kwargs "{'dry_run': 1}"
"""

import frappe
from frappe.utils import cint


def run(cutoff="2026-10-01", attendance_from="2026-04-01", dry_run=1):
	frappe.only_for("System Manager")
	dry_run = cint(dry_run)

	checkins = frappe.get_all(
		"Employee Checkin", filters={"time": ["<", cutoff + " 00:00:00"]}, pluck="name", limit=0
	)
	attendance = frappe.get_all(
		"Attendance",
		filters={"attendance_date": ["between", [attendance_from, _day_before(cutoff)]]},
		fields=["name", "docstatus"],
		limit=0,
	)
	requests = frappe.get_all(
		"Attendance Request", filters={"from_date": ["<", cutoff]}, fields=["name", "docstatus"], limit=0
	)
	kept = frappe.db.count("Attendance", {"attendance_date": ["<", attendance_from]})
	report = {
		"dry_run": dry_run,
		"checkins": len(checkins),
		"attendance": len(attendance),
		"attendance_requests": len(requests),
		"attendance_kept_before_" + attendance_from: kept,
	}
	if dry_run:
		return report

	# Check-ins first: they point at Attendance.
	for name in checkins:
		frappe.db.set_value("Employee Checkin", name, "attendance", None, update_modified=False)
		frappe.delete_doc(
			"Employee Checkin", name, force=True, ignore_permissions=True, delete_permanently=False
		)
	for row in attendance:
		_delete(row, "Attendance")
	for row in requests:
		_delete(row, "Attendance Request")
	frappe.db.commit()
	report["checkins_left"] = frappe.db.count("Employee Checkin", {"time": ["<", cutoff + " 00:00:00"]})
	report["attendance_left_in_range"] = frappe.db.count(
		"Attendance", {"attendance_date": ["between", [attendance_from, _day_before(cutoff)]]}
	)
	return report


def _day_before(day):
	from frappe.utils import add_days

	return str(add_days(day, -1))


def _delete(row, doctype):
	if row.docstatus == 1:
		# Submitted: mark cancelled in place so Frappe lets it go, without running
		# the cancel hooks (these are old test records, no ledger or payroll behind them).
		frappe.db.set_value(doctype, row.name, "docstatus", 2, update_modified=False)
	frappe.delete_doc(doctype, row.name, force=True, ignore_permissions=True, delete_permanently=False)
