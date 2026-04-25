# Cooperheat Payroll — Developer Documentation

This document explains the architecture, data model, calculation logic, and
extension points for engineers maintaining or extending this app.

---

## 1. App layout

```
cooperheat/
├── hooks.py               # after_install / after_migrate hooks → setup.py
├── setup.py               # default-setting seeding, legacy-field cleanup
└── cooperheat/
    └── doctype/
        ├── pay_batch/                  # Link doctype: pay groups
        ├── employee_compensation/      # Per-employee comp master, versioned by from_date
        ├── pay_sheet_settings/         # Single doctype: calc params + mapping
        ├── pay_sheet_component_mapping/# Child of pay_sheet_settings
        ├── payroll_sheet/              # Submittable: one slip per (employee, month, year)
        ├── payroll_import/             # Submittable: bulk import driver + log
        └── payroll_import_row/         # Child of payroll_import (the log table)
    └── report/
        ├── pay_sheet_detail/
        └── pay_sheet_summary/
```

Reports are **Script Reports**, not Query Reports — see their `.py` files.

---

## 2. Data model

### Pay Batch *(link doctype)*
Just a `batch_name` and optional description. Used by Employee Compensation and
displayed in the reports' grouping.

### Employee Compensation *(versioned per-employee master)*

| Concern | Field |
|---|---|
| Naming | `naming_series = "EC-.YYYY.-"` |
| Versioning | `from_date` (Date, required) — uniqueness `(employee, from_date)` |
| Activation | `is_active` Check |
| Identity | `employee` Link, `employee_name` / `designation` fetched from Employee |
| Grouping | `pay_batch`, `employee_category` (Expat/Saudi), `currency` |
| Earnings | `basic` + 12 named allowances |
| Deductions | 7 fixed monthly deductions |

The same employee can have many records; the **active record for a given date**
is the latest where `is_active = 1 AND from_date ≤ <date>`.

### Pay Sheet Settings *(Single)*

OT multipliers, GOSI rate + applicable category, rounding flag, default Salary
Structure, and the **Component Mapping** child table.

`payroll_field` in the mapping is a hard-coded Select with the exact set of
Payroll Sheet currency fields — see
`pay_sheet_component_mapping.json`. Adding a new mappable field requires updating
that Select's options.

### Payroll Sheet *(submittable)*

One per `(employee, month, year)`. Two halves:

- **Compensation-derived** fields filled from the linked `compensation` record:
  basic + 12 allowances + 7 fixed deductions + `pay_batch` + `employee_category`.
- **Variable / Excel-derived** fields: `worked_days`, `normal_ot_hours`,
  `holiday_ot_hours`, `travel_ot_hours`, `expenses`, `others`, `vacation_pay`,
  `bonus`, `air_fare`, `gratuity`, `retention` + Excel-stacked
  `housing_deduction` and `other_deduction`.
- **Computed** fields written in `validate()`: `days_in_month`, OT amounts +
  `total_ot_amount`, `gosi`, `total_earnings`, `total_deduction`, `net_payable`.

### Payroll Import *(submittable, but `submit_after_create` controls auto-submit of children)*

| Field | Use |
|---|---|
| `file` | Attach (Excel) |
| `company`, `month`, `year`, `posting_date` | Per-row defaults applied to created Payroll Sheets |
| `submit_after_create` | If checked, also `submit()` each created Payroll Sheet |
| `status` | Draft / Running / Completed / Failed |
| `total_rows`, `created_count`, `skipped_count`, `error_count` | Counters |
| `error_message` | Top-level failure (set in `finally`) |
| `rows` (Table) | Per-row log |

---

## 3. Key flows

### 3.1 Excel parsing → Payroll Sheets

`payroll_import.py::import_file` is the whitelisted entry called from the JS
button.

```
import_file(name)
  └── _process(doc)
        ├── _read_rows(doc.file)        # openpyxl, header detection, COLUMN_MAP
        └── for each row:
              frappe.db.savepoint("row_sp")
              try:
                  _process_row(doc, row)
              except: rollback(savepoint)
              _append_row(...)           # log entry
              commit
```

`_process_row` resolves Employee, deletes any draft Payroll Sheet for the
period, errors on submitted ones, fetches active Compensation, then calls
`_make_payroll_sheet(...).insert()`. Proration happens inside
`PayrollSheet.validate()` — see §3.2.

The **savepoint per row** is important: errors in one row roll back only that
row's work, the log entry still gets written, and the next row proceeds.

### 3.2 Payroll Sheet calculation

`payroll_sheet.py::PayrollSheet.validate()`:

```python
def validate(self):
    self.set_days_in_month()      # calendar days for the month
    self.apply_proration()        # re-read from Compensation, prorate earnings
    self.calculate_overtime()
    self.calculate_gosi()
    self.calculate_totals()
```

Notes:

- **`apply_proration` is idempotent**: it always re-reads the **full** values
  from the linked `compensation` record, then writes prorated values to the
  earnings fields. This means manual edits to `housing_allowance` etc. on a
  Payroll Sheet are **discarded on save** — the Compensation record is the
  source of truth. To customize per-slip, clear the `compensation` link first.
- `basic` is **never prorated**. `worked_days = 0` zeroes out earnings.
- Deductions (Compensation-side fixed deductions and Excel-stacked ones) are
  **not** touched by `apply_proration` — they're set once at import time and
  preserved on subsequent saves.
- OT formula: `basic / settings.monthly_working_hours × multiplier × hours`.
- GOSI: only when `employee_category == settings.gosi_applicable_category`.
- All reads of Settings go through `frappe.get_cached_doc("Pay Sheet Settings")`.

The form-side recalc in `payroll_sheet.js` mirrors this logic for live UX.
The JS caches the Compensation record on `frm.__comp` to avoid round-trips.

### 3.3 Salary Slip creation

`payroll_sheet.py::create_salary_slip`:

```
1. Validate Payroll Sheet is submitted (docstatus=1).
2. Read Pay Sheet Settings (mapping, default structure).
3. _ensure_salary_structure_assignment(employee, company, start_date, settings)
     • If a submitted SSA exists with from_date ≤ start_date → reuse.
     • Else → create + submit new SSA pointing at settings.default_salary_structure
       with base = doc.basic.
4. Build a new Salary Slip:
     - salary_structure = SSA.salary_structure
     - payroll_frequency = "Monthly"
     - payment_days = total_working_days = days_in_month  (prevents HRMS re-proration)
5. For each mapping row, append the doc.<field> amount to earnings/deductions.
6. _ensure_salary_component(name, type) creates missing Salary Components on
   the fly, with depends_on_payment_days = 0 so HRMS does NOT re-scale our amounts.
7. slip.insert() → returns slip name.
```

#### Why `depends_on_payment_days = 0`?

HRMS's `get_amount_based_on_payment_days` rescales any earning whose component
has the flag = 1 by `payment_days / total_working_days`. We've already prorated
based on `worked_days` upstream — letting HRMS prorate *again* would be wrong.
Setting flag = 0 keeps the row's `amount` intact.

Trade-off: components flagged 0 don't pick up "pay only for days worked"
behaviour automatically. We compensate by always setting `payment_days =
total_working_days`, which produces a factor of 1 for any component that
*does* have the flag. End-to-end the math works out.

### 3.4 Date-aware Compensation lookup

`payroll_sheet.py::get_employee_compensation(employee, posting_date=None)` is
the single read-side helper. Used by:

- The Payroll Sheet form JS (`pull_compensation`) when you pick an employee
- `payroll_import.py::_process_row`
- `_make_payroll_sheet` indirectly via the import

Picks `Employee Compensation` where `is_active=1 AND from_date ≤ posting_date`,
ordered by `from_date DESC` — i.e. the most recent applicable record.

---

## 4. Settings hooks

`setup.py`:

- `after_install` → `setup_custom_fields` (no-op today, future hook point) +
  `seed_settings` (writes default OT/GOSI values into the Single).
- `after_migrate` → also `cleanup_legacy_employee_fields` (deletes the old
  `Employee.employee_category`/`Employee.pay_batch` custom fields that an
  earlier version of this app installed) and `backfill_compensation_from_date`
  (sets `from_date` on legacy Compensation records that pre-date the field).

`hooks.py` does not declare `fixtures = […]` for custom fields; the
`Employee.custom_division` reference used by the Payroll Sheet's `division`
field is a **production-side** custom field that this app does not own.

---

## 5. Extension points

### 5.1 Adding a new Payroll Sheet field

1. Add the field to `payroll_sheet/payroll_sheet.json`. Bump `modified` so
   migrate picks it up.
2. If it's a currency that should appear in the totals, add it to
   `EARNING_FIELDS`, `SPECIAL_EARNINGS`, or `DEDUCTION_FIELDS` in
   `payroll_sheet.py`. Mirror in `payroll_sheet.js`.
3. If it should be prorated, ensure it's in the Compensation doctype too,
   and `PRORATED_EARNING_FIELDS` will pick it up automatically.
4. To make it mappable to a Salary Component, add the fieldname to the
   `payroll_field` Select options in
   `pay_sheet_component_mapping/pay_sheet_component_mapping.json`.
5. To pre-seed a default mapping, append to `DEFAULT_MAPPING` in
   `pay_sheet_settings.py` and re-run **Setup Defaults**.

### 5.2 Changing OT formula

All OT logic reads from **Pay Sheet Settings** — change the multipliers there
or `monthly_working_hours`. No code changes needed.

If you need a fundamentally different formula (e.g. piecewise rates), edit
`PayrollSheet.calculate_overtime` and the JS mirror.

### 5.3 Changing how proration works

Edit `PayrollSheet.apply_proration`. The mirror in `payroll_sheet.js` is
`apply_proration(frm)` — keep them in sync. The proration factor formula:

```
factor = min(worked_days, days_in_month) / days_in_month
```

To prorate `basic` too (currently fixed), include it in the loop and remove
the explicit "basic stays fixed" comment. Note this would change all GOSI and
OT calcs since they're based on the basic value at calc time.

### 5.4 Adding a new pay batch / employee category

Pay Batch is a normal doctype — create a new record at `/app/pay-batch/new`.

`employee_category` Select on Employee Compensation has a fixed
`Expat\nSaudi` option list. Adding a third value requires editing the
`employee_compensation.json` field options, plus the same field on Payroll
Sheet, plus the `gosi_applicable_category` Select on Pay Sheet Settings.

---

## 6. Reports

Both reports are **Script Reports**. Their `get_data` builds plain SQL against
`tabPayroll Sheet` with whitelisted filter keys. Default filter is
`docstatus = 1`; passing `include_draft = 1` widens to `docstatus < 2`.

To add a new column: add a `{label, fieldname, fieldtype, width}` dict to
`get_columns`, include the field in the `SELECT`, done.

---

## 7. Common pitfalls

- **Frappe `rename_doc` regenerates JSONs on disk** when developer mode is on.
  This bit us during the cooperheat-prefix → bare-name rename refactor; clean
  approach is to rename files first, update JSON `name` fields, then call
  `frappe.delete_doc("DocType", old_name)` directly rather than `rename_doc`.
- **`bench migrate` won't pick up JSON changes** unless the `modified`
  timestamp in the JSON is newer than what the DB knows. If a doctype change
  doesn't show up after migrate, bump `modified` to a clearly newer value.
- **`frappe.get_value` requires `pluck` only on `get_all`**, not `get_value`.
  Use `as_dict=True` instead when you need a dict.
- **HRMS Salary Slip recalc**: any Salary Component with
  `depends_on_payment_days = 1` gets its amount *replaced* during validate by
  `default_amount × payment_days / total_working_days`. We work around this by
  setting flag = 0 and forcing `payment_days = total_working_days`.

---

## 8. Site config

App is installed via `bench install-app cooperheat`. Tested on:

- Frappe v15.70.0 / ERPNext v15.65.1 / HRMS (latest 15.x)

`hooks.py` declares only `after_install` and `after_migrate`; no scheduled
tasks, no doc events. The app is purely UI/CRUD with calculation logic on the
Payroll Sheet doctype.

---

## 9. Testing

`payroll_sheet/test_payroll_sheet.py` is currently a placeholder. Suggested
tests to add:

- `apply_proration` produces correct values for full / half / zero months
- `calculate_overtime` reads Settings and applies multipliers correctly
- `calculate_gosi` is zero for non-Saudi, non-zero with correct rate for Saudi
- `_ensure_salary_structure_assignment` reuses existing SSA, creates new one
  with correct from_date
- Import: re-importing same Excel replaces drafts but skips submitted
- Date-aware `get_employee_compensation` picks the latest applicable record
