"""Organisation structure: Division / Department / Business Line / Product Line.

Everything lives in one HRMS Department tree. Each node carries a Unit Type.
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

BUSINESS_LINE = "Business Line"
PRODUCT_LINE = "Product Line"
OPERATIONS_TYPES = (BUSINESS_LINE, PRODUCT_LINE)
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
	row = next((r for r in effective_matrix(department, employee, location) if r.approval_level == 1), None)
	return row.approver if row else None


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
		if unit_type(pl) != PRODUCT_LINE:
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
		if unit_type(doc.department) == PRODUCT_LINE:
			doc.custom_product_line = doc.department
		doc.custom_business_line = nearest_of_type(doc.department, BUSINESS_LINE)


def reroute_on_move(doc):
	"""Employee moved (department or assigned location changed): clear Reports To
	and approver fields that still point at the OLD placement's approvers, so they
	re-resolve for the new one. Values HR set by hand to someone else are kept."""
	if doc.is_new():
		return
	old = frappe.db.get_value("Employee", doc.name, ["department", "custom_assigned_location"], as_dict=True)
	if not old or (old.department == doc.get("department") and old.custom_assigned_location == doc.get("custom_assigned_location")):
		return
	# What the old placement would have filled in automatically.
	old_auto = next(
		(r.approver for r in effective_matrix(old.department, location=old.custom_assigned_location) if r.approver != doc.name),
		None,
	)
	if not old_auto:
		return
	if doc.get("reports_to") == old_auto:
		doc.reports_to = None
	old_user = frappe.db.get_value("Employee", old_auto, "user_id")
	for field in ("leave_approver", "shift_request_approver", "expense_approver"):
		if old_user and doc.meta.has_field(field) and doc.get(field) == old_user:
			doc.set(field, None)


def fill_default_approvers(doc):
	"""Empty Leave / Shift Request / Expense approver -> the Level 1 approver's user.

	HRMS requires a Leave Approver on every leave; without this, HR cannot save
	a leave for anyone whose employee record was never given one.
	"""
	if not doc.get("department"):
		return
	# First approver who is not the employee themself (a supervisor's own leave
	# goes to the next level up).
	rows = effective_matrix(doc.department, location=doc.get("custom_assigned_location"))
	approver = next((r.approver for r in rows if r.approver != doc.name), None)
	if not approver:
		return
	user = frappe.db.get_value("Employee", approver, "user_id")
	if not user:
		return
	for field in ("leave_approver", "shift_request_approver", "expense_approver"):
		if doc.meta.has_field(field) and not doc.get(field):
			doc.set(field, user)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def product_line_query(doctype, txt, searchfield, start, page_len, filters):
	"""Product Lines under the chosen Business Line (all of them if none chosen)."""
	conditions = [["custom_unit_type", "=", PRODUCT_LINE], ["disabled", "=", 0]]
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
