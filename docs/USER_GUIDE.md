# Cooperheat Payroll — User Guide

This guide walks an HR / payroll user through running a monthly cycle end-to-end:
configure once, import the Excel, review, submit, generate Salary Slips, run reports.

---

## 1. One-time setup (do this once per site)

### 1.1 Open Pay Sheet Settings → Setup Defaults

`/app/pay-sheet-settings`

Click **Actions → Setup Defaults**. This:

- Creates 29 ERPNext **Salary Components** (Basic, Housing Allowance, Transport
  Allowance, Living Allowance, Service Allowance, Driving Allowance, Merit Award,
  Aramco Certification, Supervisor Allowance, Education Allowance, RSO Allowance,
  RPP Allowance, Other Allowance, Overtime, Others, Bonus, Expenses, Air Fare,
  Vacation Pay, Gratuity, Retention, GOSI, General Advance, Housing Advance,
  Housing Deduction, Transport Deduction, Education Deduction, Retention Deduction,
  Other Deduction).
- Populates the **Component Mapping** table — one row per Payroll Sheet field,
  pointing to the matching Salary Component.
- Creates a placeholder **Cooperheat Default** Salary Structure and links it as
  the *Default Salary Structure*. This is what gets assigned to employees who
  don't have a Salary Structure Assignment yet — needed because ERPNext requires
  one before a Salary Slip can exist.

The button is idempotent: existing rows / components are left alone, and existing
components are flipped to `depends_on_payment_days = 0` so HRMS doesn't re-prorate
amounts that the Cooperheat side already prorated.

### 1.2 Confirm calculation parameters

Same Settings page, **Calculation** section:

| Field | Default | What it controls |
|---|---|---|
| Monthly Working Hours | 240 | Denominator for OT (8 h × 30 d) |
| Normal OT Multiplier | 1.5 | `normal_ot = basic / 240 × 1.5 × hours` |
| Holiday OT Multiplier | 2 | `holiday_ot = basic / 240 × 2 × hours` |
| Travel OT Multiplier | 1.5 | `travel_ot = basic / 240 × 1.5 × hours` |
| GOSI Rate (%) | 9.75 | `gosi = (basic + housing) × rate%` |
| GOSI Applicable Category | Saudi | Which `employee_category` triggers GOSI |
| Round Amounts | Yes | Round currency fields to 2 decimals |

Adjust if your policy differs.

### 1.3 Create Pay Batches

`/app/pay-batch/new`

One per pay group, e.g. `UAE - Fixed 260`, `KSA - Variable`. These appear on
both the Employee Compensation record and the reports' grouping.

### 1.4 Adjust the Component Mapping if needed

In Pay Sheet Settings → **Component Mapping** table you can:

- Delete a row to **omit** that field from generated Salary Slips
- Change `Salary Component` to point to a different ERPNext component
  (e.g. "Allowance — Housing" instead of "Housing Allowance")
- Add a row for a field you want included that wasn't in the defaults

A mapping with a non-existent Salary Component is created automatically the
first time a Salary Slip needs it.

---

## 2. Define each employee's compensation

`/app/employee-compensation/new`

One record per employee per package. Fill in:

| Field | Notes |
|---|---|
| Employee | The Employee record |
| Effective From | Date this package starts. The Payroll Sheet picks the latest record where `from_date ≤ posting_date`. |
| Pay Batch | Group used by reports |
| Employee Category | **Expat** or **Saudi** — drives GOSI |
| Currency | Default SAR |
| Is Active | Uncheck to hide a record without deleting it |
| **Earnings / Allowances** | Full monthly amounts (the import will prorate based on worked days) |
| **Fixed Monthly Deductions** | Fixed amounts (not prorated) |

### Versioning

If an employee gets a raise on 2026-05-01, **don't edit** the existing record.
Create a new Compensation record with `Effective From = 2026-05-01` and the new
amounts. April payroll keeps using the old record; May onward uses the new one.

The validation blocks two records with the same `(employee, from_date)` pair.

---

## 3. Import the monthly Excel

### 3.1 Excel format

The import expects these columns (header in row 1, any row order):

| Column | Maps to | Notes |
|---|---|---|
| DocNo | (display only) | Visible in the import log |
| Code | Employee | Matched against `Employee.employee_number` first, then Employee id |
| Month | (display only) | The month/year on the Payroll Import doc is what's used |
| Days | `worked_days` | Used for proration |
| OT | `normal_ot_hours` | Hours, not amount |
| HOT | `holiday_ot_hours` | Hours |
| TravelOT | `travel_ot_hours` | Hours |
| Expenses | `expenses` | Currency, NOT prorated |
| Other | `others` | Currency, NOT prorated |
| Vacation | `vacation_pay` | Currency, NOT prorated |
| Bonus | `bonus` | Currency, NOT prorated |
| Airfare | `air_fare` | Currency, NOT prorated |
| Otherded | `other_deduction` | Stacks on top of Compensation's fixed deduction |
| Housingded | `housing_deduction` | Stacks on top of Compensation's fixed deduction |

Empty cells = 0.

### 3.2 Run the import

`/app/payroll-import/new`

1. Pick **Company**, **Month**, **Year**.
2. Set **Posting Date** (used to pick the right Compensation record).
3. Optionally tick **Submit on Create** to auto-submit the generated Payroll
   Sheets. Leave unchecked if you want to review them first (recommended).
4. Attach the Excel file.
5. **Save**.
6. Click **Start Import**.

Status moves Draft → Running → Completed. Refresh if needed.

### 3.3 Read the import log

After completion you see:

- **Headline banner**: "Imported X rows" (green) or "Y rows not imported" (red)
- **Rows not imported** panel — error rows with reasons (Doc No / Code / Employee / Reason)
- **Log table** — every row, color-coded:
  - Green-ish = Created
  - Amber = Skipped (already submitted for this period)
  - Red = Error

Common errors:

| Reason | Fix |
|---|---|
| Employee not found for code X | Set `employee_number` on the Employee, or rename the Employee id |
| No active Employee Compensation with Effective From on or before… | Create a Compensation record for that employee |
| Payroll Sheet already submitted for this period; cancel it first | Cancel the existing submitted Payroll Sheet to re-import |

### 3.4 Re-running

Re-running an import for the same Month/Year:

- **Drafts** are deleted and re-created with fresh data — safe to re-run.
- **Submitted** sheets are skipped with a clear reason — cancel them first if
  you really need to overwrite.

---

## 4. Review and submit Payroll Sheets

`/app/payroll-sheet`

Each row is editable while in Draft. Common edits:

- Change `Worked Days` → all allowances re-prorate from Compensation
  immediately, OT and totals update
- Adjust Excel-stacked deductions (`housing_deduction`, `other_deduction`)
- Edit OT hours
- Add **Remarks**

When happy, **Submit**. Status changes to Submitted, the row enters the reports.

### Pull from Compensation

If you change the Employee on a draft, click **Pull from Compensation** to
refresh allowances/deductions from the linked Compensation. Same effect runs
automatically when you select an Employee.

---

## 5. Generate Salary Slips

On a **Submitted** Payroll Sheet, click **Create Salary Slip**. This:

1. Auto-creates a Salary Structure Assignment for the employee (using the
   default structure) if none exists with `from_date ≤ slip.start_date`.
2. Reads the Component Mapping from Pay Sheet Settings.
3. Creates a Salary Slip with `payroll_frequency = Monthly`,
   `payment_days = total_working_days = days_in_month` (so HRMS doesn't
   re-prorate).
4. Pushes amounts into Earnings / Deductions per the mapping.

You're routed to the new Salary Slip. Submit it through ERPNext's normal flow.

---

## 6. Reports

Two Script Reports under Reports → Cooperheat:

### Pay Sheet Detail
Per-employee row with all earnings, OT split, every deduction, and net payable.
Defaults to grouping by Pay Batch.

### Pay Sheet Summary
More compact — Designation, Division, Department, then totals
(Monthly Additions / Monthly Deductions / Net).

**Filters** on both reports:
- Company, Month, Year, Pay Batch, Employee, Status
- From / To Posting Date
- **Include Drafts** (off by default — only submitted sheets show)

Reports support standard Frappe export (Excel / CSV / PDF).

---

## 7. Cheat-sheet for monthly cycle

1. Receive Excel with that month's Days / OT / variables.
2. (If new hires or raises) → create Employee Compensation records.
3. Payroll Import → upload Excel → Start Import.
4. Review red rows, fix the cause, **Re-run Import**.
5. Open the list of Payroll Sheets for the month → Submit (bulk-submit if happy).
6. Run Pay Sheet Detail and Pay Sheet Summary reports → export / print.
7. Per employee → **Create Salary Slip** if you need ERPNext slips.
