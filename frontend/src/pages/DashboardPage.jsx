import { useState, useCallback, useEffect } from "react";
import { apiGet, apiPost } from "../api.js";
import { useWebSocket } from "../hooks/useWebSocket.js";
import styles from "./DashboardPage.module.css";

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

  // Initial load
  useEffect(() => {
    fetchDashboard();
    // Poll every 30 seconds as fallback
    const timer = setInterval(fetchDashboard, 30_000);
    return () => clearInterval(timer);
  }, [fetchDashboard]);

  // WebSocket — push refresh on attendance event
  const handleWsMessage = useCallback(
    (msg) => { if (msg === "refresh") fetchDashboard(); },
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
    <div className={styles.page}>
      <h1 className={styles.heading}>Dashboard</h1>

      {error && <div className={styles.error}>{error}</div>}

      {/* Stats row */}
      <div className={styles.statsRow}>
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
      <section className={styles.card}>
        <h2>Camera Control</h2>
        <p className={styles.cameraStatus}>{data?.camera ?? "Unknown"}</p>
        <div className={styles.btnGroup}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            disabled={cameraLoading}
            onClick={() => handleCamera("start")}
          >
            ▶ Start Camera
          </button>
          <button
            className={`${styles.btn} ${styles.btnDanger}`}
            disabled={cameraLoading}
            onClick={() => handleCamera("stop")}
          >
            ■ Stop Camera
          </button>
        </div>
      </section>

      {/* Recent attendance events */}
      <section className={styles.card}>
        <h2>Recent Attendance Events</h2>
        {events.length === 0 ? (
          <p className={styles.empty}>No attendance recorded yet today.</p>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>Time</th>
                  <th>Direction</th>
                  <th>Capture</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => (
                  <tr key={ev.id}>
                    <td>
                      <span className={styles.empName}>{ev.name}</span>
                      <span className={styles.empId}>{ev.employee_id}</span>
                    </td>
                    <td>{new Date(ev.occurred_at).toLocaleString()}</td>
                    <td>
                      <span className={`${styles.badge} ${ev.direction === "in" ? styles.badgeIn : styles.badgeOut}`}>
                        {ev.direction === "in" ? "✓ Check In" : "← Check Out"}
                      </span>
                    </td>
                    <td>
                      {ev.image_url ? (
                        <a
                          href={`/api/events/${ev.id}/snapshot`}
                          target="_blank"
                          rel="noreferrer"
                          className={styles.viewLink}
                        >
                          View Photo
                        </a>
                      ) : (
                        <span className={styles.noPhoto}>—</span>
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

function StatCard({ label, value, color }) {
  return (
    <div className={`${styles.statCard} ${styles[`stat_${color}`]}`}>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  );
}
