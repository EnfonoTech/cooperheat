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
		],
	}
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


def after_migrate():
	cleanup_legacy_employee_fields()
	seed_nationalities()
	setup_custom_fields()
	seed_settings()
	backfill_compensation_from_date()
	setup_client_scripts()
