"""Cooperheat branding of the ERP (client request 2026-10-22): platform name, logo and favicon.

Applied by hand with ``apply_branding`` (never from migrate), so it reaches a site only when
somebody decides to: dev site first for the client's review, production afterwards.

    bench --site <site> execute cooperheat.cooperheat.branding.apply_branding
    bench --site <site> execute cooperheat.cooperheat.branding.revert_branding   # back to the stock look

Sets the name and the images in the places Frappe reads them (desk navbar, login page, browser
tab icon), and a website theme that removes the product illustration and the vendor credit from
the login page. The browser-tab title gets " | Cooperheat" from public/js/branding.js.
"""

import frappe

NAME = "Cooperheat"
LOGO = "/assets/cooperheat/images/cooperheat-logo.png"
# the version in the URL makes browsers drop a cached favicon (bump it when the file changes)
FAVICON = "/assets/cooperheat/images/cooperheat-favicon.png?v=20261024"
THEME = "Cooperheat"

# Red and white look (client request 2026-10-27), switched on separately with apply_red_theme so it
# can be reviewed on the dev site first. The desk colours are in public/css/cooperheat_theme.css,
# active while the default below is set (published to the desk as frappe.boot.cooperheat_red_theme).
RED_THEME_DEFAULT = "cooperheat_red_theme"
RED = "#97041e"
# browser-tab icon: the client's red logo tile (their picture of 27 Oct)
MARK = "/assets/cooperheat/images/cooperheat-tile-64.png?v=20261027b"
LOGIN_RED_CSS = """
.for-login .btn-login, .for-login .btn-primary { background-color: #97041e !important; border-color: #97041e !important; }
.for-login .btn-login:hover, .for-login .btn-primary:hover { background-color: #730317 !important; }
.for-login .page-card { border-color: #97041e !important; border-top: 4px solid #97041e !important; }
.for-login .form-control { border-color: #97041e66 !important; }
[data-path="login"] .navbar-light, [data-path="login"] .web-footer { border-color: #97041e !important; }
"""

# The in-built AI assistant of the Grey Theme app is called "Fateh AI" there; on this site it carries
# the client's name instead (workspace + page title; the page text is renamed by public/js/branding.js).
AI_WORKSPACE = "FATEH AI"
AI_NAME = "Cooperheat AI"

# The login page (grey_theme) shows an ERPNext product picture and "Powered By ..." next to the logo.
LOGIN_CSS = """
.login-content-bg .app-login-bg,
.login-content-bg .login-copyrights { display: none !important; }
.login-content-bg { display: flex !important; align-items: center; justify-content: center; }
.login-content-bg .app-logo {
	position: static !important; width: 150px !important; height: auto !important; max-width: 70% !important;
	max-height: none !important; object-fit: contain !important; margin: 0 auto !important; display: block;
}
"""

# Browser-tab title of the login page (the desk's titles get the suffix from public/js/branding.js)
LOGIN_JS = "document.title = document.title.replace(/ \\| Cooperheat$/, '') + ' | Cooperheat';"


def apply_branding() -> dict:
	"""Idempotent. Returns what is now set."""
	website = frappe.get_single("Website Settings")
	website.app_name = NAME
	website.app_logo = LOGO
	website.favicon = FAVICON
	website.splash_image = LOGO
	website.website_theme = _ensure_theme()
	website.flags.ignore_permissions = True
	website.save()

	navbar = frappe.get_single("Navbar Settings")
	navbar.app_logo = LOGO
	navbar.flags.ignore_permissions = True
	navbar.save()

	frappe.db.set_single_value("System Settings", "app_name", NAME)
	brand_ai_workspace()
	frappe.clear_cache()
	return current()


def apply_red_theme() -> dict:
	"""Idempotent. Red header with the white logo, red buttons and highlights, the "C" mark as
	browser-tab icon, red login button. Needs apply_branding first (name, logos)."""
	frappe.db.set_default(RED_THEME_DEFAULT, "1")
	frappe.db.set_single_value("Website Settings", "favicon", MARK)
	_ensure_theme()
	frappe.clear_cache()
	return current()


def revert_red_theme() -> dict:
	"""Back to the grey desk of apply_branding (logo, favicon and login as they were)."""
	frappe.db.set_default(RED_THEME_DEFAULT, None)
	frappe.db.set_single_value("Website Settings", "favicon", FAVICON)
	_ensure_theme()
	frappe.clear_cache()
	return current()


def red_theme_on() -> bool:
	return frappe.db.get_default(RED_THEME_DEFAULT) == "1"


def extend_bootinfo(bootinfo):
	"""Tells public/js/branding.js whether to switch the red desk on. Never raises."""
	try:
		bootinfo.cooperheat_red_theme = 1 if red_theme_on() else 0
	except Exception:
		bootinfo.cooperheat_red_theme = 0


def is_applied() -> bool:
	return frappe.db.get_single_value("Website Settings", "app_name") == NAME


def brand_ai_workspace(reverse: bool = False) -> bool:
	"""Idempotent. Shows the AI assistant of the Grey Theme app under the client's name on this site.

	The workspace record is re-imported from the app's JSON on every migrate, so ``after_migrate``
	calls this again while the branding is applied. ``reverse`` puts the original name back.
	"""
	if not frappe.db.exists("Workspace", AI_WORKSPACE):
		return False
	old, new = ("Fateh AI", AI_NAME) if not reverse else (AI_NAME, "Fateh AI")

	def swap(text: str) -> str:
		return text.replace(old.upper(), new.upper()).replace(old, new)

	ws = frappe.get_doc("Workspace", AI_WORKSPACE)
	changed = False
	for field in ("title", "content"):
		value = ws.get(field)
		if value and swap(value) != value:
			ws.set(field, swap(value))
			changed = True
	for link in ws.get("shortcuts") or []:
		if link.label and swap(link.label) != link.label:
			link.label = swap(link.label)
			changed = True
	if changed:
		ws.flags.ignore_permissions = True
		ws.flags.ignore_version = True
		ws.save()
	return changed


def revert_branding() -> dict:
	"""Back to the stock look (Frappe name, no logo, no favicon, no theme)."""
	frappe.db.set_single_value(
		"Website Settings",
		{
			"app_name": "Frappe",
			"app_logo": None,
			"favicon": None,
			"splash_image": None,
			"website_theme": None,
		},
	)
	frappe.db.set_single_value("Navbar Settings", "app_logo", None)
	frappe.db.set_single_value("System Settings", "app_name", "Frappe")
	frappe.db.set_default(RED_THEME_DEFAULT, None)
	brand_ai_workspace(reverse=True)
	frappe.clear_cache()
	return current()


def current() -> dict:
	return {
		"app_name": frappe.db.get_single_value("Website Settings", "app_name"),
		"app_logo": frappe.db.get_single_value("Website Settings", "app_logo"),
		"favicon": frappe.db.get_single_value("Website Settings", "favicon"),
		"navbar_logo": frappe.db.get_single_value("Navbar Settings", "app_logo"),
		"theme": frappe.db.get_single_value("Website Settings", "website_theme"),
		"system_app_name": frappe.db.get_single_value("System Settings", "app_name"),
		"red_theme": red_theme_on(),
	}


def _ensure_theme() -> str:
	if frappe.db.exists("Website Theme", THEME):
		theme = frappe.get_doc("Website Theme", THEME)
	else:
		theme = frappe.new_doc("Website Theme")
		theme.theme = THEME
	theme.custom = 1
	theme.js = LOGIN_JS
	theme.custom_scss = LOGIN_CSS + (LOGIN_RED_CSS if red_theme_on() else "")
	theme.flags.ignore_permissions = True
	theme.save()
	return theme.name


def welcome_email() -> str:
	"""Subject and heading of the new-user e-mail (hook ``welcome_email``): the platform name,
	not the legal Company name (client, 2026-10-29)."""
	from frappe import _

	name = frappe.db.get_single_value("System Settings", "app_name") or NAME
	return _("Welcome to {0}").format(name)
