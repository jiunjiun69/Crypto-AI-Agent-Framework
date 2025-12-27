from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

try:
    # openai>=1.0
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore
    import openai  # type: ignore

from config import (
    LLM_BACKEND,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)


def _normalized_backend() -> str:
    b = (os.getenv("LLM_BACKEND") or LLM_BACKEND or "ollama").strip().lower()
    return b if b in {"ollama", "openai"} else "ollama"


def _ollama_v1_base_url() -> str:
    """
    Ollama's OpenAI-compat API base is .../v1/
    We'll normalize whatever user puts in OLLAMA_BASE_URL.
    """
    base = (os.getenv("OLLAMA_BASE_URL") or OLLAMA_BASE_URL or "http://localhost:11434").strip()
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base + "/"


def _openai_model() -> str:
    return (os.getenv("OPENAI_MODEL") or OPENAI_MODEL or "gpt-4o-mini").strip()


def _ollama_model() -> str:
    return (os.getenv("OLLAMA_MODEL") or OLLAMA_MODEL or "llama3.2:3b").strip()


def _openai_api_key() -> str:
    return (os.getenv("OPENAI_API_KEY") or OPENAI_API_KEY or "").strip()


def _get_client() -> Any:
    backend = _normalized_backend()

    if backend == "openai":
        api_key = _openai_api_key()
        if not api_key:
            raise RuntimeError(
                "LLM_BACKEND=openai 但 OPENAI_API_KEY 是空的。請確認 .env 有被正確載入。"
            )
        if OpenAI is None:
            # legacy openai<1.0
            openai.api_key = api_key
            return openai
        return OpenAI(api_key=api_key)

    # ollama via OpenAI-compat endpoint
    base_url = _ollama_v1_base_url()
    # OpenAI python client requires a non-empty api_key string for header construction.
    # Ollama ignores it. (docs: "required but ignored")
    if OpenAI is None:
        openai.api_key = "ollama"
        openai.api_base = base_url  # type: ignore[attr-defined]
        return openai
    return OpenAI(api_key="ollama", base_url=base_url)


def _extract_json(text: str) -> Dict[str, Any]:
    """
    Try very hard to parse a JSON object from a model response.
    """
    text = text.strip()

    # remove fenced code blocks if present
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", text)
        text = re.sub(r"\n```$", "", text).strip()

    # direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # find first {...} block
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    return {"ok": False, "error": "Failed to parse JSON", "raw": text[:2000]}


def chat_text(prompt: str, *, temperature: float = 0.2) -> str:
    backend = _normalized_backend()
    client = _get_client()

    model = _openai_model() if backend == "openai" else _ollama_model()

    if OpenAI is None:
        # legacy openai<1.0
        resp = client.ChatCompletion.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return resp["choices"][0]["message"]["content"]  # type: ignore[index]

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


def chat_json(prompt: str, *, temperature: float = 0.2) -> Dict[str, Any]:
    """
    Ask the model to return a JSON object. We'll parse it defensively.
    """
    backend = _normalized_backend()
    client = _get_client()

    model = _openai_model() if backend == "openai" else _ollama_model()

    json_prompt = (
        "請你只輸出「單一 JSON object」，不要額外文字、不要 markdown。\n"
        "如果資料不足，請用 ok=false 並說明 missing 欄位。\n\n"
        f"{prompt}"
    )

    if OpenAI is None:
        resp = client.ChatCompletion.create(
            model=model,
            messages=[{"role": "user", "content": json_prompt}],
            temperature=temperature,
        )
        content = resp["choices"][0]["message"]["content"]  # type: ignore[index]
        return _extract_json(content)

    # OpenAI supports response_format json_object (Ollama docs say supported too),
    # but for maximum compatibility we still do a defensive parse.
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": json_prompt}],
            temperature=temperature,
            response_format={"type": "json_object"} if backend == "openai" else None,
        )
        content = (resp.choices[0].message.content or "").strip()
        return _extract_json(content)
    except TypeError:
        # Some backends may not accept response_format
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": json_prompt}],
            temperature=temperature,
        )
        content = (resp.choices[0].message.content or "").strip()
        return _extract_json(content)
