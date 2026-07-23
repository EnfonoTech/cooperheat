import frappe
from frappe import _
from frappe.utils import getdate


def validate(doc, method):
	_auto_set_project(doc)
	_validate_no_open_checkin(doc)
	_validate_no_overlap(doc)


def after_insert(doc, method):
	_sync_attendance_site_hours(doc)


def on_update(doc, method):
	_sync_attendance_site_hours(doc)


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

	checkin_date = getdate(doc.time)
	date_str = str(checkin_date)

	# Find the last IN that has no matching OUT yet (open checkin)
	last_in = frappe.db.get_value(
		"Employee Checkin",
		{
			"employee": doc.employee,
			"log_type": "IN",
			"time": ["between", [date_str + " 00:00:00", date_str + " 23:59:59"]],
			"name": ["!=", doc.name],
		},
		["custom_project", "time"],
		as_dict=True,
		order_by="time desc",
	)
	doc.custom_project = last_in.custom_project if last_in else None


def _validate_no_open_checkin(doc):
	"""Block a new IN if the employee's last checkin on that day is also an IN (no checkout yet)."""
	if doc.log_type != "IN" or not doc.employee or not doc.time:
		return

	date_str = str(getdate(doc.time))
	filters = [
		["employee", "=", doc.employee],
		["time", ">=", date_str + " 00:00:00"],
		["time", "<=", date_str + " 23:59:59"],
	]
	if not doc.is_new():
		filters.append(["name", "!=", doc.name])

	last = frappe.db.get_value(
		"Employee Checkin",
		filters,
		["log_type", "custom_project", "time"],
		as_dict=True,
		order_by="time desc",
	)

	if last and last.log_type == "IN":
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

	attendance_date = getdate(doc.time)
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
