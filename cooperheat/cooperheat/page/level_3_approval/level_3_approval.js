frappe.pages["level-3-approval"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Level 3 Attendance Approval"),
		single_column: true,
	});
	wrapper._l3page = new Level3ApprovalPage(wrapper, page);
};

frappe.pages["level-3-approval"].on_page_show = function (wrapper) {
	wrapper._l3page && wrapper._l3page.load_records();
};

class Level3ApprovalPage {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.records = [];
		this._setup();
	}

	_setup() {
		// ── Filter fields in page header ──────────────────────────────────
		this.f_employee = this.page.add_field({
			fieldtype: "Link",
			fieldname: "employee",
			options: "Employee",
			label: __("Employee"),
			change: () => this.load_records(),
		});

		this.f_department = this.page.add_field({
			fieldtype: "Link",
			fieldname: "department",
			options: "Department",
			label: __("Department"),
			change: () => this.load_records(),
		});

		this.f_from_date = this.page.add_field({
			fieldtype: "Date",
			fieldname: "from_date",
			label: __("From Date"),
			change: () => this.load_records(),
		});

		this.f_to_date = this.page.add_field({
			fieldtype: "Date",
			fieldname: "to_date",
			label: __("To Date"),
			change: () => this.load_records(),
		});

		// ── Action buttons ────────────────────────────────────────────────
		this.page.add_inner_button(__("Refresh"), () => this.load_records());
		this.page.add_inner_button(__("Approve Selected"), () => this._approve_batch("selected"));
		this.page.set_primary_action(__("Approve All"), () => this._approve_batch("all"), "check");

		this.$body = $(`
			<div style="padding: 15px 20px;">
				<div class="l3-summary" style="margin-bottom:12px; color:#6c757d; font-size:13px;"></div>
				<div class="l3-table-wrap" style="overflow-x:auto;"></div>
			</div>
		`).appendTo(this.page.main);

		this.$summary = this.$body.find(".l3-summary");
		this.$table_wrap = this.$body.find(".l3-table-wrap");
	}

	_get_filters() {
		return {
			employee:    this.f_employee.get_value()    || null,
			department:  this.f_department.get_value()  || null,
			from_date:   this.f_from_date.get_value()   || null,
			to_date:     this.f_to_date.get_value()     || null,
		};
	}

	load_records() {
		this.$table_wrap.html(
			'<div style="padding:40px;text-align:center;color:#6c757d;">Loading…</div>'
		);
		frappe.call({
			method: "cooperheat.cooperheat.api.api.get_pending_level3_records",
			args: this._get_filters(),
			callback: (r) => {
				this.records = (r && r.message) || [];
				this._render();
			},
		});
	}

	_render() {
		if (!this.records.length) {
			this.$summary.text("");
			this.$table_wrap.html(
				'<div style="padding:40px;text-align:center;color:#6c757d;">No attendance records are pending Level 3 approval for your department(s).</div>'
			);
			return;
		}

		this.$summary.text(__("{0} record(s) pending Level 3 approval", [this.records.length]));

		const rows = this.records
			.map(
				(r, i) => `
			<tr data-idx="${i}" data-name="${frappe.utils.escape_html(r.name)}">
				<td style="text-align:center;">
					<input type="checkbox" class="l3-chk" value="${frappe.utils.escape_html(r.name)}">
				</td>
				<td>
					<a href="/app/attendance/${frappe.utils.escape_html(r.name)}" target="_blank" style="font-size:12px;">
						${frappe.utils.escape_html(r.name)}
					</a>
				</td>
				<td>${frappe.utils.escape_html(r.employee_name || r.employee)}</td>
				<td style="white-space:nowrap;">${frappe.utils.escape_html(r.attendance_date || "")}</td>
				<td style="white-space:nowrap;">${frappe.utils.escape_html(r.department || "")}</td>
				<td>
					<input type="datetime-local" class="form-control form-control-sm l3-in-time"
						value="${this._to_input_dt(r.in_time)}" style="min-width:155px;">
				</td>
				<td>
					<input type="datetime-local" class="form-control form-control-sm l3-out-time"
						value="${this._to_input_dt(r.out_time)}" style="min-width:155px;">
				</td>
				<td>
					<input type="number" class="form-control form-control-sm l3-hours"
						value="${flt(r.working_hours, 2)}" step="0.01" min="0" style="width:75px;">
				</td>
				<td>
					<select class="form-control form-control-sm l3-status" style="min-width:110px;">
						${["Present","Absent","Half Day","Work From Home"].map(s =>
							`<option value="${s}" ${s === (r.status || "") ? "selected" : ""}>${s}</option>`
						).join("")}
					</select>
				</td>
				<td>
					<button class="btn btn-xs btn-success l3-approve-btn" style="white-space:nowrap;">
						${__("Approve")}
					</button>
				</td>
			</tr>
		`
			)
			.join("");

		this.$table_wrap.html(`
			<table class="table table-bordered table-sm" style="font-size:13px;margin-bottom:0;">
				<thead style="background:#f8f9fa;">
					<tr>
						<th style="width:36px;"><input type="checkbox" id="l3-select-all"></th>
						<th>${__("Attendance")}</th>
						<th>${__("Employee")}</th>
						<th>${__("Date")}</th>
						<th>${__("Department")}</th>
						<th>${__("In Time")}</th>
						<th>${__("Out Time")}</th>
						<th>${__("Hours")}</th>
						<th>${__("Status")}</th>
						<th>${__("Action")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		`);

		this._bind_events();
	}

	_bind_events() {
		this.$table_wrap.find("#l3-select-all").on("change", (e) => {
			this.$table_wrap.find(".l3-chk").prop("checked", e.target.checked);
		});

		this.$table_wrap.on("change", ".l3-in-time, .l3-out-time", (e) => {
			const $row = $(e.target).closest("tr");
			const inn = $row.find(".l3-in-time").val();
			const out = $row.find(".l3-out-time").val();
			if (inn && out) {
				const diff = (new Date(out) - new Date(inn)) / 3600000;
				if (diff > 0) $row.find(".l3-hours").val(Math.round(diff * 100) / 100);
			}
		});

		this.$table_wrap.on("click", ".l3-approve-btn", (e) => {
			const $row = $(e.target).closest("tr");
			this._approve_row($row);
		});
	}

	_approve_row($row, on_done) {
		const name = $row.data("name");
		const in_time = this._from_input_dt($row.find(".l3-in-time").val());
		const out_time = this._from_input_dt($row.find(".l3-out-time").val());
		const working_hours = $row.find(".l3-hours").val();
		const status = $row.find(".l3-status").val();

		const $btn = $row.find(".l3-approve-btn");
		$btn.prop("disabled", true).text(__("Approving…"));

		frappe.call({
			method: "cooperheat.cooperheat.api.api.level3_approve_attendance",
			args: { name, in_time, out_time, working_hours, status },
			callback: (r) => {
				if (r && !r.exc) {
					$row.css("background", "#d4edda");
					$btn.removeClass("btn-success").addClass("btn-secondary").text(__("Approved"));
					$row.find(".l3-chk, .l3-in-time, .l3-out-time, .l3-hours, .l3-status").prop("disabled", true);
					on_done && on_done(true);
				} else {
					$btn.prop("disabled", false).text(__("Approve"));
					on_done && on_done(false);
				}
			},
		});
	}

	_approve_batch(mode) {
		let $rows;
		if (mode === "all") {
			$rows = this.$table_wrap.find("tbody tr");
		} else {
			const selected = this.$table_wrap
				.find(".l3-chk:checked")
				.map(function () {
					return $(this).val();
				})
				.get();
			if (!selected.length) {
				frappe.show_alert({ message: __("Please select at least one record."), indicator: "orange" });
				return;
			}
			$rows = this.$table_wrap.find("tbody tr").filter(function () {
				return selected.includes($(this).data("name"));
			});
		}

		$rows = $rows.filter(function () {
			return !$(this).find(".l3-approve-btn").hasClass("btn-secondary");
		});

		if (!$rows.length) {
			frappe.show_alert({ message: __("No pending records to approve."), indicator: "blue" });
			return;
		}

		frappe.confirm(
			__("Approve {0} record(s) with the current in/out times and hours shown?", [$rows.length]),
			() => {
				let done = 0, failed = 0;
				const total = $rows.length;

				const next = (idx) => {
					if (idx >= $rows.length) {
						frappe.hide_progress();
						frappe.show_alert({
							message: __("{0} approved, {1} failed.", [done, failed]),
							indicator: failed ? "orange" : "green",
						});
						return;
					}
					frappe.show_progress(__("Approving…"), idx + 1, total);
					this._approve_row($rows.eq(idx), (ok) => {
						ok ? done++ : failed++;
						next(idx + 1);
					});
				};
				next(0);
			}
		);
	}

	_from_input_dt(val) {
		if (!val) return null;
		return val.replace("T", " ") + ":00";
	}

	_to_input_dt(val) {
		if (!val) return "";
		return String(val).substring(0, 16).replace(" ", "T");
	}
}

function flt(val, precision) {
	const n = parseFloat(val) || 0;
	return precision !== undefined ? parseFloat(n.toFixed(precision)) : n;
}
