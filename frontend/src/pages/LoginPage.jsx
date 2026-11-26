import { useState } from "react";
import { useAuth } from "../contexts/AuthContext.jsx";

const ILLUSTRATION_URL =
  "https://static.vecteezy.com/system/resources/previews/003/689/228/non_2x/online-registration-or-sign-up-login-for-account-on-smartphone-app-user-interface-with-secure-password-mobile-application-for-ui-web-banner-access-cartoon-people-illustration-vector.jpg";

export default function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [imgFailed, setImgFailed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isRegister = mode === "register";

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (isRegister && password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setBusy(true);
    try {
      if (isRegister) {
        await register(email, password);
      } else {
        await login(email, password);
      }
    } catch (err) {
      setError(err.message || (isRegister ? "Registration failed" : "Sign in failed"));
    } finally {
      setBusy(false);
    }
  }

  function switchMode(nextMode) {
    if (busy || nextMode === mode) return;
    setMode(nextMode);
    setError("");
    setConfirmPassword("");
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-950 p-4 sm:p-6 lg:p-8">
      {/* Ambient background glow */}
      <div className="pointer-events-none absolute -top-36 -left-36 h-96 w-96 rounded-full bg-blue-600/25 blur-3xl" />
      <div className="pointer-events-none absolute -right-36 -bottom-36 h-96 w-96 rounded-full bg-indigo-500/20 blur-3xl" />

      <div className="relative z-10 grid w-full max-w-5xl overflow-hidden rounded-3xl bg-white shadow-2xl ring-1 ring-white/10 lg:grid-cols-2">
        {/* Left Visual Showcase Panel */}
        <div className="flex flex-col justify-between bg-gradient-to-br from-blue-50 via-indigo-50 to-sky-100 p-7 sm:p-10">
          {/* Brand Header */}
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-600 shadow-md shadow-blue-600/25">
              <svg viewBox="0 0 48 48" fill="none" className="h-7 w-7">
                <path d="M12 18a6 6 0 1 1 12 0 6 6 0 0 1-12 0z" fill="white" />
                <path d="M34 16l8-4v16l-8-4V16z" fill="white" />
                <path
                  d="M10 34c0-4.4 3.6-8 8-8h12c4.4 0 8 3.6 8 8"
                  stroke="white"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <div>
              <div className="text-lg font-bold tracking-tight text-slate-900">
                HRNEXA Attendance
              </div>
              <div className="text-xs font-medium text-blue-700">
                Smart Workforce &amp; Payroll Suite
              </div>
            </div>
          </div>

          {/* Illustration Card */}
          <div className="my-6 overflow-hidden rounded-2xl bg-white p-3 shadow-md shadow-blue-900/5 ring-1 ring-blue-100">
            {!imgFailed ? (
              <img
                src={ILLUSTRATION_URL}
                alt="Secure account login and registration illustration"
                referrerPolicy="no-referrer"
                onError={() => setImgFailed(true)}
                className="h-60 w-full rounded-xl object-contain sm:h-72"
              />
            ) : (
              <div className="flex h-60 w-full flex-col items-center justify-center rounded-xl bg-gradient-to-br from-blue-50 to-indigo-100 p-6 text-center sm:h-72">
                <svg viewBox="0 0 120 120" fill="none" className="mb-3 h-28 w-28">
                  <rect x="28" y="14" width="64" height="92" rx="12" fill="#1e293b" />
                  <rect x="34" y="22" width="52" height="76" rx="8" fill="#eff6ff" />
                  <circle cx="60" cy="46" r="11" fill="#2563eb" />
                  <path d="M44 74c0-7.2 7.2-12 16-12s16 4.8 16 12" fill="#60a5fa" />
                  <rect x="46" y="82" width="28" height="6" rx="3" fill="#2563eb" />
                </svg>
                <p className="text-xs font-semibold text-slate-600">
                  Protected Admin Portal
                </p>
              </div>
            )}
          </div>

          {/* Feature Highlights */}
          <div className="space-y-2.5">
            <h2 className="text-base font-bold text-slate-900">
              Unified Attendance, Live CCTV &amp; Payroll
            </h2>
            <div className="flex flex-wrap gap-2">
              <FeatureBadge text="LBPH Face Recognition" />
              <FeatureBadge text="Daily Presence Overview" />
              <FeatureBadge text="Automated Payroll" />
            </div>
          </div>
        </div>

        {/* Right Authentication Form Panel */}
        <div className="flex flex-col justify-center bg-white p-7 sm:p-10 lg:p-12">
          {/* Segmented Mode Switcher */}
          <div className="mb-7 inline-grid grid-cols-2 rounded-xl bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => switchMode("login")}
              disabled={busy}
              className={`cursor-pointer rounded-lg py-2 text-xs font-semibold transition ${
                !isRegister
                  ? "bg-white text-slate-900 shadow-xs"
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => switchMode("register")}
              disabled={busy}
              className={`cursor-pointer rounded-lg py-2 text-xs font-semibold transition ${
                isRegister
                  ? "bg-white text-slate-900 shadow-xs"
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              Create Account
            </button>
          </div>

          <div className="mb-6">
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">
              {isRegister ? "Create admin account" : "Welcome back"}
            </h1>
            <p className="mt-1.5 text-sm text-slate-500">
              {isRegister
                ? "Register your administrator email and password to manage attendance."
                : "Sign in with your administrator credentials to open the dashboard."}
            </p>
          </div>

          {error && (
            <div
              role="alert"
              className="mb-5 flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" className="mt-0.5 h-4 w-4 shrink-0">
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zm-.75-11.25a.75.75 0 011.5 0v4.5a.75.75 0 01-1.5 0v-4.5zm.75 7.5a.875.875 0 100-1.75.875.875 0 000 1.75z"
                  clipRule="evenodd"
                />
              </svg>
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email */}
            <div className="space-y-1.5">
              <label htmlFor="email" className="block text-xs font-semibold tracking-wide text-slate-700 uppercase">
                Email Address
              </label>
              <div className="relative">
                <span className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-slate-400">
                  <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                    <path d="M3 4a2 2 0 00-2 2v1.161l8.441 4.221a1.25 1.25 0 001.118 0L19 7.162V6a2 2 0 00-2-2H3z" />
                    <path d="M19 8.839l-7.77 3.885a2.75 2.75 0 01-2.46 0L1 8.839V14a2 2 0 002 2h14a2 2 0 002-2V8.839z" />
                  </svg>
                </span>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@47000bc.com"
                  disabled={busy}
                  className="w-full rounded-xl border border-slate-300 bg-slate-50/50 py-2.5 pr-3.5 pl-10 text-sm text-slate-900 outline-none transition focus:border-blue-600 focus:bg-white focus:ring-4 focus:ring-blue-600/15 disabled:cursor-not-allowed disabled:opacity-60"
                />
              </div>
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label htmlFor="password" className="block text-xs font-semibold tracking-wide text-slate-700 uppercase">
                Password
              </label>
              <div className="relative">
                <span className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-slate-400">
                  <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                    <path
                      fillRule="evenodd"
                      d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z"
                      clipRule="evenodd"
                    />
                  </svg>
                </span>
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete={isRegister ? "new-password" : "current-password"}
                  required
                  minLength={6}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  disabled={busy}
                  className="w-full rounded-xl border border-slate-300 bg-slate-50/50 py-2.5 pr-16 pl-10 text-sm text-slate-900 outline-none transition focus:border-blue-600 focus:bg-white focus:ring-4 focus:ring-blue-600/15 disabled:cursor-not-allowed disabled:opacity-60"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  className="absolute inset-y-0 right-3 flex cursor-pointer items-center text-xs font-semibold text-slate-500 hover:text-slate-800"
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
            </div>

            {/* Confirm Password */}
            {isRegister && (
              <div className="space-y-1.5">
                <label
                  htmlFor="confirmPassword"
                  className="block text-xs font-semibold tracking-wide text-slate-700 uppercase"
                >
                  Confirm Password
                </label>
                <div className="relative">
                  <span className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-slate-400">
                    <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                      <path
                        fillRule="evenodd"
                        d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z"
                        clipRule="evenodd"
                      />
                    </svg>
                  </span>
                  <input
                    id="confirmPassword"
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    required
                    minLength={6}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="••••••••"
                    disabled={busy}
                    className="w-full rounded-xl border border-slate-300 bg-slate-50/50 py-2.5 pr-3.5 pl-10 text-sm text-slate-900 outline-none transition focus:border-blue-600 focus:bg-white focus:ring-4 focus:ring-blue-600/15 disabled:cursor-not-allowed disabled:opacity-60"
                  />
                </div>
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-md shadow-blue-600/20 transition hover:bg-blue-700 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy && (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              )}
              <span>
                {busy
                  ? isRegister
                    ? "Creating account…"
                    : "Signing in…"
                  : isRegister
                  ? "Register & Sign In"
                  : "Sign In to Dashboard"}
              </span>
            </button>
          </form>

          {/* Footer */}
          <div className="mt-6 flex items-center justify-center gap-2 border-t border-slate-100 pt-5 text-xs text-slate-400">
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5 text-emerald-500">
              <path
                fillRule="evenodd"
                d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z"
                clipRule="evenodd"
              />
            </svg>
            <span>Protected by Firebase Auth &amp; HttpOnly Session Cookies</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function FeatureBadge({ text }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-white/85 px-3 py-1 text-xs font-semibold text-slate-700 shadow-xs ring-1 ring-blue-200/70">
      <span className="h-1.5 w-1.5 rounded-full bg-blue-600" />
      {text}
    </span>
  );
}
