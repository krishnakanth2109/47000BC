import { useState, useRef } from "react";
import { apiFetch } from "../api.js";
import styles from "./EmployeesPage.module.css";
import { useEffect } from "react";
import { apiGet, apiPost } from "../api.js";

export default function EmployeesPage() {
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [formBusy, setFormBusy] = useState(false);
  const [search, setSearch] = useState("");
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [capturedPhotos, setCapturedPhotos] = useState([]);

  async function loadEmployees() {
    setLoading(true);
    try {
      const rows = await apiGet("employees?status=all");
      setEmployees(rows);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadEmployees();
  }, []);

  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
    } catch {
      setError("Camera access denied. Please allow camera permissions.");
    }
  }

  function stopCamera() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  }

  function capturePhoto() {
    if (!videoRef.current) return;
    const canvas = document.createElement("canvas");
    canvas.width = videoRef.current.videoWidth;
    canvas.height = videoRef.current.videoHeight;
    canvas.getContext("2d").drawImage(videoRef.current, 0, 0);
    setCapturedPhotos((prev) => [...prev, canvas.toDataURL("image/jpeg")]);
  }

  async function handleEnroll(e) {
    e.preventDefault();
    if (capturedPhotos.length < 3) {
      setError("Capture at least 3 face photos before registering.");
      return;
    }

    setFormBusy(true);
    setError("");

    try {
      const form = e.target;
      const fd = new FormData();
      fd.append("id", form.employee_id.value.trim());
      fd.append("name", form.name.value.trim());
      fd.append("department", form.department.value.trim());
      fd.append("designation", form.designation.value.trim());
      fd.append("phone", form.phone.value.trim());
      fd.append("email", form.email.value.trim());
      fd.append("joining_date", form.joining_date.value);

      // Convert base64 data URLs to Blob files
      for (let i = 0; i < capturedPhotos.length; i++) {
        const blob = await (await fetch(capturedPhotos[i])).blob();
        fd.append("photos", blob, `capture_${i}.jpg`);
      }

      await apiFetch("employees", { method: "POST", body: fd });
      setCapturedPhotos([]);
      stopCamera();
      setShowForm(false);
      form.reset();
      await loadEmployees();
    } catch (err) {
      setError(err.message);
    } finally {
      setFormBusy(false);
    }
  }

  async function toggleStatus(id, currentStatus) {
    try {
      const fd = new FormData();
      fd.append("status", currentStatus === "Active" ? "Inactive" : "Active");
      await apiFetch(`employees/${id}/status`, { method: "PUT", body: fd });
      await loadEmployees();
    } catch (err) {
      setError(err.message);
    }
  }

  const filtered = employees.filter(
    (e) =>
      e.name.toLowerCase().includes(search.toLowerCase()) ||
      e.id.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Employees</h1>
        <button className={styles.btnPrimary} onClick={() => { setShowForm((f) => !f); startCamera(); }}>
          {showForm ? "Cancel" : "+ Register Employee"}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {/* Registration Form */}
      {showForm && (
        <section className={styles.card}>
          <h2>Register New Employee</h2>
          <div className={styles.cameraSection}>
            <video
              ref={videoRef}
              autoPlay
              playsInline
              className={styles.videoFeed}
            />
            <div className={styles.cameraControls}>
              <button className={styles.btn} onClick={capturePhoto}>
                📷 Capture ({capturedPhotos.length}/10)
              </button>
              {capturedPhotos.length > 0 && (
                <button className={styles.btnDanger} onClick={() => setCapturedPhotos([])}>
                  Clear Photos
                </button>
              )}
            </div>
            <div className={styles.thumbsRow}>
              {capturedPhotos.map((src, i) => (
                <img key={i} src={src} alt={`capture ${i + 1}`} className={styles.thumb} />
              ))}
            </div>
          </div>

          <form onSubmit={handleEnroll} className={styles.form}>
            <div className={styles.formGrid}>
              <Field label="Employee ID *" name="employee_id" required />
              <Field label="Full Name *" name="name" required />
              <Field label="Department" name="department" />
              <Field label="Designation" name="designation" />
              <Field label="Phone" name="phone" type="tel" />
              <Field label="Email" name="email" type="email" />
              <Field label="Joining Date" name="joining_date" type="date" />
            </div>
            <div className={styles.formActions}>
              <button type="submit" className={styles.btnPrimary} disabled={formBusy}>
                {formBusy ? "Registering…" : "Register Employee"}
              </button>
            </div>
          </form>
        </section>
      )}

      {/* Search + Table */}
      <section className={styles.card}>
        <div className={styles.tableHeader}>
          <h2>Employee Directory</h2>
          <input
            type="search"
            placeholder="Search by name or ID…"
            className={styles.searchInput}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {loading ? (
          <p className={styles.empty}>Loading…</p>
        ) : filtered.length === 0 ? (
          <p className={styles.empty}>No employees found.</p>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>ID</th>
                  <th>Department</th>
                  <th>Designation</th>
                  <th>Phone</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((emp) => (
                  <tr key={emp.id}>
                    <td>
                      {emp.photo_url ? (
                        <div className={styles.nameCell}>
                          <img src={emp.photo_url} alt={emp.name} className={styles.avatar} />
                          {emp.name}
                        </div>
                      ) : emp.name}
                    </td>
                    <td className={styles.monospace}>{emp.id}</td>
                    <td>{emp.department || "—"}</td>
                    <td>{emp.designation || "—"}</td>
                    <td>{emp.phone || "—"}</td>
                    <td>
                      <span className={`${styles.badge} ${emp.status === "Active" ? styles.badgeActive : styles.badgeInactive}`}>
                        {emp.status}
                      </span>
                    </td>
                    <td>
                      <button
                        className={styles.actionBtn}
                        onClick={() => toggleStatus(emp.id, emp.status)}
                      >
                        {emp.status === "Active" ? "Deactivate" : "Activate"}
                      </button>
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

function Field({ label, name, type = "text", required = false }) {
  return (
    <div className={styles.field}>
      <label htmlFor={name}>{label}</label>
      <input id={name} name={name} type={type} required={required} />
    </div>
  );
}
