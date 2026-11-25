"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, CircleUserRound, LogOut, ShieldCheck } from "lucide-react";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { FleetMindApiError } from "@/lib/api";
import { change, getUser, roleLabels, type User } from "@/lib/security";

const Auth = createContext<User | null>(null);
export const useUser = () => useContext(Auth);
export function useEngineering() {
  const user = useUser();
  return user?.role === "administrator" || user?.role === "engineer";
}

function AccountMenu({ user }: { user: User }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function logout() {
    setBusy(true);
    setError("");
    try {
      await change<void>("auth/logout", "POST");
      window.location.replace("/login");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not sign out.");
      setBusy(false);
    }
  }
  return <details className="security-account">
    <summary><CircleUserRound size={19} aria-hidden="true" /><span>{user.username}</span><ChevronDown size={15} aria-hidden="true" /></summary>
    <div className="security-menu">
      <span className="security-role"><ShieldCheck size={15} aria-hidden="true" /> {roleLabels[user.role]}</span>
      <Link href="/account">Account and sessions</Link>
      {user.role === "administrator" && <Link href="/admin">Administration</Link>}
      <button type="button" onClick={() => { void logout(); }} disabled={busy}><LogOut size={15} aria-hidden="true" /> {busy ? "Signing out…" : "Sign out"}</button>
      {error && <p role="alert">{error}</p>}
    </div>
  </details>;
}

function AuthenticatedShell({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  const path = usePathname();
  useEffect(() => {
    let redirected = false;
    const expire = () => {
      if (redirected) return;
      redirected = true;
      const next = window.location.pathname + window.location.search;
      window.location.replace("/login?expired=1&next=" + encodeURIComponent(next));
    };
    const controller = new AbortController();
    window.addEventListener("fleetmind:session-expired", expire);
    void getUser(controller.signal).then((identity) => {
      if (!controller.signal.aborted) {
        setError("");
        setUser(identity);
      }
    }).catch((failure: unknown) => {
      if (controller.signal.aborted) return;
      if (failure instanceof FleetMindApiError && failure.status === 401) expire();
      else setError("The session service is unavailable. Try refreshing this page.");
    });
    return () => {
      controller.abort();
      window.removeEventListener("fleetmind:session-expired", expire);
    };
  }, [path]);

  if (!user) return <main className="security-pending"><p role={error ? "alert" : "status"}>{error || "Checking access…"}</p></main>;
  return <Auth.Provider value={user}>
    <div className="security-bar"><Link href="/" className="security-home"><ShieldCheck size={18} aria-hidden="true" /> FleetMind</Link><AccountMenu user={user} /></div>
    {error ? <main className="security-pending"><p role="alert">{error}</p></main> : children}
  </Auth.Provider>;
}

export function AuthShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  return path === "/login" ? children : <AuthenticatedShell>{children}</AuthenticatedShell>;
}
