import { useState, useCallback, useEffect } from "react";
import { apiGet, apiPost, apiUrl } from "../api.js";
import { useWebSocket } from "../hooks/useWebSocket.js";

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [cameraLoading, setCameraLoading] = useState(false);
  const [error, setError] = useState("");

  const fetchDashboard = useCallback(async () => {
    try {
      const result = await apiGet("dashboard");
      setData(result);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
    const timer = setInterval(fetchDashboard, 30_000);
    return () => clearInterval(timer);
  }, [fetchDashboard]);

  const handleWsMessage = useCallback(
    (msg) => {
      if (msg === "refresh") fetchDashboard();
    },
    [fetchDashboard]
  );
  const { connected: wsConnected } = useWebSocket(handleWsMessage, true);

  async function handleCamera(action) {
    setCameraLoading(true);
    try {
      await apiPost(`camera/${action}`);
      await fetchDashboard();
    } catch (err) {
      setError(err.message);
    } finally {
      setCameraLoading(false);
    }
  }

  const stats = data?.stats;
  const events = data?.events ?? [];

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <h1 className="text-2xl font-bold tracking-tight text-slate-900">Dashboard</h1>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Present Today" value={stats?.present_today ?? "—"} color="green" />
        <StatCard label="Total Active Employees" value={stats?.total_active ?? "—"} color="blue" />
        <StatCard
          label="Camera"
          value={data?.camera ?? "Loading…"}
          color={data?.camera === "Live" ? "green" : "orange"}
        />
        <StatCard
          label="WebSocket"
          value={wsConnected ? "Connected" : "Reconnecting…"}
          color={wsConnected ? "green" : "red"}
        />
      </div>

      {/* Camera controls */}
      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <h2 className="mb-2 text-lg font-semibold text-slate-900">Camera Control</h2>
        <p className="mb-4 text-sm text-slate-600">{data?.camera ?? "Unknown"}</p>
        <div className="flex flex-wrap gap-3">
          <button
            className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={cameraLoading}
            onClick={() => handleCamera("start")}
          >
            ▶ Start Camera
          </button>
          <button
            className="cursor-pointer rounded-lg bg-red-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={cameraLoading}
            onClick={() => handleCamera("stop")}
          >
            ■ Stop Camera
          </button>
        </div>
      </section>

      {/* Recent attendance events */}
      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <h2 className="mb-4 text-lg font-semibold text-slate-900">Recent Attendance Events</h2>
        {events.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-400">
            No attendance recorded yet today.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold tracking-wider text-slate-500 uppercase">
                  <th className="px-3 py-2.5">Employee</th>
                  <th className="px-3 py-2.5">Time</th>
                  <th className="px-3 py-2.5">Direction</th>
                  <th className="px-3 py-2.5">Capture</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {events.map((ev) => (
                  <tr key={ev.id} className="hover:bg-slate-50/70">
                    <td className="px-3 py-3">
                      <span className="block font-semibold text-slate-900">{ev.name}</span>
                      <span className="block text-xs text-slate-400">{ev.employee_id}</span>
                    </td>
                    <td className="px-3 py-3 text-slate-700">
                      {new Date(ev.occurred_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                          ev.direction === "in"
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {ev.direction === "in" ? "✓ Check In" : "← Check Out"}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      {ev.image_url ? (
                        <a
                          href={apiUrl(`events/${ev.id}/snapshot`)}
                          target="_blank"
                          rel="noreferrer"
                          className="font-medium text-blue-600 hover:underline"
                        >
                          View Photo
                        </a>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

const STAT_BORDER = {
  green: "border-l-emerald-500",
  blue: "border-l-blue-600",
  orange: "border-l-amber-500",
  red: "border-l-red-500",
};

function StatCard({ label, value, color }) {
  return (
    <div
      className={`flex flex-col gap-1 rounded-xl border border-slate-200 border-l-4 ${
        STAT_BORDER[color] || "border-l-blue-600"
      } bg-white p-5 shadow-xs`}
    >
      <span className="text-2xl font-bold text-slate-900">{value}</span>
      <span className="text-xs font-medium text-slate-500">{label}</span>
    </div>
  );
}
