"""Talks to the AI: the selectable models, their prices, and one request/response for each provider.

The runtime only sees plain dicts (LLMReply) in one shape, so tasks can be saved as JSON and tests can script
replies. Each client turns that shape into what its own API expects.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

log = logging.getLogger("fasway")

# Per million tokens. Verify against the pricing pages when updating:
# https://platform.claude.com/docs/en/about-claude/pricing  https://developers.openai.com/api/docs/pricing
MODELS = {
    "claude-opus-5-5": {"provider": "anthropic", "label": "Claude Opus 5.5", "hint": "Smartest, for tricky requests",
                        "in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00, "fallback": True},
    "claude-haiku-5-5": {"provider": "anthropic", "label": "Claude Haiku 5.5", "hint": "Fastest and cheapest",
                         "in": 0.10, "out": 0.50, "cache_read": 0.01, "cache_write": 0.125, "fallback": False},
    "gpt-6-luna": {"provider": "openai", "label": "GPT-6 Luna", "hint": "OpenAI: fast and cheap",
                   "in": 0.10, "out": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "gpt-6-sol": {"provider": "openai", "label": "GPT-6 Sol", "hint": "OpenAI: stronger, costs about 20x Luna",
                  "in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
}
PROVIDER_NAMES = {"anthropic": "Anthropic", "openai": "OpenAI"}
DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """kind: auth | rate | network | server | bad_request"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass
class LLMReply:
    stop_reason: str
    content: list[dict]       # blocks exactly as returned; must go back unchanged in the next request
    usage: dict = field(default_factory=dict)
    refusal: str | None = None


def cost_usd(model: str, usage: dict) -> float:
    p = MODELS.get(model) or MODELS[DEFAULT_MODEL]
    return (usage.get("input_tokens", 0) * p["in"] + usage.get("output_tokens", 0) * p["out"]
            + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
            + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]) / 1_000_000


class ClaudeClient:
    def __init__(self, api_key: str):
        from anthropic import AsyncAnthropic
        self._c = AsyncAnthropic(api_key=api_key, timeout=60.0, max_retries=2)

    async def create(self, *, model: str, system: str, tools: list[dict], messages: list[dict], effort: str) -> LLMReply:
        import anthropic
        kwargs = dict(model=model, max_tokens=16000, system=system, tools=tools, messages=messages,
                      output_config={"effort": effort},
                      cache_control={"type": "ephemeral"})  # caches tools, instructions and history so far
        try:
            if MODELS.get(model, {}).get("fallback"):
                # a safety decline is re-run server side on a fallback model instead of failing the task
                r = await self._c.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                r = await self._c.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise LLMError("auth", "The API key was rejected") from e
        except anthropic.PermissionDeniedError as e:
            raise LLMError("auth", "This API key can't use that model") from e
        except anthropic.RateLimitError as e:
            raise LLMError("rate", "Too many requests or no credit left on the API account") from e
        except anthropic.BadRequestError as e:
            log.warning("agent: bad request: %s", e.message)
            raise LLMError("bad_request", "The AI rejected the request") from e
        except anthropic.APIStatusError as e:
            raise LLMError("server", f"The AI service had a problem ({e.status_code})") from e
        except anthropic.APIConnectionError as e:   # includes timeouts
            raise LLMError("network", "Can't reach the AI service (no internet?)") from e

        refusal = None
        if r.stop_reason == "refusal" and getattr(r, "stop_details", None):
            refusal = r.stop_details.explanation or r.stop_details.category
        u = r.usage
        return LLMReply(
            stop_reason=r.stop_reason,
            content=[b.model_dump(mode="json", exclude_none=True) for b in r.content],
            usage={"input_tokens": u.input_tokens or 0, "output_tokens": u.output_tokens or 0,
                   "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
                   "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0},
            refusal=refusal,
        )


class OpenAIClient:
    """Same job as ClaudeClient, through OpenAI's Responses API. Nothing is stored at OpenAI between requests
    (store=False): the history goes along each time, including its reasoning items, which the API requires."""

    def __init__(self, api_key: str):
        from openai import AsyncOpenAI
        self._c = AsyncOpenAI(api_key=api_key, timeout=60.0, max_retries=2)

    @staticmethod
    def _tools(tools: list[dict]) -> list[dict]:
        return [{"type": "function", "name": t["name"], "description": t["description"], "strict": True,
                 "parameters": t["input_schema"]} for t in tools]

    @staticmethod
    def _input(messages: list[dict]) -> list[dict]:
        items = []
        for m in messages:
            if isinstance(m["content"], str):
                items.append({"role": m["role"], "content": m["content"]})
            elif m["role"] == "assistant":      # exactly as received, reasoning included
                items += [b["_item"] for b in m["content"]]
            else:
                items += [{"type": "function_call_output", "call_id": r["tool_use_id"],
                           "output": ("ERROR: " if r.get("is_error") else "") + r["content"]} for r in m["content"]]
        return items

    async def create(self, *, model: str, system: str, tools: list[dict], messages: list[dict], effort: str) -> LLMReply:
        import openai
        try:
            r = await self._c.responses.create(
                model=model, instructions=system, tools=self._tools(tools), input=self._input(messages),
                reasoning={"effort": effort}, max_output_tokens=16000, store=False,
                extra_body={"prompt_cache_options": {"mode": "implicit"}})   # not yet a named SDK argument
        except openai.AuthenticationError as e:
            raise LLMError("auth", "The OpenAI API key was rejected") from e
        except openai.PermissionDeniedError as e:
            raise LLMError("auth", "This API key can't use that model") from e
        except openai.RateLimitError as e:
            raise LLMError("rate", "Too many requests or no credit left on the OpenAI account") from e
        except openai.BadRequestError as e:
            log.warning("agent: bad request: %s", e.message)
            raise LLMError("bad_request", "The AI rejected the request") from e
        except openai.APIConnectionError as e:   # includes timeouts
            raise LLMError("network", "Can't reach the AI service (no internet?)") from e
        except openai.APIStatusError as e:
            raise LLMError("server", f"The AI service had a problem ({e.status_code})") from e
        if r.status == "failed":
            raise LLMError("server", "The AI service had a problem")

        content, refusal = [], None
        for item in r.output:
            raw = item.model_dump(mode="json", exclude_none=True)
            if item.type == "function_call":
                try:
                    args = json.loads(item.arguments)
                except ValueError:
                    args = {}
                content.append({"type": "tool_use", "id": item.call_id, "name": item.name, "input": args, "_item": raw})
            elif item.type == "message":
                refusal = next((c.refusal for c in item.content if c.type == "refusal"), refusal)
                text = "".join(c.text for c in item.content if c.type == "output_text")
                content.append({"type": "text", "text": text, "_item": raw})
            else:
                content.append({"type": item.type, "_item": raw})

        reason = r.incomplete_details.reason if r.status == "incomplete" and r.incomplete_details else None
        if refusal or reason == "content_filter":
            stop = "refusal"
        elif reason:
            stop = "max_tokens"
        else:
            stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"

        u, details = r.usage, r.usage.input_tokens_details
        cached = details.cached_tokens or 0
        written = getattr(details, "cache_write_tokens", 0) or 0
        return LLMReply(stop_reason=stop, content=content, refusal=refusal, usage={
            "input_tokens": max(0, u.input_tokens - cached - written),   # OpenAI's total includes both of these
            "output_tokens": u.output_tokens, "cache_read_input_tokens": cached, "cache_creation_input_tokens": written})


def make_client(model: str, api_key: str):
    return (OpenAIClient if MODELS[model]["provider"] == "openai" else ClaudeClient)(api_key)


async def check_key(api_key: str, provider: str = "anthropic") -> tuple[bool | None, str]:
    """Free check that a key works (reads model info; generates nothing). None = couldn't tell."""
    if provider == "openai":
        import openai as sdk
        client = sdk.AsyncOpenAI(api_key=api_key, timeout=15.0, max_retries=0)
        model = "gpt-6-luna"
    else:
        import anthropic as sdk
        client = sdk.AsyncAnthropic(api_key=api_key, timeout=15.0, max_retries=0)
        model = DEFAULT_MODEL
    name = PROVIDER_NAMES[provider]
    try:
        await client.models.retrieve(model)
        return True, f"{name} key works. AI is on: use the ✨ button on your phone"
    except sdk.AuthenticationError:
        return False, f"That {name} key was rejected, so it wasn't saved"
    except sdk.APIConnectionError:
        return None, f"{name} key saved, but couldn't check it (no internet?)"
    except sdk.APIStatusError as e:
        return None, f"{name} key saved, but the check failed ({e.status_code})"
