import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime
from frappe.model.workflow import apply_workflow

# ---------------------------------------------------------------------------
# Window-lapse auto-advance (spec §3 / §7)
# ---------------------------------------------------------------------------
# A missed approval window escalates to the NEXT level — a lapsed window is
# treated as an approval, never a rejection. The cascade is one hop per hourly
# run; the freshly-stamped next-level window (now + N hours) is not yet
# expired, so the record advances again on a later run:
#
#   Pending Level 1 Approval  (window lapsed) -> Level 1 Approve -> Pending Level 2
#   Pending Level 2 Approval  (window lapsed) -> Level 2 Approve -> Pending Level 3
#   Pending Level 3 Approval  (window lapsed) -> Level 3 Approve -> Approved
#
# So once BOTH the Level 1 and Level 2 windows have lapsed with no human action,
# the record reaches Level 3 (payroll) and, when the Level 3 window also lapses
# (or no Level 3 approver is configured — see _auto_approve_if_no_level3), it is
# finalised to Approved. Payroll is never blocked by an inattentive approver.
#
# We APPLY the workflow transition rather than raw-writing workflow_state so
# that Attendance.on_update_after_submit fires: it re-stamps the next level's
# approver + window, notifies that approver, and recomputes working_hours. The
# attendance status stays threshold-computed (Present / Half Day / Absent) — the
# escalation never forces a status.
_STATE_ACTION = {
	"Pending Level 1 Approval": "Level 1 Approve",
	"Pending Level 2 Approval": "Level 2 Approve",
	"Pending Level 3 Approval": "Level 3 Approve",
}


def process_attendance_approval_windows(limit: int = 200):
	"""Hourly scheduler task: auto-advance Attendance whose current approval
	window has lapsed.

	Runs unattended, so the scheduler user (Administrator) drives the workflow
	transition with ``ignore_permissions`` set — Attendance.validate's approver
	checks short-circuit on that flag, so a lapsed level with a missing/unset
	approver still cascades instead of stalling the batch.

	``limit`` caps how many records advance per run (oldest lapsed first). This
	bounds the work — and the next-level approver notifications each transition
	queues — per hourly tick, so a large backlog drains gradually over a few
	runs instead of in one burst. Pass ``limit=0`` to process every lapsed
	record in a single run (e.g. a deliberate one-off catch-up).

	Defensive by design:
	  * ``window_expires_at < now`` in SQL excludes NULL windows automatically.
	  * each record is re-read and re-checked inside the loop so a human action
	    landing between the query and the transition is respected (no double
	    action / no clobbering a manual approve or reject);
	  * every record is isolated in its own try/except + commit, so one bad doc
	    logs an error and the rest of the batch still advances.
	"""
	now = now_datetime()
	expired = frappe.get_all(
		"Attendance",
		filters={
			"docstatus": 1,
			"workflow_state": ["in", list(_STATE_ACTION)],
			"window_expires_at": ["<", now],
		},
		fields=["name", "workflow_state"],
		order_by="window_expires_at asc",
		limit=limit or None,
	)

	advanced = 0
	for att in expired:
		action = _STATE_ACTION.get(att.workflow_state)
		if not action:
			continue
		try:
			doc = frappe.get_doc("Attendance", att.name)

			# Re-check under a fresh read — a human may have approved/rejected,
			# or the window may have been extended, since the query above.
			if doc.workflow_state != att.workflow_state:
				continue
			wx = doc.get("window_expires_at")
			if not wx or get_datetime(wx) >= now:
				continue

			# Administrator-driven, unattended: bypass the per-level approver
			# validation (a lapsed window is a system escalation, not a human
			# acting out of turn).
			doc.flags.ignore_permissions = True
			apply_workflow(doc, action)
			frappe.db.commit()
			advanced += 1
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				frappe.get_traceback(),
				f"process_attendance_approval_windows failed: {att.name}",
			)

	return {"advanced": advanced}
