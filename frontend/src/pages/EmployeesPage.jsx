import { useState, useRef, useEffect } from "react";
import { apiFetch, apiGet } from "../api.js";

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
    return () => stopCamera();
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

  function toggleRegistrationForm() {
    setShowForm((prev) => {
      const next = !prev;
      if (next) {
        startCamera();
      } else {
        stopCamera();
      }
      return next;
    });
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
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Employees</h1>
        <button
          onClick={toggleRegistrationForm}
          className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700"
        >
          {showForm ? "Cancel" : "+ Register Employee"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Registration Form */}
      {showForm && (
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
          <h2 className="mb-4 text-lg font-semibold text-slate-900">Register New Employee</h2>

          <div className="mb-5">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              className="block w-full max-w-md rounded-lg bg-black"
            />
            <div className="my-3 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={capturePhoto}
                className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700"
              >
                📷 Capture ({capturedPhotos.length}/10)
              </button>
              {capturedPhotos.length > 0 && (
                <button
                  type="button"
                  onClick={() => setCapturedPhotos([])}
                  className="cursor-pointer rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700"
                >
                  Clear Photos
                </button>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {capturedPhotos.map((src, i) => (
                <img
                  key={i}
                  src={src}
                  alt={`capture ${i + 1}`}
                  className="h-15 w-15 rounded-md border-2 border-blue-600 object-cover"
                />
              ))}
            </div>
          </div>

          <form onSubmit={handleEnroll} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Employee ID *" name="employee_id" required />
              <Field label="Full Name *" name="name" required />
              <Field label="Department" name="department" />
              <Field label="Designation" name="designation" />
              <Field label="Phone" name="phone" type="tel" />
              <Field label="Email" name="email" type="email" />
              <Field label="Joining Date" name="joining_date" type="date" />
            </div>
            <div>
              <button
                type="submit"
                disabled={formBusy}
                className="cursor-pointer rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {formBusy ? "Registering…" : "Register Employee"}
              </button>
            </div>
          </form>
        </section>
      )}

      {/* Search + Table */}
      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-slate-900">Employee Directory</h2>
          <input
            type="search"
            placeholder="Search by name or ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full max-w-xs rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-blue-600 focus:ring-2 focus:ring-blue-600/15"
          />
        </div>

        {loading ? (
          <p className="py-8 text-center text-sm text-slate-400">Loading…</p>
        ) : filtered.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-400">No employees found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold tracking-wider text-slate-500 uppercase">
                  <th className="px-3 py-2.5">Name</th>
                  <th className="px-3 py-2.5">ID</th>
                  <th className="px-3 py-2.5">Department</th>
                  <th className="px-3 py-2.5">Designation</th>
                  <th className="px-3 py-2.5">Phone</th>
                  <th className="px-3 py-2.5">Status</th>
                  <th className="px-3 py-2.5">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((emp) => (
                  <tr key={emp.id} className="hover:bg-slate-50/70">
                    <td className="px-3 py-3 font-medium text-slate-900">
                      {emp.photo_url ? (
                        <div className="flex items-center gap-2.5">
                          <img
                            src={emp.photo_url}
                            alt={emp.name}
                            className="h-8 w-8 rounded-full object-cover"
                          />
                          <span>{emp.name}</span>
                        </div>
                      ) : (
                        emp.name
                      )}
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-slate-600">{emp.id}</td>
                    <td className="px-3 py-3 text-slate-600">{emp.department || "—"}</td>
                    <td className="px-3 py-3 text-slate-600">{emp.designation || "—"}</td>
                    <td className="px-3 py-3 text-slate-600">{emp.phone || "—"}</td>
                    <td className="px-3 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                          emp.status === "Active"
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {emp.status}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <button
                        onClick={() => toggleStatus(emp.id, emp.status)}
                        className="cursor-pointer rounded-md border border-slate-300 bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
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
    <div className="flex flex-col gap-1.5">
      <label htmlFor={name} className="text-sm font-semibold text-slate-700">
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        required={required}
        className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-blue-600 focus:ring-2 focus:ring-blue-600/15"
      />
    </div>
  );
}
