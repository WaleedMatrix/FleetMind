const COOKIE_NAMES = new Set(["fleetmind_session", "__Host-fleetmind_session"]);

export function upstreamUrl(path: string): URL {
  const base = new URL(process.env.FLEETMIND_API_URL || "http://127.0.0.1:8000");
  if (!["http:", "https:"].includes(base.protocol) || base.username || base.password
    || base.pathname !== "/" || base.search || base.hash) {
    throw new Error("Invalid FleetMind API configuration");
  }
  return new URL(path, base);
}

export function sessionCookies(header: string | null): string {
  return (header ?? "").split(";").map((part) => part.trim()).filter((part) => {
    const [name, ...value] = part.split("=");
    return COOKIE_NAMES.has(name) && /^[A-Za-z0-9_-]{43}$/.test(value.join("="));
  }).join("; ");
}
