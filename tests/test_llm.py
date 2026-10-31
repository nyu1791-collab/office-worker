"""LLM ラッパー（3リポジトリ共通）: 用途別の振り分け・検索の裏付け・安全フィルタ。偽の Gemini で検証、通信なし。"""
import contextlib
import io
import os
import types
import unittest
from unittest.mock import patch

from officeworker import llm


def fake_resp(text, uris=(), finish="STOP", block=None):
    chunks = [types.SimpleNamespace(web=types.SimpleNamespace(uri=u, title=f"t{i}", domain="d")) for i, u in enumerate(uris)]
    cand = types.SimpleNamespace(finish_reason=finish, grounding_metadata=types.SimpleNamespace(grounding_chunks=chunks))
    return types.SimpleNamespace(text=text, candidates=[cand], prompt_feedback=types.SimpleNamespace(block_reason=block) if block else None)


class LlmTests(unittest.TestCase):
    def setUp(self):
        env = {k: "" for k in os.environ if k.startswith(("GEMINI_", "LLM_PROVIDER", "OPENROUTER_"))}
        env["GEMINI_API_KEY"] = "k"
        p = patch.dict(os.environ, env); p.start(); self.addCleanup(p.stop)
        self.client = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=None))
        p2 = patch.object(llm, "_get_client", return_value=self.client); p2.start(); self.addCleanup(p2.stop)

    def run_with(self, resp):
        calls = []
        def gen(model, contents, config):
            calls.append((model, config)); return resp
        self.client.models.generate_content = gen
        return calls

    def test_task_model_routing(self):
        os.environ["GEMINI_MODEL_WRITE"] = "gemini-2.5-pro"
        calls = self.run_with(fake_resp('{"a": 1}'))
        self.assertEqual(llm.ask("x", json_mode=True, task="write"), {"a": 1})
        llm.ask("x", task="extract")
        self.assertEqual([c[0] for c in calls], ["gemini-2.5-pro", "gemini-2.5-flash"])
        self.assertEqual(calls[0][1].response_mime_type, "application/json")
        os.environ["LLM_PROVIDER_TRANSLATE"] = "openrouter"
        self.assertEqual(llm.provider("translate"), "openrouter")
        self.assertIsNone(llm.ask("x", task="translate"))   # OpenRouter のキー無し → None（落ちない）

    def test_search_attaches_google_search_and_returns_sources(self):
        calls = self.run_with(fake_resp('```json\n{"facts": ["新店舗"]}\n```', uris=["https://a.example/1"]))
        res, src = llm.ask_sources("x", json_mode=True, task="research")
        self.assertEqual(res, {"facts": ["新店舗"]})
        self.assertEqual(src, [{"title": "t0", "uri": "https://a.example/1"}])
        cfg = calls[0][1]
        self.assertTrue(cfg.tools and cfg.tools[0].google_search is not None)
        self.assertIsNone(cfg.response_mime_type)   # 検索ツールと JSON 指定は併用不可

    def test_safety_block_returns_none_with_hint(self):
        self.run_with(fake_resp("", finish="SAFETY"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertIsNone(llm.ask("x", task="translate"))
        self.assertIn("LLM_PROVIDER_TRANSLATE=openrouter", out.getvalue())

    def test_relaxed_safety_setting(self):
        os.environ["GEMINI_SAFETY"] = "relaxed"
        calls = self.run_with(fake_resp("ok"))
        llm.ask("x")
        self.assertEqual(len(calls[0][1].safety_settings), 4)

    def test_no_key_means_none(self):
        os.environ["GEMINI_API_KEY"] = ""
        with patch.object(llm, "_get_client", return_value=None):
            self.assertIsNone(llm.provider())
            self.assertIsNone(llm.ask("x"))


if __name__ == "__main__":
    unittest.main()
