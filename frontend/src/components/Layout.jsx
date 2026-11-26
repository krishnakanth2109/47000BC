import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext.jsx";
import styles from "./Layout.module.css";

export default function Layout() {
  const { user, logout } = useAuth();

  async function handleLogout() {
    await logout();
  }

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <svg viewBox="0 0 48 48" fill="none" className={styles.brandIcon}>
            <rect width="48" height="48" rx="10" fill="#2563eb" />
            <path d="M12 18a6 6 0 1 1 12 0 6 6 0 0 1-12 0z" fill="white" />
            <path d="M34 16l8-4v16l-8-4V16z" fill="white" />
          </svg>
          <span className={styles.brandName}>CCTV Attendance</span>
        </div>

        <nav className={styles.nav}>
          <NavItem to="/dashboard" icon="⊞" label="Dashboard" />
          <NavItem to="/employees" icon="👥" label="Employees" />
          <NavItem to="/attendance" icon="✓" label="Attendance" />
        </nav>

        <div className={styles.userSection}>
          <div className={styles.userInfo}>
            <div className={styles.userAvatar}>
              {user?.email?.[0]?.toUpperCase() ?? "A"}
            </div>
            <span className={styles.userEmail}>{user?.email ?? "Admin"}</span>
          </div>
          <button className={styles.logoutBtn} onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </aside>

      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}

function NavItem({ to, icon, label }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `${styles.navItem} ${isActive ? styles.navItemActive : ""}`
      }
    >
      <span className={styles.navIcon}>{icon}</span>
      {label}
    </NavLink>
  );
}
