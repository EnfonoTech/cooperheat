"""Bulk-set Staff Category (Office / Field) from the client's list.

CSV with a header row; first column = Employee ID, employee number or exact name,
second column = category ("Office Staff" / "Field Staff", or just "Office" / "Field").

    bench --site <site> execute cooperheat.cooperheat.staff_import.load --kwargs "{'path': '/tmp/staff.csv'}"

Dry run by default: pass 'dry_run': 0 to save. Saving an employee runs the normal Work
Schedule sync, so the holiday list and an empty Default Shift follow the category.
Rows that match no employee, or several, are reported and never guessed.
"""

import csv

import frappe
from frappe.utils import cint

ALIASES = {
	"office": "Office Staff",
	"office staff": "Office Staff",
	"field": "Field Staff",
	"field staff": "Field Staff",
}


def _find(key):
	key = (key or "").strip()
	if not key:
		return None, "empty"
	for field in ("name", "employee_number", "employee_name"):
		hits = frappe.get_all("Employee", filters={field: key}, pluck="name", limit=3)
		if len(hits) == 1:
			return hits[0], None
		if len(hits) > 1:
			return None, "several employees match"
	return None, "no employee found"


def load(path, dry_run=1):
	dry_run = cint(dry_run)
	report = {"updated": [], "unchanged": [], "problems": []}
	with open(path, newline="", encoding="utf-8-sig") as f:
		rows = list(csv.reader(f))[1:]
	for line, row in enumerate(rows, start=2):
		if len(row) < 2 or not any(c.strip() for c in row):
			continue
		category = ALIASES.get(row[1].strip().lower())
		if not category:
			report["problems"].append((line, row[0], "unknown category: " + row[1]))
			continue
		name, problem = _find(row[0])
		if problem:
			report["problems"].append((line, row[0], problem))
			continue
		current = frappe.db.get_value("Employee", name, "custom_staff_category")
		if current == category:
			report["unchanged"].append(name)
			continue
		if not dry_run:
			doc = frappe.get_doc("Employee", name)
			doc.custom_staff_category = category
			try:
				doc.save(ignore_permissions=True)
			except Exception as e:
				report["problems"].append((line, row[0], str(e)[:200]))
				continue
		report["updated"].append((name, current, category))
	if not dry_run:
		frappe.db.commit()
	print(
		f"dry_run={dry_run} updated={len(report['updated'])} unchanged={len(report['unchanged'])} problems={len(report['problems'])}"
	)
	for p in report["problems"]:
		print("PROBLEM", p)
	return report
