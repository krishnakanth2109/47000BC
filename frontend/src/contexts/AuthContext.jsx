import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { apiGet, apiPost, apiDelete } from "../api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = still loading
  const [loading, setLoading] = useState(true);

  // On mount — check if we already have a valid session cookie
  useEffect(() => {
    apiGet("me")
      .then((data) => setUser(data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email, password) => {
    await apiPost("auth/login", { email, password });
    const me = await apiGet("me");
    setUser(me);
    return me;
  }, []);

  const register = useCallback(async (email, password) => {
    await apiPost("auth/register", { email, password });
    const me = await apiGet("me");
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(async () => {
    await apiDelete("session");
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
