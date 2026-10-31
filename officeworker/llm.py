"""LLM 呼び出し（Gemini 中心、必要な用途だけ OpenRouter）。3リポジトリ共通・同じ内容。

使い方:  ask(prompt, task="write")              … 文章
         ask(prompt, json_mode=True, task="extract")
         ask(prompt, images=[...], task="ocr")   … 画像入力
         ask_sources(prompt, task="research")    … Google 検索で裏付け → (結果, [{"title","uri"}])
キー未設定・安全フィルタで止まった時は None（呼び出し側がテンプレ等にフォールバック）。

用途(task)ごとの切替（.env、未指定なら共通設定）:
  GEMINI_MODEL=gemini-2.5-flash            共通モデル
  GEMINI_MODEL_WRITE=gemini-2.5-pro        例: 記事だけ高精度に
  LLM_PROVIDER_TRANSLATE=openrouter        例: 翻訳だけ別モデル（成人向け作品で Gemini が止まる場合）
  OPENROUTER_MODEL_TRANSLATE=...           その時のモデル
  GEMINI_SAFETY=relaxed                    安全フィルタを「高のみブロック」に緩める（既定は API の標準）
task: research / write / translate / ocr / extract / fast
"""
import base64
import io
import json
import os
import re
import time
from pathlib import Path

_client = None
FALLBACK_MODEL = "gemini-flash-latest"
DEFAULT_MODEL = "gemini-2.5-flash"
_warned = set()


def _env(name, task):
    return (os.getenv(f"{name}_{task.upper()}") if task else None) or os.getenv(name)


def provider(task=None):
    p = (_env("LLM_PROVIDER", task) or "").lower()
    if p:
        return p
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    return None


def model(task=None):
    if provider(task) == "openrouter":
        return _env("OPENROUTER_MODEL", task) or "google/gemini-2.5-flash"
    return _env("GEMINI_MODEL", task) or DEFAULT_MODEL


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


class Blocked(Exception):
    """安全フィルタ等で生成されなかった"""


class _Retryable(Exception):
    pass


def _gemini(prompt, system, json_mode, temperature, images, task, search):
    from google.genai import errors, types
    client = _get_client()
    kw = dict(system_instruction=system, temperature=temperature)
    if search:  # Google 検索で裏付け。検索ツールと JSON 指定は併用できないので JSON はプロンプトで指示
        kw["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    elif json_mode:
        kw["response_mime_type"] = "application/json"
    if (os.getenv("GEMINI_SAFETY") or "").lower() == "relaxed":
        kw["safety_settings"] = [types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH)
                                 for c in (types.HarmCategory.HARM_CATEGORY_HARASSMENT, types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                                           types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT)]
    cfg = types.GenerateContentConfig(**kw)
    contents = [types.Part.from_bytes(data=b, mime_type=m) for b, m in map(_image_bytes, images or [])] + [prompt]
    name = model(task)
    try:
        resp = client.models.generate_content(model=name, contents=contents, config=cfg)
    except errors.APIError as e:
        code = getattr(e, "code", 0) or 0
        if code == 404 and name != FALLBACK_MODEL:
            print(f"  モデル {name} が使えないため {FALLBACK_MODEL} に切替")
            os.environ["GEMINI_MODEL"] = FALLBACK_MODEL
            for k in [k for k in os.environ if k.startswith("GEMINI_MODEL_")]:
                if os.environ[k] == name:
                    os.environ[k] = FALLBACK_MODEL
            resp = client.models.generate_content(model=FALLBACK_MODEL, contents=contents, config=cfg)
        elif code in (429, 500, 502, 503, 504):
            raise _Retryable(e)
        else:
            raise
    fb = getattr(resp, "prompt_feedback", None)
    cand = (resp.candidates or [None])[0]
    reason = str(getattr(cand, "finish_reason", "") or "")
    if (fb and getattr(fb, "block_reason", None)) or any(r in reason for r in ("SAFETY", "PROHIBITED", "BLOCKLIST", "SPII")):
        raise Blocked(str(getattr(fb, "block_reason", "") or reason))
    sources = []
    gm = getattr(cand, "grounding_metadata", None)
    for ch in (getattr(gm, "grounding_chunks", None) or []):
        web = getattr(ch, "web", None)
        if web and web.uri:
            sources.append({"title": web.title or web.domain or "", "uri": web.uri})
    return resp.text or "", sources


def _openrouter(prompt, system, json_mode, temperature, images, task, search):
    import requests
    content = [{"type": "text", "text": prompt}]
    for b, m in map(_image_bytes, images or []):
        content.append({"type": "image_url", "image_url": {"url": f"data:{m};base64,{base64.b64encode(b).decode()}"}})
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
    name = model(task) + (":online" if search and not model(task).endswith(":online") else "")
    body = {"model": name, "messages": msgs, "temperature": temperature}
    if json_mode and not search:
        body["response_format"] = {"type": "json_object"}
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", json=body, timeout=180,
                      headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    if r.status_code in (429, 500, 502, 503, 504):
        raise _Retryable(RuntimeError(f"OpenRouter HTTP {r.status_code}"))
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    sources = [{"title": a["url_citation"].get("title", ""), "uri": a["url_citation"]["url"]}
               for a in (msg.get("annotations") or []) if a.get("type") == "url_citation"]
    return msg.get("content") or "", sources


def _available(p):
    return (p == "gemini" and _get_client() is not None) or (p == "openrouter" and bool(os.getenv("OPENROUTER_API_KEY")))


def ask_sources(prompt: str, system: str | None = None, json_mode: bool = False, temperature: float = 0.7,
                retries: int = 4, images=None, task: str | None = None, search: bool = True):
    """-> (結果 or None, 出典リスト)"""
    p = provider(task)
    if not _available(p):
        return None, []
    call = _gemini if p == "gemini" else _openrouter
    for i in range(retries):
        try:
            text, sources = call(prompt, system, json_mode or False, temperature, images, task, search)
            if not json_mode:
                return text.strip(), sources
            parsed = _parse_json(text)
            if parsed is not None or i == retries - 1:
                return parsed, sources
        except Blocked as e:
            key = (task, str(e))
            if key not in _warned:
                _warned.add(key)
                hint = f"LLM_PROVIDER_{(task or '').upper()}=openrouter" if task else "LLM_PROVIDER=openrouter"
                print(f"  [LLM] {task or ''} が安全フィルタで止まりました（{e}）。この用途だけ別モデルにするなら .env に {hint}")
            return None, []
        except _Retryable as e:
            if i == retries - 1:
                raise e.args[0] if e.args else e
            time.sleep(2 ** (i + 1) * 3)
        except json.JSONDecodeError:
            if i == retries - 1:
                return None, []
    return None, []


def ask(prompt: str, system: str | None = None, json_mode: bool = False, temperature: float = 0.7,
        retries: int = 4, images=None, task: str | None = None, search: bool = False):
    return ask_sources(prompt, system, json_mode, temperature, retries, images, task, search)[0]


TASKS = ("research", "write", "translate", "ocr", "extract", "fast")


def check(search=True):
    """接続確認: 用途ごとの接続先・モデルと、実際に1回呼べるか"""
    lines = []
    for t in TASKS:
        p = provider(t)
        lines.append(f"  {t:<9} → {p or '未設定'} / {model(t) if p else '-'}" + ("" if _available(p) else "  ※キー無し"))
    print("用途ごとの接続先:\n" + "\n".join(lines))
    if not provider():
        print("✗ GEMINI_API_KEY（または OPENROUTER_API_KEY）が未設定です")
        return False
    ok = ask('「OK」とだけ返してください', temperature=0, retries=2)
    print(f"{'✓' if ok else '✗'} 文章生成: {ok!r}")
    if search:
        res, src = ask_sources("今日の日付と、日本の主要ニュースを1つ、1行で", temperature=0, retries=2, task="research")
        print(f"{'✓' if src else '△'} 検索での裏付け: 出典{len(src)}件 {src[0]['uri'][:60] + '…' if src else ''}")
    return bool(ok)
