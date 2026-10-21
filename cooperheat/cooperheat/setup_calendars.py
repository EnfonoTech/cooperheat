"""Office and field work calendars (holiday lists + shift types).

Office staff are off Friday and Saturday, field staff (technicians, operations)
Friday only. Both lists carry the Saudi public holidays from the `holidays`
package. Eid dates are astronomical estimates: HR must check them against the
official announcement each year.

Run once per year, per site:
	bench --site <site> execute cooperheat.cooperheat.setup_calendars.create_work_calendars --kwargs "{'year': 2027}"
"""

import frappe
from frappe import _
from frappe.utils import cint

CALENDARS = {
	"Office": ("Friday", "Saturday"),
	"Field": ("Friday",),
}


def holiday_list_name(kind, year):
	return f"{kind} Staff {year}"


@frappe.whitelist()
def create_work_calendars(year, start_time=None, end_time=None):
	"""Create the Office / Field holiday lists for `year` and a shift type for each.

	Idempotent: an existing holiday list or shift type is left untouched.
	Shift times default to the existing `regular` shift's times.
	"""
	frappe.only_for(("System Manager", "HR Manager"))
	year = cint(year)
	if year < 2000:
		frappe.throw(_("Enter a valid year."))

	created = []
	for kind, weekly_offs in CALENDARS.items():
		name = holiday_list_name(kind, year)
		if not frappe.db.exists("Holiday List", name):
			make_holiday_list(name, year, weekly_offs)
			created.append(name)

		shift = f"{kind} Shift"
		if not frappe.db.exists("Shift Type", shift):
			make_shift_type(shift, name, start_time, end_time)
			created.append(shift)
	return created


def make_holiday_list(name, year, weekly_offs):
	doc = frappe.new_doc("Holiday List")
	doc.holiday_list_name = name
	doc.from_date = f"{year}-01-01"
	doc.to_date = f"{year}-12-31"
	doc.country = "SA"
	doc.get_local_holidays()
	for day in weekly_offs:
		doc.weekly_off = day
		doc.get_weekly_off_dates()
	doc.insert()
	return doc


# Client shift timings (2026-10-13). Field work is flexible day or night: the shift
# is a full-day window and the 8-hour / 16-hour rules decide overtime.
SHIFTS = {
	"Office Shift": ("Office", "07:30:00", "16:30:00"),
	"Office Shift 2": ("Office", "08:30:00", "17:30:00"),
	"Field Shift": ("Field", "00:00:00", "23:59:00"),
}


@frappe.whitelist()
def setup_shifts(year=None):
	"""Create / update Office Shift (07:30-16:30), Office Shift 2 (08:30-17:30) and the
	flexible Field Shift. Idempotent; times are corrected on existing shifts."""
	frappe.only_for(("System Manager", "HR Manager"))
	from frappe.utils import getdate, nowdate

	year = cint(year) or getdate(nowdate()).year
	changed = []
	for name, (kind, start, end) in SHIFTS.items():
		holiday_list = holiday_list_name(kind, year)
		holiday_list = holiday_list if frappe.db.exists("Holiday List", holiday_list) else None
		if frappe.db.exists("Shift Type", name):
			current = frappe.db.get_value(
				"Shift Type", name, ["start_time", "end_time", "enable_auto_attendance"], as_dict=True
			)
			if (
				str(current.start_time) != start
				or str(current.end_time) != end
				or current.enable_auto_attendance
			):
				# Direct write: HRMS refuses to edit a shift while check-ins wait for ITS auto
				# attendance, which this site does not use (attendance comes from cooperheat).
				values = {"start_time": start, "end_time": end, "enable_auto_attendance": 0}
				if kind == "Field":
					values.update(
						begin_check_in_before_shift_start_time=0, allow_check_out_after_shift_end_time=0
					)
				frappe.db.set_value("Shift Type", name, values)
				frappe.clear_document_cache("Shift Type", name)
				changed.append(name)
		else:
			make_shift_type(name, holiday_list, start, end, flexible=kind == "Field")
			changed.append(name)
	return changed


def _flexible(doc, kind):
	"""A full-day Field shift would overlap itself through HRMS's grace minutes."""
	if kind == "Field":
		doc.begin_check_in_before_shift_start_time = 0
		doc.allow_check_out_after_shift_end_time = 0


def make_shift_type(name, holiday_list, start_time=None, end_time=None, flexible=False):
	regular = frappe.db.get_value("Shift Type", "regular", ["start_time", "end_time"], as_dict=True) or {}
	doc = frappe.new_doc("Shift Type")
	doc.name = name
	doc.start_time = start_time or regular.get("start_time") or "07:00:00"
	doc.end_time = end_time or regular.get("end_time") or "16:00:00"
	doc.holiday_list = holiday_list
	# Attendance comes from cooperheat's check-in job; HRMS auto attendance
	# would create duplicates.
	doc.enable_auto_attendance = 0
	if flexible:
		_flexible(doc, "Field")
	doc.insert()
	return doc
