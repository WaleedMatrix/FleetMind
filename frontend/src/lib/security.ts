import { fleetMindRequest } from "./api";

export type Role = "administrator" | "engineer" | "viewer";
export const roleLabels: Record<Role, string> = { administrator: "Administrator", engineer: "Engineer", viewer: "Viewer" };
export type User = { id: string; username: string; role: Role; expires_at: string };
export type Account = Omit<User, "expires_at"> & { active: boolean; created_at: string };
export type Session = { id: string; created_at: string; expires_at: string; current: boolean };
export type Audit = { id: string; kind: string; actor_id: string | null; target_id: string | null; created_at: string };
export type LegacyConversation = { id: string; title: string; archived: boolean; created_at: string };

export function getUser(signal?: AbortSignal) {
  return fleetMindRequest<User>("auth/me", { signal });
}
export function change<T>(path: string, method: "POST" | "PATCH" | "DELETE", input?: object) {
  return fleetMindRequest<T>(path, { method, ...(input ? {
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  } : {}) });
}
