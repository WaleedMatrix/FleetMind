import { PORTFOLIO } from "./profile";

export class FleetMindApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "FleetMindApiError";
  }
}

export function announceSessionExpiry() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("fleetmind:session-expired"));
}

export function browserHeaders(options?: RequestInit) {
  const headers = new Headers(options?.headers);
  if (typeof document !== "undefined" && ["POST", "PATCH", "DELETE", "PUT"].includes(options?.method ?? "GET")) {
    const csrf = document.cookie.match(/(?:^|;\s*)(?:__Host-)?fleetmind_csrf=([a-f0-9]{64})(?:;|$)/)?.[1];
    if (csrf) headers.set("X-FleetMind-CSRF", csrf);
  }
  return headers;
}

export async function fleetMindRequest<T>(path: string, options?: RequestInit): Promise<T> {
  if (PORTFOLIO && path !== "demo/infer") {
    if (options?.method && options.method !== "GET") throw new FleetMindApiError("The portfolio is read-only.", 405);
    options?.signal?.throwIfAborted();
    const { readPortfolio } = await import("./portfolio");
    options?.signal?.throwIfAborted();
    const result = readPortfolio(path);
    if (result === undefined) throw new FleetMindApiError("This record is unavailable in the portfolio.", 404);
    return result as T;
  }
  const response = await fetch(`/api/fleetmind/${path}`, {
    ...options, headers: PORTFOLIO ? options?.headers : browserHeaders(options), cache: "no-store",
  });
  await assertFleetMindResponse(response, path !== "auth/login");
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function assertFleetMindResponse(response: Response, expireOn401 = true) {
  if (!response.ok) {
    if (expireOn401 && response.status === 401) announceSessionExpiry();
    const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
    const detail = payload?.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail)
        ? detail.flatMap((item: unknown) => (
          typeof item === "object" && item !== null && "msg" in item && typeof item.msg === "string"
            ? [item.msg] : []
        )).join(". ")
        : "";
    throw new FleetMindApiError(message || `FleetMind API request failed (${response.status})`, response.status);
  }
}
