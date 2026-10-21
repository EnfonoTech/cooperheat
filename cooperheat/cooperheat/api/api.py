import frappe
from frappe import _
from frappe.utils import cint, flt

from cooperheat.cooperheat.api.tasks import process_attendance_approval_windows


@frappe.whitelist()
def get_approval_matrix_approver(department=None, level=1, employee=None):
	"""Return the approver employee and their linked user for an employee + level
	(from the employee's own reporting line; *department* is ignored)."""
	from cooperheat.cooperheat.overrides.attendance import _get_matrix, _row_for_level

	matrix = _get_matrix(department, employee)
	row = _row_for_level(matrix, cint(level))
	if not row:
		return None
	user_id = frappe.db.get_value("Employee", row.approver, "user_id")
	return {"approver": row.approver, "user_id": user_id}


@frappe.whitelist()
def run_attendance_approval_windows():
	"""Manually trigger the attendance approval window auto-approve task."""
	frappe.has_permission("Attendance", ptype="write", throw=True)
	process_attendance_approval_windows()
	return {"status": "ok"}


@frappe.whitelist()
def get_assigned_projects(employee, date):
	"""Return the list of projects assigned in the employee's active Shift Assignment.

	Used by the Employee Checkin form to filter the Project / Site field.
	Falls back to the legacy single custom_project_ field if the child table is empty.
	"""
	from frappe.query_builder import DocType

	frappe.has_permission("Employee Checkin", ptype="read", throw=True)

	if not employee or not date:
		return []

	SA = DocType("Shift Assignment")
	rows = (
		frappe.qb.from_(SA)
		.select(SA.name)
		.where(SA.employee == employee)
		.where(SA.docstatus == 1)
		.where(SA.status == "Active")
		.where(SA.start_date <= date)
		.where((SA.end_date.isnull()) | (SA.end_date >= date))
		.orderby(SA.start_date, order=frappe.qb.desc)
		.limit(1)
	).run(as_dict=True)

	if not rows:
		return []

	shift_assignment = rows[0].name

	return frappe.get_all(
		"Shift Assignment Project",
		filters={"parent": shift_assignment, "parentfield": "custom_project_sites"},
		pluck="project",
	)


@frappe.whitelist(methods=["POST"])
def recalculate_site_hours(attendance_name):
	"""Recalculate and refresh the site hours table on a submitted Attendance record.

	Allowed for HR Managers and for the current level approver of the record.
	"""
	frappe.has_permission("Attendance", ptype="write", throw=True)

	is_hr_manager = "HR Manager" in frappe.get_roles(frappe.session.user)
	if not is_hr_manager:
		from cooperheat.cooperheat.overrides.attendance import _approver_user, _get_matrix, _row_for_level

		att = frappe.db.get_value(
			"Attendance", attendance_name, ["workflow_state", "department", "employee"], as_dict=True
		)
		level_map = {
			"Pending Level 1 Approval": 1,
			"Pending Level 2 Approval": 2,
			"Pending Level 3 Approval": 3,
		}
		level = level_map.get(att.workflow_state if att else "")
		if not level:
			frappe.throw(
				_("Only HR Managers can recalculate site hours on an approved or non-pending record.")
			)
		matrix = _get_matrix(att.department, att.employee)
		row = _row_for_level(matrix, level)
		if not row or _approver_user(row.approver) != frappe.session.user:
			frappe.throw(
				_("Only the Level {0} approver or an HR Manager can recalculate site hours.").format(level)
			)

	doc = frappe.get_doc("Attendance", attendance_name)
	from cooperheat.cooperheat.overrides.attendance import _correct_status_on_submitted, _populate_site_hours

	_populate_site_hours(doc)
	# Reload to pick up the working_hours written by _populate_site_hours, then
	# re-run the status correction so Half Day / Present is set correctly.
	doc.reload()
	_correct_status_on_submitted(doc)
	frappe.db.commit()
	return {"status": "ok"}


def _can_approve_level3(user=None) -> bool:
	"""The Payroll step: the configured Payroll Approver, or an HR Manager."""
	from cooperheat.cooperheat.org import is_payroll_approver

	user = user or frappe.session.user
	return is_payroll_approver(user) or "HR Manager" in frappe.get_roles(user)


@frappe.whitelist()
def get_pending_level3_records(employee=None, department=None, from_date=None, to_date=None):
	"""Return Attendance records pending the Payroll (Level 3) step.
	Accepts optional filters: employee, department, from_date, to_date.
	Only the Payroll Approver and HR Managers see them."""
	frappe.has_permission("Attendance", ptype="read", throw=True)

	if not _can_approve_level3():
		return []

	filters = {
		"docstatus": 1,
		"workflow_state": "Pending Level 3 Approval",
	}

	if employee:
		filters["employee"] = employee

	if department:
		filters["department"] = department

	if from_date and to_date:
		filters["attendance_date"] = ["between", [from_date, to_date]]
	elif from_date:
		filters["attendance_date"] = [">=", from_date]
	elif to_date:
		filters["attendance_date"] = ["<=", to_date]

	records = frappe.get_all(
		"Attendance",
		filters=filters,
		fields=[
			"name",
			"employee",
			"employee_name",
			"attendance_date",
			"department",
			"in_time",
			"out_time",
			"working_hours",
			"status",
		],
		order_by="attendance_date asc, employee asc",
		limit=500,
	)

	# For records with no in_time/out_time, fall back to first IN / last OUT
	# from Employee Checkin records for that employee on that date.
	for rec in records:
		if not rec.get("in_time") or not rec.get("out_time"):
			date_str = str(rec.attendance_date)
			checkins = frappe.get_all(
				"Employee Checkin",
				filters=[
					["employee", "=", rec.employee],
					["time", ">=", date_str + " 00:00:00"],
					["time", "<=", date_str + " 23:59:59"],
				],
				fields=["log_type", "time"],
				order_by="time asc",
			)
			for c in checkins:
				if c.log_type == "IN" and not rec.get("in_time"):
					rec["in_time"] = c.time
				if c.log_type == "OUT":
					rec["out_time"] = c.time  # keep overwriting to get the last OUT

	return records


@frappe.whitelist(methods=["POST"])
def level3_approve_attendance(name, in_time=None, out_time=None, working_hours=None, status=None):
	"""Update editable fields (if changed) and apply Level 3 Approve workflow action.

	Two-step: first save field edits while still in pending state (so validate allows it),
	then apply the workflow transition to Approved.
	"""
	from frappe.model.workflow import apply_workflow

	frappe.has_permission("Attendance", ptype="write", throw=True)
	if not _can_approve_level3():
		frappe.throw(_("Only the Payroll Approver or an HR Manager can give the Payroll approval."))

	doc = frappe.get_doc("Attendance", name)
	if doc.workflow_state != "Pending Level 3 Approval":
		frappe.throw(_("Record {0} is not pending Level 3 approval.").format(name))

	valid_statuses = {"Present", "Absent", "Half Day", "Work From Home", "On Leave"}

	# Step 1: persist field edits while doc is still in pending state
	changed = False
	if in_time and str(in_time).strip() != str(doc.in_time or "").strip():
		doc.in_time = in_time
		changed = True
	if out_time and str(out_time).strip() != str(doc.out_time or "").strip():
		doc.out_time = out_time
		changed = True
	if working_hours is not None and flt(working_hours) != flt(doc.working_hours):
		doc.working_hours = flt(working_hours)
		changed = True
	if status and status in valid_statuses and status != doc.status:
		doc.status = status
		changed = True

	if changed:
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	# Step 2: apply workflow — apply_workflow reloads doc from DB then transitions
	doc2 = frappe.get_doc("Attendance", name)
	apply_workflow(doc2, "Level 3 Approve")
	doc2.save(ignore_permissions=True)
	frappe.db.commit()

	return {"status": "approved"}


@frappe.whitelist(methods=["POST"])
def bulk_level3_approve():
	"""Approve every Attendance record in 'Pending Level 3 Approval'. Payroll Approver / HR Manager only."""
	from frappe.model.workflow import apply_workflow

	frappe.has_permission("Attendance", ptype="write", throw=True)
	if not _can_approve_level3():
		frappe.throw(_("Only the Payroll Approver or an HR Manager can give the Payroll approval."))

	records = frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "workflow_state": "Pending Level 3 Approval"},
		pluck="name",
		limit=1000,
	)

	if not records:
		return {"count": 0, "errors": []}

	approved = 0
	errors = []
	for name in records:
		try:
			doc = frappe.get_doc("Attendance", name)
			apply_workflow(doc, "Level 3 Approve")
			doc.save(ignore_permissions=True)
			frappe.db.commit()
			approved += 1
		except Exception:
			frappe.db.rollback()
			errors.append(name)

	return {"count": approved, "errors": errors}
