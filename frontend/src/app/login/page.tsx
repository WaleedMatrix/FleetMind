"use client";

import { ArrowRight, KeyRound, Radio, ShieldCheck } from "lucide-react";
import { Suspense, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { change, type User } from "@/lib/security";

function destination(identity: User, query: URLSearchParams) {
  const next = query.get("next") ?? "/";
  if (!/^\/(?:$|\?|account(?:\?|$)|admin(?:[/?]|$)|assets(?:[/?]|$)|telemetry(?:\?|$)|model-intelligence(?:\?|$)|copilot(?:\?|$))/.test(next)
    || next.includes("\\") || /[\x00-\x20]/.test(next)) return "/";
  if ((next.startsWith("/admin") && identity.role !== "administrator")
    || (next.startsWith("/copilot") && identity.role === "viewer")) return "/access-denied";
  return next;
}

function LoginForm() {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const query = useSearchParams();
  const notice = query.has("unavailable")
    ? "The authentication service is unavailable. Try again shortly."
    : query.has("expired") ? "Your session ended. Sign in to continue." : "";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setProblem("");
    try {
      const identity = await change<User>("auth/login", "POST", {
        username: String(form.get("username")), password: String(form.get("password")),
      });
      window.location.replace(destination(identity, new URLSearchParams(window.location.search)));
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : "Sign-in is temporarily unavailable.");
      setBusy(false);
    }
  }

  return <main className="security-login">
    <section className="security-login-aside" aria-label="FleetMind operations">
      <div className="security-mark"><Radio size={27} aria-hidden="true" /></div>
      <span className="section-overline">FLEETMIND OPERATIONS</span>
      <h1>Maintenance<br /> intelligence</h1>
      <p>Monitor asset telemetry, investigate alerts, and review model evidence from one workspace.</p>
    </section>
    <section className="panel security-login-form">
      <KeyRound size={24} aria-hidden="true" />
      <h2>Sign in</h2>
      <form onSubmit={(event) => { void submit(event); }} aria-describedby={problem ? "login-problem" : undefined}>
        <label>Username<input name="username" autoComplete="username" maxLength={64} required /></label>
        <label>Password<input name="password" type="password" autoComplete="current-password" maxLength={128} required /></label>
        {notice && <p role="status">{notice}</p>}
        {problem && <p role="alert" id="login-problem" className="security-error">{problem}</p>}
        <button className="security-primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"} <ArrowRight size={17} aria-hidden="true" /></button>
      </form>
      <p className="security-login-note"><ShieldCheck size={16} aria-hidden="true" /> Access is managed by your FleetMind administrator.</p>
    </section>
  </main>;
}

export default function LoginPage() {
  return <Suspense fallback={<main className="security-pending"><p role="status">Loading sign-in…</p></main>}><LoginForm /></Suspense>;
}
