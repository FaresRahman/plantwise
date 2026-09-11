import React, { createContext, useContext, useEffect, useState } from "react";

import * as authApi from "../api/auth";
import { getToken, setToken } from "../api/client";

interface AuthState {
  user: authApi.UserOut | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<authApi.UserOut | null>(null);
  const [loading, setLoading] = useState(true);

  async function refreshUser() {
    if (!getToken()) {
      setUser(null);
      return;
    }
    try {
      const me = await authApi.me();
      setUser(me);
    } catch {
      setToken(null);
      setUser(null);
    }
  }

  useEffect(() => {
    refreshUser().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function handle() {
      setUser(null);
      setLoading(false);
    }
    window.addEventListener("plantwise:auth-expired", handle);
    return () => window.removeEventListener("plantwise:auth-expired", handle);
  }, []);

  async function login(email: string, password: string) {
    const { access_token } = await authApi.login({ email, password });
    setToken(access_token);
    await refreshUser();
  }

  function logout() {
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
