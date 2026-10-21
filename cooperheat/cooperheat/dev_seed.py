# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Fake Cooperheat-shaped data for DEV / STAGING sites only.

    bench --site <dev-site> execute cooperheat.cooperheat.dev_seed.run

Creates departments with approval matrices, supervisors, a manager, HR users,
technicians, projects and a few days of check-ins. Idempotent. Refuses to run
unless ``developer_mode`` is on, so it can never touch a production site by
accident. All users share the password in site config ``cooperheat_seed_password``.
"""

import frappe
from frappe.utils import add_days, today

COMPANY = "Cooperheat Dev"
ABBR = "CHD"
DOMAIN = "@cooperheat-dev.test"

DEPARTMENTS = ["Leak Sealing", "Contracting", "NDT"]

# key -> (first, last, roles)
STAFF = {
	"mustafa": ("Mustafa", "Quraishi", ["HR Manager", "System Manager"]),
	"irtaza": ("Irtaza", "Asghar", ["HR Manager", "HR User"]),
	"anil": ("Anil", "Govindaraj", ["Supervisor"]),
	"saleh": ("Saleh", "Alqahtani", ["Supervisor"]),
	"khalid": ("Khalid", "Rahman", ["Manager"]),
}

TECHS = {  # department -> count
	"Leak Sealing": 8,
	"Contracting": 6,
	"NDT": 4,
}

# Technicians with NO seeded check-ins, for tests that create/edit their own.
SANDBOX = [("Leak Sealing", 119), ("Leak Sealing", 120), ("Contracting", 121)]

PROJECTS = [
	("NRT-1001", "Yasref Turnaround"),
	("NRT-1002", "Yasref Shutdown"),
	("NRT-2001", "Jubail Hot Tapping"),
]


def dept_name(short: str) -> str:
	return short + " - " + ABBR


def email(key: str) -> str:
	return key + DOMAIN


def run(commit: bool = True):
	if not frappe.conf.get("developer_mode"):
		frappe.throw("dev_seed only runs on a site with developer_mode enabled.")
	frappe.flags.in_seed = True
	_departments()
	users = _users()
	employees = _employees(users)
	_reporting(employees)
	_projects()
	_shift_type()
	_checkins(employees)
	if commit:
		frappe.db.commit()
	return {"employees": len(employees)}


@frappe.whitelist()
def reset_demo():
	"""Dev sites only: restore the seeded two days of check-ins and regenerate the
	Attendance / approvals from them. Button on the Supervisor Workspace page."""
	frappe.only_for("System Manager")
	reset_activity(commit=True)
	from cooperheat.cooperheat.api.attendance_gen import generate

	return generate(add_days(today(), -3), today())


def reset_activity(commit: bool = False):
	"""Wipe check-ins / attendance of the seeded employees and recreate the seeded history.
	Tests call this so every run starts from the same two days of activity."""
	if not frappe.conf.get("developer_mode"):
		frappe.throw("dev_seed only runs on a site with developer_mode enabled.")
	emps = frappe.get_all("Employee", filters={"user_id": ["like", "%" + DOMAIN]}, pluck="name")
	if emps:
		frappe.db.delete("Attendance Site Hours", {"parent": ["in", frappe.get_all("Attendance", filters={"employee": ["in", emps]}, pluck="name")]})
		frappe.db.delete("Attendance", {"employee": ["in", emps]})
		frappe.db.delete("Employee Checkin", {"employee": ["in", emps]})
	return run(commit=commit)


def _departments():
	for d in DEPARTMENTS:
		if not frappe.db.exists("Department", dept_name(d)):
			frappe.get_doc(
				{
					"doctype": "Department",
					"department_name": d,
					"company": COMPANY,
					"parent_department": "All Departments",
				}
			).insert(ignore_permissions=True)


def _password() -> str:
	return frappe.conf.get("cooperheat_seed_password") or "ChangeMe-" + frappe.generate_hash(length=8)


def _make_user(key: str, first: str, last: str, roles: list[str]) -> str:
	mail = email(key)
	if not frappe.db.exists("User", mail):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": mail,
				"first_name": first,
				"last_name": last,
				"send_welcome_email": 0,
				"enabled": 1,
				"new_password": _password(),
				"roles": [{"role": r} for r in roles],
			}
		)
		user.flags.ignore_permissions = True
		user.insert()
	else:
		user = frappe.get_doc("User", mail)
		have = {r.role for r in user.roles}
		for r in roles:
			if r not in have:
				user.append("roles", {"role": r})
		user.flags.ignore_permissions = True
		user.save()
	return mail


def _users() -> dict:
	out = {}
	for key, (first, last, roles) in STAFF.items():
		out[key] = _make_user(key, first, last, roles + ["Employee"])
	return out


def _make_employee(first, last, user, dept, number):
	existing = frappe.db.get_value("Employee", {"user_id": user} if user else {"employee_number": number}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": first,
			"last_name": last,
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": "2025-01-01",
			"company": COMPANY,
			"department": dept,
			"status": "Active",
			"user_id": user,
			"employee_number": number,
			"create_user_permission": 0 if number in ("S001", "S002") else 1,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _employees(users: dict) -> dict:
	emps = {}
	for i, (key, (first, last, _roles)) in enumerate(STAFF.items(), start=1):
		dept = {"anil": "Leak Sealing", "saleh": "Contracting"}.get(key)
		emps[key] = _make_employee(first, last, users[key], dept_name(dept) if dept else None, "S%03d" % i)

	n = 100
	for dept, count in TECHS.items():
		for i in range(1, count + 1):
			n += 1
			key = "tech%d" % n
			mail = _make_user(key, "Tech%d" % n, dept.replace(" ", ""), ["Employee"])
			emps[key] = _make_employee("Tech%d" % n, dept.replace(" ", ""), mail, dept_name(dept), "T%d" % n)

	for dept, num in SANDBOX:
		key = "sandbox%d" % num
		mail = _make_user(key, "Sandbox%d" % num, dept.replace(" ", ""), ["Employee"])
		emps[key] = _make_employee("Sandbox%d" % num, dept.replace(" ", ""), mail, dept_name(dept), "T%d" % num)

	# HR users are not limited to themselves (HRMS adds "Employee = self" unless told not to)
	for key in ("mustafa", "irtaza"):
		for up in frappe.get_all("User Permission", filters={"user": email(key), "allow": "Employee"}, pluck="name"):
			frappe.delete_doc("User Permission", up, ignore_permissions=True, force=True)

	# reporting lines: Leak Sealing -> Anil, Contracting -> Saleh, supervisors -> Khalid; NDT left unlinked
	for key, name in emps.items():
		if not key.startswith(("tech", "sandbox")):
			continue
		dept = frappe.db.get_value("Employee", name, "department")
		boss = {dept_name("Leak Sealing"): emps["anil"], dept_name("Contracting"): emps["saleh"]}.get(dept)
		if boss:
			frappe.db.set_value("Employee", name, "reports_to", boss, update_modified=False)
	for key in ("anil", "saleh"):
		frappe.db.set_value("Employee", emps[key], "reports_to", emps["khalid"], update_modified=False)
	return emps


def _reporting(emps: dict):
	"""Field staff: Immediate Reporting = Reports To (set in _employees), Secondary Reporting =
	Khalid (for technicians), Payroll Approver = Irtaza. HR and Khalid are office / unlisted."""
	for key, name in emps.items():
		if key in ("mustafa", "irtaza", "khalid"):
			continue
		values = {"custom_staff_category": "Field Staff"}
		if key.startswith(("tech", "sandbox")) and frappe.db.get_value("Employee", name, "reports_to"):
			values["custom_secondary_reporting"] = emps["khalid"]
		frappe.db.set_value("Employee", name, values, update_modified=False)
	settings = frappe.get_single("Pay Sheet Settings")
	settings.payroll_approver = emps["irtaza"]
	settings.flags.ignore_permissions = True
	settings.save()


def _projects():
	for code, title in PROJECTS:
		if not frappe.db.exists("Project", code):
			doc = frappe.get_doc(
				{
					"doctype": "Project",
					"project_name": title,
					"custom_project_code": code,
					"custom_crm_no": code,
					"company": COMPANY,
					"status": "Open",
				}
			)
			doc.flags.ignore_permissions = True
			doc.insert()


def _shift_type():
	# mirror production: one "regular" shift, auto attendance on, last sync long ago
	if frappe.db.exists("Shift Type", "regular"):
		return
	frappe.get_doc(
		{
			"doctype": "Shift Type",
			"name": "regular",
			"start_time": "07:00:00",
			"end_time": "16:00:00",
			"enable_auto_attendance": 1,
			"process_attendance_after": add_days(today(), -20),
			"last_sync_of_checkin": add_days(today(), -15),
			"determine_check_in_and_check_out": "Alternating entries as IN and OUT during the same shift",
			"begin_check_in_before_shift_start_time": 60,
			"allow_check_out_after_shift_end_time": 60,
		}
	).insert(ignore_permissions=True)


def _checkins(emps: dict):
	"""Yesterday and the day before: a complete 07:15-16:40 day for every technician
	with a department; today an open IN for the first Leak Sealing tech."""
	techs = [name for key, name in emps.items() if key.startswith("tech")]
	for name in techs:
		for back in (1, 2):
			day = add_days(today(), -back)
			if frappe.db.exists("Employee Checkin", {"employee": name, "time": ["between", [day + " 00:00:00", day + " 23:59:59"]]}):
				continue
			for log_type, hh in (("IN", "07:15:00"), ("OUT", "16:40:00")):
				frappe.get_doc(
					{
						"doctype": "Employee Checkin",
						"employee": name,
						"log_type": log_type,
						"time": day + " " + hh,
						"custom_project": "NRT-1001",
					}
				).insert(ignore_permissions=True)
