import { useState } from "react";
import { useAuth } from "../contexts/AuthContext.jsx";
import styles from "./LoginPage.module.css";

export default function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
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

  function toggleMode() {
    setMode((m) => (m === "login" ? "register" : "login"));
    setError("");
    setConfirmPassword("");
  }

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <div className={styles.logo}>
          <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="48" height="48" rx="12" fill="#2563eb" />
            <path d="M12 18a6 6 0 1 1 12 0 6 6 0 0 1-12 0z" fill="white" />
            <path d="M34 16l8-4v16l-8-4V16z" fill="white" />
            <path d="M10 34c0-4.4 3.6-8 8-8h12c4.4 0 8 3.6 8 8" stroke="white" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </div>
        <h1 className={styles.title}>CCTV Attendance</h1>
        <p className={styles.subtitle}>
          {isRegister ? "Create administrator account" : "Administrator sign in"}
        </p>

        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.field}>
            <label htmlFor="email">Email address</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="admin@company.com"
              disabled={busy}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete={isRegister ? "new-password" : "current-password"}
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              disabled={busy}
            />
          </div>

          {isRegister && (
            <div className={styles.field}>
              <label htmlFor="confirmPassword">Confirm password</label>
              <input
                id="confirmPassword"
                type="password"
                autoComplete="new-password"
                required
                minLength={6}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="••••••••"
                disabled={busy}
              />
            </div>
          )}

          <button
            type="submit"
            className={styles.submitBtn}
            disabled={busy}
          >
            {busy
              ? isRegister ? "Registering…" : "Signing in…"
              : isRegister ? "Register & Sign in" : "Sign in"}
          </button>
        </form>

        <div className={styles.switchRow}>
          {isRegister ? "Already have an account?" : "First time here?"}{" "}
          <button
            type="button"
            className={styles.switchBtn}
            onClick={toggleMode}
            disabled={busy}
          >
            {isRegister ? "Sign in" : "Register"}
          </button>
        </div>
      </div>
    </div>
  );
}
