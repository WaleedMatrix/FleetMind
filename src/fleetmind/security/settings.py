"""Strict cookie and trusted browser origin configuration."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEV_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEV_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


@dataclass(frozen=True)
class SecuritySettings:
    origins: frozenset[str]
    insecure_local_http: bool = False
    session_seconds: int = 28_800

    @property
    def cookie(self):
        return (
            "fleetmind_session"
            if self.insecure_local_http
            else "__Host-fleetmind_session"
        )

    @property
    def csrf_cookie(self):
        return "fleetmind_csrf" if self.insecure_local_http else "__Host-fleetmind_csrf"

    @classmethod
    def from_environment(cls):
        insecure = os.getenv("FLEETMIND_AUTH_INSECURE_LOCAL_HTTP", "0") == "1"
        values = os.getenv("FLEETMIND_AUTH_ORIGINS", DEV_ORIGINS if insecure else "")
        origins = frozenset(
            value.strip() for value in values.split(",") if value.strip()
        )
        for origin in origins:
            parsed = urlsplit(origin)
            allowed_scheme = parsed.scheme == "https" or (
                insecure and parsed.scheme == "http" and parsed.hostname in DEV_HOSTS
            )
            if (
                not allowed_scheme
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
                or "*" in origin
                or (insecure and parsed.hostname not in DEV_HOSTS)
            ):
                raise ValueError(
                    "Configure exact HTTPS origins or explicit loopback development."
                )
        minutes = int(os.getenv("FLEETMIND_AUTH_SESSION_MINUTES", "480"))
        if not 5 <= minutes <= 1440:
            raise ValueError("Session lifetime must be between 5 and 1440 minutes.")
        return cls(origins, insecure, minutes * 60)
