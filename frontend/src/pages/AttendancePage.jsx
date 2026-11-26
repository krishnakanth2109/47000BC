import { useState, useEffect, useCallback } from "react";
import { apiGet } from "../api.js";
import styles from "./AttendancePage.module.css";

export default function AttendancePage() {
  const today = new Date().toISOString().slice(0, 10);
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(today);
  const [employeeId, setEmployeeId] = useState("");
  const [direction, setDirection] = useState("");
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fetchAttendance = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        employee_id: employeeId,
        direction,
      });
      const data = await apiGet(`attendance?${params}`);
      setRecords(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [startDate, endDate, employeeId, direction]);

  useEffect(() => { fetchAttendance(); }, [fetchAttendance]);

  function handleExport() {
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    window.open(`/api/reports/export?${params}`, "_blank");
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Attendance Records</h1>
        <button className={styles.exportBtn} onClick={handleExport}>
          ↓ Export CSV
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {/* Filters */}
      <section className={styles.filters}>
        <div className={styles.filterField}>
          <label>From</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </div>
        <div className={styles.filterField}>
          <label>To</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </div>
        <div className={styles.filterField}>
          <label>Employee ID</label>
          <input
            type="text"
            placeholder="All employees"
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
          />
        </div>
        <div className={styles.filterField}>
          <label>Direction</label>
          <select value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="">All</option>
            <option value="in">Check In</option>
            <option value="out">Check Out</option>
          </select>
        </div>
        <button className={styles.filterBtn} onClick={fetchAttendance}>
          Filter
        </button>
      </section>

      {/* Results */}
      <section className={styles.card}>
        {loading ? (
          <p className={styles.empty}>Loading…</p>
        ) : records.length === 0 ? (
          <p className={styles.empty}>No attendance records found for the selected period.</p>
        ) : (
          <>
            <p className={styles.resultCount}>{records.length} record(s)</p>
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Employee</th>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Direction</th>
                    <th>Capture</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <span className={styles.empName}>{r.name}</span>
                        <span className={styles.empId}>{r.employee_id}</span>
                      </td>
                      <td>{r.day}</td>
                      <td>{new Date(r.occurred_at).toLocaleTimeString()}</td>
                      <td>
                        <span className={`${styles.badge} ${r.direction === "in" ? styles.badgeIn : styles.badgeOut}`}>
                          {r.direction === "in" ? "✓ In" : "← Out"}
                        </span>
                      </td>
                      <td>
                        {r.image_url ? (
                          <a
                            href={`/api/events/${r.id}/snapshot`}
                            target="_blank"
                            rel="noreferrer"
                            className={styles.viewLink}
                          >
                            View
                          </a>
                        ) : "—"}
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
  );
}
