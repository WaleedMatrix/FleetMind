export class FleetMindApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "FleetMindApiError";
  }
}

export async function fleetMindRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/fleetmind/${path}`, { ...options, cache: "no-store" });
  if (!response.ok) {
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
  return response.json() as Promise<T>;
}
