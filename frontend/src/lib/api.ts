export class FleetMindApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "FleetMindApiError";
  }
}

export async function fleetMindRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/fleetmind/${path}`, { ...options, cache: "no-store" });
  await assertFleetMindResponse(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function assertFleetMindResponse(response: Response) {
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
}
