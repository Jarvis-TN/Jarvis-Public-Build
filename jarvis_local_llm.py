"""Jarvis local-LLM brain - a private, offline conversational tier.

Talks to a LOCAL OpenAI-compatible chat endpoint, so the runtime is swappable:
  * Ollama          http://localhost:11434/v1   (easiest default; wraps llama.cpp)
  * llama.cpp server / LM Studio / vLLM / TabbyAPI(ExLlama)  - all expose /v1 too
Point `local_llm_base_url` at whichever is fastest on your hardware - no code
change. The model just needs tool-calling support (llama3.1, qwen2.5, mistral,
etc.) to use Jarvis's tools.

Dependency-light: plain `requests`. This is the middle tier between the cloud
Claude brain (online) and the deterministic offline handler (jarvis_offline).
"""

import json
import requests


def openai_tools(anthropic_tools):
    """Convert Jarvis's Anthropic-style tool schemas to OpenAI 'function' tools."""
    out = []
    for t in anthropic_tools or []:
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def available(base_url, timeout=1.5):
    """Is a local OpenAI-compatible server reachable?"""
    try:
        r = requests.get(base_url.rstrip("/") + "/models", timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def chat(base_url, model, messages, tools=None, temperature=0.6,
         max_tokens=1024, api_key="local", timeout=120):
    """One /v1/chat/completions call. Returns the parsed JSON response."""
    payload = {
        "model": model, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens, "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post(base_url.rstrip("/") + "/chat/completions",
                      json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()
