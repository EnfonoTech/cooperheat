app_name = "cooperheat"
app_title = "cooperheat"
app_publisher = "enfonotechnology"
app_description = "cooperheat"
app_email = "roshnatnbr@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "cooperheat",
# 		"logo": "/assets/cooperheat/logo.png",
# 		"title": "cooperheat",
# 		"route": "/cooperheat",
# 		"has_permission": "cooperheat.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/cooperheat/css/cooperheat.css"
# app_include_js = "/assets/cooperheat/js/cooperheat.js"
app_include_js = ["/assets/cooperheat/js/branding.js"]
# bump ?v= when the file changes: the CDN in front of the site caches assets by URL
app_include_css = ["/assets/cooperheat/css/cooperheat_theme.css?v=20261027d"]
extend_bootinfo = ["cooperheat.cooperheat.branding.extend_bootinfo"]

# include js, css files in header of web template
# web_include_css = "/assets/cooperheat/css/cooperheat.css"
# web_include_js = "/assets/cooperheat/js/cooperheat.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "cooperheat/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_js = {
	"Employee": "public/js/employee.js",
	"Department": "public/js/department.js",
	"Service Request": "public/js/service_request.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
doctype_list_js = {
	"Employee Checkin": "public/js/employee_checkin_list.js",
	"Department": "public/js/department_list.js",
}
doctype_tree_js = {"Department": "public/js/department_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "cooperheat/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "cooperheat.utils.jinja_methods",
# 	"filters": "cooperheat.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "cooperheat.install.before_install"
after_install = "cooperheat.setup.after_install"
after_migrate = "cooperheat.setup.after_migrate"

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					# Attendance
					"Attendance-approval_details_section",
					"Attendance-approval_window_hours",
					"Attendance-current_approval_level",
					"Attendance-current_approver",
					"Attendance-current_approver_name",
					"Attendance-level_assigned_at",
					"Attendance-window_expires_at",
					"Attendance-window_reminder_sent",
					"Attendance-custom_site_hours_section",
					"Attendance-custom_site_hours",
					# Department
					"Department-approval_matrix",
					"Department-approval_matrix_section",
					# Employee
					"Employee-custom_section_break_ujd19",
					"Employee-custom_site_id",
					# Employee Checkin
					"Employee Checkin-activity_log",
					"Employee Checkin-activity_log_section",
					"Employee Checkin-custom_project",
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
			
					"Shift Assignment-custom_section_break_hu5yo",
					"Shift Assignment-custom_project_sites",
					# Attendance Request
					"Attendance Request-custom_sites_section",
					"Attendance Request-custom_assigned_sites",

					"Project-level_2_approval_window",
                   	"Employee-custom_id_type",
                    "Employee-custom_site_id",
                    "Employee-custom_column_break_z4stf",
                    "Employee-custom_expairy_date",
					# Leave Application
					"Leave Application-custom_client_approval_section",
					"Leave Application-custom_client_approval_required",
					"Leave Application-custom_client_approval_received",
					"Leave Application-custom_client_approval_attachment",
					# Organisation structure
					"Department-custom_unit_type",
					"Employee-custom_business_line",
					"Employee-custom_product_line",
					"Employee-custom_assigned_location",
					"Employee-custom_work_schedule_section",
					"Employee-custom_staff_category",
					"Employee-custom_secondary_reporting",
					"Employee-custom_support_reporting",
					"Employee-custom_job_code",
					"Cost Center-custom_business_line",
					"Cost Center-custom_product_line",
					"Cost Center-custom_description",
					"Employee-custom_compensation_tab",
					"Employee-custom_compensation_html",
					"Attendance-custom_overtime_section",
					"Attendance-custom_regular_hours",
					"Attendance-custom_ot_hours",
					"Attendance-custom_holiday_ot_hours",
					"Attendance-custom_ot_basis",
				],
			]
		],
	},
	"Client Script",
	{
		"dt": "Property Setter",
		"filters": [
			["name", "in", [
				# Attendance
				"Attendance-in_time-allow_on_submit",
				"Attendance-in_time-read_only",
				"Attendance-in_time-depends_on",
				"Attendance-out_time-allow_on_submit",
				"Attendance-out_time-read_only",
				"Attendance-out_time-depends_on",
				"Attendance-working_hours-allow_on_submit",
				"Attendance-working_hours-read_only",
				"Attendance-working_hours-depends_on",
				"Attendance-status-allow_on_submit",
				"Attendance-status-read_only",
				# Project
				"Project-main-field_order",
				"Project-customer-label",
				"Project-naming_series-options",
				"Project-status-hidden",
				# Shift Assignment
				"Shift Assignment-main-field_order",
				"Shift Assignment-shift_location-fetch_from",
				# Employee: Location is enough (client, 2026-10-28)
				"Employee-branch-hidden",
				# show "HTLS", "160-MSS" instead of "HTLS - C", "160-MSS - C" (client, 2026-10-28)
				"Department-main-title_field",
				"Department-main-show_title_field_in_link",
				"Cost Center-main-title_field",
				"Cost Center-main-show_title_field_in_link",
			]],
		],
	},
	{
		"dt": "Workflow State",
		"filters": [
			[
				"name",
				"in",
				[
					"Draft",
					"Pending Level 1 Approval",
					"Pending Level 2 Approval",
					"Pending Level 3 Approval",
					"Approved",
					"Rejected",
				],
			]
		],
	},
	{
		"dt": "Workflow",
		"filters": [["name", "=", "Attendance Approval"]],
	},
]

# Uninstallation
# ------------

# before_uninstall = "cooperheat.uninstall.before_uninstall"
# after_uninstall = "cooperheat.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "cooperheat.utils.before_app_install"
# after_app_install = "cooperheat.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "cooperheat.utils.before_app_uninstall"
# after_app_uninstall = "cooperheat.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "cooperheat.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Attendance": {
		"before_validate": "cooperheat.cooperheat.overrides.attendance.before_validate",
		"on_submit": "cooperheat.cooperheat.overrides.attendance.on_submit",
		"validate": "cooperheat.cooperheat.overrides.attendance.validate",
		"before_update_after_submit": "cooperheat.cooperheat.overrides.attendance.before_update_after_submit",
		"on_update_after_submit": "cooperheat.cooperheat.overrides.attendance.on_update_after_submit",
	},
	"Department": {
		"before_validate": "cooperheat.cooperheat.overrides.department.before_validate",
		"validate": "cooperheat.cooperheat.overrides.department.validate",
	},
	"Employee": {
		"before_validate": "cooperheat.cooperheat.overrides.employee.before_validate",
		"on_update": "cooperheat.cooperheat.overrides.employee.on_update",
	},
	"Project": {
		"autoname": "cooperheat.cooperheat.overrides.project.autoname",
	},
	"Leave Application": {
		"before_validate": "cooperheat.cooperheat.approval_workflows.before_validate",
		"validate": "cooperheat.cooperheat.overrides.leave_application.validate",
		"on_update": "cooperheat.cooperheat.approval_workflows.on_update",
	},
	"Expense Claim": {
		"before_validate": "cooperheat.cooperheat.approval_workflows.before_validate",
		"on_update": "cooperheat.cooperheat.approval_workflows.on_update",
	},
	"User": {
		"validate": "cooperheat.cooperheat.roles_simple.guard_admin_accounts",
		"on_update": "cooperheat.cooperheat.permissions.scope.on_user_update",
	},
	"Employee Checkin": {
		"validate": "cooperheat.cooperheat.overrides.employee_checkin.validate",
		"after_insert": "cooperheat.cooperheat.overrides.employee_checkin.after_insert",
		"on_update": "cooperheat.cooperheat.overrides.employee_checkin.on_update",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"hourly": [
		"cooperheat.cooperheat.auto_checkout.close_forgotten_checkins",
		"cooperheat.cooperheat.api.attendance_gen.generate_attendance_from_checkins",
		"cooperheat.cooperheat.api.tasks.process_attendance_approval_windows",
	],
	"daily": [
		"cooperheat.cooperheat.work_schedule.roll_over_calendars",
	],
}

# Testing
# -------

# before_tests = "cooperheat.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "cooperheat.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "cooperheat.task.get_dashboard_data"
# }

override_doctype_dashboards = {"Employee": "cooperheat.cooperheat.dashboards.employee_dashboard"}

# the AI assistant of the Grey Theme app runs model-written SQL without permission checks: IT only
override_whitelisted_methods = {
	"grey_theme.chat_handler.handle_ai_query": "cooperheat.cooperheat.ai_guard.handle_ai_query"
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["cooperheat.utils.before_request"]
# after_request = ["cooperheat.utils.after_request"]

# Job Events
# ----------
# before_job = ["cooperheat.utils.before_job"]
# after_job = ["cooperheat.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"cooperheat.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


# Team scoping for Supervisor / Manager users (see cooperheat/permissions/scope.py)
permission_query_conditions = {
	"Employee": "cooperheat.cooperheat.permissions.scope.employee_query",
	"Employee Checkin": "cooperheat.cooperheat.permissions.scope.employee_checkin_query",
	"Attendance": "cooperheat.cooperheat.permissions.scope.attendance_query",
	"Shift Assignment": "cooperheat.cooperheat.permissions.scope.shift_assignment_query",
	"Department": "cooperheat.cooperheat.permissions.scope.department_query",
	"Service Request": "cooperheat.cooperheat.service_request_tools.query_conditions",
	"Employee Transfer Request": "cooperheat.cooperheat.doctype.employee_transfer_request.employee_transfer_request.query_conditions",
}

has_permission = {
	"Employee": "cooperheat.cooperheat.permissions.scope.employee_has_permission",
	"Employee Checkin": "cooperheat.cooperheat.permissions.scope.employee_doc_has_permission",
	"Attendance": "cooperheat.cooperheat.permissions.scope.employee_doc_has_permission",
	"Shift Assignment": "cooperheat.cooperheat.permissions.scope.employee_doc_has_permission",
	"Department": "cooperheat.cooperheat.permissions.scope.department_has_permission",
	"Service Request": "cooperheat.cooperheat.service_request_tools.has_permission",
	"Employee Transfer Request": "cooperheat.cooperheat.doctype.employee_transfer_request.employee_transfer_request.has_permission",
}
