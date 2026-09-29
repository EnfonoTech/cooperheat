# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Bulk salary-slip pipeline driven from a Payroll Import.

	Create Salary Slips  ->  Submit Salary Slips  ->  Send Salary Slip Emails

Each step walks the import's log rows one by one. A row runs inside its own
savepoint and is committed on its own, and the outcome is written straight back
onto the row - so one bad employee never stops the next one, and the table always
shows the true state per employee.

Row state is derived, not trusted: the slip state is read from Payroll Sheet /
Salary Slip and the mail state from the Email Queue. ``compute_rows`` is the only
place that reads those documents, so the form, the background jobs and the
Salary Slip Dispatch Status report cannot disagree.

Mail goes through the standard Email Queue (retries, error text and the sent log
come for free). We keep the queue name on the row and mirror its status back.
"""

from contextlib import contextmanager
from datetime import date

import frappe
from frappe import _
from frappe.utils import (
	cint,
	cstr,
	escape_html,
	flt,
	getdate,
	now_datetime,
	strip_html,
	time_diff_in_seconds,
	validate_email_address,
)

from cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet import (
	create_salary_slip,
	days_in_month,
	month_index,
)

IMPORT_DT = "Payroll Import"
ROW_DT = "Payroll Import Row"
SLIP_DT = "Salary Slip"
ALLOWED_ROLES = ["System Manager", "HR Manager"]

ACTIONS = {
	"create_slips": "Create Salary Slips",
	"submit_slips": "Submit Salary Slips",
	"send_emails": "Send Salary Slip Emails",
}

# A queued/running action that has not touched its heartbeat for this long is dead.
STALE_AFTER_SECONDS = 15 * 60

NO_EMAIL_MESSAGE = "No email address on the Employee record"

# Email Queue.status -> Payroll Import Row.email_status
QUEUE_STATUS = {
	"Sent": "Sent",
	"Not Sent": "Queued",
	"Sending": "Queued",
	"Partially Sent": "Failed",
	"Error": "Failed",
	"Expired": "Failed",
}

SLIP_STATUS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}

ROW_FIELDS = [
	"name", "idx", "doc_no", "code", "employee", "employee_name", "payroll_sheet", "row_status", "message",
	"salary_slip", "slip_status", "slip_error",
	"email_status", "email_to", "email_sent_on", "email_error", "email_queue",
]

# The columns compute_rows() derives and sync_rows() writes back onto each row.
STATE_FIELDS = [
	"salary_slip", "slip_status", "slip_error",
	"email_status", "email_to", "email_sent_on", "email_error", "email_queue",
]

SHEET_FIELDS = ["name", "docstatus", "salary_slip", "employee", "month", "year", "net_payable", "currency"]
SLIP_FIELDS = ["name", "docstatus", "employee", "start_date", "end_date", "net_pay", "currency"]
QUEUE_FIELDS = ["name", "status", "error", "modified", "retry"]
EMPLOYEE_FIELDS = [
	"name", "employee_name", "department", "prefered_email", "company_email", "personal_email", "user_id",
]


# ---------------------------------------------------------------------------
# Row state (single source of truth)
# ---------------------------------------------------------------------------

def employee_email(emp):
	"""First usable address: the preferred one, then company, personal, then the login id."""
	for field in ("prefered_email", "company_email", "personal_email", "user_id"):
		value = cstr(emp.get(field)).strip()
		if value and validate_email_address(value):
			return value
	return ""


def _live(slip):
	return bool(slip) and cint(slip.docstatus) != 2


def _last_line(text):
	lines = [ln.strip() for ln in cstr(text).splitlines() if ln.strip()]
	return lines[-1][:300] if lines else ""


def _period(sheet):
	month = month_index(sheet.month)
	year = cint(sheet.year)
	if not (month and year):
		return None
	return date(year, month, 1), date(year, month, days_in_month(year, sheet.month))


def _rows(name, row_names=None):
	filters = {"parent": name, "parenttype": IMPORT_DT, "parentfield": "rows"}
	if row_names:
		filters["name"] = ["in", list(row_names)]
	return frappe.get_all(
		ROW_DT, filters=filters, fields=ROW_FIELDS, order_by="idx asc, creation asc",
		parent_doctype=IMPORT_DT, limit_page_length=0,
	)


def import_rows(name):
	"""The log rows of a Payroll Import, with the stored slip / mail columns (used by the report)."""
	return _rows(name)


def _never_mailed(r):
	return not r.email_queue and r.email_status in ("", "Skipped", None)


def _load(rows):
	"""Batch-read everything the row states depend on - a handful of queries, not N per row."""
	ctx = frappe._dict(
		sheets={}, slips={}, by_period={}, employees={}, queues={}, latest_queue={}, recipient={}, row_slip={},
	)

	sheet_names = sorted({r.payroll_sheet for r in rows if r.payroll_sheet})
	if sheet_names:
		for s in frappe.get_all(
			"Payroll Sheet", filters={"name": ["in", sheet_names]}, fields=SHEET_FIELDS, limit_page_length=0
		):
			ctx.sheets[s.name] = s

	linked = sorted({s.salary_slip for s in ctx.sheets.values() if s.salary_slip})
	if linked:
		for s in frappe.get_all(
			SLIP_DT, filters={"name": ["in", linked]}, fields=SLIP_FIELDS, limit_page_length=0
		):
			ctx.slips[s.name] = s

	# A sheet whose back-link is empty or cancelled may still have a slip made another way.
	orphans = [s for s in ctx.sheets.values() if not _live(ctx.slips.get(s.salary_slip))]
	periods = [p for p in (_period(s) for s in orphans) if p]
	if periods:
		for s in frappe.get_all(
			SLIP_DT,
			filters={
				"employee": ["in", sorted({o.employee for o in orphans})],
				"docstatus": ["<", 2],
				"start_date": [">=", min(p[0] for p in periods)],
				"end_date": ["<=", max(p[1] for p in periods)],
			},
			fields=SLIP_FIELDS, order_by="creation asc", limit_page_length=0,
		):
			# oldest first, so the newest slip for a period wins
			ctx.by_period[(s.employee, getdate(s.start_date), getdate(s.end_date))] = s

	for r in rows:
		sheet = ctx.sheets.get(r.payroll_sheet)
		if not sheet:
			continue
		linked_slip = ctx.slips.get(sheet.salary_slip) if sheet.salary_slip else None
		slip = linked_slip if _live(linked_slip) else None
		if not slip:
			period = _period(sheet)
			slip = ctx.by_period.get((sheet.employee, period[0], period[1])) if period else None
		# a cancelled back-link with nothing newer still shows up, as "Cancelled"
		ctx.row_slip[r.name] = slip or linked_slip

	emp_names = {r.employee for r in rows if r.employee} | {s.employee for s in ctx.sheets.values() if s.employee}
	if emp_names:
		for e in frappe.get_all(
			"Employee", filters={"name": ["in", sorted(emp_names)]}, fields=EMPLOYEE_FIELDS, limit_page_length=0
		):
			ctx.employees[e.name] = e

	stored = sorted({r.email_queue for r in rows if r.email_queue})
	if stored:
		for q in frappe.get_all(
			"Email Queue", filters={"name": ["in", stored]}, fields=QUEUE_FIELDS, limit_page_length=0
		):
			ctx.queues[q.name] = q

	# Rows never mailed from here may still have been mailed by HRMS when the slip was submitted.
	unmailed = sorted({
		ctx.row_slip[r.name].name for r in rows if _never_mailed(r) and _live(ctx.row_slip.get(r.name))
	})
	if unmailed:
		for q in frappe.get_all(
			"Email Queue",
			filters={"reference_doctype": SLIP_DT, "reference_name": ["in", unmailed]},
			fields=[*QUEUE_FIELDS, "reference_name"], order_by="creation asc", limit_page_length=0,
		):
			ctx.latest_queue[q.reference_name] = q
			ctx.queues[q.name] = q

	if ctx.queues:
		for rc in frappe.get_all(
			"Email Queue Recipient", filters={"parent": ["in", sorted(ctx.queues)]},
			fields=["parent", "recipient"], parent_doctype="Email Queue", order_by="idx asc", limit_page_length=0,
		):
			ctx.recipient.setdefault(rc.parent, rc.recipient)

	return ctx


def _state(r, ctx):
	sheet = ctx.sheets.get(r.payroll_sheet) if r.payroll_sheet else None
	slip = ctx.row_slip.get(r.name)
	emp = ctx.employees.get(r.employee or (sheet.employee if sheet else None))

	if not sheet:
		slip_status = ""
	elif slip:
		slip_status = SLIP_STATUS.get(cint(slip.docstatus), "")
	elif cint(sheet.docstatus) == 0:
		slip_status = "Sheet Draft"
	elif cint(sheet.docstatus) == 2:
		slip_status = "Sheet Cancelled"
	else:
		slip_status = "Not Created"

	# a slip error only means something while the slip is still waiting on that step
	slip_error = cstr(r.slip_error) if slip_status in ("Sheet Draft", "Not Created", "Draft") else ""
	has_slip = slip_status in ("Draft", "Submitted")
	# the address is shown as soon as there is a sheet, so a missing one can be fixed before slips exist
	address = employee_email(emp) if (emp and slip_status in ("Sheet Draft", "Not Created", "Draft", "Submitted")) else ""

	q = ctx.queues.get(r.email_queue) if r.email_queue else None
	if not q and _never_mailed(r) and _live(slip):
		q = ctx.latest_queue.get(slip.name)

	email = {"email_queue": "", "email_status": "", "email_to": "", "email_sent_on": None, "email_error": ""}
	if q:
		status = QUEUE_STATUS.get(q.status, "Queued")
		error = ""
		if status == "Failed":
			error = _last_line(q.error) or cstr(q.status)
		elif status == "Queued" and cint(q.retry) and q.error:
			error = _("Retry {0}: {1}").format(cint(q.retry), _last_line(q.error))
		keep_to = r.email_to if r.email_queue == q.name else ""
		email.update(
			email_queue=q.name,
			email_status=status,
			email_to=keep_to or ctx.recipient.get(q.name) or address,
			email_sent_on=q.modified if status == "Sent" else None,
			email_error=error,
		)
	elif r.email_queue:
		# the queue entry is gone (log clean-up removes old ones)
		if r.email_status == "Sent":
			email.update(email_queue=r.email_queue, email_status="Sent", email_to=r.email_to, email_sent_on=r.email_sent_on)
		else:
			email.update(
				email_status="Failed", email_to=r.email_to or address,
				email_error=_("The queued email no longer exists. Send it again."),
			)
	elif r.email_status == "Failed" and has_slip:
		# the attempt failed before anything was queued - keep the reason
		email.update(email_status="Failed", email_to=r.email_to or address, email_error=cstr(r.email_error))
	elif has_slip:
		email["email_to"] = address
		if not address:
			email.update(email_status="Skipped", email_error=_(NO_EMAIL_MESSAGE))
	else:
		email["email_to"] = address  # no slip yet: show the address, flag nothing

	return {
		"salary_slip": slip.name if slip else "",
		"slip_status": slip_status,
		"slip_error": slip_error,
		**email,
	}


def compute_rows(rows):
	"""Return ({row name: state}, ctx) - the true state of each row, read from the source documents."""
	ctx = _load(rows)
	return {r.name: _state(r, ctx) for r in rows}, ctx


def _norm(value):
	return "" if value in (None, "") else cstr(value)


def _persist(rows, states):
	changed = 0
	for r in rows:
		state = states.get(r.name)
		if not state:
			continue
		diff = {k: state[k] for k in STATE_FIELDS if _norm(r.get(k)) != _norm(state[k])}
		if diff:
			frappe.db.set_value(ROW_DT, r.name, diff, update_modified=False)
			changed += 1
	return changed


def sync_rows(name, row_names=None):
	"""Refresh the slip and mail columns from the source documents. Returns how many rows changed."""
	rows = _rows(name, row_names)
	states, _ctx = compute_rows(rows)
	return _persist(rows, states)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summary(name):
	rows = _rows(name)
	s = frappe._dict(
		rows=len(rows), with_sheet=0, sheet_draft=0, not_created=0,
		slip_draft=0, slip_submitted=0, slip_cancelled=0,
		mail_pending=0, mail_queued=0, mail_sent=0, mail_failed=0, mail_skipped=0, no_address=0, needs_sync=0,
	)
	slip_key = {
		"Sheet Draft": "sheet_draft", "Not Created": "not_created", "Draft": "slip_draft",
		"Submitted": "slip_submitted", "Cancelled": "slip_cancelled",
	}
	mail_key = {"Queued": "mail_queued", "Sent": "mail_sent", "Failed": "mail_failed", "Skipped": "mail_skipped"}

	for r in rows:
		if not r.payroll_sheet:
			continue
		s.with_sheet += 1
		if not r.slip_status:
			s.needs_sync += 1
			continue
		if r.slip_status in slip_key:
			s[slip_key[r.slip_status]] += 1
		if r.slip_status in ("Sheet Draft", "Not Created", "Draft", "Submitted") and not r.email_to:
			s.no_address += 1
		if r.slip_status not in ("Draft", "Submitted"):
			continue
		if r.email_status in mail_key:
			s[mail_key[r.email_status]] += 1
			if r.email_status == "Queued":
				s.needs_sync += 1
		elif r.slip_status == "Submitted":
			s.mail_pending += 1

	bulk = frappe.db.get_value(
		IMPORT_DT, name, ["status", "bulk_action", "bulk_status", "bulk_message", "bulk_updated_on"], as_dict=True
	) or {}
	active = bulk.get("bulk_status") in ("Queued", "Running")
	s["import_status"] = bulk.get("status")
	s["bulk"] = {
		"action": bulk.get("bulk_action"),
		"status": bulk.get("bulk_status"),
		"message": bulk.get("bulk_message"),
		"updated_on": bulk.get("bulk_updated_on"),
		"stale": 1 if (active and _is_stale(bulk.get("bulk_updated_on"))) else 0,
	}
	return s


# ---------------------------------------------------------------------------
# Whitelisted API
# ---------------------------------------------------------------------------

def _check_access(name):
	frappe.only_for(ALLOWED_ROLES)
	if not frappe.db.exists(IMPORT_DT, name):
		frappe.throw(_("Payroll Import {0} not found.").format(name), frappe.DoesNotExistError)
	frappe.has_permission(IMPORT_DT, "write", doc=name, throw=True)


@frappe.whitelist()
def get_summary(name: str):
	"""Counts for the form's progress panel. Reads what is stored on the rows - cheap enough to poll."""
	_check_access(name)
	return _summary(name)


@frappe.whitelist()
def refresh_status(name: str):
	"""Re-read slips and mail status from the source documents and store them on the rows."""
	_check_access(name)
	changed = sync_rows(name)
	frappe.db.commit()
	return {"changed": changed, "summary": _summary(name)}


@frappe.whitelist()
def start_bulk(name: str, action: str, options=None):
	"""Queue one pipeline step for the whole import. Returns at once; poll get_summary for progress."""
	_check_access(name)
	if action not in ACTIONS:
		frappe.throw(_("Unknown action {0}.").format(action))
	options = frappe._dict(frappe.parse_json(options) if options else {})

	state = frappe.db.get_value(IMPORT_DT, name, ["status", "bulk_status", "bulk_updated_on"], as_dict=True)
	if state.status != "Completed":
		frappe.throw(_("Run the import to completion first (status is {0}).").format(state.status))
	if state.bulk_status in ("Queued", "Running") and not _is_stale(state.bulk_updated_on):
		frappe.throw(_("Another salary slip action is still running for this import. Wait for it to finish."))
	if action == "send_emails":
		_assert_outgoing_email()

	_set_bulk(name, bulk_action=ACTIONS[action], bulk_status="Queued", bulk_message=_("Waiting for a worker..."))
	job = frappe.enqueue(
		"cooperheat.cooperheat.doctype.payroll_import.slip_dispatch.run_bulk",
		queue="long", timeout=7200, job_id=f"payroll_import_bulk::{name}", deduplicate=True,
		name=name, action=action, options=dict(options),
	)
	if not job:
		frappe.throw(_("An action for this import is already queued. Wait for it to finish."))
	return {"queued": True}


@frappe.whitelist()
def resend_email(name: str, row: str):
	"""Send (or send again) the salary slip email for one employee, straight from the table."""
	_check_access(name)
	_assert_outgoing_email()

	sync_rows(name, [row])
	rows = _rows(name, [row])
	if not rows:
		frappe.throw(_("Row {0} does not belong to {1}.").format(row, name))
	r = rows[0]
	who = r.employee_name or r.employee or r.code

	if r.slip_status != "Submitted":
		frappe.throw(_("Submit {0}'s salary slip before emailing it.").format(who))
	if r.email_status == "Queued":
		frappe.throw(_("An email for {0} is already waiting in the queue - give it a minute.").format(who))
	if not r.email_to:
		frappe.throw(_("{0}: {1}.").format(who, _(NO_EMAIL_MESSAGE)))

	outcome = _process(name, "send_emails", r, r, frappe._dict())
	fresh = _rows(name, [row])[0]
	return {
		"outcome": outcome,
		"email_status": fresh.email_status,
		"email_error": fresh.email_error,
		"summary": _summary(name),
	}


# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------

def _is_stale(updated_on):
	return not updated_on or time_diff_in_seconds(now_datetime(), updated_on) > STALE_AFTER_SECONDS


def _set_bulk(name, **fields):
	fields["bulk_updated_on"] = now_datetime()
	frappe.db.set_value(IMPORT_DT, name, fields, update_modified=False)
	frappe.db.commit()


def _assert_outgoing_email():
	account = frappe.db.get_value(
		"Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, ["name", "awaiting_password"], as_dict=True
	)
	if not account and not frappe.conf.get("mail_server"):
		frappe.throw(_("No default outgoing Email Account is set up. Configure one under Email Account first."))
	if account and cint(account.awaiting_password):
		frappe.throw(
			_("Email Account {0} is still awaiting its password. Save the password there first.").format(account.name)
		)


def _eligible(action, state, options):
	slip_status = state["slip_status"]
	if action == "create_slips":
		return slip_status == "Not Created" or (slip_status == "Sheet Draft" and cint(options.get("submit_sheets")))
	if action == "submit_slips":
		return slip_status == "Draft"
	if action == "send_emails":
		if slip_status != "Submitted":
			return False
		if state["email_status"] == "Queued":
			return False  # never double-queue
		if state["email_status"] == "Sent":
			return bool(cint(options.get("resend_all")))
		return True  # never sent, failed earlier, or no address (skipped again if still none)
	return False


def run_bulk(name, action, options=None):
	"""Background job: run one pipeline step over every eligible row of the import."""
	options = frappe._dict(options or {})
	label = ACTIONS[action]
	counts = frappe._dict(ok=0, failed=0, skipped=0)
	try:
		_set_bulk(name, bulk_status="Running", bulk_message=_("Working out what to do..."))
		sync_rows(name)
		frappe.db.commit()

		rows = _rows(name)
		states, _ctx = compute_rows(rows)
		todo = [r for r in rows if _eligible(action, states[r.name], options)]
		total = len(todo)

		for i, r in enumerate(todo, 1):
			counts[_process(name, action, r, states[r.name], options)] += 1
			_set_bulk(name, bulk_message=_("{0}: {1} of {2}").format(label, i, total))

		_set_bulk(name, bulk_status="Completed", bulk_message=_summary_line(action, counts, total))
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title=f"Payroll Import {name}: {label} stopped", message=frappe.get_traceback())
		_set_bulk(
			name, bulk_status="Failed",
			bulk_message=_("{0} stopped unexpectedly after {1} employee(s). See the Error Log.").format(
				label, counts.ok + counts.failed + counts.skipped
			),
		)


def _summary_line(action, counts, total):
	if not total:
		return _("Nothing to do - no employee needed this step.")
	verb = {"create_slips": _("Created"), "submit_slips": _("Submitted"), "send_emails": _("Queued")}[action]
	noun = _("email(s)") if action == "send_emails" else _("salary slip(s)")
	line = _("{0} {1} {2}").format(verb, counts.ok, noun)
	if counts.skipped:
		line += _("; {0} skipped ({1})").format(counts.skipped, _(NO_EMAIL_MESSAGE).lower())
	if counts.failed:
		reason = _("Email Note") if action == "send_emails" else _("Slip Error")
		line += _("; {0} failed - see {1} in the table").format(counts.failed, reason)
	return line + "."


def _process(name, action, r, state, options):
	"""Run one step for one row. Never raises; returns 'ok', 'skipped' or 'failed'."""
	frappe.db.savepoint("dispatch_row")
	error = ""
	try:
		if action == "send_emails":
			outcome = _step_send(r, state)
		else:
			STEPS[action](r, state, options)
			outcome = "ok"
	except Exception as e:
		_rollback_row()
		outcome, error = "failed", _error_text(e)
		if not isinstance(e, frappe.ValidationError | frappe.PermissionError):
			frappe.log_error(
				title=f"Payroll Import {name}: {ACTIONS[action]} failed for {r.employee or r.code}",
				message=frappe.get_traceback(),
			)
	frappe.clear_messages()  # drop popups the step queued; the reason lives on the row

	sync_rows(name, [r.name])
	if outcome == "failed":
		if action == "send_emails":
			frappe.db.set_value(
				ROW_DT, r.name, {"email_status": "Failed", "email_error": error, "email_queue": ""},
				update_modified=False,
			)
		else:
			frappe.db.set_value(ROW_DT, r.name, "slip_error", error, update_modified=False)
	frappe.db.commit()
	return outcome


def _rollback_row():
	"""Undo the failed row's uncommitted work.

	Rendering a PDF writes an Access Log and commits, which releases the savepoint mid-step.
	When that happened, fall back to rolling back whatever is still uncommitted - the failed
	row must never take the rest of the run down with it."""
	try:
		frappe.db.rollback(save_point="dispatch_row")
	except Exception:
		frappe.db.rollback()


def _error_text(e):
	if isinstance(e, frappe.ValidationError | frappe.PermissionError):
		text = strip_html(cstr(e))
	else:
		text = f"{type(e).__name__}: {e}"
	return text.strip()[:500]


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@contextmanager
def _mailing_is_separate():
	"""HRMS mails a slip from Salary Slip.on_submit when Payroll Settings has "Email Salary
	Slip to Employee" on - a fire-and-forget job with no status and no way to retry. Setting
	HRMS's own via_payroll_entry flag keeps mailing a separate, tracked step."""
	previous = frappe.flags.via_payroll_entry
	frappe.flags.via_payroll_entry = True
	try:
		yield
	finally:
		frappe.flags.via_payroll_entry = previous


def assert_slip_matches_sheet(slip_name, sheet_name):
	"""Refuse a slip whose net pay is not what the Payroll Sheet worked out.

	HRMS fills in the Salary Structure's own default amounts when none of the mapped components
	has a value (e.g. an employee with zero worked days), so a slip can quietly come out with a
	different - non-zero - net than the sheet. In a bulk run that would be emailed to the employee."""
	sheet_net = flt(frappe.db.get_value("Payroll Sheet", sheet_name, "net_payable"), 2)
	slip_net = flt(frappe.db.get_value(SLIP_DT, slip_name, "net_pay"), 2)
	if abs(slip_net - sheet_net) > 0.01:
		frappe.throw(
			_(
				"Net pay on the Salary Slip ({0}) does not match the Payroll Sheet ({1}). "
				"Check the Salary Structure and the Component Mapping, then create or submit this one individually."
			).format(f"{slip_net:,.2f}", f"{sheet_net:,.2f}")
		)


def _step_create(r, state, options):
	if state["slip_status"] == "Sheet Draft":
		sheet = frappe.get_doc("Payroll Sheet", r.payroll_sheet)
		sheet.flags.ignore_permissions = True
		sheet.submit()
	slip_name = create_salary_slip(r.payroll_sheet)
	assert_slip_matches_sheet(slip_name, r.payroll_sheet)  # raises -> this employee's work is rolled back


def _step_submit(r, state, options):
	assert_slip_matches_sheet(state["salary_slip"], r.payroll_sheet)
	slip = frappe.get_doc(SLIP_DT, state["salary_slip"])
	slip.flags.ignore_permissions = True
	with _mailing_is_separate():
		slip.submit()


def _step_send(r, state):
	address = state["email_to"]
	if not address:
		return "skipped"
	queue = queue_slip_email(state["salary_slip"], address)
	frappe.db.set_value(
		ROW_DT, r.name,
		{
			"email_queue": queue, "email_status": "Queued", "email_to": address,
			"email_error": "", "email_sent_on": None,
		},
		update_modified=False,
	)
	return "ok"


STEPS = {"create_slips": _step_create, "submit_slips": _step_submit}


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def slip_print_format():
	"""The Print Format for the emailed PDF: Pay Sheet Settings, else "Salary Slip" if present."""
	try:
		chosen = frappe.db.get_single_value("Pay Sheet Settings", "slip_print_format")
	except frappe.ValidationError:
		chosen = None  # the field arrives with the doctype reload; until then use the default
	if chosen and frappe.db.exists("Print Format", {"name": chosen, "disabled": 0}):
		return chosen
	if frappe.db.exists("Print Format", {"name": "Salary Slip", "doc_type": SLIP_DT, "disabled": 0}):
		return "Salary Slip"
	return None


def _compose(slip, settings):
	"""Subject and message. Payroll Settings' Email Template wins, exactly as it does in HRMS."""
	if settings.email_template:
		template = frappe.get_doc("Email Template", settings.email_template)
		rendered = template.get_formatted_email(slip.as_dict())
		return rendered["subject"], rendered["message"]

	subject = f"Salary Slip - from {slip.start_date} to {slip.end_date}"
	message = "<p>{greeting}</p><p>{body}</p><p>{regards}<br>{company}</p>".format(
		greeting=_("Dear {0},").format(escape_html(cstr(slip.employee_name))),
		body=_("Please find attached your salary slip for the period {0} to {1}.").format(
			slip.start_date, slip.end_date
		),
		regards=_("Regards,"),
		company=escape_html(cstr(slip.company)),
	)
	return subject, message


def queue_slip_email(slip_name, address):
	"""Put one salary slip email (PDF attached) on the Email Queue. Returns the queue name."""
	slip = frappe.get_doc(SLIP_DT, slip_name)
	if cint(slip.docstatus) != 1:
		frappe.throw(_("Salary Slip {0} is not submitted.").format(slip_name))

	settings = frappe.get_single("Payroll Settings")
	subject, message = _compose(slip, settings)

	password = None
	if cint(settings.encrypt_salary_slips_in_emails):
		from hrms.payroll.doctype.salary_slip.salary_slip import generate_password_for_pdf

		password = generate_password_for_pdf(settings.password_policy, slip.employee)
		if not settings.email_template:
			message += "<p>" + _(
				"Note: Your salary slip is password protected, the password to unlock the PDF is of the format {0}."
			).format(settings.password_policy) + "</p>"

	attachment = frappe.attach_print(
		SLIP_DT, slip.name,
		file_name=f"Payslip-{slip.employee}-{getdate(slip.start_date).strftime('%B-%Y')}",
		print_format=slip_print_format(), password=password,
	)
	queued = frappe.sendmail(
		recipients=[address],
		sender=settings.sender_email or "",
		subject=subject,
		message=message,
		attachments=[attachment],
		reference_doctype=SLIP_DT,
		reference_name=slip.name,
	)
	if not queued:
		frappe.throw(_("The email was not queued - the address may be invalid or unsubscribed."))
	return queued.name
