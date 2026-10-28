"""Cost Centers under Business Line > Product Line (client request 2026-10-26).

The Employee field ``custom_job_code`` (a Link to Cost Center, created by hand on
production before this app owned it) is shown as "Cost Center". Each Cost Center
carries the Business Line / Product Line it belongs to, so the Employee form offers
only the Cost Centers of the chosen Product Line (or Business Line). Cost Centers
without a Business Line (Administration, Finance, HR ...) are offered to everyone
who has no Business Line.

The client's list (Excel of 2026-10-26) is in ``data/cost_centers_2026-10-27.csv``,
loaded with ``load(dry_run=1)``:

    bench --site <site> execute cooperheat.cooperheat.cost_center.load --kwargs "{'dry_run': 1}"
"""

import csv
import os

import frappe
from frappe import _
from frappe.utils import cint

from cooperheat.cooperheat.org import BUSINESS_LINE, PRODUCT_TYPES, ancestors, unit_type

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "cost_centers_2026-10-27.csv")

# Client abbreviations -> department_name of the Business Line / Product Line node.
BUSINESS_LINES = {
	"IBL": "Inspection Business Line",
	"HTBL": "Heat Treatment Business Line",
	"SMSBL": "Specialized Mechanical Services Business Line",
	"FSBL": "Fabrication Business Line",
}
# Only the Product Lines whose node is certain. NDT-PL (CNDT?), HoT-PL (HTLS?), HTE-PL, FSE-PL,
# FSI-PL and SD-PL (under three Business Lines) wait for the client's answer: their Cost Centers
# are created under the Business Line only and listed in the result as "pl_unmapped".
PRODUCT_LINES = {
	"TPI-PL": "TPI",
	"ANDT-PL": "ANDT",
	"HTS-PL": "Heat Treatment Services",
	"OLS-PL": "Online Leak Sealing",
}
SKIP_DESCRIPTIONS = ("please do not use",)


def _node(department_name: str, wanted, parent: str | None = None) -> str | None:
	types = list(wanted) if isinstance(wanted, (list, tuple)) else [wanted]
	names = frappe.get_all(
		"Department",
		filters={"department_name": department_name, "custom_unit_type": ["in", types], "disabled": 0},
		pluck="name",
	)
	if parent:
		names = [n for n in names if parent in ancestors(n)]
	return names[0] if len(names) == 1 else None


def _company_root(company: str) -> str:
	root = frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 1, "parent_cost_center": ["is", "not set"]}
	)
	if not root:
		frappe.throw(_("Company {0} has no root Cost Center.").format(company))
	return root


@frappe.whitelist()
def load(dry_run=1, company: str | None = None, pl_names=None) -> dict:
	"""Create / update the client's Cost Centers and tag them with Business Line and
	Product Line. Existing Cost Centers keep their name; only the tags and description
	are set. "Please do not use" rows are skipped. ``pl_names`` adds Product Line
	mappings ({"NDT-PL": "CNDT"}) once the client confirms them."""
	frappe.only_for("System Manager")
	dry_run = cint(dry_run)
	company = company or frappe.defaults.get_global_default("company")
	abbr = frappe.get_cached_value("Company", company, "abbr")
	product_lines = dict(PRODUCT_LINES, **(frappe.parse_json(pl_names) if pl_names else {}))
	root = _company_root(company)

	result = {"created": [], "updated": [], "skipped": [], "bl_unmapped": set(), "pl_unmapped": set()}
	with open(DATA_FILE, newline="") as f:
		rows = list(csv.DictReader(f))

	for r in rows:
		code, desc = r["cost_center"].strip(), r["description"].strip()
		if desc.lower() in SKIP_DESCRIPTIONS:
			result["skipped"].append(code)
			continue
		bl = pl = None
		if r["business_line"]:
			bl = _node(BUSINESS_LINES.get(r["business_line"], ""), BUSINESS_LINE)
			if not bl:
				result["bl_unmapped"].add(r["business_line"])
		if bl and r["product_line"]:
			pl = _node(product_lines.get(r["product_line"], ""), PRODUCT_TYPES, parent=bl)
			if not pl:
				result["pl_unmapped"].add(r["business_line"] + "/" + r["product_line"])

		name = code + " - " + abbr
		values = {"custom_business_line": bl, "custom_product_line": pl, "custom_description": desc}
		if frappe.db.exists("Cost Center", name):
			result["updated"].append(name)
			if not dry_run:
				frappe.db.set_value("Cost Center", name, values)
			continue
		result["created"].append(name)
		if not dry_run:
			frappe.get_doc(
				{
					"doctype": "Cost Center",
					"cost_center_name": code,
					"company": company,
					"parent_cost_center": root,
					"is_group": 0,
					**values,
				}
			).insert(ignore_permissions=True)

	if not dry_run:
		frappe.db.commit()
	result["bl_unmapped"] = sorted(result["bl_unmapped"])
	result["pl_unmapped"] = sorted(result["pl_unmapped"])
	result["dry_run"] = dry_run
	return result


def _lines_of(product_line: str) -> list[str]:
	"""A Sub-Product Line also uses the Cost Centers of its Product Line."""
	return [product_line] + [a for a in ancestors(product_line) if unit_type(a) in PRODUCT_TYPES]


def _filters_for(business_line: str | None, product_line: str | None) -> list:
	"""Narrowest list that has something in it: the Product Line's Cost Centers, else
	the Business Line's, else all. Until the client's list is loaded (no Cost Center
	is tagged yet) the picker shows every Cost Center, as before."""
	if not frappe.db.exists("Cost Center", {"custom_business_line": ["is", "set"]}):
		return []
	if product_line:
		lines = _lines_of(product_line)
		if frappe.db.exists("Cost Center", {"custom_product_line": ["in", lines]}):
			return [["custom_product_line", "in", lines]]
	if business_line:
		if frappe.db.exists("Cost Center", {"custom_business_line": business_line}):
			return [["custom_business_line", "=", business_line]]
		return []
	return [["custom_business_line", "is", "not set"]]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def cost_center_query(doctype, txt, searchfield, start, page_len, filters):
	"""Cost Centers of the chosen Product Line (else Business Line; else those without one)."""
	filters = filters or {}
	conditions = [["is_group", "=", 0], ["disabled", "=", 0]]
	conditions += _filters_for(filters.get("business_line"), filters.get("product_line"))
	if filters.get("company"):
		conditions.append(["company", "=", filters["company"]])
	or_filters = None
	if txt:
		pattern = "%" + txt + "%"
		or_filters = [["name", "like", pattern], ["custom_description", "like", pattern]]
	return frappe.get_list(
		"Cost Center",
		filters=conditions,
		or_filters=or_filters,
		fields=["name", "custom_description"],
		limit_start=start,
		limit_page_length=page_len,
		order_by="name asc",
		as_list=True,
	)


def validate_employee_cost_center(doc):
	"""Employee validate: a Cost Center tagged with a Business Line / Product Line must
	match the employee's. Untagged (general) Cost Centers are allowed for anyone."""
	cc = doc.get("custom_job_code")
	if not cc or not frappe.get_meta("Cost Center").has_field("custom_business_line"):
		return
	tags = frappe.db.get_value("Cost Center", cc, ["custom_business_line", "custom_product_line"], as_dict=True)
	if not tags or not tags.custom_business_line:
		return
	bl, pl = doc.get("custom_business_line"), doc.get("custom_product_line")
	if bl and tags.custom_business_line != bl:
		frappe.throw(
			_("Cost Center {0} belongs to Business Line {1}, not {2}.").format(
				frappe.bold(cc), frappe.bold(tags.custom_business_line), frappe.bold(bl)
			)
		)
	if pl and tags.custom_product_line and tags.custom_product_line not in _lines_of(pl):
		frappe.throw(
			_("Cost Center {0} belongs to Product Line {1}, not {2}.").format(
				frappe.bold(cc), frappe.bold(tags.custom_product_line), frappe.bold(pl)
			)
		)


# --- Cost Center on the Shift Assignment (client, 2026-10-28) -----------------------------------
def _employee_lines(employee: str | None):
	if not employee:
		return None, None
	return frappe.db.get_value("Employee", employee, ["custom_business_line", "custom_product_line"]) or (None, None)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def employee_cost_center_query(doctype, txt, searchfield, start, page_len, filters):
	"""The Cost Centers of the employee's Product Line / Business Line, for a Shift Assignment."""
	filters = dict(filters or {})
	bl, pl = _employee_lines(filters.pop("employee", None))
	filters.update(business_line=bl, product_line=pl)
	return cost_center_query(doctype, txt, searchfield, start, page_len, filters)


def validate_shift_cost_center(doc, method=None):
	"""Shift Assignment validate: a tagged Cost Center must belong to the employee's lines."""
	if not doc.get("custom_cost_center"):
		return
	probe = frappe._dict(custom_job_code=doc.custom_cost_center)
	probe.custom_business_line, probe.custom_product_line = _employee_lines(doc.employee)
	validate_employee_cost_center(probe)


def cost_center_of_day(employee: str, day) -> str | None:
	"""Cost Center of the employee's active Shift Assignment covering ``day``."""
	sa = frappe.qb.DocType("Shift Assignment")
	rows = (
		frappe.qb.from_(sa)
		.select(sa.custom_cost_center)
		.where(sa.employee == employee)
		.where(sa.docstatus == 1)
		.where(sa.status == "Active")
		.where(sa.start_date <= day)
		.where((sa.end_date.isnull()) | (sa.end_date >= day))
		.where(sa.custom_cost_center.isnotnull())
		.orderby(sa.start_date, order=frappe.qb.desc)
		.limit(1)
	).run()
	return rows[0][0] if rows else None
