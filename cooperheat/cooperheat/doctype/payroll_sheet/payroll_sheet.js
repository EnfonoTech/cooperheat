// Copyright (c) 2026, enfonotechnology and contributors
// For license information, please see license.txt

const EARNING_FIELDS = [
	"basic", "housing_allowance", "transport_allowance", "living_allowance",
	"service_allowance", "driving_allowance", "merit_award", "aramco_certification",
	"supervisor_allowance", "education_allowance", "rso_allowance", "rpp_allowance",
	"other_allowance",
];

const PRORATED_EARNING_FIELDS = EARNING_FIELDS.filter(f => f !== "basic");

const SPECIAL_EARNINGS = [
	"others", "bonus", "expenses", "air_fare", "vacation_pay", "gratuity", "retention",
];

const DEDUCTION_FIELDS = [
	"general_advance", "housing_advance", "housing_deduction",
	"transport_deduction", "education_deduction", "retention_deduction",
	"other_deduction",
	"additional_housing_deduction", "additional_other_deduction",
];

const MONTHS = [
	"January", "February", "March", "April", "May", "June",
	"July", "August", "September", "October", "November", "December",
];

function days_in_month(year, month_name) {
	const idx = MONTHS.indexOf(month_name);
	if (idx === -1 || !year) return 30;
	return new Date(parseInt(year), idx + 1, 0).getDate();
}

let cached_settings = null;
async function get_settings() {
	if (cached_settings) return cached_settings;
	const r = await frappe.db.get_doc("Pay Sheet Settings");
	cached_settings = r;
	return r;
}

function recalc(frm, settings) {
	const dim = frm.doc.days_in_month || days_in_month(frm.doc.year, frm.doc.month);
	frm.set_value("days_in_month", dim);

	const mwh = settings.monthly_working_hours || 240;
	const basic = flt(frm.doc.basic);
	const hourly = mwh ? basic / mwh : 0;

	const normal = hourly * (settings.normal_ot_multiplier || 1.5) * flt(frm.doc.normal_ot_hours);
	const holiday = hourly * (settings.holiday_ot_multiplier || 2) * flt(frm.doc.holiday_ot_hours);
	const travel = hourly * (settings.travel_ot_multiplier || 1.5) * flt(frm.doc.travel_ot_hours);

	frm.set_value("normal_ot_amount", normal);
	frm.set_value("holiday_ot_amount", holiday);
	frm.set_value("travel_ot_amount", travel);
	const total_ot = normal + holiday + travel;
	frm.set_value("total_ot_amount", total_ot);

	// GOSI
	const applicable = (settings.gosi_applicable_category || "Saudi").trim();
	const gosi = (frm.doc.employee_category || "").trim() === applicable
		? (basic + flt(frm.doc.housing_allowance)) * (settings.gosi_rate_percent || 0) / 100
		: 0;
	frm.set_value("gosi", gosi);

	// Totals
	let earnings = 0;
	EARNING_FIELDS.forEach(f => earnings += flt(frm.doc[f]));
	SPECIAL_EARNINGS.forEach(f => earnings += flt(frm.doc[f]));
	earnings += total_ot;
	frm.set_value("total_earnings", earnings);

	let deductions = gosi;
	DEDUCTION_FIELDS.forEach(f => deductions += flt(frm.doc[f]));
	frm.set_value("total_deduction", deductions);

	frm.set_value("net_payable", earnings - deductions);
}

async function trigger_recalc(frm, fieldname) {
	if (frm.__recalc_in_progress) return;
	frm.__recalc_in_progress = true;
	try {
		const settings = await get_settings();
		if (REPRORATE_ON_CHANGE.includes(fieldname)) {
			await apply_proration(frm);
		}
		recalc(frm, settings);
	} finally {
		frm.__recalc_in_progress = false;
	}
}

async function apply_proration(frm) {
	if (!frm.doc.compensation) return;
	if (!frm.__comp || frm.__comp.name !== frm.doc.compensation) {
		frm.__comp = await frappe.db.get_doc("Employee Compensation", frm.doc.compensation);
	}
	const comp = frm.__comp;
	const dim = frm.doc.days_in_month || days_in_month(frm.doc.year, frm.doc.month);
	const worked = flt(frm.doc.worked_days);
	const factor = (worked > 0 && dim > 0) ? Math.min(worked, dim) / dim : 0;
	frm.doc.basic = flt(comp.basic);
	frm.refresh_field("basic");
	PRORATED_EARNING_FIELDS.forEach(f => {
		frm.doc[f] = flt(comp[f]) * factor;
		frm.refresh_field(f);
	});
}

// Fields whose change should trigger re-proration (pull fresh from Compensation)
const REPRORATE_ON_CHANGE = ["worked_days", "month", "year", "compensation"];

const RECALC_FIELDS = [
	"worked_days", "month", "year", "employee_category",
	"normal_ot_hours", "holiday_ot_hours", "travel_ot_hours",
	...EARNING_FIELDS, ...SPECIAL_EARNINGS, ...DEDUCTION_FIELDS,
];

const handlers = {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Create Salary Slip"), () => {
				frappe.call({
					method: "cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet.create_salary_slip",
					args: { payroll_sheet: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating Salary Slip..."),
				}).then(r => {
					if (r.message) {
						frappe.set_route("Form", "Salary Slip", r.message);
					}
				});
			});
		}
		if (!frm.is_new() && frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Pull from Compensation"), () => pull_compensation(frm, true));
		}
	},
	employee(frm) {
		if (frm.doc.employee && frm.doc.docstatus === 0) {
			pull_compensation(frm, false);
		}
	},
};

function pull_compensation(frm, explicit) {
	if (!frm.doc.employee) {
		if (explicit) frappe.msgprint(__("Select Employee first."));
		return;
	}
	frappe.call({
		method: "cooperheat.cooperheat.doctype.payroll_sheet.payroll_sheet.get_employee_compensation",
		args: {
			employee: frm.doc.employee,
			posting_date: frm.doc.posting_date,
		},
	}).then(r => {
		const data = r.message || {};
		if (!data.compensation) {
			if (explicit) {
				frappe.msgprint({
					title: __("No compensation record"),
					message: __("No active Employee Compensation found for {0}.", [frm.doc.employee]),
					indicator: "orange",
				});
			}
			return;
		}
		frm.set_value("compensation", data.compensation);
		Object.entries(data.values || {}).forEach(([k, v]) => frm.set_value(k, v));
		trigger_recalc(frm);
	});
}

RECALC_FIELDS.forEach(f => {
	handlers[f] = (frm) => trigger_recalc(frm, f);
});

frappe.ui.form.on("Payroll Sheet", handlers);
