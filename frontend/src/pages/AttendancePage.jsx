import { useState, useEffect, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { apiDelete, apiGet, apiPost } from "../api.js";
import { useWebSocket } from "../hooks/useWebSocket.js";

function shiftIsoDate(isoDate, deltaDays) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + deltaDays));
  return dt.toISOString().slice(0, 10);
}

function formatTime(isoString) {
  if (!isoString) return "—";
  return new Date(isoString).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function toInputTime(isoString) {
  if (!isoString) return "";
  const match = isoString.match(/T(\d{2}:\d{2})/);
  if (match) return match[1];
  const d = new Date(isoString);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

const STATUS_FILTERS = [
  { key: "all", label: "All" },
  { key: "present", label: "Present" },
  { key: "inside", label: "Inside" },
  { key: "checked_out", label: "Checked Out" },
  { key: "absent", label: "Absent" },
  { key: "late", label: "Late" },
];

export default function AttendancePage() {
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);

  // View tab: "daily" (Overview + Daily Management) or "logs" (Raw CCTV Event Logs)
  const [activeTab, setActiveTab] = useState("daily");

  // Daily Attendance & Management state
  const [selectedDate, setSelectedDate] = useState(today);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [dailyData, setDailyData] = useState(null);
  const [dailyLoading, setDailyLoading] = useState(false);

  // Raw Event Logs state
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(today);
  const [employeeId, setEmployeeId] = useState("");
  const [direction, setDirection] = useState("");
  const [events, setEvents] = useState([]);
  const [eventsLoading, setEventsLoading] = useState(false);

  // Feedback & modal state
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [actionBusyId, setActionBusyId] = useState("");
  const [editingRecord, setEditingRecord] = useState(null);
  const [editCheckIn, setEditCheckIn] = useState("");
  const [editCheckOut, setEditCheckOut] = useState("");
  const [editBusy, setEditBusy] = useState(false);

  const fetchDailyAttendance = useCallback(async () => {
    setDailyLoading(true);
    try {
      const params = new URLSearchParams({
        day: selectedDate,
        q: search,
        status: statusFilter,
      });
      const data = await apiGet(`attendance/daily?${params}`);
      setDailyData(data);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setDailyLoading(false);
    }
  }, [selectedDate, search, statusFilter]);

  const fetchEventLogs = useCallback(async () => {
    setEventsLoading(true);
    try {
      const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        employee_id: employeeId,
        direction,
      });
      const data = await apiGet(`attendance?${params}`);
      setEvents(data);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setEventsLoading(false);
    }
  }, [startDate, endDate, employeeId, direction]);

  useEffect(() => {
    fetchDailyAttendance();
  }, [fetchDailyAttendance]);

  useEffect(() => {
    if (activeTab === "logs") {
      fetchEventLogs();
    }
  }, [activeTab, fetchEventLogs]);

  // Live updates over WebSocket when CCTV records an event
  const handleWsMessage = useCallback(
    (msg) => {
      if (msg === "refresh") {
        fetchDailyAttendance();
        if (activeTab === "logs") fetchEventLogs();
      }
    },
    [fetchDailyAttendance, fetchEventLogs, activeTab]
  );
  useWebSocket(handleWsMessage, true);

  function showSuccess(msg) {
    setNotice(msg);
    setTimeout(() => setNotice((curr) => (curr === msg ? "" : curr)), 4000);
  }

  async function handleQuickMark(rec, dir) {
    setActionBusyId(`${rec.employee_id}:${dir}`);
    setError("");
    try {
      await apiPost("attendance/manual", {
        employee_id: rec.employee_id,
        day: selectedDate,
        direction: dir,
      });
      showSuccess(
        `Marked ${dir === "in" ? "Check-In" : "Check-Out"} for ${rec.name} (${rec.employee_id}).`
      );
      await fetchDailyAttendance();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionBusyId("");
    }
  }

  async function handleClearDay(rec, dir = "") {
    setActionBusyId(`${rec.employee_id}:clear`);
    setError("");
    try {
      const params = new URLSearchParams({
        employee_id: rec.employee_id,
        day: selectedDate,
        direction: dir,
      });
      await apiDelete(`attendance/manual?${params}`);
      showSuccess(`Cleared attendance for ${rec.name} on ${selectedDate}.`);
      await fetchDailyAttendance();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionBusyId("");
    }
  }

  function openEditModal(rec) {
    setEditingRecord(rec);
    setEditCheckIn(toInputTime(rec.check_in_at));
    setEditCheckOut(toInputTime(rec.check_out_at));
    setError("");
  }

  async function handleSaveEdit(e) {
    e.preventDefault();
    if (!editingRecord) return;
    setEditBusy(true);
    setError("");

    try {
      const empId = editingRecord.employee_id;

      if (editCheckIn) {
        await apiPost("attendance/manual", {
          employee_id: empId,
          day: selectedDate,
          direction: "in",
          time: editCheckIn,
        });
      } else if (editingRecord.check_in_at) {
        const params = new URLSearchParams({
          employee_id: empId,
          day: selectedDate,
          direction: "in",
        });
        await apiDelete(`attendance/manual?${params}`);
      }

      if (editCheckOut) {
        await apiPost("attendance/manual", {
          employee_id: empId,
          day: selectedDate,
          direction: "out",
          time: editCheckOut,
        });
      } else if (editingRecord.check_out_at) {
        const params = new URLSearchParams({
          employee_id: empId,
          day: selectedDate,
          direction: "out",
        });
        await apiDelete(`attendance/manual?${params}`);
      }

      showSuccess(`Updated attendance times for ${editingRecord.name}.`);
      setEditingRecord(null);
      await fetchDailyAttendance();
    } catch (err) {
      setError(err.message);
    } finally {
      setEditBusy(false);
    }
  }

  function handleExportCsv() {
    const params =
      activeTab === "daily"
        ? new URLSearchParams({ start_date: selectedDate, end_date: selectedDate })
        : new URLSearchParams({ start_date: startDate, end_date: endDate });
    window.open(`/api/reports/export?${params}`, "_blank");
  }

  const overview = dailyData?.overview;
  const records = dailyData?.records ?? [];
  const totalEmployees = overview?.total_employees ?? 0;
  const insidePct = totalEmployees ? ((overview?.inside ?? 0) / totalEmployees) * 100 : 0;
  const checkedOutPct = totalEmployees ? ((overview?.checked_out ?? 0) / totalEmployees) * 100 : 0;

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      {/* Header & Top Date Controls */}
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Attendance Overview &amp; Management
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Daily workforce summary, live check-in/out status, and manual attendance management.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex items-center rounded-lg border border-slate-200 bg-white p-1 shadow-xs">
            <button
              type="button"
              onClick={() => setSelectedDate((d) => shiftIsoDate(d, -1))}
              className="cursor-pointer rounded-md px-2.5 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-100"
              title="Previous day"
            >
              ← Prev
            </button>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => e.target.value && setSelectedDate(e.target.value)}
              className="border-x border-slate-200 px-2.5 py-1 text-sm font-medium text-slate-800 outline-none"
            />
            <button
              type="button"
              onClick={() => setSelectedDate((d) => shiftIsoDate(d, 1))}
              className="cursor-pointer rounded-md px-2.5 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-100"
              title="Next day"
            >
              Next →
            </button>
          </div>

          {selectedDate !== today && (
            <button
              type="button"
              onClick={() => setSelectedDate(today)}
              className="cursor-pointer rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-xs transition hover:bg-slate-100"
            >
              Today
            </button>
          )}

          <button
            type="button"
            onClick={() => {
              fetchDailyAttendance();
              if (activeTab === "logs") fetchEventLogs();
            }}
            className="cursor-pointer rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-xs transition hover:bg-slate-100"
          >
            ↻ Refresh
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

      {/* Attendance Overview KPI Cards */}
      <section aria-label="Daily Attendance Overview" className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
          <OverviewCard
            label="Total Active"
            value={overview?.total_employees ?? "—"}
            hint="Enrolled staff"
            accent="border-t-blue-600"
            valueClass="text-slate-900"
            active={statusFilter === "all"}
            onClick={() => {
              setActiveTab("daily");
              setStatusFilter("all");
            }}
          />
          <OverviewCard
            label="Present"
            value={overview?.present ?? "—"}
            hint={`${overview?.attendance_rate ?? 0}% rate`}
            accent="border-t-emerald-500"
            valueClass="text-emerald-700"
            active={statusFilter === "present"}
            onClick={() => {
              setActiveTab("daily");
              setStatusFilter("present");
            }}
          />
          <OverviewCard
            label="Absent"
            value={overview?.absent ?? "—"}
            hint="No check-in"
            accent="border-t-rose-500"
            valueClass="text-rose-600"
            active={statusFilter === "absent"}
            onClick={() => {
              setActiveTab("daily");
              setStatusFilter("absent");
            }}
          />
          <OverviewCard
            label="Currently Inside"
            value={overview?.inside ?? "—"}
            hint="Active shift"
            accent="border-t-indigo-500"
            valueClass="text-indigo-700"
            active={statusFilter === "inside"}
            onClick={() => {
              setActiveTab("daily");
              setStatusFilter("inside");
            }}
          />
          <OverviewCard
            label="Checked Out"
            value={overview?.checked_out ?? "—"}
            hint="Completed day"
            accent="border-t-sky-500"
            valueClass="text-sky-700"
            active={statusFilter === "checked_out"}
            onClick={() => {
              setActiveTab("daily");
              setStatusFilter("checked_out");
            }}
          />
          <OverviewCard
            label="Late Arrivals"
            value={overview?.late ?? "—"}
            hint={`After ${overview?.office_start ?? "09:30"}`}
            accent="border-t-amber-500"
            valueClass="text-amber-600"
            active={statusFilter === "late"}
            onClick={() => {
              setActiveTab("daily");
              setStatusFilter("late");
            }}
          />
        </div>

        {/* Attendance Rate Progress Bar */}
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs font-medium text-slate-600">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-slate-900">
                Daily Presence ({overview?.date ?? selectedDate})
              </span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                {overview?.timezone ?? "Asia/Kolkata"}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                Inside: {overview?.inside ?? 0}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-sky-500" />
                Checked Out: {overview?.checked_out ?? 0}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-slate-200" />
                Absent: {overview?.absent ?? 0}
              </span>
              <span className="font-semibold text-slate-800">
                Total Hours: {(overview?.total_hours ?? 0).toFixed(2)}h
              </span>
            </div>
          </div>
          <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="bg-emerald-500 transition-all duration-300"
              style={{ width: `${insidePct}%` }}
            />
            <div
              className="bg-sky-500 transition-all duration-300"
              style={{ width: `${checkedOutPct}%` }}
            />
          </div>
        </div>
      </section>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-200">
        <button
          type="button"
          onClick={() => setActiveTab("daily")}
          className={`cursor-pointer border-b-2 px-4 py-2.5 text-sm font-semibold transition ${
            activeTab === "daily"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          Daily Attendance Management
          <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
            {records.length}
          </span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("logs")}
          className={`cursor-pointer border-b-2 px-4 py-2.5 text-sm font-semibold transition ${
            activeTab === "logs"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          CCTV Event Logs (Range)
        </button>
      </div>

      {/* TAB 1: Daily Attendance Management */}
      {activeTab === "daily" && (
        <section className="rounded-xl border border-slate-200 bg-white shadow-xs">
          {/* Search + Status Pills */}
          <div className="flex flex-col justify-between gap-3 border-b border-slate-200 p-4 lg:flex-row lg:items-center">
            <div className="flex flex-wrap gap-1.5">
              {STATUS_FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => setStatusFilter(f.key)}
                  className={`cursor-pointer rounded-full px-3 py-1.5 text-xs font-semibold transition ${
                    statusFilter === f.key
                      ? "bg-blue-600 text-white shadow-xs"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  {f.label}
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

          {dailyLoading && !dailyData ? (
            <div className="p-10 text-center text-sm text-slate-400">
              Loading daily attendance…
            </div>
          ) : records.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 p-12 text-center">
              <p className="text-sm font-medium text-slate-600">
                {totalEmployees === 0
                  ? "No active employees enrolled yet."
                  : "No employees match the current search or filter."}
              </p>
              {totalEmployees === 0 ? (
                <Link
                  to="/employees"
                  className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-blue-700"
                >
                  + Enroll Employees
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setSearch("");
                    setStatusFilter("all");
                  }}
                  className="cursor-pointer rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
                >
                  Reset Filters
                </button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold tracking-wider text-slate-500 uppercase">
                    <th className="px-4 py-3">Employee</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Check In</th>
                    <th className="px-4 py-3">Check Out</th>
                    <th className="px-4 py-3">Hours</th>
                    <th className="px-4 py-3 text-right">Manage</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {records.map((rec) => {
                    const isBusy = actionBusyId.startsWith(`${rec.employee_id}:`);
                    return (
                      <tr key={rec.employee_id} className="transition hover:bg-slate-50/80">
                        <td className="px-4 py-3.5">
                          <div className="flex items-center gap-3">
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-bold text-slate-700">
                              {rec.name?.slice(0, 2).toUpperCase()}
                            </div>
                            <div>
                              <div className="font-semibold text-slate-900">{rec.name}</div>
                              <div className="text-xs text-slate-500">
                                <span className="font-mono">{rec.employee_id}</span>
                                {rec.department ? ` • ${rec.department}` : ""}
                                {rec.designation ? ` (${rec.designation})` : ""}
                              </div>
                            </div>
                          </div>
                        </td>

                        <td className="px-4 py-3.5">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <StatusBadge status={rec.attendance_status} />
                            {rec.is_late && (
                              <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                                Late
                              </span>
                            )}
                          </div>
                        </td>

                        <td className="px-4 py-3.5">
                          {rec.check_in_at ? (
                            <div className="space-y-0.5">
                              <div className="font-medium text-slate-800">
                                {formatTime(rec.check_in_at)}
                              </div>
                              <div className="flex items-center gap-2 text-xs">
                                <SourceChip source={rec.check_in_source} />
                                {rec.check_in_has_photo && rec.check_in_event_id && (
                                  <a
                                    href={`/api/events/${rec.check_in_event_id}/snapshot`}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="font-medium text-blue-600 hover:underline"
                                  >
                                    Photo
                                  </a>
                                )}
                              </div>
                            </div>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>

                        <td className="px-4 py-3.5">
                          {rec.check_out_at ? (
                            <div className="space-y-0.5">
                              <div className="font-medium text-slate-800">
                                {formatTime(rec.check_out_at)}
                              </div>
                              <div className="flex items-center gap-2 text-xs">
                                <SourceChip source={rec.check_out_source} />
                                {rec.check_out_has_photo && rec.check_out_event_id && (
                                  <a
                                    href={`/api/events/${rec.check_out_event_id}/snapshot`}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="font-medium text-blue-600 hover:underline"
                                  >
                                    Photo
                                  </a>
                                )}
                              </div>
                            </div>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>

                        <td className="px-4 py-3.5 font-medium text-slate-700">
                          {rec.working_hours !== null ? `${rec.working_hours.toFixed(2)} hrs` : "—"}
                        </td>

                        <td className="px-4 py-3.5">
                          <div className="flex flex-wrap justify-end gap-1.5">
                            {!rec.check_in_at && (
                              <button
                                type="button"
                                disabled={isBusy}
                                onClick={() => handleQuickMark(rec, "in")}
                                className="cursor-pointer rounded-md bg-emerald-600 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
                              >
                                Check In
                              </button>
                            )}
                            {rec.check_in_at && !rec.check_out_at && (
                              <button
                                type="button"
                                disabled={isBusy}
                                onClick={() => handleQuickMark(rec, "out")}
                                className="cursor-pointer rounded-md bg-sky-600 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-sky-700 disabled:opacity-50"
                              >
                                Check Out
                              </button>
                            )}
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => openEditModal(rec)}
                              className="cursor-pointer rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
                            >
                              Edit
                            </button>
                            {(rec.check_in_at || rec.check_out_at) && (
                              <button
                                type="button"
                                disabled={isBusy}
                                onClick={() => handleClearDay(rec)}
                                className="cursor-pointer rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-xs font-semibold text-rose-700 transition hover:bg-rose-100 disabled:opacity-50"
                              >
                                Clear
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* TAB 2: Raw CCTV Event Logs (Date Range) */}
      {activeTab === "logs" && (
        <div className="space-y-4">
          <section className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold tracking-wider text-slate-500 uppercase">
                From
              </label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-600"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold tracking-wider text-slate-500 uppercase">
                To
              </label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-600"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold tracking-wider text-slate-500 uppercase">
                Employee ID
              </label>
              <input
                type="text"
                placeholder="All employees"
                value={employeeId}
                onChange={(e) => setEmployeeId(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-600"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold tracking-wider text-slate-500 uppercase">
                Direction
              </label>
              <select
                value={direction}
                onChange={(e) => setDirection(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-600"
              >
                <option value="">All</option>
                <option value="in">Check In</option>
                <option value="out">Check Out</option>
              </select>
            </div>
            <button
              type="button"
              onClick={fetchEventLogs}
              className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700"
            >
              Filter
            </button>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
            {eventsLoading ? (
              <p className="py-8 text-center text-sm text-slate-400">Loading…</p>
            ) : events.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-400">
                No attendance events found for the selected period.
              </p>
            ) : (
              <>
                <p className="mb-3 text-xs font-medium text-slate-500">
                  {events.length} event record(s)
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold tracking-wider text-slate-500 uppercase">
                        <th className="px-3 py-2.5">Employee</th>
                        <th className="px-3 py-2.5">Date</th>
                        <th className="px-3 py-2.5">Time</th>
                        <th className="px-3 py-2.5">Direction</th>
                        <th className="px-3 py-2.5">Capture</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {events.map((r) => (
                        <tr key={r.id} className="hover:bg-slate-50/70">
                          <td className="px-3 py-3">
                            <span className="block font-semibold text-slate-900">{r.name}</span>
                            <span className="block font-mono text-xs text-slate-400">
                              {r.employee_id}
                            </span>
                          </td>
                          <td className="px-3 py-3 text-slate-700">{r.day}</td>
                          <td className="px-3 py-3 text-slate-700">
                            {new Date(r.occurred_at).toLocaleTimeString()}
                          </td>
                          <td className="px-3 py-3">
                            <span
                              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                                r.direction === "in"
                                  ? "bg-emerald-100 text-emerald-800"
                                  : "bg-amber-100 text-amber-800"
                              }`}
                            >
                              {r.direction === "in" ? "✓ In" : "← Out"}
                            </span>
                          </td>
                          <td className="px-3 py-3">
                            {r.image_url ? (
                              <a
                                href={`/api/events/${r.id}/snapshot`}
                                target="_blank"
                                rel="noreferrer"
                                className="font-medium text-blue-600 hover:underline"
                              >
                                View
                              </a>
                            ) : (
                              <span className="text-slate-400">Manual</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        </div>
      )}

      {/* Edit Attendance Modal */}
      {editingRecord && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-xs">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
            <div className="mb-4 flex items-start justify-between">
              <div>
                <h2 className="text-lg font-bold text-slate-900">
                  Manage Daily Attendance
                </h2>
                <p className="text-xs text-slate-500">
                  {editingRecord.name} ({editingRecord.employee_id}) • {selectedDate}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setEditingRecord(null)}
                className="cursor-pointer rounded-md px-2 py-1 text-sm text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSaveEdit} className="space-y-4">
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold tracking-wider text-slate-600 uppercase">
                    Check-In Time
                  </label>
                  {editCheckIn && (
                    <button
                      type="button"
                      onClick={() => setEditCheckIn("")}
                      className="cursor-pointer text-xs font-medium text-rose-600 hover:underline"
                    >
                      Clear
                    </button>
                  )}
                </div>
                <input
                  type="time"
                  value={editCheckIn}
                  onChange={(e) => setEditCheckIn(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-600/15"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold tracking-wider text-slate-600 uppercase">
                    Check-Out Time
                  </label>
                  {editCheckOut && (
                    <button
                      type="button"
                      onClick={() => setEditCheckOut("")}
                      className="cursor-pointer text-xs font-medium text-rose-600 hover:underline"
                    >
                      Clear
                    </button>
                  )}
                </div>
                <input
                  type="time"
                  value={editCheckOut}
                  onChange={(e) => setEditCheckOut(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-600/15"
                />
              </div>

              <p className="text-xs text-slate-500">
                Leave a field empty and save to clear that check-in or check-out event.
              </p>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setEditingRecord(null)}
                  disabled={editBusy}
                  className="cursor-pointer rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={editBusy}
                  className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  {editBusy ? "Saving…" : "Save Changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function OverviewCard({ label, value, hint, accent, valueClass, active, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex cursor-pointer flex-col items-start rounded-xl border border-slate-200 border-t-4 ${accent} bg-white p-4 text-left shadow-xs transition hover:shadow-sm ${
        active ? "ring-2 ring-blue-500/40" : ""
      }`}
    >
      <span className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
        {label}
      </span>
      <span className={`mt-1.5 text-2xl font-bold ${valueClass}`}>{value}</span>
      <span className="mt-1 text-xs text-slate-400">{hint}</span>
    </button>
  );
}

function StatusBadge({ status }) {
  if (status === "Inside") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        Inside
      </span>
    );
  }
  if (status === "Checked Out") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-semibold text-sky-800">
        Checked Out
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-semibold text-rose-700">
      Absent
    </span>
  );
}

function SourceChip({ source }) {
  if (!source) return null;
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
        source === "CCTV"
          ? "bg-blue-50 text-blue-700"
          : "bg-slate-100 text-slate-600"
      }`}
    >
      {source}
    </span>
  );
}
