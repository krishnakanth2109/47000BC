import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext.jsx";

export default function Layout() {
  const { user, logout } = useAuth();

  async function handleLogout() {
    await logout();
  }

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900 md:flex-row">
      <aside className="flex w-full shrink-0 flex-col bg-slate-900 text-white md:sticky md:top-0 md:h-screen md:w-64 md:overflow-y-auto">
        <div className="flex items-center gap-3 border-b border-white/10 px-4 py-5">
          <svg viewBox="0 0 48 48" fill="none" className="h-9 w-9 shrink-0">
            <rect width="48" height="48" rx="10" fill="#2563eb" />
            <path d="M12 18a6 6 0 1 1 12 0 6 6 0 0 1-12 0z" fill="white" />
            <path d="M34 16l8-4v16l-8-4V16z" fill="white" />
          </svg>
          <span className="text-base font-bold leading-tight text-white">
           Hexacore
          </span>
        </div>

        <nav className="flex flex-1 flex-row flex-wrap gap-1 px-2 py-3 md:flex-col">
          <NavItem to="/dashboard" icon="⊞" label="Dashboard" />
          <NavItem to="/employees" icon="👥" label="Employees" />
          <NavItem to="/attendance" icon="✓" label="Attendance" />
          <NavItem to="/payroll" icon="₹" label="Payroll" />
        </nav>

        <div className="border-t border-white/10 p-4">
          <div className="mb-3 flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">
              {user?.email?.[0]?.toUpperCase() ?? "A"}
            </div>
            <span className="truncate text-xs text-slate-300">
              {user?.email ?? "Admin"}
            </span>
          </div>
          <button
            onClick={handleLogout}
            className="w-full cursor-pointer rounded-md border border-white/15 bg-white/10 px-3 py-2 text-xs font-medium text-slate-200 transition hover:bg-red-500/30 hover:text-white"
          >
            Sign out
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">
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
        `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
          isActive
            ? "bg-blue-600 text-white shadow-sm"
            : "text-slate-300 hover:bg-white/10 hover:text-white"
        }`
      }
    >
      <span className="text-base leading-none">{icon}</span>
      <span>{label}</span>
    </NavLink>
  );
}
