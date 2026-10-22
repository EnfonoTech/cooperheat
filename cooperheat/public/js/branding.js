// Cooperheat: the browser-tab title ends with the platform name ("Division | Cooperheat").
(function () {
	const BRAND = "Cooperheat";
	const original = frappe.utils.set_title;
	frappe.utils.set_title = function (title) {
		original.call(this, title);
		if (document.title && !document.title.endsWith(BRAND)) {
			document.title = document.title + " | " + BRAND;
		}
	};
})();
