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
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
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
					"Attendance-checkin_log_section",
					"Attendance-checkin_log_html",
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
					"Shift Assignment-custom_project_",
					"Shift Assignment-custom_project_code",
					"Shift Assignment-custom_section_break_hu5yo",
					"Shift Assignment-custom_project_sites",
					# Attendance Request
					"Attendance Request-custom_sites_section",
					"Attendance Request-custom_assigned_sites",

					"Project-level_2_approval_window",
                   	"Employee-custom_id_type",
                    "Employee-custom_site_id",
                    "Employee-custom_column_break_z4stf",
                    "Employee-custom_expairy_date"
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
		"on_update_after_submit": "cooperheat.cooperheat.overrides.attendance.on_update_after_submit",
	},
	"Department": {
		"on_update": "cooperheat.cooperheat.overrides.department.on_update",
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
		"cooperheat.cooperheat.api.tasks.process_attendance_approval_windows",
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

