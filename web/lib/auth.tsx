"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, restoreSession, setSession } from "./api";
import type { Role, User } from "./types";

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => void;
  /** After a password change: every older token is dead, so carry on with the new one. */
  passwordChanged: (nextToken: string) => void;
}

const AuthContext = createContext<AuthState | null>(null);

/** Where each role lands after signing in. */
export const ROLE_HOME: Record<Role, string> = {
  institution: "/institution",
  aicte_viewer: "/aicte",
  aicte_officer: "/aicte",
  student: "/student/records",
  verifier: "/verifier",
  // Operators have no portal; reset and reseed are CLI commands.
  admin: "",
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const restored = restoreSession();
    if (restored.token && restored.user) setUser(restored.user);
    setReady(true);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const response = await api.login(username, password);
    setSession(response.access_token, response.user);
    setUser(response.user);
    return response.user;
  }, []);

  const logout = useCallback(() => {
    setSession(null, null);
    setUser(null);
  }, []);

  const passwordChanged = useCallback(
    (nextToken: string) => {
      if (!user) return;
      const next = { ...user, must_change_password: false };
      setSession(nextToken, next);
      setUser(next);
    },
    [user],
  );

  const value = useMemo(
    () => ({ user, ready, login, logout, passwordChanged }),
    [user, ready, login, logout, passwordChanged],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

/**
 * Route guard. Renders nothing until the session is known, then sends the wrong role
 * to its own home rather than showing a page it may not read.
 */
export function useRequireRole(roles: Role[]) {
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (user.must_change_password) {
      router.replace("/account/password");
      return;
    }
    if (!roles.includes(user.role)) router.replace(ROLE_HOME[user.role] || "/login");
  }, [ready, user, roles, router]);

  return {
    user,
    allowed: Boolean(user && !user.must_change_password && roles.includes(user.role)),
    ready,
  };
}
