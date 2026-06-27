import frappe
from frappe import _
from frappe.utils import cint, flt, get_url_to_form, now, now_datetime, get_datetime, time_diff_in_hours, add_to_date, getdate

# ---------------------------------------------------------------------------
# Authorization map: (prev_workflow_state, next_workflow_state) → required level
# ---------------------------------------------------------------------------
_LEVEL_REQUIRED: dict[tuple[str, str], int] = {
	("Pending Level 1 Approval", "Pending Level 2 Approval"): 1,
	("Pending Level 1 Approval", "Rejected"): 1,
	("Pending Level 2 Approval", "Pending Level 3 Approval"): 2,
	("Pending Level 2 Approval", "Rejected"): 2,
	("Pending Level 3 Approval", "Approved"): 3,
	("Pending Level 3 Approval", "Rejected"): 3,
}

_NOTIFY_LEVEL: dict[str, int] = {
	"Pending Level 1 Approval": 1,
	"Pending Level 2 Approval": 2,
	"Pending Level 3 Approval": 3,
}

_INITIAL_WORKFLOW_STATE = "Pending Level 1 Approval"


# ---------------------------------------------------------------------------
# doc_events entry points
# ---------------------------------------------------------------------------


def before_validate(doc, method):
	pass


def on_submit(doc, method):
	"""Seed initial approval state and populate per-site hours.

	Auto-attendance submits records programmatically, bypassing the workflow
	action buttons.  We therefore seed the workflow state here so the approval
	chain starts correctly for both auto-generated and manually submitted records.
	"""
	frappe.db.set_value(
		"Attendance",
		doc.name,
		"workflow_state",
		_INITIAL_WORKFLOW_STATE,
		update_modified=False,
	)
	_populate_site_hours(doc)
	_correct_status_on_submitted(doc)
	_send_notification_for_level(doc, 1)
	_stamp_tracking_fields(doc, 1)


def validate(doc, method):
	"""Block unauthorised workflow state transitions and hours edits."""
	_validate_approver_authorization(doc)
	_validate_hours_edit_authorization(doc)
	_recalculate_site_hours_from_times(doc)  # recalc row hours and sync parent times from child table
	_fill_checkin_times(doc)                 # fill in_time/out_time from checkins (draft only)
	_recalculate_working_hours(doc)          # recalc parent working_hours (skipped if site hours exist)
	_set_status_from_thresholds(doc)
	_sync_current_approver(doc)


def on_update_after_submit(doc, method):
	"""Recalculate working_hours and send notification when state advances."""
	_update_working_hours_from_site_hours(doc)
	_correct_status_on_submitted(doc)

	prev_state, new_state = _state_changed(doc)
	if not new_state:
		return
	level = _NOTIFY_LEVEL.get(new_state)
	if not level:
		return
	_send_notification_for_level(doc, level)
	_stamp_tracking_fields(doc, level)

	# If the department has no Level 3 approver configured, auto-approve
	# immediately when the record lands in "Pending Level 3 Approval".
	if new_state == "Pending Level 3 Approval":
		_auto_approve_if_no_level3(doc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fill_checkin_times(doc):
	"""Fill in_time / out_time from Employee Checkin records if they are empty on a draft record."""
	if doc.docstatus == 1:
		return
	if not doc.employee or not doc.attendance_date:
		return
	if doc.in_time and doc.out_time:
		return  # already set, nothing to do
	date_str = str(doc.attendance_date)
	checkins = frappe.get_all(
		"Employee Checkin",
		filters={"employee": doc.employee, "time": ["between", [date_str + " 00:00:00", date_str + " 23:59:59"]]},
		fields=["log_type", "time"],
		order_by="time asc",
	)
	if not checkins:
		return
	if not doc.in_time:
		first_in = next((c.time for c in checkins if c.log_type == "IN"), None)
		if first_in:
			doc.in_time = first_in
	if not doc.out_time:
		last_out = None
		for c in checkins:
			if c.log_type == "OUT":
				last_out = c.time
		if last_out:
			doc.out_time = last_out


def _set_status_from_thresholds(doc):
	"""Set attendance status using Shift Type hour thresholds (only on draft records with checkins).

	Logic mirrors HRMS auto-attendance:
	  working_hours < threshold_for_absent  → Absent
	  working_hours < threshold_for_half_day → Half Day
	  otherwise                              → Present
	Zero threshold means disabled (ignored).
	"""
	if doc.docstatus == 1:
		return
	if not doc.employee or not doc.attendance_date:
		return
	# Only override if checkin records exist for this employee/date
	date_str = str(doc.attendance_date)
	has_checkins = frappe.db.exists("Employee Checkin", {
		"employee": doc.employee,
		"time": ["between", [date_str + " 00:00:00", date_str + " 23:59:59"]],
	})
	if not has_checkins:
		return
	# Read thresholds from the Shift Type linked on this attendance
	shift_type = doc.get("shift")
	threshold_absent = 0.0
	threshold_half_day = 0.0
	if shift_type:
		st = frappe.db.get_value(
			"Shift Type",
			shift_type,
			["working_hours_threshold_for_absent", "working_hours_threshold_for_half_day"],
			as_dict=True,
		) or {}
		threshold_absent = flt(st.get("working_hours_threshold_for_absent"))
		threshold_half_day = flt(st.get("working_hours_threshold_for_half_day"))
	hours = flt(doc.working_hours)
	if threshold_absent > 0 and hours < threshold_absent:
		doc.status = "Absent"
	elif threshold_half_day > 0 and hours < threshold_half_day:
		doc.status = "Half Day"
	else:
		doc.status = "Present"


def _correct_status_on_submitted(doc):
	"""Same threshold logic as _set_status_from_thresholds but for submitted records.

	Uses frappe.db.set_value so the change persists without re-triggering validate.
	Only runs when checkin records exist for this employee/date.
	"""
	if not doc.employee or not doc.attendance_date:
		return
	date_str = str(doc.attendance_date)
	has_checkins = frappe.db.exists("Employee Checkin", {
		"employee": doc.employee,
		"time": ["between", [date_str + " 00:00:00", date_str + " 23:59:59"]],
	})
	if not has_checkins:
		return
	shift_type = doc.get("shift")
	threshold_absent = 0.0
	threshold_half_day = 0.0
	if shift_type:
		st = frappe.db.get_value(
			"Shift Type",
			shift_type,
			["working_hours_threshold_for_absent", "working_hours_threshold_for_half_day"],
			as_dict=True,
		) or {}
		threshold_absent = flt(st.get("working_hours_threshold_for_absent"))
		threshold_half_day = flt(st.get("working_hours_threshold_for_half_day"))
	hours = flt(doc.working_hours)
	if threshold_absent > 0 and hours < threshold_absent:
		correct_status = "Absent"
	elif threshold_half_day > 0 and hours < threshold_half_day:
		correct_status = "Half Day"
	else:
		correct_status = "Present"
	if doc.status != correct_status:
		frappe.db.set_value("Attendance", doc.name, "status", correct_status, update_modified=False)
		doc.status = correct_status


def fix_all_attendance_status():
	"""One-shot: correct status on every submitted Attendance that has checkins."""
	records = frappe.get_all(
		"Attendance",
		filters={"docstatus": 1},
		fields=["name", "employee", "attendance_date", "shift", "working_hours", "status"],
		limit=0,
	)
	fixed = 0
	for r in records:
		date_str = str(r.attendance_date)
		has_checkins = frappe.db.exists("Employee Checkin", {
			"employee": r.employee,
			"time": ["between", [date_str + " 00:00:00", date_str + " 23:59:59"]],
		})
		if not has_checkins:
			continue
		threshold_absent = 0.0
		threshold_half_day = 0.0
		if r.shift:
			st = frappe.db.get_value(
				"Shift Type", r.shift,
				["working_hours_threshold_for_absent", "working_hours_threshold_for_half_day"],
				as_dict=True,
			) or {}
			threshold_absent = flt(st.get("working_hours_threshold_for_absent"))
			threshold_half_day = flt(st.get("working_hours_threshold_for_half_day"))
		hours = flt(r.working_hours)
		if threshold_absent > 0 and hours < threshold_absent:
			correct_status = "Absent"
		elif threshold_half_day > 0 and hours < threshold_half_day:
			correct_status = "Half Day"
		else:
			correct_status = "Present"
		if r.status != correct_status:
			frappe.db.set_value("Attendance", r.name, "status", correct_status, update_modified=False)
			frappe.logger().info(f"fix_attendance_status: {r.name} {r.status}->{correct_status} ({hours}h)")
			fixed += 1
	frappe.db.commit()
	return f"Fixed {fixed} of {len(records)} attendance records."


def _auto_approve_if_no_level3(doc):
	"""Auto-approve when no Level 3 approver is configured for the department.

	Called after the record enters "Pending Level 3 Approval". If the department
	approval matrix has no row for level 3, the record is approved immediately
	without any manual action — triggering on_update_after_submit again, but that
	second call sees "Approved" which is not in _NOTIFY_LEVEL and exits cleanly.
	"""
	matrix = _get_matrix(doc.get("department") or "")
	if _row_for_level(matrix, 3):
		return  # Level 3 approver exists — normal flow, do nothing

	try:
		current_state = frappe.db.get_value("Attendance", doc.name, "workflow_state")
		if current_state != "Pending Level 3 Approval":
			return  # already moved on, nothing to do
		# apply_workflow internally reloads and saves — do NOT call doc2.save() after
		from frappe.model.workflow import apply_workflow
		doc2 = frappe.get_doc("Attendance", doc.name)
		apply_workflow(doc2, "Level 3 Approve")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Auto Level 3 Approve failed: " + doc.name)


def _get_matrix(department: str) -> list:
	if not department:
		return []
	return frappe.get_all(
		"Department Approval Matrix",
		filters={"parent": department, "parentfield": "approval_matrix"},
		fields=["approval_level", "approver", "approval_window_hours"],
		order_by="approval_level asc",
	)


def _row_for_level(matrix: list, level: int):
	return next((r for r in matrix if cint(r.approval_level) == level), None)


def _approver_user(employee: str) -> str | None:
	return frappe.db.get_value("Employee", employee, "user_id")


def _approver_email(employee: str) -> str | None:
	return (
		frappe.db.get_value("Employee", employee, "company_email")
		or frappe.db.get_value("Employee", employee, "personal_email")
		or _approver_user(employee)
	)


def _state_changed(doc) -> tuple[str | None, str | None]:
	prev = doc.get_doc_before_save()
	prev_state = prev.workflow_state if prev else None
	new_state = doc.get("workflow_state")
	if prev_state == new_state:
		return None, None
	return prev_state, new_state


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _sync_current_approver(doc):
	"""Keep current_approver in sync with the Department Approval Matrix.

	If the matrix is changed after an attendance record is already pending,
	this ensures the stored approver is refreshed on the next save.
	"""
	if doc.docstatus != 1:
		return
	level_map = {
		"Pending Level 1 Approval": 1,
		"Pending Level 2 Approval": 2,
		"Pending Level 3 Approval": 3,
	}
	level = level_map.get(doc.get("workflow_state") or "")
	if not level or not doc.department:
		return
	matrix = _get_matrix(doc.department)
	row = _row_for_level(matrix, level)
	if not row:
		return
	if doc.get("current_approver") != row.approver:
		approver_name = frappe.db.get_value("Employee", row.approver, "employee_name") or row.approver
		frappe.db.set_value(
			"Attendance", doc.name,
			{
				"current_approver": row.approver,
				"current_approver_name": approver_name,
			},
			update_modified=False,
		)


def _child_table_changed(doc) -> bool:
	"""Return True if custom_site_hours rows differ from what is stored in the DB."""
	if not doc.name:
		return False
	db_rows = frappe.get_all(
		"Attendance Site Hours",
		filters={"parent": doc.name, "parentfield": "custom_site_hours"},
		fields=["project", "hours", "check_in_time", "check_out_time"],
		order_by="idx asc",
	)
	doc_rows = doc.get("custom_site_hours") or []
	if len(db_rows) != len(doc_rows):
		return True
	for db_row, doc_row in zip(db_rows, doc_rows):
		if (
			(db_row.project or "") != (doc_row.get("project") or "")
			or flt(db_row.hours) != flt(doc_row.get("hours") or 0)
			or str(db_row.check_in_time or "") != str(doc_row.get("check_in_time") or "")
			or str(db_row.check_out_time or "") != str(doc_row.get("check_out_time") or "")
		):
			return True
	return False


def _recalculate_site_hours_from_times(doc):
	"""On submitted doc saves, recalculate each row's hours from check_in/out times and sync parent fields."""
	if doc.docstatus != 1:
		return
	rows = doc.get("custom_site_hours") or []
	if not rows:
		return

	total_hours = 0.0
	all_in_times = []
	all_out_times = []

	for row in rows:
		if row.check_in_time and row.check_out_time:
			hours = flt(time_diff_in_hours(row.check_out_time, row.check_in_time), 2)
			if hours > 0:
				row.hours = hours
		total_hours += flt(row.hours or 0)
		if row.check_in_time:
			all_in_times.append(get_datetime(row.check_in_time))
		if row.check_out_time:
			all_out_times.append(get_datetime(row.check_out_time))

	doc.working_hours = flt(total_hours, 2)
	if all_in_times:
		doc.in_time = min(all_in_times)
	if all_out_times:
		doc.out_time = max(all_out_times)


def _validate_hours_edit_authorization(doc):
	"""Only the current level's approver may edit status / in_time / out_time / site hours."""
	if doc.docstatus != 1:
		return
	# Skip during internal saves (auto-approve, system corrections, etc.)
	if doc.flags.get("ignore_permissions"):
		return

	# Read current DB values directly — get_doc_before_save() is unreliable on submitted docs
	db_vals = frappe.db.get_value(
		"Attendance", doc.name, ["in_time", "out_time", "status"], as_dict=True
	)
	if not db_vals:
		return

	fields_changed = (
		str(doc.get("in_time")) != str(db_vals.in_time)
		or str(doc.get("out_time")) != str(db_vals.out_time)
		or str(doc.get("status") or "") != str(db_vals.status or "")
		or _child_table_changed(doc)
	)
	if not fields_changed:
		return

	# Block edit if approval window has already expired
	window_expires_at = frappe.db.get_value("Attendance", doc.name, "window_expires_at")
	if window_expires_at and now_datetime() > get_datetime(window_expires_at):
		frappe.throw(_("The approval window has expired. Attendance fields can no longer be edited."))

	workflow_state = doc.get("workflow_state") or ""
	level_map = {
		"Pending Level 1 Approval": 1,
		"Pending Level 2 Approval": 2,
		"Pending Level 3 Approval": 3,
	}
	level = level_map.get(workflow_state)

	if not level:
		frappe.throw(_("Attendance fields can only be edited while the record is pending approval."))

	department = doc.department
	if not department:
		frappe.throw(_("Department is required to validate approver."))

	matrix = _get_matrix(department)
	row = _row_for_level(matrix, level)

	if not row:
		frappe.throw(
			_("No Level {0} approver configured for Department {1}.").format(level, department)
		)

	approver_user = _approver_user(row.approver)
	if frappe.session.user != approver_user:
		emp_name = frappe.db.get_value("Employee", row.approver, "employee_name") or row.approver
		frappe.throw(
			_("Attendance can only be corrected by the Level {0} approver: {1}.").format(
				level, emp_name
			)
		)


def _recalculate_working_hours(doc):
	"""Auto-recalculate working_hours when in_time/out_time changes on a submitted doc.

	Skipped when site hours rows exist — in that case working_hours is already managed
	as the sum of child row hours by _recalculate_site_hours_from_times.
	"""
	if doc.docstatus != 1:
		return
	if doc.get("custom_site_hours"):
		return  # managed by _recalculate_site_hours_from_times
	if not (doc.in_time and doc.out_time):
		return
	db_vals = frappe.db.get_value("Attendance", doc.name, ["in_time", "out_time"], as_dict=True)
	if db_vals and (
		str(doc.in_time) != str(db_vals.in_time) or str(doc.out_time) != str(db_vals.out_time)
	):
		doc.working_hours = time_diff_in_hours(doc.out_time, doc.in_time)


def _update_working_hours_from_site_hours(doc):
	"""After save, sync working_hours, in_time, out_time from child table to the DB record.

	Uses db.set_value to bypass validate_update_after_submit restrictions.
	- working_hours = sum of all row hours
	- in_time       = earliest check_in_time across all rows
	- out_time      = latest check_out_time across all rows
	"""
	rows = frappe.get_all(
		"Attendance Site Hours",
		filters={"parent": doc.name, "parentfield": "custom_site_hours"},
		fields=["hours", "check_in_time", "check_out_time"],
	)
	if not rows:
		return

	total = flt(sum(flt(r.hours or 0) for r in rows), 2)
	in_times = [r.check_in_time for r in rows if r.check_in_time]
	out_times = [r.check_out_time for r in rows if r.check_out_time]

	current = frappe.db.get_value(
		"Attendance", doc.name, ["working_hours", "in_time", "out_time"], as_dict=True
	) or {}

	updates = {}
	if flt(current.get("working_hours")) != total:
		updates["working_hours"] = total
	if in_times:
		earliest_in = min(get_datetime(t) for t in in_times)
		if str(current.get("in_time") or "") != str(earliest_in):
			updates["in_time"] = earliest_in
	if out_times:
		latest_out = max(get_datetime(t) for t in out_times)
		if str(current.get("out_time") or "") != str(latest_out):
			updates["out_time"] = latest_out

	if updates:
		frappe.db.set_value("Attendance", doc.name, updates, update_modified=False)
		# Mirror changes onto the in-memory doc so _correct_status_on_submitted
		# (called immediately after) uses the freshly calculated values.
		for k, v in updates.items():
			setattr(doc, k, v)


def _validate_approver_authorization(doc):
	# Skip during internal saves (auto-approve, system corrections)
	if doc.flags.get("ignore_permissions"):
		return

	new_state = doc.get("workflow_state")
	if not new_state:
		return

	prev = doc.get_doc_before_save()
	if not prev:
		return

	key = (prev.workflow_state, new_state)
	required_level = _LEVEL_REQUIRED.get(key)
	if required_level is None:
		return

	department = doc.department
	if not department:
		frappe.throw(_("Department is required on the Attendance record for approval routing."))

	matrix = _get_matrix(department)
	row = _row_for_level(matrix, required_level)

	if not row:
		if required_level == 3:
			# No Level 3 approver configured — auto-approval is allowed
			return
		frappe.throw(
			_("No Level {0} approver configured for Department {1}. "
			  "Please set up the Approval Matrix on the Department record.").format(
				required_level, department
			)
		)

	approver_user = _approver_user(row.approver)
	if not approver_user:
		frappe.throw(
			_("Employee {0} (Level {1} approver) has no linked User account. "
			  "Please link a User to that Employee before proceeding.").format(
				row.approver, required_level
			)
		)

	# Only Administrator can bypass the approver restriction
	if frappe.session.user == "Administrator":
		return

	if frappe.session.user != approver_user:
		emp_name = frappe.db.get_value("Employee", row.approver, "employee_name") or row.approver
		frappe.throw(
			_("Level {0} approval must be performed by {1} ({2}).").format(
				required_level, emp_name, row.approver
			)
		)


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------


def _send_notification_for_level(doc, level: int):
	department = doc.department
	if not department:
		return

	matrix = _get_matrix(department)
	row = _row_for_level(matrix, level)
	if not row:
		return

	recipient = _approver_email(row.approver)
	if not recipient:
		frappe.log_error(
			title="Attendance Approval: approver email missing",
			message=f"Employee {row.approver} has no email. Cannot notify for {doc.name}.",
		)
		return

	approver_name = frappe.db.get_value("Employee", row.approver, "employee_name") or row.approver
	doc_url = get_url_to_form("Attendance", doc.name)

	try:
		frappe.sendmail(
			recipients=[recipient],
			subject=_("Action Required – Attendance Level {0} Approval: {1}").format(level, doc.name),
			message=_(
				"""<p>Dear {approver_name},</p>
<p>An Attendance record requires your <strong>Level {level} approval</strong>.</p>
<table border="0" cellpadding="6" style="border-collapse:collapse;">
  <tr><td><strong>Document</strong></td><td>{doc_name}</td></tr>
  <tr><td><strong>Employee</strong></td><td>{employee_name}</td></tr>
  <tr><td><strong>Department</strong></td><td>{department}</td></tr>
  <tr><td><strong>Date</strong></td><td>{attendance_date}</td></tr>
  <tr><td><strong>Status</strong></td><td>{status}</td></tr>
  <tr><td><strong>Approval Window</strong></td><td>{window} hours</td></tr>
</table>
<p><a href="{url}">Open in ERPNext</a></p>"""
			).format(
				approver_name=approver_name,
				level=level,
				doc_name=doc.name,
				employee_name=doc.employee_name or doc.employee,
				department=department,
				attendance_date=doc.attendance_date,
				status=doc.status,
				window=flt(row.approval_window_hours),
				url=doc_url,
			),
			now=False,
		)
	except Exception:
		frappe.log_error(
			title="Attendance Approval: email send failed",
			message=frappe.get_traceback(),
		)


# ---------------------------------------------------------------------------
# Tracking fields
# ---------------------------------------------------------------------------


def _get_project_for_attendance(doc) -> str | None:
	"""Return the project from the active Shift Assignment's legacy custom_project_ field."""
	if not doc.employee or not doc.attendance_date:
		return None

	filters = {
		"employee": doc.employee,
		"docstatus": 1,
		"start_date": ["<=", doc.attendance_date],
	}
	if doc.shift:
		filters["shift_type"] = doc.shift
	return frappe.db.get_value(
		"Shift Assignment", filters, "custom_project_", order_by="start_date desc"
	)


def _populate_site_hours(doc) -> None:
	"""Calculate per-project working hours from Employee Checkin records and persist them.

	Pairs consecutive IN/OUT logs per project for the attendance date, sums the
	hours, writes rows into Attendance Site Hours, and updates working_hours on
	the parent Attendance record.
	"""
	from collections import defaultdict

	checkins = frappe.get_all(
		"Employee Checkin",
		filters=[
			["employee", "=", doc.employee],
			["time", ">=", str(doc.attendance_date) + " 00:00:00"],
			["time", "<=", str(doc.attendance_date) + " 23:59:59"],
			["skip_auto_attendance", "=", 0],
		],
		fields=["name", "log_type", "time", "custom_project", "activity_log"],
		order_by="time asc",
		limit=200,
	)
	if not checkins:
		return

	project_logs = defaultdict(list)
	for c in checkins:
		project_logs[c.custom_project or ""].append(c)

	site_rows = []
	total_hours = 0.0

	for project, logs in project_logs.items():
		hours = _calculate_hours_from_pairs(logs)
		if hours <= 0:
			continue
		project_name = ""
		if project:
			project_name = frappe.db.get_value("Project", project, "project_name") or ""
		activity_entries = [
			c.activity_log for c in logs if c.log_type == "OUT" and c.activity_log
		]
		activity_log = "\n".join(activity_entries)
		in_times = [get_datetime(c.time) for c in logs if c.log_type == "IN"]
		out_times = [get_datetime(c.time) for c in logs if c.log_type == "OUT"]
		site_rows.append({
			"project": project,
			"project_name": project_name,
			"hours": hours,
			"activity_log": activity_log,
			"check_in_time": min(in_times) if in_times else None,
			"check_out_time": max(out_times) if out_times else None,
		})
		total_hours += hours

	if not site_rows:
		return

	# Link any unlinked checkins for this employee+date to this attendance so HRMS
	# does not try to create a duplicate attendance on the next auto-attendance run.
	frappe.db.sql(
		"""
		UPDATE `tabEmployee Checkin`
		SET attendance = %s
		WHERE employee = %s
		  AND DATE(time) = %s
		  AND (attendance IS NULL OR attendance = '')
		  AND skip_auto_attendance = 0
		""",
		(doc.name, doc.employee, str(doc.attendance_date)),
	)

	frappe.db.delete("Attendance Site Hours", {"parent": doc.name})
	for idx, row in enumerate(site_rows, start=1):
		child = frappe.new_doc("Attendance Site Hours")
		child.parent = doc.name
		child.parentfield = "custom_site_hours"
		child.parenttype = "Attendance"
		child.idx = idx
		child.project = row["project"]
		child.project_name = row["project_name"]
		child.hours = flt(row["hours"], 2)
		child.activity_log = row.get("activity_log") or ""
		child.check_in_time = row.get("check_in_time")
		child.check_out_time = row.get("check_out_time")
		child.db_insert()

	doc.working_hours = flt(total_hours, 2)
	frappe.db.set_value(
		"Attendance", doc.name, "working_hours", flt(total_hours, 2), update_modified=False
	)


def _calculate_hours_from_pairs(logs: list) -> float:
	"""Sum hours from consecutive IN/OUT pairs in a list of checkin logs."""
	from frappe.utils import get_datetime, time_diff_in_hours

	total = 0.0
	in_time = None
	for log in sorted(logs, key=lambda x: x.time):
		if log.log_type == "IN":
			in_time = get_datetime(log.time)
		elif log.log_type == "OUT" and in_time is not None:
			total += flt(time_diff_in_hours(log.time, in_time), 4)
			in_time = None
	return total


def _get_project_window_hours(project: str, level: int) -> float:
	"""Return the project-level approval window hours for the given level, or 0 if not set."""
	field_map = {
		1: "supervisor_approval_window",
		2: "level_2_approval_window",
		3: "manager_payroll_final_approval_window",
	}
	field = field_map.get(level)
	if not field or not project:
		return 0
	return flt(frappe.db.get_value("Project", project, field))


def _stamp_tracking_fields(doc, level: int):
	department = doc.department
	if not department:
		return
	matrix = _get_matrix(department)
	row = _row_for_level(matrix, level)
	if not row:
		return

	# Project window hours take priority; fall back to Department Approval Matrix
	project = _get_project_for_attendance(doc)
	window_hours = _get_project_window_hours(project, level) if project else 0
	if not window_hours:
		window_hours = flt(row.approval_window_hours)

	expires_at = add_to_date(now(), hours=window_hours) if window_hours else None

	approver_name = frappe.db.get_value("Employee", row.approver, "employee_name") or row.approver

	frappe.db.set_value(
		"Attendance",
		doc.name,
		{
			"current_approval_level": level,
			"current_approver": row.approver,
			"current_approver_name": approver_name,
			"level_assigned_at": now(),
			"approval_window_hours": window_hours,
			"window_expires_at": expires_at,
			"window_reminder_sent": 0,
		},
		update_modified=False,
	)
