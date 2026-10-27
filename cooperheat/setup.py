# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


# Field names owned by this app on the Employee doctype.
# (Previously we also owned pay_batch and employee_category; these now live on
# Employee Compensation, so we clean them up on migrate.)
EMPLOYEE_CUSTOM_FIELD_OWNED = {
	"employee_category",
	"pay_batch",
	"cooperheat_payroll_section",
}


def setup_custom_fields():
	custom_fields = {
		"Employee": [
			{
				"fieldname": "nationality",
				"label": "Nationality",
				"fieldtype": "Link",
				"options": "Nationality",
				"insert_after": "status",
				"description": "",
			},
			{
				"fieldname": "custom_pay_batch",
				"label": "Pay Batch",
				"fieldtype": "Link",
				"options": "Pay Batch",
				"insert_after": "nationality",
				"description": "Payroll runs can be limited to one batch (main, sponsor batches, visa batches...).",
			},
			# read-only salary view for employees (own) and managers (team); filled by
			# compensation.get_salary_view, shown by public/js/employee.js
			{
				"fieldname": "custom_salary_view_tab",
				"label": "Salary",
				"fieldtype": "Tab Break",
				"insert_after": "custom_compensation_html",
			},
			{
				"fieldname": "custom_salary_view_html",
				"label": "Salary",
				"fieldtype": "HTML",
				"insert_after": "custom_salary_view_tab",
			},
		],
	}
	from cooperheat.cooperheat.approval_workflows import final_approver_field

	for doctype, after in (("Leave Application", "leave_approver"), ("Expense Claim", "expense_approver")):
		if frappe.db.exists("DocType", doctype):
			custom_fields[doctype] = [dict(final_approver_field(), insert_after=after)]
	create_custom_fields(custom_fields, update=True)


DEFAULT_NATIONALITIES = [
	("Saudi", 1),
	("Indian", 0),
	("Pakistani", 0),
	("Bangladeshi", 0),
	("Nepali", 0),
	("Filipino", 0),
	("Egyptian", 0),
	("Yemeni", 0),
	("Sudanese", 0),
	("Sri Lankan", 0),
	("Other", 0),
]


def seed_nationalities():
	if not frappe.db.exists("DocType", "Nationality"):
		return
	for name, is_local in DEFAULT_NATIONALITIES:
		if not frappe.db.exists("Nationality", name):
			doc = frappe.new_doc("Nationality")
			doc.nationality_name = name
			doc.is_local = is_local
			doc.flags.ignore_permissions = True
			doc.insert()


def cleanup_legacy_employee_fields():
	for fn in EMPLOYEE_CUSTOM_FIELD_OWNED:
		name = f"Employee-{fn}"
		if frappe.db.exists("Custom Field", name):
			try:
				frappe.delete_doc("Custom Field", name, ignore_permissions=True)
			except Exception:
				frappe.log_error(
					title="failed to delete legacy custom field",
					message=f"{name}",
				)


DEFAULT_SETTINGS = {
	"monthly_working_hours": 240,
	"normal_ot_multiplier": 1.5,
	"holiday_ot_multiplier": 2.0,
	"travel_ot_multiplier": 1.5,
	"gosi_rate_percent": 9.75,
	"gosi_applicable_category": "Saudi",
	"round_amounts": 1,
	# Attendance approval windows (client rule 2026-10-20: 48 h supervisor, 72 h manager)
	"immediate_approval_window_hours": 48,
	"secondary_approval_window_hours": 72,
	"payroll_approval_window_hours": 48,
}


def seed_settings():
	if not frappe.db.exists("DocType", "Pay Sheet Settings"):
		return
	doc = frappe.get_single("Pay Sheet Settings")
	changed = False
	for k, v in DEFAULT_SETTINGS.items():
		if not doc.get(k):
			doc.set(k, v)
			changed = True
	if changed:
		doc.flags.ignore_permissions = True
		doc.save()


def after_install():
	seed_nationalities()
	setup_custom_fields()
	seed_settings()
	ensure_roles()


def backfill_compensation_from_date():
	if not frappe.db.exists("DocType", "Employee Compensation"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabEmployee Compensation`
		SET from_date = COALESCE(from_date, DATE(creation), CURDATE())
		WHERE from_date IS NULL OR from_date = '0000-00-00'
		"""
	)


_CHECKIN_PROJECT_FILTER_SCRIPT = """\
frappe.ui.form.on("Employee Checkin", {
    refresh(frm) {
        _set_project_filter(frm);
    },
    employee(frm) {
        _set_project_filter(frm);
        frm.set_value("custom_project", "");
    },
    time(frm) {
        _set_project_filter(frm);
    }
});

function _set_project_filter(frm) {
    const employee = frm.doc.employee;
    if (!employee) return;
    const date = frm.doc.time
        ? frappe.datetime.str_to_obj(frm.doc.time).toISOString().slice(0, 10)
        : frappe.datetime.get_today();

    frappe.call({
        method: "cooperheat.cooperheat.api.api.get_assigned_projects",
        args: { employee, date },
        callback(r) {
            const projects = r.message || [];
            if (!projects.length) {
                frm.set_query("custom_project", () => ({}));
                return;
            }
            frm.set_query("custom_project", () => ({
                filters: [["Project", "name", "in", projects]]
            }));
        }
    });
}
"""

_ATTENDANCE_RECALC_SCRIPT = """\
frappe.ui.form.on("Attendance", {
    refresh(frm) {
        if (frm.doc.docstatus === 1 && frappe.user.has_role("HR Manager")) {
            frm.add_custom_button(__("Recalculate Site Hours"), () => {
                frappe.call({
                    method: "cooperheat.cooperheat.api.api.recalculate_site_hours",
                    args: { attendance_name: frm.docname },
                    callback(r) {
                        if (r.message && r.message.status === "ok") {
                            frappe.msgprint(__("Site hours recalculated."));
                            frm.reload_doc();
                        }
                    }
                });
            }, __("Actions"));
        }
    }
});
"""


def setup_client_scripts():
	scripts = [
		{
			"name": "Employee Checkin – Assigned Sites Filter",
			"dt": "Employee Checkin",
			"view": "Form",
			"script": _CHECKIN_PROJECT_FILTER_SCRIPT,
		},
		{
			"name": "Attendance – Recalculate Site Hours Button",
			"dt": "Attendance",
			"view": "Form",
			"script": _ATTENDANCE_RECALC_SCRIPT,
		},
	]
	for meta in scripts:
		if frappe.db.exists("Client Script", meta["name"]):
			doc = frappe.get_doc("Client Script", meta["name"])
			doc.script = meta["script"]
			doc.enabled = 1
			doc.flags.ignore_permissions = True
			doc.save()
		else:
			doc = frappe.new_doc("Client Script")
			doc.name = meta["name"]
			doc.dt = meta["dt"]
			doc.view = meta["view"]
			doc.enabled = 1
			doc.script = meta["script"]
			doc.flags.ignore_permissions = True
			doc.insert()


# ---------------------------------------------------------------------------
# Supervisor / Manager roles, permissions and desk
# ---------------------------------------------------------------------------

SCOPED_ROLE_NAMES = ("Supervisor", "Manager")

# doctype -> (permlevel, ptypes granted to Supervisor and Manager). Deliberately
# no ``delete`` anywhere, and Employee is read-only: moving a technician between
# departments stays an HR action. Team scoping (permissions/scope.py) narrows
# every one of these to the user's own team.
_SCOPED_ROLE_PERMS = [
	("Employee", 0, ("read",)),
	("Department", 0, ("read", "write")),
	("Project", 0, ("read", "write", "create")),
	("Shift Assignment", 0, ("read", "write", "create", "submit")),
	# submit: a workflow approval on a submitted Attendance is a "submit-level" action
	("Attendance", 0, ("read", "write", "submit")),
	("Employee Checkin", 0, ("read", "write", "create")),
	# the ``time`` field sits at permlevel 1
	("Employee Checkin", 1, ("read", "write")),
]


def ensure_roles():
	for role in SCOPED_ROLE_NAMES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def _grant(doctype, role, permlevel, ptypes):
	"""Add the rights only when the (doctype, role, permlevel) combination has no
	Custom DocPerm row yet. A row an administrator already made - even a narrower
	one - is left exactly as they set it. Never raises: a failed grant is logged and
	must not abort ``bench migrate`` on a live site."""
	from frappe.permissions import add_permission, update_permission_property

	try:
		if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": permlevel}):
			return
		add_permission(doctype, role, permlevel)
		for ptype in ptypes:
			update_permission_property(doctype, role, permlevel, ptype, 1)
	except Exception:
		frappe.log_error(
			title="cooperheat: could not grant %s on %s (permlevel %s)" % (role, doctype, permlevel),
			message=frappe.get_traceback(),
		)


def ensure_role_permissions():
	"""Idempotent and add-only."""
	for role in SCOPED_ROLE_NAMES:
		for doctype, permlevel, ptypes in _SCOPED_ROLE_PERMS:
			if frappe.db.exists("DocType", doctype):
				_grant(doctype, role, permlevel, ptypes)
	# HR Manager can create and maintain Pay Batches (also in the DocType JSON)
	if frappe.db.exists("DocType", "Pay Batch"):
		_grant("Pay Batch", "HR Manager", 0, ("read", "write", "create"))


def ensure_project_display():
	"""Show the project NAME (searchable by code and CRM number) wherever a
	Project is picked, instead of only the system id."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	make_property_setter("Project", None, "title_field", "project_name", "Data", for_doctype=True)
	make_property_setter("Project", None, "show_title_field_in_link", "1", "Check", for_doctype=True)
	make_property_setter(
		"Project", None, "search_fields", "project_name,custom_project_code,custom_crm_no", "Data", for_doctype=True
	)


SUPERVISOR_WORKSPACE = "Supervisor Desk"

_PENDING_STATES = ["Pending Level 1 Approval", "Pending Level 2 Approval", "Pending Level 3 Approval"]

# name -> (doctype, filters). Counted through the normal permission layer, so a
# supervisor's numbers are his own team's.
_NUMBER_CARDS = {
	"Team Pending Approvals": (
		"Attendance",
		[["Attendance", "workflow_state", "in", _PENDING_STATES, False], ["Attendance", "docstatus", "=", 1, False]],
		"#E67E22",
	),
	"Team Check-ins Today": ("Employee Checkin", [["Employee Checkin", "time", "Timespan", "today", False]], "#2D9CDB"),
	"Team Members": ("Employee", [["Employee", "status", "=", "Active", False]], "#27AE60"),
}

# card title -> [(label, link_type, link_to)]
_LINK_CARDS = {
	"My Team": [
		("Supervisor Workspace", "Page", "supervisor-workspace"),
		("Employee", "DocType", "Employee"),
		("Org Chart", "Page", "organizational-chart"),
	],
	"Attendance & Approvals": [
		("Attendance", "DocType", "Attendance"),
		("Employee Checkin", "DocType", "Employee Checkin"),
		("Shift Assignment", "DocType", "Shift Assignment"),
		("Level 3 Attendance Approval", "Page", "level-3-approval"),
		("Approver Technician Summary", "Report", "Approver Technician Summary"),
	],
	"Projects & Sites": [
		("Project", "DocType", "Project"),
		("Task", "DocType", "Task"),
	],
	"HR Tools": [
		("Employee Approver Exceptions", "Report", "Employee Approver Exceptions"),
		("Pay Batch", "DocType", "Pay Batch"),
		("Payroll Import", "DocType", "Payroll Import"),
	],
}


def ensure_number_cards():
	import json

	for label, (doctype, filters, color) in _NUMBER_CARDS.items():
		values = {
			"document_type": doctype,
			"function": "Count",
			"filters_json": json.dumps(filters),
			"is_public": 1,
			"show_percentage_stats": 0,
			"color": color,
			"module": "cooperheat",
			"type": "Document Type",
		}
		if frappe.db.exists("Number Card", label):
			doc = frappe.get_doc("Number Card", label)
			doc.update(values)
		else:
			doc = frappe.new_doc("Number Card")
			doc.label = label
			doc.name = label
			doc.update(values)
		doc.flags.ignore_permissions = True
		doc.save()


def ensure_supervisor_workspace():
	"""A workspace for supervisors and managers: numbers, shortcuts and grouped cards.
	Visible to the Supervisor and Manager roles; each of them only ever sees their
	own team. Rebuilt on every migrate so it follows this definition."""
	import json

	ensure_number_cards()

	shortcuts = [
		("Supervisor Workspace", "Page", "supervisor-workspace", None),
		("Request", "DocType", "Service Request", "New"),
		("Requests", "DocType", "Service Request", "List"),
		("Employee", "DocType", "Employee", "List"),
		("Project", "DocType", "Project", "List"),
		("Employee Checkin", "DocType", "Employee Checkin", "List"),
		("Attendance", "DocType", "Attendance", "List"),
		("Org Chart", "URL", "/app/organizational-chart", None),
	]

	def header(i, text):
		return {"id": "h%d" % i, "type": "header", "data": {"text": "<span class=\"h4\">%s</span>" % text, "col": 12}}

	content = [header(0, "Today at a glance")]
	for i, label in enumerate(_NUMBER_CARDS):
		content.append({"id": "nc%d" % i, "type": "number_card", "data": {"number_card_name": label, "col": 4}})
	content.append(header(1, "Shortcuts"))
	for i, (label, *_rest) in enumerate(shortcuts):
		content.append({"id": "sc%d" % i, "type": "shortcut", "data": {"shortcut_name": label, "col": 3}})
	content.append(header(2, "Everything in one place"))
	for i, title in enumerate(_LINK_CARDS):
		content.append({"id": "cd%d" % i, "type": "card", "data": {"card_name": title, "col": 4}})

	if frappe.db.exists("Workspace", SUPERVISOR_WORKSPACE):
		ws = frappe.get_doc("Workspace", SUPERVISOR_WORKSPACE)
		for table in ("shortcuts", "roles", "links", "number_cards"):
			ws.set(table, [])
	else:
		ws = frappe.new_doc("Workspace")
		ws.name = SUPERVISOR_WORKSPACE
		ws.title = SUPERVISOR_WORKSPACE
		ws.label = SUPERVISOR_WORKSPACE
	ws.module = "cooperheat"
	ws.public = 1
	ws.is_hidden = 0
	ws.content = json.dumps(content)

	for label, stype, link, view in shortcuts:
		row = {"label": label, "type": stype, "link_to": link}
		if stype == "URL":
			row = {"label": label, "type": "URL", "url": link}
		elif view:
			row["doc_view"] = view
		ws.append("shortcuts", row)

	for title, links in _LINK_CARDS.items():
		ws.append("links", {"type": "Card Break", "label": title, "hidden": 0})
		for label, link_type, link_to in links:
			ws.append(
				"links",
				{
					"type": "Link",
					"label": label,
					"link_type": link_type,
					"link_to": link_to,
					"is_query_report": 1 if link_type == "Report" else 0,
					"onboard": 0,
					"hidden": 0,
				},
			)

	for label in _NUMBER_CARDS:
		ws.append("number_cards", {"label": label, "number_card_name": label})
	for role in SCOPED_ROLE_NAMES + ("HR Manager", "HR User"):
		ws.append("roles", {"role": role})
	ws.flags.ignore_permissions = True
	ws.save()


def ensure_reporting_labels():
	"""Employee.reports_to is the Direct Reporting (office) / Immediate Reporting (field)
	person; approvals and the organisation chart both read it."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	make_property_setter("Employee", "reports_to", "label", "Direct / Immediate Reporting", "Data")
	# the stock "Salary" tab (CTC, salary mode, bank) is called CTC; the compensation package has its own tab
	make_property_setter("Employee", "salary_information", "label", "CTC", "Data")


def ensure_slip_print_format():
	"""Salary slip emails use the Cooperheat "Salary Slip" print format, never the plain
	standard layout: made the document default and named in Pay Sheet Settings. Only when the
	format exists on the site; an administrator's own choice is never overwritten."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	name = "Salary Slip"
	if not frappe.db.exists("Print Format", {"name": name, "doc_type": "Salary Slip", "disabled": 0}):
		return
	if not frappe.db.get_value("Property Setter", {"doc_type": "Salary Slip", "property": "default_print_format"}, "value"):
		make_property_setter("Salary Slip", None, "default_print_format", name, "Data", for_doctype=True)
	if frappe.db.exists("DocType", "Pay Sheet Settings") and not frappe.db.get_single_value("Pay Sheet Settings", "slip_print_format"):
		frappe.db.set_single_value("Pay Sheet Settings", "slip_print_format", name)


def ensure_no_automatic_slip_email():
	"""Salary slips are sent only from Payroll Import, with the Cooperheat print format. The
	standard HRMS option that e-mails every slip the moment it is submitted (always in the
	default layout) is switched off (client decision 2026-10-21)."""
	if frappe.db.exists("DocType", "Payroll Settings") and frappe.db.get_single_value(
		"Payroll Settings", "email_salary_slip_to_employee"
	):
		frappe.db.set_single_value("Payroll Settings", "email_salary_slip_to_employee", 0)


def ensure_ai_restricted():
	"""Idempotent. The Grey Theme assistant (Page ai-chat, Workspace FATEH AI) is for System Manager only.
	Both records are re-imported from the Grey Theme app on migrate, so this runs again each time."""
	for doctype, name in (("Page", "ai-chat"), ("Workspace", "FATEH AI")):
		if not frappe.db.exists(doctype, name):
			continue
		doc = frappe.get_doc(doctype, name)
		if [r.role for r in doc.roles] == ["System Manager"]:
			continue
		doc.roles = []
		doc.append("roles", {"role": "System Manager"})
		doc.flags.ignore_permissions = True
		doc.flags.ignore_version = True
		doc.save()


def ensure_division_menu():
	"""One menu for the whole hierarchy: the HR workspace entry that opened the Department
	list becomes "Division" and opens the Division screen (a plain drill-down, see
	page/division_screen). The DocType stays Department. Supervisors keep no Department entry."""
	frappe.db.sql(
		"UPDATE `tabWorkspace Link` SET label = %s, link_type = 'Page', link_to = 'division-screen' "
		"WHERE parent = %s AND link_to IN ('Department', 'division', 'division-screen') AND type = 'Link'",
		("Division", "HR"),
	)
	# The screen was first published as page "division", which a DocType of the same name
	# (production has one) hides; the old page record goes away, the new one is "division-screen".
	if frappe.db.exists("Page", "division"):
		frappe.delete_doc("Page", "division", force=True, ignore_permissions=True)


def sync_scoped_user_permissions():
	"""One-off clean-up of Employee/Department User Permissions held by
	supervisors (see permissions/scope.py)."""
	from cooperheat.cooperheat.permissions.scope import sync_all_user_permissions

	return sync_all_user_permissions()


def after_migrate():
	cleanup_legacy_employee_fields()
	seed_nationalities()
	setup_custom_fields()
	seed_settings()
	backfill_compensation_from_date()
	setup_client_scripts()
	ensure_roles()
	ensure_role_permissions()
	ensure_project_display()
	ensure_supervisor_workspace()
	ensure_division_menu()
	ensure_reporting_labels()
	ensure_slip_print_format()
	ensure_no_automatic_slip_email()
	ensure_ai_restricted()
	from cooperheat.cooperheat.roles_simple import ensure_timesheet_reviewer

	ensure_timesheet_reviewer()
	from cooperheat.cooperheat.employee_security import ensure_employee_field_security

	ensure_employee_field_security()
	from cooperheat.cooperheat import branding

	if branding.is_applied():
		branding.brand_ai_workspace()
	from cooperheat.cooperheat.approval_workflows import ensure_workflows

	ensure_workflows()
	from cooperheat.cooperheat.work_schedule import place_default_shift_field

	place_default_shift_field()
