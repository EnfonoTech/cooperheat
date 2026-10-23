// Cooperheat: the browser-tab title ends with the platform name ("Division | Cooperheat"), and the
// in-built AI assistant (a page of the Grey Theme app, "Fateh AI") shows the client's name.
(function () {
	const BRAND = "Cooperheat";
	const original = frappe.utils.set_title;
	frappe.utils.set_title = function (title) {
		original.call(this, title);
		if (document.title && !document.title.endsWith(BRAND)) {
			document.title = document.title + " | " + BRAND;
		}
	};

	const AI_OLD = /Fateh AI/gi;
	const AI_NEW = "Cooperheat AI";
	// Only once the branding is applied on the site (the Cooperheat logo is the navbar logo).
	const branded = () => (frappe.boot?.app_logo_url || "").includes("cooperheat");

	function rename_in(root) {
		const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
		for (let node = walker.nextNode(); node; node = walker.nextNode()) {
			if (AI_OLD.test(node.nodeValue))
				node.nodeValue = node.nodeValue.replace(AI_OLD, AI_NEW);
			AI_OLD.lastIndex = 0;
		}
		if (/Fateh AI/i.test(document.title))
			document.title = document.title.replace(AI_OLD, AI_NEW);
	}

	function brand_ai_chat() {
		const root = document.querySelector('[data-page-route="ai-chat"]');
		if (!root || root.dataset.cooperheatAi || !branded()) return;
		root.dataset.cooperheatAi = "1";
		const crumbs = document.querySelector("#navbar-breadcrumbs");
		const rename = () => {
			rename_in(root);
			if (crumbs) rename_in(crumbs);
		};
		rename();
		const observer = new MutationObserver(rename);
		observer.observe(root, { childList: true, subtree: true, characterData: true });
		if (crumbs)
			observer.observe(crumbs, { childList: true, subtree: true, characterData: true });
	}
	$(document).on("page-change", () => setTimeout(brand_ai_chat, 0));
})();
