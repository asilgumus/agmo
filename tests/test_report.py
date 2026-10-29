"""Rapor üreteci smoke testleri."""
import unittest

from agmo.analyze import analyze
from agmo.report import render, render_json
from tests.factories import make_hw, make_proc, make_snapshot


def _analysis(game: bool = False):
    procs = [make_proc("Chrome", 1200, cpu=5, key="chrome", kind="browser")]
    if game:
        procs.append(make_proc("Valorant", 3000, cpu=40, key="valorant", kind="game",
                               family="riot", names=["VALORANT-Win64.exe"], gpu_mib=2200))
    snap = make_snapshot(procs, used_pct=70 if game else 60)
    return analyze(snap, make_hw(16), include_storage=False)


class TestRender(unittest.TestCase):
    def test_render_smoke_plain(self):
        out = render(_analysis(), make_hw(16), color=False)
        self.assertIn("Taban çizgisi", out)
        self.assertIn("Bulgular", out)

    def test_render_game_exclusion_shown(self):
        a = _analysis(game=True)
        out = render(a, make_hw(16), color=False)
        self.assertIn("Valorant hariç", out)
        # oyunun kendisi bulgu başlığında suçlanmaz
        for f in a.findings:
            self.assertNotIn("Valorant", f.title)

    def test_render_ai_off_section(self):
        a = _analysis()
        a.ai = {"status": "off", "detail": "anahtar yok"}
        out = render(a, make_hw(16), color=False)
        self.assertIn("AI", out)

    def test_render_json_smoke(self):
        import json
        data = json.loads(render_json(_analysis(), make_hw(16)))
        self.assertIn("baseline", data)
        self.assertIn("findings", data)


if __name__ == "__main__":
    unittest.main()