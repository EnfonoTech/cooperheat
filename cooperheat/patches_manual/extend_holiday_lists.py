"""Keep the plain Friday + Saudi public holiday calendar covering the whole year.

Production has one Holiday List ("2026") that stops on 31 Oct. This extends it to
31 Dec 2026 and creates "2027". Weekly off = Friday; public holidays from the
`holidays` package (country SA). Eid dates are astronomical estimates: HR must
check them against the official announcement.

Additive only: existing rows are never removed or changed. Dry run by default.

	bench --site <site> execute cooperheat.patches_manual.extend_holiday_lists.run \
		--kwargs "{'dry_run': 0}"
"""

import frappe
from frappe.utils import cint, getdate

WEEKLY_OFF = "Friday"


def _generated(from_date, to_date):
	"""Friday + Saudi public holiday rows for the range, as Holiday List would build them."""
	tmp = frappe.new_doc("Holiday List")
	tmp.from_date, tmp.to_date, tmp.country = from_date, to_date, "SA"
	tmp.get_local_holidays()
	tmp.weekly_off = WEEKLY_OFF
	tmp.get_weekly_off_dates()
	return list(tmp.holidays)


def _extend(name, from_date, to_date, dry_run):
	if frappe.db.exists("Holiday List", name):
		doc = frappe.get_doc("Holiday List", name)
		start = max(getdate(doc.to_date), getdate(from_date))
		known = {getdate(h.holiday_date) for h in doc.holidays}
		doc.to_date = to_date
		verb = "extend"
	else:
		doc = frappe.new_doc("Holiday List")
		doc.holiday_list_name = name
		doc.from_date, doc.to_date, doc.country = from_date, to_date, "SA"
		start, known, verb = getdate(from_date), set(), "create"
	added = 0
	for row in _generated(start, to_date):
		day = getdate(row.holiday_date)
		if day >= start and day not in known:
			doc.append(
				"holidays",
				{"holiday_date": day, "description": row.description, "weekly_off": row.weekly_off},
			)
			known.add(day)
			added += 1
	print(f"{verb} {name}: {from_date}..{to_date} +{added} rows")
	if not dry_run:
		doc.save(ignore_permissions=True)
	return added


def run(list_2026="2026", dry_run=1):
	dry_run = cint(dry_run)
	_extend(list_2026, "2026-10-01", "2026-12-31", dry_run)
	_extend("2027", "2027-01-01", "2027-12-31", dry_run)
	if not dry_run:
		frappe.db.commit()
	print(f"dry_run={dry_run}")
