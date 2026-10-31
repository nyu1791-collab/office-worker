"""Gemini 呼び出しの薄いラッパー。キー未設定なら None を返し、呼び出し側がテンプレにフォールバックする。
- 429/5xx は指数バックオフで再試行
- モデル名が廃止(404)なら gemini-flash-latest（常に最新Flashを指すエイリアス）に自動切替"""
import json
import os
import re
import time

_client = None
FALLBACK_MODEL = "gemini-flash-latest"


def _get_client():
    global _client
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return None
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=key)
    return _client


def _parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        return json.loads(m.group(0)) if m else None


def ask(prompt: str, system: str | None = None, json_mode: bool = False, temperature: float = 0.7, retries: int = 4):
    client = _get_client()
    if client is None:
        return None
    from google.genai import errors, types
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
    )
    model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    for i in range(retries):
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
            text = resp.text or ""
            return _parse_json(text) if json_mode else text.strip()
        except errors.APIError as e:
            code = getattr(e, "code", 0) or 0
            if code == 404 and model != FALLBACK_MODEL:
                print(f"  モデル {model} が使えないため {FALLBACK_MODEL} に切替")
                model = FALLBACK_MODEL
                continue
            if code in (429, 500, 502, 503, 504) and i < retries - 1:
                time.sleep(2 ** (i + 1) * 3)
                continue
            raise
        except json.JSONDecodeError:
            if i < retries - 1:
                continue
            return None
