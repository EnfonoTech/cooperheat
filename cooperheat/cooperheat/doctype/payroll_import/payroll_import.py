# Copyright (c) 2026, enfonotechnology and contributors
# For license information, please see license.txt

import os

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate
from frappe.utils.file_manager import get_file_path

from cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet import (
	PRORATED_EARNING_FIELDS,
	days_in_month,
	get_employee_compensation,
)


COLUMN_MAP = {
	"DocNo": "doc_no",
	"Code": "code",
	"Month": "month",
	"Days": "days",
	"OT": "ot",
	"HOT": "hot",
	"TravelOT": "travel_ot",
	"Expenses": "expenses",
	"Other": "other",
	"Vacation": "vacation",
	"Bonus": "bonus",
	"Airfare": "airfare",
	"Otherded": "otherded",
	"Housingded": "housingded",
}


class PayrollImport(Document):
	def validate(self):
		if not self.is_new() and self.status in ("Running", "Queued"):
			# Don't allow edits while running
			pass

	def start(self):
		"""Run processing inline (small files) or enqueue (large files)."""
		frappe.only_for(["System Manager", "HR Manager"])
		if self.status in ("Running", "Queued"):
			frappe.throw(_("Import is already {0}.").format(self.status))
		run_import(self.name)


@frappe.whitelist()
def start_import(name):
	doc = frappe.get_doc("Payroll Import", name)
	doc.start()
	return frappe.db.get_value("Payroll Import", name, "status")


def run_import(doc_name, user=None):
	if user:
		frappe.set_user(user)

	frappe.db.set_value(
		"Payroll Import", doc_name,
		{"status": "Running", "error_message": ""},
		update_modified=False,
	)
	frappe.db.commit()

	final_status = "Failed"
	error_message = ""
	try:
		doc = frappe.get_doc("Payroll Import", doc_name)
		_process(doc)
		final_status = "Completed"
	except Exception as e:
		frappe.db.rollback()
		import traceback
		frappe.log_error(
			title=f"Payroll Import {doc_name} failed",
			message=traceback.format_exc(),
		)
		error_message = f"{type(e).__name__}: {e}"
	finally:
		update = {"status": final_status}
		if error_message:
			update["error_message"] = error_message[:1000]
		try:
			frappe.db.set_value("Payroll Import", doc_name, update, update_modified=False)
			frappe.db.commit()
		except Exception:
			pass


def _process(doc):
	rows = _read_rows(doc.file)
	# Reset log child table
	frappe.db.sql("DELETE FROM `tabPayroll Import Row` WHERE parent = %s", (doc.name,))
	frappe.db.commit()

	total = created = skipped = errors = 0
	for r in rows:
		total += 1
		frappe.db.savepoint("row_sp")
		try:
			status, payroll_sheet, employee, message = _process_row(doc, r)
		except Exception as e:
			frappe.db.rollback(save_point="row_sp")
			status, payroll_sheet, employee, message = "Error", None, "", str(e)
		else:
			if status == "Error":
				frappe.db.rollback(save_point="row_sp")

		_append_row(doc.name, r, status, payroll_sheet, employee, message)

		if status == "Created":
			created += 1
		elif status == "Skipped":
			skipped += 1
		else:
			errors += 1
		frappe.db.commit()

	frappe.db.set_value(
		"Payroll Import", doc.name,
		{
			"total_rows": total, "created_count": created,
			"skipped_count": skipped, "error_count": errors,
		},
		update_modified=False,
	)
	frappe.db.commit()


def _process_row(doc, r):
	code = (r.get("code") or "").strip() if r.get("code") is not None else ""
	if not code:
		return "Error", None, "", _("Empty Code")

	employee = _resolve_employee(code)
	if not employee:
		return "Error", None, "", _("Employee not found for code {0}").format(code)

	# Submitted sheets are protected — cannot overwrite
	submitted = frappe.db.get_value("Payroll Sheet", {
		"employee": employee, "month": doc.month, "year": doc.year,
		"docstatus": 1,
	}, "name")
	if submitted:
		return "Skipped", submitted, employee, _(
			"Payroll Sheet already submitted for this period; cancel it first to re-import."
		)

	# Existing drafts get replaced with fresh data from this import
	draft = frappe.db.get_value("Payroll Sheet", {
		"employee": employee, "month": doc.month, "year": doc.year,
		"docstatus": 0,
	}, "name")
	if draft:
		frappe.delete_doc(
			"Payroll Sheet", draft,
			force=True, ignore_permissions=True, delete_permanently=True,
		)

	comp_data = get_employee_compensation(employee, doc.posting_date)
	if not comp_data:
		return "Error", None, employee, _(
			"No active Employee Compensation with Effective From on or before {0}"
		).format(doc.posting_date or "today")

	ps = _make_payroll_sheet(
		company=doc.company, employee=employee,
		month=doc.month, year=int(doc.year),
		posting_date=doc.posting_date, row=r, comp_data=comp_data,
	)
	if doc.submit_after_create:
		ps.submit()
	return "Created", ps.name, employee, ""


def _append_row(parent, r, status, payroll_sheet, employee, message):
	frappe.get_doc({
		"doctype": "Payroll Import Row",
		"parenttype": "Payroll Import",
		"parentfield": "rows",
		"parent": parent,
		"doc_no": r.get("doc_no"),
		"code": r.get("code"),
		"employee": employee or "",
		"employee_name": frappe.db.get_value("Employee", employee, "employee_name") if employee else "",
		"payroll_sheet": payroll_sheet or "",
		"row_status": status,
		"message": message or "",
	}).insert(ignore_permissions=True)


def _resolve_employee(code):
	emp = frappe.db.get_value("Employee", {"employee_number": code}, "name")
	if emp:
		return emp
	return frappe.db.get_value("Employee", code, "name")


def _make_payroll_sheet(company, employee, month, year, posting_date, row, comp_data):
	dim = days_in_month(year, month)
	posting_date = getdate(posting_date) if posting_date else getdate()

	ps = frappe.new_doc("Payroll Sheet")
	ps.company = company
	ps.employee = employee
	ps.month = month
	ps.year = year
	ps.posting_date = posting_date
	ps.compensation = comp_data.get("compensation")
	for k, v in (comp_data.get("values") or {}).items():
		ps.set(k, v)

	# Days from the Excel: missing/empty/zero all mean "absent" (worked_days = 0).
	# Fractional values are preserved (e.g. 15.5).
	ps.worked_days = flt(row.get("days"))
	ps.days_in_month = dim

	ps.normal_ot_hours = flt(row.get("ot"))
	ps.holiday_ot_hours = flt(row.get("hot"))
	ps.travel_ot_hours = flt(row.get("travel_ot"))
	ps.expenses = flt(row.get("expenses"))
	ps.others = flt(row.get("other"))
	ps.vacation_pay = flt(row.get("vacation"))
	ps.bonus = flt(row.get("bonus"))
	ps.air_fare = flt(row.get("airfare"))
	# Excel-only deductions live in their own fields, kept separate from
	# the recurring monthly deductions sourced from Employee Compensation.
	ps.additional_other_deduction = flt(row.get("otherded"))
	ps.additional_housing_deduction = flt(row.get("housingded"))

	# Proration is applied in PayrollSheet.validate() — no need to do it here.
	ps.flags.ignore_permissions = True
	ps.insert()
	return ps


def _read_rows(file_url):
	import openpyxl

	path = _resolve_file_path(file_url)
	wb = openpyxl.load_workbook(path, data_only=True)
	ws = wb.active

	header = None
	rows = []
	for raw in ws.iter_rows(values_only=True):
		if header is None:
			cells = [str(c).strip() if c is not None else "" for c in raw]
			if "Code" in cells and "Days" in cells:
				header = cells
			continue
		if all(c is None or c == "" for c in raw):
			continue
		row = {}
		for i, val in enumerate(raw):
			if i >= len(header):
				break
			h = header[i]
			key = COLUMN_MAP.get(h)
			if not key:
				continue
			row[key] = val
		if row:
			rows.append(row)

	if header is None:
		frappe.throw(_("Could not find header row. Required columns: Code, Days, OT, HOT, ..."))
	return rows


def _resolve_file_path(file_url):
	if not file_url:
		frappe.throw(_("File is required."))
	try:
		path = get_file_path(file_url)
		if path and os.path.exists(path):
			return path
	except Exception:
		pass
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	return file_doc.get_full_path()
