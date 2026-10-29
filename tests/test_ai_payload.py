"""AI katmanı payload testleri: kullanıcı adı temizliği, JSON uyumluluk."""
import json
import unittest

from agmo import ai
from agmo.analyze import analyze
from tests.factories import make_hw, make_proc, make_snapshot


def _analysis():
    snap = make_snapshot([make_proc("Chrome", 1200, cpu=5, key="chrome", kind="browser")],
                         used_pct=65)
    return analyze(snap, make_hw(16), include_storage=False)


class TestScrub(unittest.TestCase):
    def test_home_dir_scrubbed(self):
        home = "/home/asil"
        self.assertNotIn(home, ai.scrub("cmd: /home/asil/.cache/foo"))

    def test_windows_user_scrubbed(self):
        out = ai.scrub("C:\\Users\\Asil\\AppData\\Local\\foo")
        self.assertNotIn("Asil", out)
        self.assertIn("C:\\Users\\USER", out)


class TestPayload(unittest.TestCase):
    def test_payload_is_valid_json(self):
        a = _analysis()
        payload = json.loads(ai.build_payload(a.snapshot, make_hw(16), a))
        self.assertIn("taban_cizgisi", payload)
        self.assertIn("odak_oyun", payload)

    def test_payload_no_user_paths(self):
        payload = ai.build_payload(_analysis().snapshot, make_hw(16), _analysis())
        self.assertNotIn("/home/asil", payload)


class TestJsonExtraction(unittest.TestCase):
    def test_fenced_json(self):
        txt = "selam\n```json\n{\"a\": 1}\n```\ntamam"
        self.assertEqual(ai._extract_json(txt), {"a": 1})

    def test_balanced_braces(self):
        txt = 'önce metin {"a": {"b": 2}} sonra'
        self.assertEqual(ai._extract_json(txt), {"a": {"b": 2}})

    def test_no_json_returns_none(self):
        self.assertIsNone(ai._extract_json("burada json yok"))


class TestSeverityValidation(unittest.TestCase):
    def test_unknown_severity_clamped_to_medium(self):
        self.assertEqual(ai._valid_sev("ultra"), "medium")

    def test_valid_severity_kept(self):
        self.assertEqual(ai._valid_sev("HIGH"), "high")
        self.assertEqual(ai._valid_sev("critical"), "critical")


if __name__ == "__main__":
    unittest.main()