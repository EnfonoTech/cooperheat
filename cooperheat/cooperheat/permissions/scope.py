# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

"""Team scoping for supervisors and managers.

A user holding a *scoped* role (Supervisor / Manager) and none of the HR /
System roles only sees:

  * their own Employee record,
  * everyone below them through ``Employee.reports_to`` (the whole subtree), and
  * everyone who names them as Secondary Reporting (and the subtree below those).

The rule is evaluated per request from live data, so a new joiner or a changed
reporting line takes effect immediately - no per-user User Permission rows to
maintain. The Payroll Approver (Pay Sheet Settings) is never restricted: the
final approval step needs every record.

Scoped doctypes: Employee, Employee Checkin, Attendance, Shift Assignment and
Department. HR Manager / HR User / System Manager / Administrator are never
restricted, and users without a scoped role keep the standard behaviour.
"""

import frappe

SCOPED_ROLES = frozenset({"Supervisor", "Manager"})
UNRESTRICTED_ROLES = frozenset({"System Manager", "HR Manager", "HR User"})

# reports_to chains in a company this size are a handful deep; the cap is a
# guard against a cycle in bad data, not a business limit.
MAX_DEPTH = 10

_CACHE_KEY = "cooperheat_scope_cache"


def unrestricted_roles() -> frozenset:
	"""HR / System roles plus any extra roles listed in site config
	``cooperheat_unrestricted_roles`` (e.g. a payroll role that must keep seeing everyone)."""
	extra = frappe.conf.get("cooperheat_unrestricted_roles") or []
	return UNRESTRICTED_ROLES | frozenset(extra)


def is_scoped(user: str | None = None) -> bool:
	"""True when ``user`` must be limited to their own team."""
	user = user or frappe.session.user
	if user == "Administrator":
		return False
	roles = set(frappe.get_roles(user))
	if not (roles & SCOPED_ROLES) or (roles & unrestricted_roles()):
		return False
	from cooperheat.cooperheat.org import is_payroll_approver

	return not is_payroll_approver(user)


def _own_employees(user: str) -> list[str]:
	return frappe.get_all("Employee", filters={"user_id": user}, pluck="name")


def _subtree(roots: list[str]) -> set[str]:
	seen = set(roots)
	frontier = list(roots)
	for _ in range(MAX_DEPTH):
		if not frontier:
			break
		children = frappe.get_all(
			"Employee",
			or_filters={
				"reports_to": ["in", frontier],
				"custom_secondary_reporting": ["in", frontier],
				"custom_support_reporting": ["in", frontier],
			},
			pluck="name",
		)
		frontier = [c for c in children if c not in seen]
		seen.update(frontier)
	return seen


def get_scope(user: str | None = None) -> frappe._dict:
	"""Return ``{employees: set, departments: set}`` visible to ``user``.

	Cached for the duration of the request.
	"""
	user = user or frappe.session.user
	cache = _cache()
	if user in cache:
		return cache[user]

	own = _own_employees(user)
	employees = _subtree(own)

	departments = set()
	if employees:
		departments.update(
			d
			for d in frappe.get_all("Employee", filters={"name": ["in", list(employees)]}, pluck="department")
			if d
		)

	cache[user] = frappe._dict(employees=employees, departments=departments)
	return cache[user]


def _cache() -> dict:
	cache = getattr(frappe.local, _CACHE_KEY, None)
	if cache is None:
		cache = {}
		setattr(frappe.local, _CACHE_KEY, cache)
	return cache


def clear_cache():
	setattr(frappe.local, _CACHE_KEY, {})


def _in_clause(column: str, values) -> str:
	"""``column in ('a', 'b')`` with every value escaped; ``1=0`` when empty.
	``column`` is always a hard-coded identifier from this module."""
	values = sorted(v for v in values if v)
	if not values:
		return "1=0"
	return column + " in (" + ", ".join(frappe.db.escape(v) for v in values) + ")"


# ---------------------------------------------------------------------------
# hooks.py entry points
# ---------------------------------------------------------------------------


def employee_query(user=None, doctype=None):
	if not is_scoped(user):
		return ""
	return _in_clause("`tabEmployee`.`name`", get_scope(user or frappe.session.user).employees)


def employee_checkin_query(user=None, doctype=None):
	if not is_scoped(user):
		return ""
	return _in_clause("`tabEmployee Checkin`.`employee`", get_scope(user or frappe.session.user).employees)


def attendance_query(user=None, doctype=None):
	if not is_scoped(user):
		return ""
	return _in_clause("`tabAttendance`.`employee`", get_scope(user or frappe.session.user).employees)


def shift_assignment_query(user=None, doctype=None):
	if not is_scoped(user):
		return ""
	return _in_clause("`tabShift Assignment`.`employee`", get_scope(user or frappe.session.user).employees)


def department_query(user=None, doctype=None):
	if not is_scoped(user):
		return ""
	return _in_clause("`tabDepartment`.`name`", get_scope(user or frappe.session.user).departments)


def _deny_unless_in(user, employee) -> bool | None:
	"""``False`` when the record is outside the user's team; ``None`` (defer to
	the standard checks) otherwise. Never returns ``True`` so it cannot widen
	access that role permissions or User Permissions already deny."""
	user = user or frappe.session.user
	if not is_scoped(user):
		return None
	if not employee:
		# new / blank document: nothing to scope yet (the employee link is validated on save)
		return None
	if employee in get_scope(user).employees:
		return None
	return False


def employee_has_permission(doc, ptype=None, user=None, debug=False):
	return _deny_unless_in(user, doc.name)


def employee_doc_has_permission(doc, ptype=None, user=None, debug=False):
	# Employee Checkin / Attendance / Shift Assignment all carry ``employee``
	return _deny_unless_in(user, doc.get("employee"))


def department_has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if not is_scoped(user):
		return None
	if doc.name in get_scope(user).departments:
		return None
	return False


# ---------------------------------------------------------------------------
# User Permission clean-up
# ---------------------------------------------------------------------------
# HRMS creates an ``Employee = <self>`` User Permission for every user linked to
# an Employee. For a scoped user that row would hide their team again (User
# Permissions are applied on top of role permissions), so scoped users must not
# carry it. A manually added ``Department`` User Permission has the same effect
# on Employee lists and is removed for the same reason.

_STALE_UP_DOCTYPES = ("Employee", "Department")


def sync_user_permissions(user: str) -> list[dict]:
	"""Remove stale Employee / Department User Permissions of a scoped user.
	Returns the removed rows (``user``, ``allow``, ``for_value``) so callers can log them."""
	if not is_scoped(user):
		return []
	rows = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": ["in", _STALE_UP_DOCTYPES]},
		fields=["name", "user", "allow", "for_value"],
	)
	for row in rows:
		frappe.delete_doc("User Permission", row.name, ignore_permissions=True, force=True)
	return [{"user": r.user, "allow": r.allow, "for_value": r.for_value} for r in rows]


def restore_self_permission(user: str):
	"""A user who is no longer a supervisor/manager is an ordinary employee again:
	give back the HRMS "Employee = self" restriction that scoping removed."""
	if is_scoped(user) or user == "Administrator":
		return
	roles = set(frappe.get_roles(user))
	if roles & unrestricted_roles():
		return
	emp = frappe.db.get_value("Employee", {"user_id": user}, ["name", "create_user_permission"], as_dict=True)
	if not emp or not emp.create_user_permission:
		return
	if frappe.db.exists("User Permission", {"user": user, "allow": "Employee", "for_value": emp.name}):
		return
	from frappe.permissions import add_user_permission

	add_user_permission("Employee", emp.name, user, ignore_permissions=True)


def sync_all_user_permissions() -> list[dict]:
	users = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ["in", list(SCOPED_ROLES)]},
		pluck="parent",
		distinct=True,
	)
	removed = []
	for user in users:
		removed.extend(sync_user_permissions(user))
	return removed


def on_user_update(doc, method=None):
	"""Roles changed on a User: drop the stale User Permissions of a new
	supervisor, or restore the self restriction of one who lost the role."""
	clear_cache()
	if sync_user_permissions(doc.name):
		return
	restore_self_permission(doc.name)


def on_employee_update(doc, method=None):
	"""HRMS re-creates ``Employee = self`` whenever an Employee is saved."""
	if doc.get("user_id"):
		sync_user_permissions(doc.user_id)
