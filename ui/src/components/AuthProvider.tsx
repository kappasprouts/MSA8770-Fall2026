"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { SessionUser } from "@/lib/auth-policy";

const AuthContext = createContext<SessionUser | null>(null);
export const useSessionUser = () => useContext(AuthContext);
export default function AuthProvider({ user, children }: { user: SessionUser | null; children: ReactNode }) {
  return <AuthContext.Provider value={user}>{children}</AuthContext.Provider>;
}
