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
FAVICON = "/assets/cooperheat/images/cooperheat-favicon.png"
THEME = "Cooperheat"

# The login page (grey_theme) shows an ERPNext product picture and "Powered By ..." next to the logo.
LOGIN_CSS = """
.login-content-bg .app-login-bg,
.login-content-bg .login-copyrights { display: none !important; }
.login-content-bg { display: flex !important; align-items: center; justify-content: center; }
.login-content-bg .app-logo {
	position: static !important; width: 230px !important; height: auto !important; max-width: 70% !important;
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
	frappe.clear_cache()
	return current()


def revert_branding() -> dict:
	"""Back to the stock look (Frappe name, no logo, no favicon, no theme)."""
	frappe.db.set_single_value(
		"Website Settings",
		{"app_name": "Frappe", "app_logo": None, "favicon": None, "splash_image": None, "website_theme": None},
	)
	frappe.db.set_single_value("Navbar Settings", "app_logo", None)
	frappe.db.set_single_value("System Settings", "app_name", "Frappe")
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
	}


def _ensure_theme() -> str:
	if frappe.db.exists("Website Theme", THEME):
		theme = frappe.get_doc("Website Theme", THEME)
	else:
		theme = frappe.new_doc("Website Theme")
		theme.theme = THEME
	theme.custom = 1
	theme.js = LOGIN_JS
	theme.custom_scss = LOGIN_CSS
	theme.flags.ignore_permissions = True
	theme.save()
	return theme.name
