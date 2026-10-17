import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, post, setUnauthorizedHandler } from "./api";
import { setDefaultCurrency } from "./format";
import type { User } from "./types";

interface LoginResult {
  user: User | null;
  mfaRequired: boolean;
}

export interface RegisterInput {
  businessName: string;
  industry: string;
  region: string;
  foundedDate: string;
  employees: number;
  currency: string;
  fullName: string;
  email: string;
  password: string;
  acceptTerms: boolean;
}

interface AuthState {
  user: User | null;
  ready: boolean;
  /** Returns true when a two-factor code is still needed. */
  login: (email: string, password: string) => Promise<boolean>;
  verifyMfa: (code: string) => Promise<void>;
  register: (input: RegisterInput) => Promise<void>;
  acceptInvite: (token: string, fullName: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  // Before children render, so every amount on screen uses the business's currency.
  setDefaultCurrency(user?.business?.currency);

  const refresh = useCallback(async () => {
    try {
      setUser(await api<User>("/auth/me"));
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    // The session lives in an HttpOnly cookie; asking the server is the only way to know who we are.
    setUnauthorizedHandler(() => setUser(null));
    void refresh().finally(() => setReady(true));
    return () => setUnauthorizedHandler(null);
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await post<LoginResult>("/auth/login", { email, password });
    if (!res.mfaRequired) setUser(res.user);
    return res.mfaRequired;
  }, []);

  const verifyMfa = useCallback(async (code: string) => {
    const res = await post<LoginResult>("/auth/mfa/verify", { code });
    setUser(res.user);
  }, []);

  const register = useCallback(async (input: RegisterInput) => {
    const res = await post<LoginResult>("/auth/register", input);
    setUser(res.user);
  }, []);

  const acceptInvite = useCallback(async (token: string, fullName: string, password: string) => {
    const res = await post<LoginResult>("/auth/invite/accept", { token, fullName, password });
    setUser(res.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await post("/auth/logout");
    } finally {
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, ready, login, verifyMfa, register, acceptInvite, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
