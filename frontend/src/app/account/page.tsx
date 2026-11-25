"use client";

import { KeyRound, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useUser } from "@/components/auth-shell";
import { change, roleLabels, type Session, type User } from "@/lib/security";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";

export default function AccountPage() {
  const user = useUser();
  const [revision, setRevision] = useState(0);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const sessions = useFleetMindQuery<Session[]>("auth/sessions", { revision });

  async function update(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    setMessage("");
    setError("");
    if (fields.get("new") !== fields.get("confirm")) {
      setError("The new passwords must match.");
      return;
    }
    setWorking(true);
    try {
      await change<User>("auth/password", "POST", {
        current_password: fields.get("current"), new_password: fields.get("new"),
      });
      form.reset();
      setRevision((n) => n + 1);
      setMessage("Password updated. Your other sessions were signed out.");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not change your password.");
    } finally { setWorking(false); }
  }

  async function revoke(session: Session) {
    setWorking(true);
    setError("");
    setMessage("");
    try {
      await change<void>("auth/sessions/" + session.id, "DELETE");
      if (session.current) window.location.replace("/login");
      else {
        setRevision((n) => n + 1);
        setMessage("Session revoked.");
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not revoke the session.");
    } finally { setWorking(false); }
  }

  return <main className="security-content">
    <header><span className="section-overline">WORKSPACE ACCESS</span><h1>Account and sessions</h1>
      {user && <p>{user.username} · {roleLabels[user.role]}</p>}
    </header>
    {error && <p className="security-error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <div className="security-grid">
      <section className="panel security-card">
        <KeyRound aria-hidden="true" /><h2>Change password</h2>
        <form onSubmit={(event) => { void update(event); }}>
          <label>Current password<input name="current" type="password" autoComplete="current-password" maxLength={128} required /></label>
          <label>New password<input name="new" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></label>
          <label>Confirm new password<input name="confirm" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></label>
          <button className="security-primary" disabled={working}>Update password</button>
        </form>
      </section>
      <section className="panel security-card">
        <ShieldCheck aria-hidden="true" /><h2>Signed-in sessions</h2>
        {sessions.pending && <p role="status">Loading sessions…</p>}
        {sessions.error && <p role="alert">{sessions.error}</p>}
        {sessions.data?.map((session) => <div className="security-row" key={session.id}>
          <div><strong>{session.current ? "This browser" : "Other session"}</strong>
            <small>Started {new Date(session.created_at).toLocaleString()}</small>
            <small>Expires {new Date(session.expires_at).toLocaleString()}</small></div>
          <button className="security-secondary" disabled={working} onClick={() => { void revoke(session); }}>
            {session.current ? "Sign out here" : "Revoke"}
          </button></div>)}
      </section>
    </div>
  </main>;
}
