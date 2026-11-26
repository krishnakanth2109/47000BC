import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { initializeApp, getApps } from "firebase/app";
import {
  getAuth,
  inMemoryPersistence,
  setPersistence,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut,
} from "firebase/auth";
import firebaseConfig from "../firebase.js";
import { apiGet, apiPost, apiDelete } from "../api.js";

const AuthContext = createContext(null);

function getFirebaseAuth() {
  const app = getApps()[0] || initializeApp(firebaseConfig);
  return getAuth(app);
}

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

  const _establishSession = useCallback(async (auth, credential) => {
    const idToken = await credential.user.getIdToken();

    // Exchange Firebase ID token for a server-side session cookie
    try {
      await apiPost("session", { token: idToken });
    } finally {
      await signOut(auth); // Don't keep Firebase client-side state
    }

    const me = await apiGet("me");
    setUser(me);
    return me;
  }, []);

  const login = useCallback(async (email, password) => {
    const auth = getFirebaseAuth();
    await setPersistence(auth, inMemoryPersistence);
    const credential = await signInWithEmailAndPassword(auth, email, password);
    return _establishSession(auth, credential);
  }, [_establishSession]);

  const register = useCallback(async (email, password) => {
    const auth = getFirebaseAuth();
    await setPersistence(auth, inMemoryPersistence);
    const credential = await createUserWithEmailAndPassword(auth, email, password);
    return _establishSession(auth, credential);
  }, [_establishSession]);

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
