from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime


def validate(doc, method):
	_enforce_edit_window(doc)
	_auto_set_project(doc)
	_validate_no_open_checkin(doc)
	_validate_no_instant_checkout(doc)
	_validate_no_overlap(doc)


# A check-out seconds after the check-in is a second tap, not a shift (production, 28 Oct:
# an iPhone user tapped twice and turned every check-in into a 30-second pair).
MIN_SHIFT = timedelta(minutes=2)


def _validate_no_instant_checkout(doc):
	if not doc.is_new() or doc.log_type != "OUT" or not doc.employee or not doc.time:
		return
	from cooperheat.cooperheat.work_day import open_in_before

	opened = open_in_before(doc.employee, doc.time)
	if opened and get_datetime(doc.time) - get_datetime(opened.time) < MIN_SHIFT:
		frappe.throw(
			_("You checked in at {0}. A check-out is possible from 2 minutes after the check-in.").format(
				get_datetime(opened.time).strftime("%H:%M")
			),
			title=_("Already checked in"),
		)


def after_insert(doc, method):
	_sync_attendance_site_hours(doc)


def on_update(doc, method):
	_sync_attendance_site_hours(doc)


_FINAL_STATES = ("Approved", "Rejected")
_CLOCK_SKEW = timedelta(minutes=5)


def _enforce_edit_window(doc):
	"""Supervisors/managers may record or correct a check-in time only within the
	last 48 hours (HR Manager / System Manager are exempt). Enforced on the
	document, so every route - desk form, Supervisor Workspace, mobile approval
	screen, API - is covered:

	* an existing log older than 48h cannot be changed (time, employee or type);
	* the new time can never be in the future or older than 48h;
	* a log whose Attendance is already approved/rejected is frozen for them;
	* a supervisor's own punch (created for their own Employee record) is a normal
	  check-in and not restricted on insert.

	Every change of time is written to the document timeline."""
	from cooperheat.cooperheat.api.supervisor import EDIT_WINDOW_HOURS, can_edit_checkin_time
	from cooperheat.cooperheat.permissions.scope import is_scoped

	user = frappe.session.user
	scoped = is_scoped(user)
	before = None if doc.is_new() else doc.get_doc_before_save()
	time_changed = bool(before) and get_datetime(doc.time) != get_datetime(before.time)

	if scoped:
		own = set(frappe.get_all("Employee", filters={"user_id": user}, pluck="name"))
		own_punch = doc.is_new() and doc.employee in own
		if not own_punch and (doc.is_new() or time_changed):
			new_time = get_datetime(doc.time)
			if new_time > now_datetime() + _CLOCK_SKEW:
				frappe.throw(_("A check-in time cannot be set in the future."))
			if not can_edit_checkin_time(new_time, user):
				frappe.throw(
					_("Supervisors can only record or change check-ins from the last {0} hours. "
					  "Please ask HR.").format(EDIT_WINDOW_HOURS),
					title=_("Edit window closed"),
				)
		if before:
			if not can_edit_checkin_time(before.time, user) and (
				time_changed or doc.employee != before.employee or doc.log_type != before.log_type
			):
				frappe.throw(
					_("This check-in is more than {0} hours old and can no longer be changed by a supervisor. "
					  "Please ask HR to correct it.").format(EDIT_WINDOW_HOURS),
					title=_("Edit window closed"),
				)
			if time_changed:
				state = frappe.db.get_value(
					"Attendance",
					{"employee": before.employee, "attendance_date": getdate(before.time), "docstatus": 1},
					"workflow_state",
				)
				if state in _FINAL_STATES:
					frappe.throw(
						_("The attendance for this day is already {0}. Please ask HR to correct it.").format(state)
					)

	if time_changed:
		doc.add_comment(
			"Info",
			_("Time changed from {0} to {1} by {2}").format(before.time, doc.time, user),
		)


def _auto_set_project(doc):
	"""Set custom_project automatically.

	OUT → always resynced from the most recent open IN log on the same day, so the
	      OUT is always paired with the right project - this also corrects a stale
	      value already sitting on the field (e.g. carried over from an active
	      list view filter when the record was created via "New" from a filtered
	      list). If that IN had no project, the OUT is cleared too.
	IN  → intentionally left alone. Leaving Project Site blank on an IN log is
	      a deliberate choice (department-only checkin) and must not be
	      silently overridden from the employee's Shift Assignment.
	"""
	if not doc.employee or not doc.time:
		return
	if doc.log_type != "OUT":
		return

	# The open IN before this OUT - including one from before midnight (night shift).
	from cooperheat.cooperheat.work_day import open_in_before

	last_in = open_in_before(doc.employee, doc.time, exclude=doc.name)
	doc.custom_project = last_in.custom_project if last_in else None


def _validate_no_open_checkin(doc):
	"""Block a new IN if the employee's last checkin on that day is also an IN (no checkout yet)."""
	if doc.log_type != "IN" or not doc.employee or not doc.time:
		return

	from cooperheat.cooperheat.work_day import open_in_before

	date_str = str(getdate(doc.time))
	# Still-open shift from earlier (also from before midnight) blocks a new IN.
	last = open_in_before(doc.employee, doc.time, exclude=None if doc.is_new() else doc.name)

	if last:
		project_msg = _(" at project {0}").format(last.custom_project) if last.custom_project else ""
		frappe.throw(
			_("Employee already has an open check-in{0} on {1}. Please check out first.").format(
				project_msg, date_str
			)
		)


def _validate_no_overlap(doc):
	"""Block save if this record would cause the employee's check-in pairs to overlap on the same day."""
	if not doc.employee or not doc.time:
		return

	date_str = str(getdate(doc.time))
	filters = [
		["employee", "=", doc.employee],
		["time", ">=", date_str + " 00:00:00"],
		["time", "<=", date_str + " 23:59:59"],
	]
	if not doc.is_new():
		filters.append(["name", "!=", doc.name])

	all_checkins = frappe.get_all(
		"Employee Checkin",
		filters=filters,
		fields=["name", "log_type", "time"],
		order_by="time asc",
	)

	# Build completed IN-OUT pairs from existing records
	pairs = []
	open_in = None
	for c in all_checkins:
		if c.log_type == "IN":
			open_in = c
		elif c.log_type == "OUT" and open_in:
			pairs.append((open_in.time, c.time))
			open_in = None

	def fmt(t):
		return str(t)[11:16]  # HH:MM

	if doc.log_type == "IN":
		t = doc.time
		for pair_in, pair_out in pairs:
			if pair_in <= t < pair_out:
				frappe.throw(
					_("Check-in at {0} overlaps an existing attendance period {1}–{2}.").format(
						fmt(t), fmt(pair_in), fmt(pair_out)
					)
				)

	elif doc.log_type == "OUT":
		if not open_in:
			return
		t_in = open_in.time
		t_out = doc.time
		if t_out <= t_in:
			return
		for pair_in, pair_out in pairs:
			if t_in < pair_out and t_out > pair_in:
				frappe.throw(
					_("Check-out at {0} creates a period {1}–{2} that overlaps an existing attendance {3}–{4}.").format(
						fmt(t_out), fmt(t_in), fmt(t_out), fmt(pair_in), fmt(pair_out)
					)
				)


def _sync_attendance_site_hours(doc):
	"""If submitted attendance already exists for this employee+date, recalculate site hours.

	Handles late-entry checkins added after auto-attendance has already run.
	"""
	if not doc.employee or not doc.time:
		return
	if doc.skip_auto_attendance:
		return

	# The shift's date, not the calendar date: an after-midnight OUT updates the
	# attendance of the day the shift started.
	from cooperheat.cooperheat.work_day import open_in_before

	opened = open_in_before(doc.employee, doc.time, exclude=doc.name) if doc.log_type == "OUT" else None
	attendance_date = getdate(opened.time) if opened else getdate(doc.time)
	attendance_name = frappe.db.get_value(
		"Attendance",
		{"employee": doc.employee, "attendance_date": attendance_date, "docstatus": 1},
		"name",
	)
	if not attendance_name:
		return

	att_doc = frappe.get_doc("Attendance", attendance_name)
	from cooperheat.cooperheat.overrides.attendance import _populate_site_hours, _correct_status_on_submitted
	_populate_site_hours(att_doc)
	_correct_status_on_submitted(att_doc)
