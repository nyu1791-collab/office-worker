"""Gemini 呼び出しの薄いラッパー。キー未設定なら None を返し、呼び出し側がテンプレにフォールバックする。"""
import json
import os
import re

_client = None


def _get_client():
    global _client
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return None
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=key)
    return _client


def ask(prompt: str, system: str | None = None, json_mode: bool = False, temperature: float = 0.7):
    client = _get_client()
    if client is None:
        return None
    from google.genai import types
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
    )
    resp = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), contents=prompt, config=cfg
    )
    text = resp.text or ""
    if json_mode:
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        return json.loads(m.group(0) if m else text)
    return text.strip()
