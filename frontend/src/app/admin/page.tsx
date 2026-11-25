"use client";

import { useState, type FormEvent } from "react";
import { ShieldCheck, UsersRound } from "lucide-react";
import { useUser } from "@/components/auth-shell";
import { change, roleLabels, type Account, type Audit, type LegacyConversation, type Role } from "@/lib/security";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";

const PAGE_SIZE = 25;
const roles = Object.entries(roleLabels) as [Role, string][];
const roleOptions = roles.map(([value, label]) => <option key={value} value={value}>{label}</option>);
type Service = { id: string; name: string; expires_at: string; revoked_at: string | null };

function AccountRow({ item, disabled, onSave }: { item: Account; disabled: boolean; onSave: (changes: object) => void }) {
  const [role, setRole] = useState(item.role);
  const [active, setActive] = useState(item.active);
  return <form className="security-row security-profile" onSubmit={(event) => {
    event.preventDefault();
    onSave({ role, active });
  }}>
    <div><strong>{item.username}</strong><small className="security-account-id">{item.id}</small></div>
    <label>Role<select value={role} onChange={(event) => setRole(event.target.value as Role)}>{roleOptions}</select></label>
    <label>Status<select value={active ? "active" : "inactive"} onChange={(event) => setActive(event.target.value === "active")}>
      <option value="active">Active</option><option value="inactive">Inactive</option>
    </select></label>
    <button className="security-secondary" disabled={disabled || (role === item.role && active === item.active)}>Save</button>
  </form>;
}

const pages = ["Users", "Audit", "Legacy conversations", "Service credentials"] as const;
type Tab = typeof pages[number];

function Administration() {
  const [tab, setTab] = useState<Tab>("Users");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const query = "?limit=" + PAGE_SIZE + "&offset=" + offset;
  const users = useFleetMindQuery<Account[]>(tab === "Users" ? "admin/users" + query : null, { revision });
  const audit = useFleetMindQuery<Audit[]>(tab === "Audit" ? "admin/audit" + query : null, { revision });
  const legacy = useFleetMindQuery<LegacyConversation[]>(tab === "Legacy conversations" ? "admin/orphan-conversations" + query : null, { revision });
  const services = useFleetMindQuery<Service[]>(tab === "Service credentials" ? "admin/service-credentials" + query : null, { revision });
  const active = { Users: users, Audit: audit, "Legacy conversations": legacy, "Service credentials": services }[tab];

  async function apply(path: string, method: "POST" | "PATCH" | "DELETE", input?: object) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      await change(path, method, input);
      setRevision((n) => n + 1);
      setNotice("Change saved.");
      return true;
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save the change.");
      return false;
    } finally { setBusy(false); }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = Object.fromEntries(new FormData(form));
    if (await apply("admin/users", "POST", input)) form.reset();
  }

  return <main className="security-content">
    <header><span className="section-overline">WORKSPACE ACCESS</span><h1>Administration</h1><p>Manage accounts, review security events, and resolve legacy conversation ownership.</p></header>
    <nav className="security-tabs" aria-label="Administration sections">{pages.map((name) =>
      <button type="button" key={name} aria-pressed={tab === name} onClick={() => {
        setTab(name); setOffset(0); setError(""); setNotice("");
      }}>{name}</button>)}</nav>
    {error && <p role="alert" className="security-error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <section className="panel security-card">
      <h2>{tab}</h2>
      {active.pending && <p role="status">Loading {tab.toLowerCase()}…</p>}
      {active.error && <p role="alert" className="security-error">{active.error}</p>}
      {active.data?.length === 0 && <p>No records on this page.</p>}
      {tab === "Users" && users.data?.map((item) => <AccountRow key={item.id + item.role + item.active} item={item}
        disabled={busy} onSave={(values) => { void apply("admin/users/" + item.id, "PATCH", values); }} />)}
      {tab === "Audit" && audit.data?.map((item) => <div className="security-row" key={item.id}>
        <div><strong>{item.kind.replaceAll("_", " ")}</strong>
          {item.actor_id && <small>Actor {item.actor_id}</small>}
          {item.target_id && <small>Target {item.target_id}</small>}</div>
        <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time></div>)}
      {tab === "Legacy conversations" && legacy.data?.map((item) => <div className="security-row security-legacy" key={item.id}>
        <div><strong>{item.title}</strong><small>{item.archived ? "Archived" : "Unassigned"} · {new Date(item.created_at).toLocaleDateString()}</small></div>
        <form onSubmit={(event) => {
          event.preventDefault();
          const ownerId = new FormData(event.currentTarget).get("owner");
          void apply("admin/orphan-conversations/" + item.id, "PATCH", { action: "adopt", owner_id: ownerId });
        }}>
          <label>Engineer or administrator ID<input name="owner" maxLength={36} required /></label>
          <button className="security-secondary" disabled={busy}>Assign owner</button>
        </form>
        {!item.archived && <button className="security-secondary" disabled={busy}
          onClick={() => { void apply("admin/orphan-conversations/" + item.id, "PATCH", { action: "archive" }); }}>Archive</button>}
      </div>)}
      {tab === "Service credentials" && <>
        <p>Create credentials from the FleetMind operator CLI.</p>
        {services.data?.map((item) => <div className="security-row" key={item.id}>
          <div><strong>{item.name}</strong><small>{item.revoked_at ? "Revoked" : "Expires " + new Date(item.expires_at).toLocaleString()}</small></div>
          {!item.revoked_at && <button className="security-secondary" disabled={busy} onClick={() => {
            if (window.confirm("Revoke this prediction credential?")) void apply("admin/service-credentials/" + item.id, "DELETE");
          }}>Revoke</button>}</div>)}
      </>}
      <div className="security-pagination">
        <button className="security-secondary" disabled={!offset || active.pending}
          onClick={() => setOffset((n) => n - PAGE_SIZE)}>Previous</button>
        <span>Page {offset / PAGE_SIZE + 1}</span>
        <button className="security-secondary" disabled={active.pending || active.data?.length !== PAGE_SIZE}
          onClick={() => setOffset((n) => n + PAGE_SIZE)}>Next</button>
      </div>
    </section>
    {tab === "Users" && <section className="panel security-card"><UsersRound aria-hidden="true" /><h2>Create account</h2>
      <form className="security-create" onSubmit={(event) => { void create(event); }}>
        <label>Username<input name="username" autoComplete="off" required minLength={3} maxLength={64}
          pattern="[a-z0-9][a-z0-9_.\-]{2,63}" aria-describedby="username-hint" /><small id="username-hint">Use lowercase letters, numbers, periods, dashes, or underscores.</small></label>
        <label>Initial password<input name="password" autoComplete="new-password" type="password" required minLength={12} maxLength={128} /></label>
        <label>Role<select name="role" defaultValue="viewer">{roleOptions}</select></label>
        <button className="security-primary" disabled={busy}>Create account</button>
      </form>
    </section>}
  </main>;
}

export default function AdminPage() {
  const user = useUser();
  return user?.role === "administrator" ? <Administration />
    : <main className="security-content"><ShieldCheck aria-hidden="true" /><h1>Access restricted</h1></main>;
}
