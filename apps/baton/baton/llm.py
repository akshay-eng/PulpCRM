"""Multi-provider LLM client.

One `chat()` entry point over five provider shapes, chosen by config rather than
code. Baton's constraint is zero recurring spend, and the free tiers live behind
different wire formats -- so the adapter layer is the difference between "switch
provider" being a settings change and a rewrite.

Supported:
    openai_compatible  OpenAI, Groq, Together, OpenRouter, vLLM, LM Studio
    anthropic          /v1/messages
    google             Gemini generateContent
    ollama             local /api/chat, no key
    azure_openai       deployment-style URLs

Adding a provider means adding one adapter below and one Select option on
`Baton AI Model`. Nothing else changes.
"""

import json

import frappe
import requests

DEFAULT_TIMEOUT = 90


class LLMNotConfigured(frappe.ValidationError):
    pass


class LLMCallFailed(frappe.ValidationError):
    pass


# --------------------------------------------------------------------------
# provider adapters
#
# Each returns plain text. `want_json` asks the provider for strict JSON where
# it supports it; callers must still tolerate prose, because several providers
# treat it as a hint.
# --------------------------------------------------------------------------

def _openai_compatible(cfg, key, messages, want_json, temperature, max_tokens, timeout):
    body = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    if want_json:
        body["response_format"] = {"type": "json_object"}

    r = requests.post(
        f"{cfg.base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    _raise_for_status(r, cfg)
    return r.json()["choices"][0]["message"]["content"]


def _anthropic(cfg, key, messages, want_json, temperature, max_tokens, timeout):
    # Anthropic takes the system prompt out of band rather than as a message.
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    convo = [m for m in messages if m["role"] != "system"]
    if want_json:
        system = (system + "\n\nRespond with a single valid JSON object and nothing else.").strip()

    body = {
        "model": cfg.model,
        "messages": convo,
        "max_tokens": max_tokens or 4096,
        "temperature": temperature,
    }
    if system:
        body["system"] = system

    r = requests.post(
        f"{(cfg.base_url or 'https://api.anthropic.com').rstrip('/')}/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=timeout,
    )
    _raise_for_status(r, cfg)
    parts = r.json().get("content", [])
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")


def _google(cfg, key, messages, want_json, temperature, max_tokens, timeout):
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [
        # Gemini names the assistant role "model".
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
        if m["role"] != "system"
    ]
    gen = {"temperature": temperature}
    if max_tokens:
        gen["maxOutputTokens"] = max_tokens
    if want_json:
        gen["responseMimeType"] = "application/json"

    body = {"contents": contents, "generationConfig": gen}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    base = (cfg.base_url or "https://generativelanguage.googleapis.com").rstrip("/")
    r = requests.post(
        f"{base}/v1beta/models/{cfg.model}:generateContent",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        json=body,
        timeout=timeout,
    )
    _raise_for_status(r, cfg)
    cands = r.json().get("candidates", [])
    if not cands:
        raise LLMCallFailed(f"{cfg.name}: model returned no candidates (possibly safety-blocked)")
    return "".join(p.get("text", "") for p in cands[0]["content"]["parts"])


def _ollama(cfg, key, messages, want_json, temperature, max_tokens, timeout):
    # Local models need no key, and default to the standard loopback port.
    body = {
        "model": cfg.model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if max_tokens:
        body["options"]["num_predict"] = max_tokens
    if want_json:
        body["format"] = "json"

    r = requests.post(
        f"{(cfg.base_url or 'http://localhost:11434').rstrip('/')}/api/chat",
        json=body,
        timeout=timeout,
    )
    _raise_for_status(r, cfg)
    return r.json()["message"]["content"]


def _azure_openai(cfg, key, messages, want_json, temperature, max_tokens, timeout):
    body = {"messages": messages, "temperature": temperature}
    if max_tokens:
        body["max_tokens"] = max_tokens
    if want_json:
        body["response_format"] = {"type": "json_object"}

    # Azure puts the deployment in the path and the version in the query string.
    r = requests.post(
        f"{cfg.base_url.rstrip('/')}/openai/deployments/{cfg.model}/chat/completions",
        params={"api-version": cfg.api_version or "2024-02-15-preview"},
        headers={"api-key": key, "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    _raise_for_status(r, cfg)
    return r.json()["choices"][0]["message"]["content"]


ADAPTERS = {
    "OpenAI Compatible": _openai_compatible,
    "Anthropic": _anthropic,
    "Google Gemini": _google,
    "Ollama": _ollama,
    "Azure OpenAI": _azure_openai,
}

# Providers that run locally and therefore need no credential.
KEYLESS = {"Ollama"}


def _raise_for_status(r, cfg):
    if r.status_code >= 400:
        # Surface the provider's own message: "model not found" and "quota
        # exceeded" are the two that actually happen, and both are actionable.
        raise LLMCallFailed(f"{cfg.name} ({cfg.provider}) returned {r.status_code}: {r.text[:400]}")


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

def get_model_config(purpose=None):
    """Resolve the `Baton AI Model` to use for a purpose, falling back to default."""
    name = None
    if purpose:
        name = frappe.db.get_value(
            "Baton AI Model", {"purpose": purpose, "enabled": 1}, "name"
        )
    if not name:
        name = frappe.db.get_value("Baton AI Model", {"is_default": 1, "enabled": 1}, "name")
    if not name:
        raise LLMNotConfigured(
            "No enabled Baton AI Model. Add one under Settings, or mark an existing one default."
        )
    return frappe.get_cached_doc("Baton AI Model", name)


def _api_key(cfg):
    if cfg.provider in KEYLESS:
        return None
    key = cfg.get_password("api_key", raise_exception=False)
    if not key:
        raise LLMNotConfigured(f"Baton AI Model '{cfg.name}' has no API key set.")
    return key


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def chat(messages, purpose=None, want_json=False, temperature=None, max_tokens=None, config=None):
    """Send a chat completion through the model configured for `purpose`.

    Returns the assistant text. Raises LLMNotConfigured / LLMCallFailed.
    """
    if not frappe.db.get_single_value("Baton Settings", "ai_enabled"):
        raise LLMNotConfigured("AI is switched off in Baton Settings.")

    cfg = config or get_model_config(purpose)
    adapter = ADAPTERS.get(cfg.provider)
    if not adapter:
        raise LLMNotConfigured(f"Unknown provider '{cfg.provider}' on Baton AI Model '{cfg.name}'.")

    return adapter(
        cfg,
        _api_key(cfg),
        messages,
        want_json,
        cfg.temperature if temperature is None else temperature,
        max_tokens or cfg.max_tokens,
        cfg.timeout or DEFAULT_TIMEOUT,
    )


JSON_ATTEMPTS = 3


def chat_json(messages, purpose=None, attempts=JSON_ATTEMPTS, **kw):
    """Chat, insisting on a JSON object back.

    Retries on unparseable output. This is not defensive padding -- models
    genuinely corrupt their own JSON mid-generation. Measured against
    gemini-2.5-flash at temperature 0, one query returned structurally broken
    output (a stray token spliced into a string array) on 2 of 5 identical
    calls. The corruption is non-deterministic, so a retry clears it; better
    extraction cannot, because the bytes are wrong rather than wrapped.

    On retry the model is shown its own invalid output, which measurably helps
    it self-correct rather than repeat the same glitch.
    """
    from baton.audit import log_action

    convo = list(messages)
    last_error = None

    for attempt in range(1, attempts + 1):
        raw = chat(convo, purpose=purpose, want_json=True, **kw)
        try:
            return extract_json(raw)
        except Exception as e:
            last_error = e
            log_action(
                "llm.json_parse_failed",
                status="Failed",
                actor_type="AI_AGENT",
                error=str(e)[:400],
                output={"raw": str(raw)[:1000]},
                reason=f"attempt {attempt} of {attempts}",
            )
            if attempt < attempts:
                convo = list(messages) + [
                    {"role": "assistant", "content": str(raw)[:2000]},
                    {"role": "user", "content":
                        f"That was not valid JSON ({e}). Return the corrected "
                        "JSON object only, with no commentary."},
                ]

    raise LLMCallFailed(
        f"Model returned unparseable JSON after {attempts} attempts: {last_error}"
    )


def extract_json(raw):
    """Parse JSON that may be wrapped in prose or a fenced block."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    text = str(raw)
    if "```" in text:
        # ```json ... ``` is the most common wrapper.
        chunk = text.split("```")[1]
        text = chunk[4:] if chunk.startswith("json") else chunk
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMCallFailed(f"Model did not return JSON: {str(raw)[:300]}")
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Trailing commas before a closing brace/bracket are the other common
        # malformation and are cheap to repair.
        import re
        return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))


@frappe.whitelist()
def test_model(name):
    """Settings-page connectivity check. Returns {ok, message, latency_ms}."""
    import time

    frappe.only_for(["System Manager", "Sales Manager"])
    cfg = frappe.get_doc("Baton AI Model", name)
    started = time.time()
    try:
        reply = chat(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            config=cfg,
            max_tokens=16,
        )
        return {
            "ok": True,
            "message": (reply or "").strip()[:120],
            "latency_ms": int((time.time() - started) * 1000),
        }
    except Exception as e:
        return {"ok": False, "message": str(e)[:400], "latency_ms": int((time.time() - started) * 1000)}
