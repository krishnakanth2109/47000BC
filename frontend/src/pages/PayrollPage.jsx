import { useState, useEffect, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost, apiPut, apiDelete, apiUrl } from "../api.js";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const PAYMENT_FILTERS = ["all", "Pending", "Processed", "Paid"];

function formatCurrency(amount) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(Number(amount || 0));
}

function countWeekdays(year, month) {
  const days = new Date(year, month, 0).getDate();
  let count = 0;
  for (let d = 1; d <= days; d++) {
    const day = new Date(year, month - 1, d).getDay();
    if (day !== 0 && day !== 6) count++;
  }
  return count;
}

export default function PayrollPage() {
  const now = useMemo(() => new Date(), []);
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [workingDays, setWorkingDays] = useState(() =>
    countWeekdays(now.getFullYear(), now.getMonth() + 1)
  );
  const [dailyHours, setDailyHours] = useState(8);

  const [activeTab, setActiveTab] = useState("payroll"); // "payroll" | "structures"
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const [payrollData, setPayrollData] = useState(null);
  const [structures, setStructures] = useState([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Salary structure modal state
  const [editingStruct, setEditingStruct] = useState(null);
  const [structForm, setStructForm] = useState({
    basic_salary: "",
    hra: "",
    allowances: "",
    deductions: "",
    overtime_rate: "",
  });
  const [structBusy, setStructBusy] = useState(false);

  // Payslip preview modal state
  const [payslipRecord, setPayslipRecord] = useState(null);

  const fetchPayroll = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        month: String(month),
        year: String(year),
        q: search,
        status: statusFilter,
      });
      const data = await apiGet(`payroll?${params}`);
      setPayrollData(data);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [month, year, search, statusFilter]);

  const fetchStructures = useCallback(async () => {
    try {
      const rows = await apiGet("salary-structures");
      setStructures(rows);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    fetchPayroll();
  }, [fetchPayroll]);

  useEffect(() => {
    fetchStructures();
  }, [fetchStructures]);

  function handleMonthChange(newMonth) {
    setMonth(newMonth);
    setWorkingDays(countWeekdays(year, newMonth));
  }

  function handleYearChange(newYear) {
    setYear(newYear);
    setWorkingDays(countWeekdays(newYear, month));
  }

  function showNotice(msg) {
    setNotice(msg);
    setTimeout(() => setNotice((curr) => (curr === msg ? "" : curr)), 5000);
  }

  async function handleGeneratePayroll(employeeId = null) {
    setGenerating(true);
    setError("");
    try {
      const res = await apiPost("payroll/generate", {
        month: Number(month),
        year: Number(year),
        working_days: Number(workingDays),
        standard_daily_hours: Number(dailyHours),
        employee_id: employeeId,
      });
      const skippedCount = res.skipped_no_structure?.length || 0;
      showNotice(
        `Generated payroll for ${res.generated} employee(s) for ${MONTHS[month - 1]} ${year}` +
          (skippedCount ? ` (${skippedCount} skipped without salary structure)` : ".")
      );
      await fetchPayroll();
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  }

  async function handlePaymentStatus(recordId, nextStatus) {
    setError("");
    try {
      await apiPut(`payroll/${recordId}/payment`, { payment_status: nextStatus });
      showNotice(`Payroll #${recordId} marked as ${nextStatus}.`);
      await fetchPayroll();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDeletePayroll(recordId) {
    setError("");
    try {
      await apiDelete(`payroll/${recordId}`);
      showNotice(`Deleted payroll record #${recordId}.`);
      await fetchPayroll();
    } catch (err) {
      setError(err.message);
    }
  }

  function openStructureModal(emp) {
    setEditingStruct(emp);
    setStructForm({
      basic_salary: String(emp.basic_salary ?? 0),
      hra: String(emp.hra ?? 0),
      allowances: String(emp.allowances ?? 0),
      deductions: String(emp.deductions ?? 0),
      overtime_rate: String(emp.overtime_rate ?? 0),
    });
    setError("");
  }

  async function handleSaveStructure(e) {
    e.preventDefault();
    if (!editingStruct) return;
    setStructBusy(true);
    setError("");
    try {
      await apiPost("salary-structures", {
        employee_id: editingStruct.employee_id,
        basic_salary: Number(structForm.basic_salary || 0),
        hra: Number(structForm.hra || 0),
        allowances: Number(structForm.allowances || 0),
        deductions: Number(structForm.deductions || 0),
        overtime_rate: Number(structForm.overtime_rate || 0),
      });
      showNotice(`Saved salary structure for ${editingStruct.name}.`);
      setEditingStruct(null);
      await Promise.all([fetchStructures(), fetchPayroll()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setStructBusy(false);
    }
  }

  function handleExportCsv() {
    const params = new URLSearchParams({ month: String(month), year: String(year) });
    window.open(apiUrl(`payroll/export?${params}`), "_blank");
  }

  const summary = payrollData?.summary;
  const records = payrollData?.records ?? [];
  const filteredStructures = structures.filter(
    (s) =>
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      s.employee_id.toLowerCase().includes(search.toLowerCase()) ||
      (s.department || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      {/* Header & Controls */}
      <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Attendance-Based Payroll
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Calculate monthly salaries automatically from check-in/out logs, working days, and overtime.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-2.5">
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
              Month
            </label>
            <select
              value={month}
              onChange={(e) => handleMonthChange(Number(e.target.value))}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 shadow-xs outline-none focus:border-blue-600"
            >
              {MONTHS.map((label, idx) => (
                <option key={label} value={idx + 1}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
              Year
            </label>
            <input
              type="number"
              min={2000}
              max={2100}
              value={year}
              onChange={(e) => handleYearChange(Number(e.target.value))}
              className="w-22 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 shadow-xs outline-none focus:border-blue-600"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
              Work Days
            </label>
            <input
              type="number"
              min={1}
              max={31}
              value={workingDays}
              onChange={(e) => setWorkingDays(Number(e.target.value))}
              className="w-20 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 shadow-xs outline-none focus:border-blue-600"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
              Shift Hrs
            </label>
            <input
              type="number"
              min={1}
              max={24}
              step={0.5}
              value={dailyHours}
              onChange={(e) => setDailyHours(Number(e.target.value))}
              className="w-20 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 shadow-xs outline-none focus:border-blue-600"
            />
          </div>

          <button
            type="button"
            disabled={generating}
            onClick={() => handleGeneratePayroll()}
            className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white shadow-xs transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {generating ? "Generating…" : "⚡ Generate Payroll"}
          </button>

          <button
            type="button"
            onClick={handleExportCsv}
            className="cursor-pointer rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white shadow-xs transition hover:bg-emerald-700"
          >
            ↓ Export CSV
          </button>
        </div>
      </div>

      {/* Alerts */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      )}

      {/* Missing Salary Structure Callout */}
      {(summary?.unconfigured_structures ?? 0) > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <span>
            <strong>{summary.unconfigured_structures}</strong> active employee(s) do not have a salary
            structure configured yet. Configure their base pay before generating payroll.
          </span>
          <button
            type="button"
            onClick={() => setActiveTab("structures")}
            className="cursor-pointer rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-amber-700"
          >
            Configure Structures →
          </button>
        </div>
      )}

      {/* Summary KPI Cards */}
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <KpiCard
          label="Total Net Payout"
          value={formatCurrency(summary?.total_net)}
          hint={`${MONTHS[month - 1]} ${year}`}
          accent="border-t-emerald-500"
          valueClass="text-emerald-700"
        />
        <KpiCard
          label="Total Gross"
          value={formatCurrency(summary?.total_gross)}
          hint="Prorated + overtime"
          accent="border-t-blue-600"
          valueClass="text-slate-900"
        />
        <KpiCard
          label="Total Deductions"
          value={formatCurrency(summary?.total_deductions)}
          hint="Fixed deductions"
          accent="border-t-rose-500"
          valueClass="text-rose-600"
        />
        <KpiCard
          label="Payroll Records"
          value={summary?.total_records ?? 0}
          hint={`${summary?.total_worked_hours ?? 0} total hrs logged`}
          accent="border-t-indigo-500"
          valueClass="text-indigo-700"
        />
        <KpiCard
          label="Payment Status"
          value={`${summary?.paid_count ?? 0} Paid`}
          hint={`${summary?.pending_count ?? 0} Pending • ${summary?.processed_count ?? 0} Processed`}
          accent="border-t-amber-500"
          valueClass="text-amber-600"
        />
      </section>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-200">
        <button
          type="button"
          onClick={() => setActiveTab("payroll")}
          className={`cursor-pointer border-b-2 px-4 py-2.5 text-sm font-semibold transition ${
            activeTab === "payroll"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          Monthly Payroll Register
          <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
            {records.length}
          </span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("structures")}
          className={`cursor-pointer border-b-2 px-4 py-2.5 text-sm font-semibold transition ${
            activeTab === "structures"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          Salary Structures
          <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
            {structures.length}
          </span>
        </button>
      </div>

      {/* TAB 1: Monthly Payroll Register */}
      {activeTab === "payroll" && (
        <section className="rounded-xl border border-slate-200 bg-white shadow-xs">
          <div className="flex flex-col justify-between gap-3 border-b border-slate-200 p-4 lg:flex-row lg:items-center">
            <div className="flex flex-wrap gap-1.5">
              {PAYMENT_FILTERS.map((st) => (
                <button
                  key={st}
                  type="button"
                  onClick={() => setStatusFilter(st)}
                  className={`cursor-pointer rounded-full px-3 py-1.5 text-xs font-semibold capitalize transition ${
                    statusFilter === st
                      ? "bg-blue-600 text-white shadow-xs"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>

            <input
              type="search"
              placeholder="Search employee name, ID, or department…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3.5 py-2 text-sm outline-none transition focus:border-blue-600 focus:ring-2 focus:ring-blue-600/15 lg:w-72"
            />
          </div>

          {loading && !payrollData ? (
            <div className="p-10 text-center text-sm text-slate-400">Loading payroll…</div>
          ) : records.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 p-12 text-center">
              <p className="text-sm font-medium text-slate-600">
                No payroll records generated for {MONTHS[month - 1]} {year} yet.
              </p>
              {structures.length === 0 ? (
                <Link
                  to="/employees"
                  className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700"
                >
                  + Enroll Employees First
                </Link>
              ) : (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setActiveTab("structures")}
                    className="cursor-pointer rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    1. Set Salary Structures
                  </button>
                  <button
                    type="button"
                    disabled={generating}
                    onClick={() => handleGeneratePayroll()}
                    className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700"
                  >
                    2. ⚡ Generate Payroll Now
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold tracking-wider text-slate-500 uppercase">
                    <th className="px-4 py-3">Employee</th>
                    <th className="px-4 py-3">Attendance</th>
                    <th className="px-4 py-3">Earnings</th>
                    <th className="px-4 py-3">Deductions</th>
                    <th className="px-4 py-3">Net Pay</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {records.map((rec) => (
                    <tr key={rec.id} className="transition hover:bg-slate-50/80">
                      <td className="px-4 py-3.5">
                        <div className="font-semibold text-slate-900">{rec.name}</div>
                        <div className="text-xs text-slate-500">
                          <span className="font-mono">{rec.employee_id}</span>
                          {rec.department ? ` • ${rec.department}` : ""}
                        </div>
                      </td>

                      <td className="px-4 py-3.5 text-xs">
                        <div className="font-semibold text-slate-800">
                          {rec.present_days}/{rec.working_days} days present
                        </div>
                        <div className="text-slate-500">
                          {rec.absent_days} absent • {rec.late_days} late • {rec.worked_hours}h
                          {rec.overtime_hours > 0 ? ` (+${rec.overtime_hours}h OT)` : ""}
                        </div>
                      </td>

                      <td className="px-4 py-3.5 text-xs">
                        <div className="text-sm font-semibold text-slate-900">
                          {formatCurrency(rec.gross_salary)}
                        </div>
                        <div className="text-slate-500">
                          Base {formatCurrency(rec.basic_salary)} + HRA {formatCurrency(rec.hra)} + Allow{" "}
                          {formatCurrency(rec.allowances)}
                          {rec.overtime_amount > 0 ? ` + OT ${formatCurrency(rec.overtime_amount)}` : ""}
                        </div>
                      </td>

                      <td className="px-4 py-3.5 font-medium text-rose-600">
                        -{formatCurrency(rec.deductions)}
                      </td>

                      <td className="px-4 py-3.5 text-base font-bold text-emerald-700">
                        {formatCurrency(rec.net_salary)}
                      </td>

                      <td className="px-4 py-3.5">
                        <PaymentBadge status={rec.payment_status} date={rec.payment_date} />
                      </td>

                      <td className="px-4 py-3.5">
                        <div className="flex flex-wrap justify-end gap-1.5">
                          {rec.payment_status === "Pending" && (
                            <button
                              type="button"
                              onClick={() => handlePaymentStatus(rec.id, "Processed")}
                              className="cursor-pointer rounded-md bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-blue-700"
                            >
                              Process
                            </button>
                          )}
                          {rec.payment_status !== "Paid" ? (
                            <button
                              type="button"
                              onClick={() => handlePaymentStatus(rec.id, "Paid")}
                              className="cursor-pointer rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-emerald-700"
                            >
                              Mark Paid
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handlePaymentStatus(rec.id, "Pending")}
                              className="cursor-pointer rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
                            >
                              Reopen
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => setPayslipRecord(rec)}
                            className="cursor-pointer rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
                          >
                            Payslip
                          </button>
                          <button
                            type="button"
                            disabled={generating}
                            onClick={() => handleGeneratePayroll(rec.employee_id)}
                            className="cursor-pointer rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                            title="Recalculate from latest attendance"
                          >
                            ↻
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeletePayroll(rec.id)}
                            className="cursor-pointer rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-100"
                            title="Delete payroll record"
                          >
                            ✕
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* TAB 2: Salary Structures */}
      {activeTab === "structures" && (
        <section className="rounded-xl border border-slate-200 bg-white shadow-xs">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-4">
            <div>
              <h2 className="text-base font-semibold text-slate-900">
                Employee Salary Structures
              </h2>
              <p className="text-xs text-slate-500">
                Monthly base figures are prorated by (Present Days / Working Days) when generating payroll.
              </p>
            </div>
            <input
              type="search"
              placeholder="Search employees…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3.5 py-2 text-sm outline-none focus:border-blue-600 sm:w-64"
            />
          </div>

          {filteredStructures.length === 0 ? (
            <div className="p-10 text-center text-sm text-slate-400">
              No active employees found. Enroll employees on the Employees page first.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold tracking-wider text-slate-500 uppercase">
                    <th className="px-4 py-3">Employee</th>
                    <th className="px-4 py-3">Basic</th>
                    <th className="px-4 py-3">HRA</th>
                    <th className="px-4 py-3">Allowances</th>
                    <th className="px-4 py-3">Deductions</th>
                    <th className="px-4 py-3">OT Rate / hr</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filteredStructures.map((emp) => (
                    <tr key={emp.employee_id} className="hover:bg-slate-50/70">
                      <td className="px-4 py-3.5">
                        <div className="font-semibold text-slate-900">{emp.name}</div>
                        <div className="text-xs text-slate-500">
                          <span className="font-mono">{emp.employee_id}</span>
                          {emp.department ? ` • ${emp.department}` : ""}
                        </div>
                      </td>
                      <td className="px-4 py-3.5">{formatCurrency(emp.basic_salary)}</td>
                      <td className="px-4 py-3.5">{formatCurrency(emp.hra)}</td>
                      <td className="px-4 py-3.5">{formatCurrency(emp.allowances)}</td>
                      <td className="px-4 py-3.5 text-rose-600">{formatCurrency(emp.deductions)}</td>
                      <td className="px-4 py-3.5">{formatCurrency(emp.overtime_rate)}</td>
                      <td className="px-4 py-3.5">
                        <span
                          className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                            emp.configured
                              ? "bg-emerald-100 text-emerald-800"
                              : "bg-amber-100 text-amber-800"
                          }`}
                        >
                          {emp.configured ? "Configured" : "Not Set"}
                        </span>
                      </td>
                      <td className="px-4 py-3.5 text-right">
                        <button
                          type="button"
                          onClick={() => openStructureModal(emp)}
                          className="cursor-pointer rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-blue-700"
                        >
                          {emp.configured ? "Edit" : "Configure"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* Salary Structure Modal */}
      {editingStruct && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-xs">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
            <div className="mb-4 flex items-start justify-between">
              <div>
                <h2 className="text-lg font-bold text-slate-900">Configure Salary Structure</h2>
                <p className="text-xs text-slate-500">
                  {editingStruct.name} ({editingStruct.employee_id})
                </p>
              </div>
              <button
                type="button"
                onClick={() => setEditingStruct(null)}
                className="cursor-pointer rounded-md px-2 py-1 text-sm text-slate-400 hover:bg-slate-100"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSaveStructure} className="space-y-3.5">
              <NumberInput
                label="Monthly Basic Salary (₹)"
                value={structForm.basic_salary}
                onChange={(v) => setStructForm((f) => ({ ...f, basic_salary: v }))}
              />
              <NumberInput
                label="Monthly HRA (₹)"
                value={structForm.hra}
                onChange={(v) => setStructForm((f) => ({ ...f, hra: v }))}
              />
              <NumberInput
                label="Monthly Allowances (₹)"
                value={structForm.allowances}
                onChange={(v) => setStructForm((f) => ({ ...f, allowances: v }))}
              />
              <NumberInput
                label="Fixed Monthly Deductions (₹)"
                value={structForm.deductions}
                onChange={(v) => setStructForm((f) => ({ ...f, deductions: v }))}
              />
              <NumberInput
                label="Overtime Hourly Rate (₹ / hr)"
                value={structForm.overtime_rate}
                onChange={(v) => setStructForm((f) => ({ ...f, overtime_rate: v }))}
              />

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  disabled={structBusy}
                  onClick={() => setEditingStruct(null)}
                  className="cursor-pointer rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={structBusy}
                  className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  {structBusy ? "Saving…" : "Save Structure"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Payslip Modal */}
      {payslipRecord && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-xs">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
            <div className="mb-4 flex items-start justify-between border-b border-slate-200 pb-4">
              <div>
                <h2 className="text-lg font-bold text-slate-900">
                  Payslip — {MONTHS[payslipRecord.pay_month - 1]} {payslipRecord.pay_year}
                </h2>
                <p className="text-xs text-slate-500">
                  {payslipRecord.name} ({payslipRecord.employee_id})
                  {payslipRecord.department ? ` • ${payslipRecord.department}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPayslipRecord(null)}
                className="cursor-pointer rounded-md px-2 py-1 text-sm text-slate-400 hover:bg-slate-100"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-4 gap-2 rounded-xl bg-slate-50 p-3 text-center text-xs">
                <div>
                  <div className="text-slate-500">Present</div>
                  <div className="font-bold text-slate-900">
                    {payslipRecord.present_days}/{payslipRecord.working_days}
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">Absent</div>
                  <div className="font-bold text-rose-600">{payslipRecord.absent_days}</div>
                </div>
                <div>
                  <div className="text-slate-500">Late</div>
                  <div className="font-bold text-amber-600">{payslipRecord.late_days}</div>
                </div>
                <div>
                  <div className="text-slate-500">Worked / OT</div>
                  <div className="font-bold text-slate-900">
                    {payslipRecord.worked_hours}h / {payslipRecord.overtime_hours}h
                  </div>
                </div>
              </div>

              <div className="divide-y divide-slate-100 rounded-xl border border-slate-200">
                <PayslipRow label="Earned Basic Salary" value={formatCurrency(payslipRecord.basic_salary)} />
                <PayslipRow label="Earned HRA" value={formatCurrency(payslipRecord.hra)} />
                <PayslipRow label="Earned Allowances" value={formatCurrency(payslipRecord.allowances)} />
                <PayslipRow label="Overtime Pay" value={formatCurrency(payslipRecord.overtime_amount)} />
                <PayslipRow label="Gross Salary" value={formatCurrency(payslipRecord.gross_salary)} bold />
                <PayslipRow
                  label="Deductions"
                  value={`-${formatCurrency(payslipRecord.deductions)}`}
                  valueClass="text-rose-600"
                />
                <PayslipRow
                  label="Net Payable"
                  value={formatCurrency(payslipRecord.net_salary)}
                  bold
                  valueClass="text-emerald-700 text-base"
                />
              </div>

              <div className="flex items-center justify-between pt-2">
                <PaymentBadge status={payslipRecord.payment_status} date={payslipRecord.payment_date} />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => window.print()}
                    className="cursor-pointer rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    Print
                  </button>
                  <button
                    type="button"
                    onClick={() => setPayslipRecord(null)}
                    className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700"
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function KpiCard({ label, value, hint, accent, valueClass }) {
  return (
    <div
      className={`flex flex-col rounded-xl border border-slate-200 border-t-4 ${accent} bg-white p-4 shadow-xs`}
    >
      <span className="text-xs font-semibold tracking-wide text-slate-500 uppercase">{label}</span>
      <span className={`mt-1.5 text-xl font-bold ${valueClass}`}>{value}</span>
      <span className="mt-1 text-xs text-slate-400">{hint}</span>
    </div>
  );
}

function PaymentBadge({ status, date }) {
  const styles =
    status === "Paid"
      ? "bg-emerald-100 text-emerald-800"
      : status === "Processed"
      ? "bg-blue-100 text-blue-800"
      : "bg-amber-100 text-amber-800";
  return (
    <div className="space-y-0.5">
      <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${styles}`}>
        {status}
      </span>
      {date && <div className="text-[11px] text-slate-400">Paid {date}</div>}
    </div>
  );
}

function NumberInput({ label, value, onChange }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold text-slate-700">{label}</label>
      <input
        type="number"
        min={0}
        step="0.01"
        required
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-600/15"
      />
    </div>
  );
}

function PayslipRow({ label, value, bold = false, valueClass = "text-slate-900" }) {
  return (
    <div className={`flex items-center justify-between px-4 py-2.5 ${bold ? "bg-slate-50 font-bold" : ""}`}>
      <span className="text-slate-600">{label}</span>
      <span className={valueClass}>{value}</span>
    </div>
  );
}
