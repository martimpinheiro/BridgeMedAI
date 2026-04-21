import React, { createContext, useContext, useEffect, useState, useCallback } from "react";

const STORAGE_KEY = "bridgemedai.auth";
export const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

const AuthContext = createContext(null);

function readStored() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.token || !parsed?.user) return null;
    if (parsed.expires_at && new Date(parsed.expires_at) < new Date()) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [apiBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const [session, setSession] = useState(() => readStored());

  const persist = useCallback((next) => {
    if (next) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
    setSession(next);
  }, []);

  const login = useCallback((payload) => {
    persist({
      token: payload.token,
      expires_at: payload.expires_at,
      user: payload.user,
      specialist_profile: payload.specialist_profile || null,
    });
  }, [persist]);

  const updateUser = useCallback((patch) => {
    setSession((prev) => {
      if (!prev) return prev;
      const next = { ...prev, user: { ...prev.user, ...patch } };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const logout = useCallback(() => persist(null), [persist]);

  useEffect(() => {
    if (!session?.expires_at) return;
    const ms = new Date(session.expires_at).getTime() - Date.now();
    if (ms <= 0) {
      logout();
      return;
    }
    const t = setTimeout(logout, ms);
    return () => clearTimeout(t);
  }, [session?.expires_at, logout]);

  const value = {
    token: session?.token || null,
    user: session?.user || null,
    specialistProfile: session?.specialist_profile || null,
    apiBaseUrl,
    login,
    logout,
    updateUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth deve ser usado dentro de <AuthProvider>");
  return ctx;
}
