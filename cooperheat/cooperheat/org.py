"""Organisation structure: Division / Department / Business Line / Product Line.

Everything lives in one HRMS Department tree. Each node carries a Unit Type.
Support side: Division > Department > Sub-Department.
Operations side: Business Line > Product Line > Sub-Product Line.
Operations staff are placed with Business Line + Product Line on the Employee;
`Employee.department` is derived from them, so every approval path that reads
the department keeps working.

Approvers are inherited: for each level, the nearest node (the employee's own,
then its parents) that has an approver for that level wins. A matrix row with a
Location only applies to employees assigned to that location; a row without a
Location applies to everyone.
"""

import frappe
from frappe import _
from frappe.utils import cint

DIVISION = "Division"
DEPARTMENT = "Department"
SUB_DEPARTMENT = "Sub-Department"
BUSINESS_LINE = "Business Line"
PRODUCT_LINE = "Product Line"
SUB_PRODUCT_LINE = "Sub-Product Line"
# A Sub-Product Line is a Product Line one level further down: an employee can
# be placed on either.
PRODUCT_TYPES = (PRODUCT_LINE, SUB_PRODUCT_LINE)
OPERATIONS_TYPES = (BUSINESS_LINE, PRODUCT_LINE, SUB_PRODUCT_LINE)
# What a new node under a parent of this type is. Everything below a
# Sub-Department / Sub-Product Line stays the same type.
CHILD_TYPE = {
	DIVISION: DEPARTMENT,
	DEPARTMENT: SUB_DEPARTMENT,
	SUB_DEPARTMENT: SUB_DEPARTMENT,
	BUSINESS_LINE: PRODUCT_LINE,
	PRODUCT_LINE: SUB_PRODUCT_LINE,
	SUB_PRODUCT_LINE: SUB_PRODUCT_LINE,
}
MATRIX_FIELDS = ["parent", "approval_level", "approver", "approval_window_hours", "location"]


def _cache() -> dict:
	if not hasattr(frappe.local, "cooperheat_org_cache"):
		frappe.local.cooperheat_org_cache = {}
	return frappe.local.cooperheat_org_cache


def clear_cache():
	if hasattr(frappe.local, "cooperheat_org_cache"):
		frappe.local.cooperheat_org_cache = {}


def unit_type(department: str | None) -> str | None:
	if not department:
		return None
	return frappe.db.get_value("Department", department, "custom_unit_type")


def ancestors(department: str | None) -> list[str]:
	"""The department and its parents, nearest first."""
	if not department:
		return []
	key = ("ancestors", department)
	cache = _cache()
	if key not in cache:
		bounds = frappe.db.get_value("Department", department, ["lft", "rgt"], as_dict=True)
		if not bounds:
			cache[key] = [department]
		else:
			Department = frappe.qb.DocType("Department")
			cache[key] = (
				frappe.qb.from_(Department)
				.select(Department.name)
				.where((Department.lft <= bounds.lft) & (Department.rgt >= bounds.rgt))
				.orderby(Department.lft, order=frappe.qb.desc)
			).run(pluck=True)
	return cache[key]


def descendants(departments) -> set[str]:
	"""The given departments and everything below them."""
	out = set()
	for name in departments or []:
		bounds = frappe.db.get_value("Department", name, ["lft", "rgt"], as_dict=True)
		if not bounds:
			continue
		out.update(
			frappe.get_all(
				"Department", filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]}, pluck="name"
			)
		)
	return out


def nearest_of_type(department: str | None, wanted: str) -> str | None:
	for name in ancestors(department):
		if unit_type(name) == wanted:
			return name
	return None


def employee_location(employee: str | None) -> str | None:
	if not employee:
		return None
	return frappe.db.get_value("Employee", employee, "custom_assigned_location")


def effective_matrix(department: str | None, employee: str | None = None, location: str | None = None) -> list:
	"""Approval rows that apply, one per level, inherited up the tree.

	Each row: approval_level, approver, approval_window_hours, location, source
	(the department the row came from).
	"""
	if not department:
		return []
	location = location or employee_location(employee)
	key = ("matrix", department, location)
	cache = _cache()
	if key in cache:
		return cache[key]

	chain = ancestors(department)
	rows = frappe.get_all(
		"Department Approval Matrix",
		filters={"parent": ["in", chain], "parentfield": "approval_matrix"},
		fields=MATRIX_FIELDS,
	)
	by_node = {}
	for r in rows:
		by_node.setdefault(r.parent, []).append(r)

	levels = sorted({cint(r.approval_level) for r in rows if r.approver})
	result = []
	for level in levels:
		row = _pick(chain, by_node, level, location)
		if row:
			result.append(
				frappe._dict(
					approval_level=level,
					approver=row.approver,
					approval_window_hours=row.approval_window_hours,
					location=row.location,
					source=row.parent,
				)
			)
	cache[key] = result
	return result


def _pick(chain, by_node, level, location):
	for node in chain:
		candidates = [r for r in by_node.get(node, []) if cint(r.approval_level) == level and r.approver]
		if not candidates:
			continue
		if location:
			exact = [r for r in candidates if r.location == location]
			if exact:
				return exact[0]
		generic = [r for r in candidates if not r.location]
		if generic:
			return generic[0]
		if not location:
			# Location unknown (department-level question): any row answers it.
			return candidates[0]
	return None


def l1_approver(department: str | None, employee: str | None = None, location: str | None = None) -> str | None:
	"""Legacy: first approver from the Department Approval Matrix. Routing no longer reads it
	(see approval_chain); kept so old data can still be inspected."""
	row = next((r for r in effective_matrix(department, employee, location) if r.approval_level == 1), None)
	return row.approver if row else None


# ---------------------------------------------------------------------------
# Approval chain: the employee's own reporting line
# ---------------------------------------------------------------------------
#
# Level 1  Direct Reporting (office) / Immediate Reporting (field)  = Employee.reports_to
# Level 2  Secondary Reporting (field staff only)                   = Employee.custom_secondary_reporting
# Level 3  Payroll                                                  = Pay Sheet Settings.payroll_approver
#
# A level nobody holds is skipped by the Attendance workflow (it passes on by
# itself), so an office employee goes Direct Reporting -> Payroll, and everything
# passes to Payroll alone when no Payroll Approver is set. Nobody approves their
# own record: a person already used at an earlier level is dropped from later ones.

OFFICE_STAFF = "Office Staff"
FIELD_STAFF = "Field Staff"
DEFAULT_WINDOW_HOURS = {1: 48, 2: 72, 3: 48}
_WINDOW_FIELDS = {
	1: "immediate_approval_window_hours",
	2: "secondary_approval_window_hours",
	3: "payroll_approval_window_hours",
}
PENDING_LEVEL = {
	"Pending Level 1 Approval": 1,
	"Pending Level 2 Approval": 2,
	"Pending Level 3 Approval": 3,
}


def approval_settings() -> dict:
	cache = _cache()
	if "approval_settings" not in cache:
		cache["approval_settings"] = frappe.db.get_singles_dict("Pay Sheet Settings") or {}
	return cache["approval_settings"]


def window_hours(level: int) -> int:
	return cint(approval_settings().get(_WINDOW_FIELDS[level])) or DEFAULT_WINDOW_HOURS[level]


def payroll_approver() -> str | None:
	return approval_settings().get("payroll_approver") or None


def is_payroll_approver(user: str | None = None) -> bool:
	approver = payroll_approver()
	if not approver:
		return False
	return frappe.db.get_value("Employee", approver, "user_id") == (user or frappe.session.user)


def approval_chain(employee: str | None) -> list:
	"""Approval rows for one employee: approval_level, approver, approval_window_hours, source.
	Only levels that have somebody are returned."""
	if not employee:
		return []
	emp = frappe.db.get_value(
		"Employee", employee, ["reports_to", "custom_secondary_reporting", "custom_staff_category"], as_dict=True
	)
	if not emp:
		return []
	rows, used = [], {employee}

	def add(level, approver, source):
		if approver and approver not in used:
			used.add(approver)
			rows.append(
				frappe._dict(
					approval_level=level,
					approver=approver,
					approval_window_hours=window_hours(level),
					location=None,
					source=source,
				)
			)

	add(1, emp.reports_to, "reports_to")
	if emp.custom_staff_category != OFFICE_STAFF:
		add(2, emp.custom_secondary_reporting, "custom_secondary_reporting")
	add(3, payroll_approver(), "payroll_approver")
	return rows


def first_approver(employee: str | None) -> str | None:
	row = next((r for r in approval_chain(employee) if r.approval_level == 1), None)
	return row.approver if row else None


def _stamp_approver(attendance: str, approver: str | None):
	name = frappe.db.get_value("Employee", approver, "employee_name") if approver else None
	frappe.db.set_value(
		"Attendance",
		attendance,
		{"current_approver": approver, "current_approver_name": name or approver},
		update_modified=False,
	)


def restamp_pending_attendance(employee: str):
	"""The employee's reporting line changed: records still waiting on an approver
	move to the new one, so nobody is locked out by a stale name."""
	pending = frappe.get_all(
		"Attendance",
		filters={"employee": employee, "workflow_state": ["in", list(PENDING_LEVEL)], "docstatus": 1},
		fields=["name", "workflow_state", "current_approver"],
	)
	if not pending:
		return
	chain = approval_chain(employee)
	for rec in pending:
		row = next((r for r in chain if r.approval_level == PENDING_LEVEL[rec.workflow_state]), None)
		if row and row.approver != rec.current_approver:
			_stamp_approver(rec.name, row.approver)


def restamp_payroll_step():
	"""Payroll Approver changed: everything waiting at the Payroll step follows."""
	clear_cache()  # the settings were just saved; do not read a copy cached earlier in the request
	approver = payroll_approver()
	if not approver:
		return
	for rec in frappe.get_all(
		"Attendance",
		filters={"workflow_state": "Pending Level 3 Approval", "docstatus": 1, "current_approver": ["!=", approver]},
		fields=["name"],
	):
		_stamp_approver(rec.name, approver)


# ---------------------------------------------------------------------------
# Employee placement
# ---------------------------------------------------------------------------


def sync_employee_org(doc):
	"""Business Line / Product Line <-> department, validated.

	* Product Line given without Business Line: Business Line is filled from the tree.
	* Business Line set: department = Product Line, or the Business Line itself for its head.
	* Department picked directly on an operations node: the two fields are filled from it.
	"""
	bl, pl = doc.get("custom_business_line"), doc.get("custom_product_line")

	if pl:
		if unit_type(pl) not in PRODUCT_TYPES:
			frappe.throw(_("{0} is not a Product Line.").format(frappe.bold(pl)))
		parent_bl = nearest_of_type(pl, BUSINESS_LINE)
		if not bl:
			bl = doc.custom_business_line = parent_bl
		elif parent_bl != bl:
			frappe.throw(
				_("Product Line {0} does not belong to Business Line {1}.").format(frappe.bold(pl), frappe.bold(bl))
			)

	if bl:
		if unit_type(bl) != BUSINESS_LINE:
			frappe.throw(_("{0} is not a Business Line.").format(frappe.bold(bl)))
		doc.department = pl or bl
		return

	if doc.get("department") and unit_type(doc.department) in OPERATIONS_TYPES:
		if unit_type(doc.department) in PRODUCT_TYPES:
			doc.custom_product_line = doc.department
		doc.custom_business_line = nearest_of_type(doc.department, BUSINESS_LINE)


APPROVER_FIELDS = ("leave_approver", "shift_request_approver", "expense_approver")


def fill_secondary_reporting(doc):
	"""Anyone who is not Office Staff (Field Staff, or a category not set yet) without a Secondary
	Reporting person gets their supervisor's own reporting person (normally the Manager), once:
	when Reports To is set or changes, or when the Staff Category is set or changes. HR can
	overwrite or clear it afterwards. Office Staff never use Secondary Reporting."""
	if not doc.meta.has_field("custom_secondary_reporting"):
		return
	if doc.get("custom_staff_category") == OFFICE_STAFF or doc.get("custom_secondary_reporting"):
		return
	if not doc.get("reports_to"):
		return
	if not (doc.is_new() or doc.has_value_changed("reports_to") or doc.has_value_changed("custom_staff_category")):
		return
	boss = frappe.db.get_value("Employee", doc.reports_to, "reports_to")
	if boss and boss != doc.name:
		doc.custom_secondary_reporting = boss


def backfill_secondary_reporting(dry_run=True) -> dict:
	"""One-off for employees that existed before Secondary Reporting did: fill it from the
	supervisor's own reporting person where empty (not for Office Staff), then move Attendance
	that is still waiting for approval to the right people. Writes straight to the database (no
	other hooks run); dry_run only counts."""
	rows = frappe.get_all(
		"Employee",
		filters={"status": "Active", "reports_to": ["is", "set"], "custom_secondary_reporting": ["is", "not set"]},
		fields=["name", "reports_to", "custom_staff_category"],
	)
	bosses = {
		e.name: e.reports_to
		for e in frappe.get_all(
			"Employee", filters={"name": ["in", sorted({r.reports_to for r in rows}) or [""]]}, fields=["name", "reports_to"]
		)
	}
	changed = []
	for r in rows:
		boss = bosses.get(r.reports_to)
		if r.custom_staff_category == OFFICE_STAFF or not boss or boss == r.name:
			continue
		changed.append((r.name, boss))
		if not dry_run:
			frappe.db.set_value("Employee", r.name, "custom_secondary_reporting", boss, update_modified=False)
	restamped = 0
	if not dry_run:
		clear_cache()
		pending = frappe.get_all(
			"Attendance", filters={"docstatus": 1, "workflow_state": ["in", list(PENDING_LEVEL)]}, pluck="employee"
		)
		for employee in sorted(set(pending)):
			restamp_pending_attendance(employee)
			restamped += 1
	return {"filled": len(changed), "employees_restamped": restamped, "dry_run": bool(dry_run)}


def fill_default_approvers(doc):
	"""Leave / Shift Request / Expense approver = the Direct / Immediate Reporting
	person's User. An empty field is filled; one that still holds the PREVIOUS
	reporting person's User follows the change; a value HR set by hand is kept.

	HRMS requires a Leave Approver on every leave; without this, HR cannot save
	a leave for anyone whose employee record was never given one.
	"""
	approver = doc.get("reports_to")
	if not approver or approver == doc.name:
		return
	user = frappe.db.get_value("Employee", approver, "user_id")
	if not user:
		return
	old_user = None
	if not doc.is_new():
		old = frappe.db.get_value("Employee", doc.name, "reports_to")
		if old and old != approver:
			old_user = frappe.db.get_value("Employee", old, "user_id")
	for field in APPROVER_FIELDS:
		if not doc.meta.has_field(field):
			continue
		current = doc.get(field)
		if not current or (old_user and current == old_user):
			doc.set(field, user)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def product_line_query(doctype, txt, searchfield, start, page_len, filters):
	"""Product Lines (and Sub-Product Lines) under the chosen Business Line (all of them if none chosen)."""
	conditions = [["custom_unit_type", "in", list(PRODUCT_TYPES)], ["disabled", "=", 0]]
	business_line = (filters or {}).get("business_line")
	if business_line:
		conditions.append(["name", "in", list(descendants([business_line])) or [""]])
	if txt:
		conditions.append(["name", "like", "%" + txt + "%"])
	return frappe.get_list(
		"Department",
		filters=conditions,
		fields=["name", "parent_department"],
		limit_start=start,
		limit_page_length=page_len,
		order_by="lft asc",
		as_list=True,
	)


# ---------------------------------------------------------------------------
# Hierarchy screens (Division tree and Department form)
# ---------------------------------------------------------------------------


def child_unit_type(parent: str | None) -> str | None:
	"""The Unit Type a new node under *parent* gets (None when the parent has no type,
	e.g. the root: the person adding it then picks Division or Business Line)."""
	return CHILD_TYPE.get(unit_type(parent)) if parent else None


def _employee_counts(departments) -> dict:
	if not departments:
		return {}
	from frappe.query_builder.functions import Count

	Employee = frappe.qb.DocType("Employee")
	rows = (
		frappe.qb.from_(Employee)
		.select(Employee.department, Count(Employee.name).as_("total"))
		.where((Employee.department.isin(list(departments))) & (Employee.status == "Active"))
		.groupby(Employee.department)
	).run(as_dict=True)
	return {r.department: r.total for r in rows}


@frappe.whitelist()
def department_children(doctype, parent=None, company=None, is_root=False):
	"""Children for the Division tree: the stock ERPNext rows plus Unit Type,
	company and the number of active employees placed directly on each node."""
	frappe.has_permission("Department", "read", throw=True)
	from erpnext.setup.doctype.department.department import get_children

	rows = get_children(doctype, parent, company, is_root)
	names = [r["value"] for r in rows]
	meta = {
		d.name: d
		for d in frappe.get_all(
			"Department", filters={"name": ["in", names]}, fields=["name", "custom_unit_type", "company"]
		)
	} if names else {}
	counts = _employee_counts(names)
	for row in rows:
		info = meta.get(row["value"])
		row["unit_type"] = info.custom_unit_type if info else None
		row["company"] = info.company if info else None
		row["employees"] = counts.get(row["value"], 0)
	return rows


@frappe.whitelist()
def department_overview(department):
	"""What the Department form shows under a node: its direct children, the type
	a new child would get, and head counts (placed on the node itself, and
	including everything below each child)."""
	frappe.has_permission("Department", "read", doc=department, throw=True)
	bounds = frappe.db.get_value("Department", department, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return {"unit_type": None, "child_type": None, "employees": 0, "children": []}
	# One pass over the subtree: nodes with their bounds, and active head counts.
	nodes = frappe.get_all(
		"Department",
		filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt], "disabled": 0},
		fields=["name", "department_name", "custom_unit_type", "is_group", "parent_department", "lft", "rgt"],
		order_by="lft asc",
	)
	counts = _employee_counts([n.name for n in nodes])
	children = [n for n in nodes if n.parent_department == department]
	for child in children:
		child["employees"] = sum(
			counts.get(n.name, 0) for n in nodes if n.lft >= child.lft and n.rgt <= child.rgt
		)
	return {
		"unit_type": unit_type(department),
		"child_type": child_unit_type(department),
		"employees": counts.get(department, 0),
		"children": children,
	}


# ---------------------------------------------------------------------------
# Division screen: plain drill-down, no tree
# ---------------------------------------------------------------------------

KIND_ROOT_TYPE = {"Division": DIVISION, "Business Line": BUSINESS_LINE}
SUPPORT_TYPES = (DIVISION, DEPARTMENT, SUB_DEPARTMENT)


def kind_of(unit: str | None) -> str:
	"""Which tab of the Division screen a node belongs to."""
	if unit in SUPPORT_TYPES:
		return "Division"
	if unit in OPERATIONS_TYPES:
		return "Business Line"
	return "Other"


def _screen_company(node, company):
	if company:
		return company
	if node:
		return frappe.db.get_value("Department", node, "company")
	typed = frappe.get_all(
		"Department",
		filters={"custom_unit_type": ["in", list(CHILD_TYPE)]},
		fields=["company", "count(name) as total"],
		group_by="company",
		order_by="total desc",
	)
	with_structure = [t.company for t in typed if t.company]
	preferred = frappe.defaults.get_user_default("Company")
	if preferred in with_structure or not with_structure:
		return preferred or frappe.db.get_value("Company", {}, "name")
	return with_structure[0]


@frappe.whitelist()
def division_view(node=None, kind="Division", company=None):
	"""Everything the Division screen shows for one step of the drill-down.

	No node: the top level of the chosen tab (support Divisions, Business Lines, or old
	departments that have no type yet). With a node: its sub-units and the active
	employees placed directly on it.
	"""
	from frappe.utils.nestedset import get_root_of

	frappe.has_permission("Department", "read", throw=True)
	company = _screen_company(node, company)
	companies = frappe.get_all("Company", pluck="name")
	units = frappe.get_all(
		"Department",
		filters={"company": company, "disabled": 0},
		fields=["name", "department_name", "custom_unit_type", "is_group", "parent_department", "lft", "rgt"],
		order_by="lft asc",
	)
	by_name = {u.name: u for u in units}
	counts = _employee_counts(list(by_name))
	root = get_root_of("Department")

	def row(u):
		below = [n for n in units if n.lft >= u.lft and n.rgt <= u.rgt]
		return {
			"name": u.name,
			"label": u.department_name,
			"unit_type": u.custom_unit_type,
			"employees": sum(counts.get(n.name, 0) for n in below),
			"sub_units": len(below) - 1,
		}

	out = {
		"company": company,
		"companies": companies if len(companies) > 1 else [],
		"kind": kind,
		"can_create": bool(frappe.has_permission("Department", "create")),
		"root": root,
	}
	if not node:
		wanted = KIND_ROOT_TYPE.get(kind)
		tops = [u for u in units if u.parent_department == root and (u.custom_unit_type or None) == wanted]
		out.update(
			node=None,
			breadcrumb=[],
			children=[row(u) for u in tops],
			employees=[],
			add_type=wanted,
			old_departments=sum(1 for u in units if u.parent_department == root and not u.custom_unit_type),
		)
		return out

	current = by_name.get(node)
	if not current:
		frappe.throw(_("{0} was not found.").format(node))
	crumbs, up = [], current
	while up and up.name != root:
		crumbs.append({"name": up.name, "label": up.department_name})
		up = by_name.get(up.parent_department)
	crumbs.reverse()

	employees = frappe.get_list(
		"Employee",
		filters={"department": node, "status": "Active"},
		fields=["name", "employee_name", "designation", "custom_staff_category", "reports_to"],
		order_by="employee_name asc",
		limit_page_length=500,
	)
	bosses = {
		e.name: e.employee_name
		for e in frappe.get_all(
			"Employee", filters={"name": ["in", [e.reports_to for e in employees if e.reports_to] or [""]]}, fields=["name", "employee_name"]
		)
	}
	for e in employees:
		e["reports_to_name"] = bosses.get(e.reports_to)
	out.update(
		node=row(current),
		breadcrumb=crumbs,
		children=[row(u) for u in units if u.parent_department == node],
		employees=employees,
		add_type=CHILD_TYPE.get(current.custom_unit_type),
		kind=kind_of(current.custom_unit_type) if current.custom_unit_type else kind,
	)
	return out


def _division_node(division: str | None) -> str | None:
	"""The Department tree node of unit type Division that carries the legacy Division's name
	("Finance" -> "Finance Division - C", "Management" -> "Management - C"); None when there is none
	(Admin, the business lines ...)."""
	if not division:
		return None
	rows = frappe.get_all(
		"Department",
		filters={"custom_unit_type": "Division", "disabled": 0},
		or_filters=[["name", "like", f"{division} Division - %"], ["name", "like", f"{division} - %"]],
		pluck="name",
		order_by="name asc",
	)
	return rows[0] if rows else None


@frappe.whitelist()
def departments_in_division(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for Employee.department: only the departments below the chosen legacy Division;
	every department of the company when the Division has no matching node (or is empty)."""
	filters = frappe._dict(filters or {})
	node = _division_node(filters.get("division"))
	conditions = {"disabled": 0}
	if filters.get("company"):
		conditions["company"] = filters.company
	if node:
		below = descendants([node]) - {node}
		if not below:
			return []
		conditions["name"] = ["in", list(below)]
	return frappe.get_all(
		"Department",
		filters=conditions,
		or_filters=[["name", "like", f"%{txt}%"], ["department_name", "like", f"%{txt}%"]],
		fields=["name", "custom_unit_type"],
		order_by="name asc",
		limit_start=cint(start),
		limit_page_length=cint(page_len),
		as_list=True,
	)


@frappe.whitelist()
def department_in_division(division: str, department: str) -> bool | None:
	"""Does ``department`` belong to the Division? None when the Division has no department node."""
	node = _division_node(division)
	if not node:
		return None
	return department in (descendants([node]) - {node})
