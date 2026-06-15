# Cooperheat App — Changes Documentation

## 1. Fixtures — `hooks.py`

### Custom Field Filter (explicit name list)
Previously `"Custom Field"` had no filter, which exported ALL custom fields from the entire system (including HRMS standard fields). Now it uses an explicit name list to export only cooperheat-owned fields.

```python
{
    "dt": "Custom Field",
    "filters": [
        ["name", "in", [
            # Attendance
            "Attendance-approval_details_section",
            "Attendance-approval_window_hours",
            "Attendance-current_approval_level",
            "Attendance-current_approver",
            "Attendance-current_approver_name",
            "Attendance-level_assigned_at",
            "Attendance-window_expires_at",
            "Attendance-window_reminder_sent",
            # Department
            "Department-approval_matrix",
            "Department-approval_matrix_section",
            # Employee
            "Employee-custom_section_break_ujd19",
            "Employee-custom_site_id",
            # Employee Checkin
            "Employee Checkin-activity_log",
            "Employee Checkin-activity_log_section",
            # Project
            "Project-custom_crm_no",
            "Project-custom_estimated_no_of_technicians",
            "Project-custom_is_vehicle_required",
            "Project-custom_location",
            "Project-custom_max_overtime_hours__day",
            "Project-custom_overtime_allowed",
            "Project-custom_project_code",
            "Project-custom_project_status",
            "Project-custom_regular_working_hours__day",
            "Project-geo_fence_radius",
            "Project-geo_location_rule",
            "Project-manager_payroll_final_approval_window",
            "Project-site_work_section",
            "Project-special_site_id_required",
            "Project-supervisor_approval_window",
            "Project-total_expense_claim",
            # Shift Assignment
            "Shift Assignment-custom_project_",
            "Shift Assignment-custom_project_code",
        ]]
    ],
},
```

> **Rule:** When adding a new custom field through the UI, also add its name here and run `bench --site cooperheats.new export-fixtures` from `~/fifteen-bench`.

---

### Workflow Filter Fixed
Old filter pointed to the deactivated "Shift Assignment Approval" workflow. Updated to the active one.

| Before | After |
|--------|-------|
| `"Shift Assignment Approval"` | `"Attendance Approval"` |

---

### Scheduler Path Updated
Scheduled task path updated to match the new `api/` folder structure.

| Before | After |
|--------|-------|
| `cooperheat.cooperheat.tasks.process_attendance_approval_windows` | `cooperheat.cooperheat.api.tasks.process_attendance_approval_windows` |

---

## 2. New `api/` Folder

**Path:** `apps/cooperheat/cooperheat/cooperheat/api/`

```
api/
  __init__.py
  tasks.py     ← moved from cooperheat/tasks.py
  api.py       ← new whitelisted endpoint
```

### `tasks.py` (moved)
Hourly scheduled task that auto-approves attendance records when the approval window expires. No logic changed — only moved to the `api/` folder.

### `api.py` (new)
Exposes the scheduled task as a callable API endpoint for manual triggering.

```python
@frappe.whitelist()
def run_attendance_approval_windows():
    frappe.has_permission("Attendance", ptype="write", throw=True)
    process_attendance_approval_windows()
    return {"status": "ok"}
```

**Call from browser console:**
```js
frappe.call("cooperheat.cooperheat.api.api.run_attendance_approval_windows")
```

---

## 3. Employee Custom Fields — Module Fixed

`Employee-custom_site_id` and `Employee-custom_section_break_ujd19` had `module = NULL` in the database, so they were not being exported by `bench export-fixtures`.

**Fix:** Set `module = 'cooperheat'` on both fields in the DB. They are now included in `custom_field.json`.

| Field | Type | Description |
|-------|------|-------------|
| `Employee-custom_section_break_ujd19` | Section Break | Section header inserted after `date_of_retirement` |
| `Employee-custom_site_id` | Table → Employee Site Access | Links employee to site access records |

---

## 4. `custom_field.json` — Clean Export

After the above fixes, `bench export-fixtures` now exports exactly **32 cooperheat-owned custom fields** across 6 DocTypes:

| DocType | Fields |
|---------|--------|
| Attendance | 8 |
| Department | 2 |
| Employee | 2 |
| Employee Checkin | 2 |
| Project | 16 |
| Shift Assignment | 2 |

No HRMS/ERPNext standard fields are included.

---

## 5. How to Export Fixtures

Always run from the bench root:

```bash
cd ~/fifteen-bench
bench --site cooperheats.new export-fixtures
```

**Do NOT run from inside `apps/cooperheat/` — the JSON files will not update.**

---

## 6. Patch — `deactivate_shift_assignment_workflow`

**Path:** `apps/cooperheat/cooperheat/cooperheat/patches/v1/deactivate_shift_assignment_workflow.py`

One-time migration patch created when the approval flow moved from Shift Assignment → Attendance. It:
- Deactivates the "Shift Assignment Approval" workflow
- Removes old approval fields (`current_approver`, `current_approval_level`, etc.) from Shift Assignment

Already executed on `cooperheats.new`. Safe to leave as-is — Frappe patches run only once per site.
