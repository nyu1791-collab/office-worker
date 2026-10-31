"""LLM 呼び出しの薄いラッパー（Gemini / OpenRouter）。キー未設定なら None を返し、呼び出し側がテンプレにフォールバックする。
- LLM_PROVIDER=gemini|openrouter（未指定ならキーがある方。両方あれば gemini）
- images=[パス|bytes|PIL画像] で画像も渡せる（OCR・画像説明用）
- 429/5xx は指数バックオフで再試行。Gemini のモデル名が廃止(404)なら gemini-flash-latest に自動切替"""
import base64
import io
import json
import os
import re
import time
from pathlib import Path

_client = None
FALLBACK_MODEL = "gemini-flash-latest"


def provider():
    p = (os.getenv("LLM_PROVIDER") or "").lower()
    if p:
        return p
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    return None


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
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        return json.loads(m.group(0)) if m else None


def _image_bytes(img):
    """-> (bytes, mime)"""
    if isinstance(img, (bytes, bytearray)):
        return bytes(img), "image/png" if bytes(img[:4]) == b"\x89PNG" else "image/jpeg"
    if isinstance(img, (str, Path)):
        p = Path(img)
        return p.read_bytes(), "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    buf = io.BytesIO()  # PIL.Image
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue(), "image/png"


def _gemini(prompt, system, json_mode, temperature, images):
    from google.genai import errors, types
    client = _get_client()
    cfg = types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                      response_mime_type="application/json" if json_mode else None)
    contents = [types.Part.from_bytes(data=b, mime_type=m) for b, m in map(_image_bytes, images or [])] + [prompt]
    model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    try:
        return client.models.generate_content(model=model, contents=contents, config=cfg).text or ""
    except errors.APIError as e:
        if getattr(e, "code", 0) == 404 and model != FALLBACK_MODEL:
            print(f"  モデル {model} が使えないため {FALLBACK_MODEL} に切替")
            os.environ["GEMINI_MODEL"] = FALLBACK_MODEL
            return client.models.generate_content(model=FALLBACK_MODEL, contents=contents, config=cfg).text or ""
        raise _Retryable(e) if getattr(e, "code", 0) in (429, 500, 502, 503, 504) else e


def _openrouter(prompt, system, json_mode, temperature, images):
    import requests
    content = [{"type": "text", "text": prompt}]
    for b, m in map(_image_bytes, images or []):
        content.append({"type": "image_url", "image_url": {"url": f"data:{m};base64,{base64.b64encode(b).decode()}"}})
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
    body = {"model": os.getenv("OPENROUTER_MODEL") or "google/gemini-2.5-flash", "messages": msgs, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", json=body, timeout=180,
                      headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    if r.status_code in (429, 500, 502, 503, 504):
        raise _Retryable(RuntimeError(f"OpenRouter HTTP {r.status_code}"))
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


class _Retryable(Exception):
    pass


def ask(prompt: str, system: str | None = None, json_mode: bool = False, temperature: float = 0.7,
        retries: int = 4, images=None):
    p = provider()
    if p not in ("gemini", "openrouter") or (p == "gemini" and _get_client() is None) or \
            (p == "openrouter" and not os.getenv("OPENROUTER_API_KEY")):
        return None
    call = _gemini if p == "gemini" else _openrouter
    for i in range(retries):
        try:
            text = call(prompt, system, json_mode, temperature, images)
            if not json_mode:
                return text.strip()
            parsed = _parse_json(text)
            if parsed is not None or i == retries - 1:
                return parsed
        except _Retryable as e:
            if i == retries - 1:
                raise e.args[0] if e.args else e
            time.sleep(2 ** (i + 1) * 3)
        except json.JSONDecodeError:
            if i == retries - 1:
                return None
    return None
