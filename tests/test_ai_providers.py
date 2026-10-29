"""Sağlayıcı katmanı testleri: Gemini/xAI seçimi, env önceliği, model çözümü,
yanıt ayrıştırma (thought parçası + MAX_TOKENS kesilmesi) ve düşüş davranışı."""
from __future__ import annotations

import json
import os
import unittest
import urllib.error
from unittest import mock

from agmo import ai as mod
from agmo import config as config_mod
from agmo.config import DEFAULT_MODEL, get_ai_config
from tests.factories import make_hw, make_proc, make_snapshot


# ---------- provider_of / base_of ----------

class TestProviderOf(unittest.TestCase):
    def test_prefix_aq_is_gemini(self):
        self.assertEqual(mod.provider_of({"api_key": "AQ.Ab3x", "provider": None}), "gemini")

    def test_prefix_aiza_is_gemini(self):
        self.assertEqual(mod.provider_of({"api_key": "AIzaSy0", "provider": None}), "gemini")

    def test_prefix_xai_is_xai(self):
        self.assertEqual(mod.provider_of({"api_key": "xai-abc", "provider": None}), "xai")

    def test_unknown_key_defaults_to_xai(self):
        self.assertEqual(mod.provider_of({"api_key": "sk-whatever", "provider": None}), "xai")

    def test_explicit_config_overrides_prefix(self):
        cfg = {"api_key": "xai-abc", "provider": "gemini"}
        self.assertEqual(mod.provider_of(cfg), "gemini")
        cfg = {"api_key": "AQ.x", "provider": "grok"}
        self.assertEqual(mod.provider_of(cfg), "xai")

    def test_base_urls(self):
        self.assertEqual(mod.base_of({}, "gemini"), mod.GEMINI_BASE)
        self.assertEqual(mod.base_of({}, "xai"), mod.XAI_BASE)
        self.assertEqual(mod.base_of({"base_url": "http://proxy/v1/"}, "xai"), "http://proxy/v1")


# ---------- get_ai_config: env önceliği (dosya yoksa) ----------

class TestConfigEnv(unittest.TestCase):
    def setUp(self):
        # hermetik: gerçek config.toml dosyasına bakılmasın
        self.pat = mock.patch.object(config_mod, "CONFIG_PATH", "/nonexistent/agmo/config.toml")
        self.pat.start()
        self.addCleanup(self.pat.stop)

    def test_env_precedence_gemini_before_xai(self):
        env = {"GEMINI_API_KEY": "AQ.g", "XAI_API_KEY": "xai-x"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = get_ai_config()
            self.assertEqual(cfg["api_key"], "AQ.g")
            self.assertEqual(mod.provider_of(cfg), "gemini")

    def test_env_precedence_google_before_xai(self):
        env = {"GOOGLE_API_KEY": "AIzaSy0", "XAI_API_KEY": "xai-x"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = get_ai_config()
            self.assertEqual(cfg["api_key"], "AIzaSy0")

    def test_xai_env_used_when_no_gemini(self):
        env = {"XAI_API_KEY": "xai-x", "GROK_API_KEY": "would-lose"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = get_ai_config()
            self.assertEqual(cfg["api_key"], "xai-x")

    def test_default_model_is_auto(self):
        self.assertEqual(DEFAULT_MODEL, "auto")
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = get_ai_config()
            self.assertEqual(cfg["model"], DEFAULT_MODEL)

    def test_agmo_model_env_override(self):
        with mock.patch.dict(os.environ, {"AGMO_MODEL": "gemini-2.0-flash"}, clear=True):
            self.assertEqual(get_ai_config()["model"], "gemini-2.0-flash")


# ---------- istek gövdesi / yanıt ayrıştırma ----------

class TestGeminiRequestShape(unittest.TestCase):
    def test_body_json_mode_adds_response_mime(self):
        body = mod._gemini_body("merhaba", True, 512)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 512)
        self.assertEqual(body["contents"], [{"role": "user", "parts": [{"text": "merhaba"}]}])
        self.assertIn("parts", body["systemInstruction"])

    def test_body_without_json_mode_has_no_mime(self):
        body = mod._gemini_body("x", False, 512)
        self.assertNotIn("responseMimeType", body["generationConfig"])


class TestGeminiText(unittest.TestCase):
    def test_joins_plain_parts(self):
        data = {"candidates": [
            {"content": {"parts": [{"text": '{"a":'}, {"text": '1}'}]}}]}
        self.assertEqual(mod._gemini_text(data), '{"a":1}')

    def test_think_part_is_skipped(self):
        data = {"candidates": [
            {"content": {"parts": [
                {"text": "içeriden düşünceler...", "thought": True},
                {"text": '{"a":1}'}]}}]}
        self.assertEqual(mod._gemini_text(data), '{"a":1}')

    def test_thought_only_yields_empty(self):
        data = {"candidates": [{"content": {"parts": [{"text": "hm", "thought": True}]}}]}
        self.assertEqual(mod._gemini_text(data), "")


class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestGeminiTruncation(unittest.TestCase):
    """MAX_TOKENS ile kesilmiş JSON düz metin gibi dolu görünür; büyüterek tekrar
    denemeli. (Gerçek taramada 'ok' başlığı + boş summary üreten senaryo.)"""

    def _url(self, base, key, model, user_text, max_tokens=2600):
        return mod._gemini_content(base, key, model, user_text, max_tokens)

    def test_max_tokens_partial_retries_with_larger_budget(self):
        partial = '{"summary": "kesilmiş...'  # ortadan kesilmiş JSON
        complete = json.dumps({"summary": "tam", "baseline_note": "bn"})
        payloads = [
            _FakeResp(json.dumps({
                "candidates": [{"content": {"parts": [{"text": partial}]},
                               "finishReason": "MAX_TOKENS"}]}).encode()),
            _FakeResp(json.dumps({
                "candidates": [{"content": {"parts": [{"text": complete}]},
                               "finishReason": "STOP"}]}).encode()),
        ]
        state = {"n": 0, "tokens": []}

        def fake_req(req, timeout=None):
            state["tokens"].append(
                json.loads(req.data.decode())["generationConfig"]["maxOutputTokens"])
            resp = payloads[state["n"]]
            state["n"] += 1
            return resp

        with mock.patch.object(mod.urllib.request, "urlopen", fake_req):
            text, detail = self._url(mod.GEMINI_BASE, "AQ.k", "gemini-3.5-flash", "p")
        self.assertEqual(text, complete)
        self.assertEqual(detail, "")
        self.assertEqual(state["tokens"], [2600, 4000])  # ilk deneme bütçesi + 1400

    def test_max_tokens_on_both_attempts_returns_best_effort(self):
        complete = json.dumps({"summary": "yine kesik ama dönen", "x": 1})[:-2]  # kesik
        payloads = [
            _FakeResp(json.dumps({"candidates": [{"content": {"parts": [{"text": complete}]},
                                                 "finishReason": "MAX_TOKENS"}]}).encode()),
            _FakeResp(json.dumps({"candidates": [{"content": {"parts": [{"text": complete}]},
                                                 "finishReason": "MAX_TOKENS"}]}).encode()),
        ]
        state = {"n": 0}

        def fake_req(req, timeout=None):
            resp = payloads[state["n"]]
            state["n"] += 1
            return resp

        with mock.patch.object(mod.urllib.request, "urlopen", fake_req):
            text, detail = mod._gemini_content(mod.GEMINI_BASE, "AQ.k", "m", "p", 2600)
        self.assertTrue(text)  # elimizdekiyle devam
        self.assertIn("MAX_TOKENS", detail)


class TestGeminiModelResolve(unittest.TestCase):
    def test_configured_model_used_verbatim(self):
        self.assertEqual(mod.resolve_model("gemini", mod.GEMINI_BASE, "k", "gemini-2.0-flash"),
                         "gemini-2.0-flash")

    def test_configured_models_prefix_stripped(self):
        self.assertEqual(mod.resolve_model("gemini", mod.GEMINI_BASE, "k", "models/gemini-2.0-flash"),
                         "gemini-2.0-flash")

    def test_auto_prefers_preference_list(self):
        with mock.patch.object(mod, "_gemini_model_ids",
                               return_value=["gemini-2.0-flash", "gemini-2.5-flash"]):
            got = mod.resolve_model("gemini", mod.GEMINI_BASE, "k", DEFAULT_MODEL)
        self.assertEqual(got, "gemini-2.5-flash")

    def test_auto_falls_back_to_token_match(self):
        with mock.patch.object(mod, "_gemini_model_ids",
                               return_value=["gemini-flash-lite-latest", "gemini-pro-1"]):
            got = mod.resolve_model("gemini", mod.GEMINI_BASE, "k", DEFAULT_MODEL)
        self.assertIn("flash-lite", got)

    def test_auto_raises_when_nothing_matches(self):
        with mock.patch.object(mod, "_gemini_model_ids", return_value=[]):
            with self.assertRaises(RuntimeError):
                mod.resolve_model("gemini", mod.GEMINI_BASE, "k", DEFAULT_MODEL)


# ---------- enrich: düşüş davranışı ----------

class TestGeminiTransientRetry(unittest.TestCase):
    """503 'high demand' gibi geçici hatalarda tek seferlik bekle-tekrar düşüşü."""

    def _ok_resp(self) -> _FakeResp:
        return _FakeResp(json.dumps({
            "candidates": [{"content": {"parts": [{"text": '{"a":1}'}]},
                           "finishReason": "STOP"}]}).encode())

    def test_503_retries_once_then_succeeds(self):
        err = urllib.error.HTTPError("u", 503, "busy", None, None)
        state = {"n": 0}

        def fake_req(req, timeout=None):
            if state["n"] == 0:
                state["n"] += 1
                raise err
            state["n"] += 1
            return self._ok_resp()

        with mock.patch.object(mod.urllib.request, "urlopen", fake_req), \
             mock.patch.object(mod.time, "sleep"):
            text, detail = mod._gemini_content(mod.GEMINI_BASE, "AQ.k", "m", "p", 2600)
        self.assertEqual(text, '{"a":1}')
        self.assertEqual(detail, "")
        self.assertEqual(state["n"], 2)

    def test_404_does_not_retry(self):
        err = urllib.error.HTTPError("u", 404, "yok", None, None)
        state = {"n": 0}

        def fake_req(req, timeout=None):
            state["n"] += 1
            raise err

        with mock.patch.object(mod.urllib.request, "urlopen", fake_req):
            text, detail = mod._gemini_content(mod.GEMINI_BASE, "AQ.k", "m", "p", 2600)
        self.assertIsNone(text)
        self.assertIn("HTTP 404", detail)
        self.assertEqual(state["n"], 1)


class TestEnrich(unittest.TestCase):
    def _analysis(self):
        proc = make_proc("brave", 900, cpu=10.0)
        snap = make_snapshot([proc], ram_gib=16.0, used_pct=50.0, cpu_total=10.0)
        hw = make_hw()
        from agmo import analyze as analyze_mod
        return analyze_mod.analyze(snap, hw, include_storage=False)

    def _cfg(self):
        return {"api_key": "AQ.k", "provider": "gemini", "model": "m", "base_url": None}

    def test_off_without_key(self):
        a = self._analysis()
        out = mod.enrich(a, make_hw(), {"api_key": None})
        self.assertEqual(out.ai["status"], "off")

    def test_parse_failure_falls_back_to_error_status(self):
        a = self._analysis()
        local_n = len(a.findings)
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = self._cfg()
            with mock.patch.object(mod, "resolve_model", return_value="m"), \
                 mock.patch.object(mod, "_chat", return_value=("bu json değil", "")):
                out = mod.enrich(a, make_hw(), cfg)
        self.assertEqual(out.ai["status"], "error")
        self.assertIn("JSON ayrıştıramadı", out.ai["detail"])
        self.assertEqual(len(out.findings), local_n)  # yerel bulgular korunur

    def test_valid_json_appends_ai_findings(self):
        a = self._analysis()
        local_n = len(a.findings)
        payload = json.dumps({
            "summary": "kısa özet",
            "baseline_note": "taban notu",
            "findings": [{"title": "AI bulgusu", "severity": "medium", "category": "memory",
                          "why": "n", "evidence": "e", "fix_steps": ["bir şey yap"], "risk": "careful"}],
        }, ensure_ascii=False)
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = self._cfg()
            with mock.patch.object(mod, "resolve_model", return_value="m"), \
                 mock.patch.object(mod, "_chat", return_value=(payload, "")):
                out = mod.enrich(a, make_hw(), cfg)
        self.assertEqual(out.ai["status"], "ok")
        self.assertEqual(out.ai["provider"], "gemini")
        self.assertEqual(out.ai["model"], "m")
        self.assertEqual(out.ai["summary"], "kısa özet")
        self.assertAlmostEqual(out.ai["baseline_note"], "taban notu")
        self.assertEqual(len(out.findings), local_n + 1)
        ai_f = out.findings[-1]
        self.assertEqual(ai_f.source, "ai")
        self.assertEqual(ai_f.severity, "medium")

    def test_invalid_severity_downgraded_to_medium(self):
        a = self._analysis()
        payload = json.dumps({
            "summary": "s", "baseline_note": "b",
            "findings": [{"title": "t", "severity": "ultra"}],
        })
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = self._cfg()
            with mock.patch.object(mod, "resolve_model", return_value="m"), \
                 mock.patch.object(mod, "_chat", return_value=(payload, "")):
                out = mod.enrich(a, make_hw(), cfg)
        self.assertEqual(out.findings[-1].severity, "medium")


if __name__ == "__main__":
    unittest.main()