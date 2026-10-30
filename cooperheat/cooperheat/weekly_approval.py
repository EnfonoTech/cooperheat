"""Weekly Attendance Approval (client, 2026-10-30).

An employee with the tick box "Weekly Attendance Approval" has their Direct / Immediate
Reporting person approve attendance once a week instead of daily:

* no e-mail per attendance at that level (overrides/attendance._send_notification_for_level);
* one summary e-mail per manager on the review day (send_weekly_summaries, scheduler cron);
* the escalation window of that level starts at the next review, so nothing moves on before
  the manager has had the summary: expires = next review + the level's usual window (72 h for
  Level 2 by default), then the hourly job passes it on as today.

Defaults until the client decides: review Sunday 08:00 (site time), move on after the window.
"""

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, escape_html, format_datetime, get_datetime, get_url, now_datetime

from cooperheat.cooperheat import org

REVIEW_WEEKDAY = 6  # Monday = 0 ... Sunday = 6
REVIEW_HOUR = 8
PENDING_STATES = ("Pending Level 1 Approval", "Pending Level 2 Approval", "Pending Level 3 Approval")


def next_review(after) -> datetime:
	"""The first review moment (REVIEW_WEEKDAY at REVIEW_HOUR:00) strictly after ``after``."""
	after = get_datetime(after)
	day = after.replace(hour=REVIEW_HOUR, minute=0, second=0, microsecond=0)
	day += timedelta(days=(REVIEW_WEEKDAY - day.weekday()) % 7)
	if day <= after:
		day += timedelta(days=7)
	return day


def window_expiry(level: int, now=None) -> datetime:
	"""When a weekly level escalates: the next review plus that level's usual window."""
	return add_to_date(next_review(now or now_datetime()), hours=org.window_hours(level))


def pending_for_weekly_review() -> dict[str, list]:
	"""Pending attendance waiting for a weekly approver, grouped by approver (Employee)."""
	rows = frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "workflow_state": ["in", list(PENDING_STATES)], "current_approver": ["is", "set"]},
		fields=["name", "employee", "employee_name", "attendance_date", "current_approver", "window_expires_at"],
		order_by="attendance_date asc",
	)
	if not rows:
		return {}
	weekly = {
		e.name: e.reports_to
		for e in frappe.get_all(
			"Employee",
			filters={"name": ["in", list({r.employee for r in rows})], org.WEEKLY_FIELD: 1},
			fields=["name", "reports_to"],
		)
	}
	out: dict[str, list] = {}
	for r in rows:
		# only the level the Direct / Immediate Reporting person holds is weekly
		if weekly.get(r.employee) and weekly[r.employee] == r.current_approver:
			out.setdefault(r.current_approver, []).append(r)
	return out


def _summary_html(name: str, rows: list, url: str) -> str:
	by_emp: dict[str, list] = {}
	for r in rows:
		by_emp.setdefault(r.employee_name or r.employee, []).append(r.attendance_date)
	table = "".join(
		"<tr><td>" + escape_html(emp) + "</td><td style='text-align:right'>" + str(len(dates)) + "</td><td>"
		+ str(min(dates)) + " - " + str(max(dates)) + "</td></tr>"
		for emp, dates in sorted(by_emp.items())
	)
	deadlines = [get_datetime(r.window_expires_at) for r in rows if r.window_expires_at]
	until = format_datetime(min(deadlines)) if deadlines else ""
	return (
		"<p>" + _("Dear {0},").format(escape_html(name)) + "</p>"
		+ "<p>" + _("These attendance records are waiting for your weekly approval:") + "</p>"
		+ "<table border='1' cellpadding='5' style='border-collapse:collapse'><tr><th>"
		+ _("Employee") + "</th><th>" + _("Days") + "</th><th>" + _("Dates") + "</th></tr>" + table + "</table>"
		+ "<p><a href='" + url + "'>" + _("Open the list") + "</a>: "
		+ _("tick the records and choose Actions, Approve; or use Approve all in the app.")
		+ (" " + _("Records still waiting on {0} move on to the next approver.").format(until) if until else "")
		+ "</p>"
	)


def send_weekly_summaries() -> dict:
	"""Scheduler (review day, REVIEW_HOUR): one e-mail per weekly approver with what is waiting."""
	sent = {}
	for approver, rows in pending_for_weekly_review().items():
		email = (
			frappe.db.get_value("Employee", approver, "company_email")
			or frappe.db.get_value("Employee", approver, "personal_email")
			or frappe.db.get_value("Employee", approver, "user_id")
		)
		if not email:
			frappe.log_error(title="Weekly attendance summary: no e-mail", message=approver)
			continue
		name = frappe.db.get_value("Employee", approver, "employee_name") or approver
		url = get_url("/app/attendance?docstatus=1&current_approver=" + approver)
		try:
			frappe.sendmail(
				recipients=[email],
				subject=_("Weekly attendance approval: {0} records waiting").format(len(rows)),
				message=_summary_html(name, rows, url),
				now=False,
			)
		except Exception:
			# one bad mailbox (or no outgoing account) must not stop the other summaries
			frappe.log_error(title="Weekly attendance summary not sent: " + approver)
			continue
		sent[approver] = len(rows)
	return sent
