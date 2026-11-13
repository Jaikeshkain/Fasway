"""AI API keys, kept in the system's credential store (Windows Credential Manager / macOS Keychain). They
are never written to Fasway's data folder or logs and never sent to a phone."""
from __future__ import annotations

import logging

log = logging.getLogger("fasway")
_SERVICE = "Fasway"
PROVIDERS = ("anthropic", "openai")


def _user(provider: str) -> str:
    return f"{provider}-api-key"


def provider_of(key: str) -> str:
    """Anthropic keys start with sk-ant-; OpenAI's with sk-."""
    return "anthropic" if key.strip().startswith("sk-ant-") else "openai"


def get_key(provider: str = "anthropic") -> str | None:
    try:
        import keyring
        return keyring.get_password(_SERVICE, _user(provider)) or None
    except Exception as e:  # no credential store available
        log.warning("credential store unavailable: %s", type(e).__name__)
        return None


def set_key(key: str, provider: str = "anthropic") -> bool:
    try:
        import keyring
        keyring.set_password(_SERVICE, _user(provider), key.strip())
        return True
    except Exception as e:
        log.warning("could not store the API key: %s", type(e).__name__)
        return False


def delete_key(provider: str = "anthropic"):
    try:
        import keyring
        keyring.delete_password(_SERVICE, _user(provider))
    except Exception:
        pass  # nothing stored


def has_key() -> bool:
    """Any provider's."""
    return any(get_key(p) for p in PROVIDERS)


def mask(key: str | None) -> str:
    return f"{key[:7]}…{key[-4:]}" if key and len(key) > 12 else ("set" if key else "not set")
