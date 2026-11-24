import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


class MissingCredentials(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    provider: str = "disabled"
    model: str = ""
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    request_timeout: float = 45
    provider_timeout: float = 12
    tool_timeout: float = 24
    max_tokens: int = 600
    max_rounds: int = 4
    max_tools: int = 8
    retries: int = 1
    token_parameter: str = "max_completion_tokens"

    @classmethod
    def from_environment(cls):
        def value(key: str, default=""):
            return os.getenv(f"FLEETMIND_COPILOT_{key}", str(default)).strip()

        provider = value("PROVIDER", "disabled")
        if provider not in {"disabled", "openai", "ollama", "mock"}:
            raise ValueError("Invalid Copilot provider.")
        if provider == "disabled":
            return cls(provider=provider)
        default_url = (
            "http://127.0.0.1:11434/v1"
            if provider == "ollama"
            else "https://api.openai.com/v1"
        )
        base_url = value("BASE_URL", default_url).rstrip("/")
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or (
                url.scheme == "http"
                and url.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise ValueError("Use an HTTPS provider URL or loopback HTTP.")
        model = value("MODEL")
        api_key = value("API_KEY") or (
            os.getenv("OPENAI_API_KEY", "")
            if provider == "openai" and url.netloc.lower() == "api.openai.com"
            else ""
        )
        if provider == "openai" and not api_key:
            raise MissingCredentials("Configure hosted provider credentials.")
        if (provider != "mock" and not model) or len(model) > 160:
            raise ValueError(
                "Configure the Copilot model and hosted provider credentials."
            )
        token_parameter = value(
            "TOKEN_PARAMETER",
            "max_tokens" if provider == "ollama" else "max_completion_tokens",
        )
        if token_parameter not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("Invalid Copilot token parameter.")
        settings = cls(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            request_timeout=float(value("REQUEST_TIMEOUT", 45)),
            provider_timeout=float(value("PROVIDER_TIMEOUT", 12)),
            tool_timeout=float(value("TOOL_TIMEOUT", 24)),
            max_tokens=int(value("MAX_TOKENS", 600)),
            max_rounds=int(value("MAX_ROUNDS", 4)),
            max_tools=int(value("MAX_TOOLS", 8)),
            retries=int(value("RETRIES", 1)),
            token_parameter=token_parameter,
        )
        if not (
            1 <= settings.request_timeout <= 120
            and 0.1 <= settings.provider_timeout <= 60
            and 0.1 <= settings.tool_timeout <= 60
            and 64 <= settings.max_tokens <= 2000
            and 1 <= settings.max_rounds <= 8
            and 1 <= settings.max_tools <= 16
            and 0 <= settings.retries <= 2
        ):
            raise ValueError("Copilot budget settings are outside their bounds.")
        return settings
