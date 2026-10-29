"""Analiz motoru testleri: hariç-tutma matematiği, eşik kalibrasyonu, bulgular."""
import unittest

from agmo.analyze import analyze, thresholds
from agmo.classify import match_signature
from tests.factories import make_hw, make_proc, make_snapshot


def valorant_like(mem: float = 3000.0, cpu: float = 40.0):
    return make_proc("Valorant", mem, cpu, key="valorant", kind="game", family="riot",
                     names=["VALORANT-Win64.exe"], gpu_mib=2200)


class TestThresholds(unittest.TestCase):
    def test_small_ram_lower_thresholds(self):
        t = thresholds(make_hw(ram_gib=8))
        self.assertEqual((t.mem_warn, t.mem_crit), (50.0, 66.0))

    def test_big_ram_higher_thresholds(self):
        self.assertEqual((thresholds(make_hw(32)).mem_warn), 70.0)
        self.assertEqual((thresholds(make_hw(64)).mem_warn), 76.0)

    def test_few_cores_lower_cpu_threshold(self):
        self.assertEqual(thresholds(make_hw(cores_logical=4)).cpu_warn, 52.0)

    def test_hdd_system_detected(self):
        t = thresholds(make_hw(hdd=True))
        self.assertTrue(t.hdd_system)
        self.assertEqual(t.disk_w_warn_mib_s, 6.0)


class TestBaselineExclusion(unittest.TestCase):
    """Kullanıcının ana isteği: 'Valorant açıkken (on hariç) RAM %X'."""

    def test_game_excluded_from_baseline(self):
        gw = valorant_like(mem=3000)
        snap = make_snapshot([gw], ram_gib=16, used_pct=80)  # 12.3 GiB kullanım
        hw = make_hw(ram_gib=16)
        a = analyze(snap, hw, include_storage=False)
        b = a.baseline
        self.assertTrue(ctx_game_running(a))
        self.assertAlmostEqual(b.exempt_mem_mib, 3000, places=0)
        expected_pct = (snap.mem_used_mib - 3000) / snap.mem_total_mib * 100
        self.assertAlmostEqual(b.base_mem_pct, expected_pct, delta=0.5)
        self.assertEqual(b.game_label, "Valorant")
        self.assertIn("Valorant hariç", b.line)

    def test_game_not_blamed_in_findings(self):
        gw = valorant_like(mem=3000, cpu=90)
        snap = make_snapshot([gw], ram_gib=16, used_pct=80)
        a = analyze(snap, make_hw(16), include_storage=False)
        for f in a.findings:
            self.assertNotIn("Valorant", f.title)
            self.assertNotIn("valorant", f.id)

    def test_anticheat_excluded_even_without_game(self):
        vgc = make_proc("Riot Vanguard", 60, 0, key="vanguard", kind="anticheat",
                        family="riot", names=["vgc.exe"])
        snap = make_snapshot([vgc], used_pct=70)
        a = analyze(snap, make_hw(16), include_storage=False)
        self.assertEqual(a.baseline.exempt_mem_mib, 60)

    def test_riot_client_excluded_only_with_game(self):
        client = make_proc("Riot Client", 400, 2, key="riot-client", kind="launcher",
                           family="riot", names=["RiotClientServices.exe"])
        # 1) game yokken hariç DEĞİL
        a1 = analyze(make_snapshot([client], used_pct=70), make_hw(16), include_storage=False)
        self.assertEqual(a1.baseline.exempt_mem_mib, 0)
        # 2) game varken hariç
        a2 = analyze(make_snapshot([client, valorant_like()], used_pct=70),
                     make_hw(16), include_storage=False)
        self.assertAlmostEqual(a2.baseline.exempt_mem_mib, 400 + 3000, delta=1)

    def test_steam_does_not_inherit_riot_exemption(self):
        steam = make_proc("Steam", 400, 2, key="steam", kind="launcher", family="steam",
                          names=["steam.exe"])
        a = analyze(make_snapshot([steam, valorant_like()], used_pct=70),
                    make_hw(16), include_storage=False)
        # steam riot ailesinden değil -> taban çizgisinde kalır
        self.assertAlmostEqual(a.baseline.exempt_mem_mib, 3000, delta=1)

    def test_unknown_gpu_proc_treated_as_game(self):
        proc = make_proc("MysteryGame", 2500, 45, key="unknown", kind="unknown",
                         names=["MysteryGame.exe"], gpu_mib=1800)
        # isim zaten ue-shipping sig'ında olmadığından kind unknown kalmalı
        k, kind, _ = match_signature({"MysteryGame-Xyz.exe"}, "")
        self.assertEqual(kind, "unknown")
        a = analyze(make_snapshot([proc], used_pct=80), make_hw(16), include_storage=False)
        self.assertTrue(a.baseline.exempt_mem_mib >= 2500 - 1)

    def test_cpu_normalized_by_cores(self):
        game = valorant_like(mem=3000, cpu=700)  # 16T makinede çok çekirdekli oyun
        chrome = make_proc("Chrome", 2000, cpu=600, key="chrome", kind="browser")
        snap = make_snapshot([game, chrome], used_pct=70, cpu_total=90)
        a = analyze(snap, make_hw(ram_gib=16, cores_logical=16), include_storage=False)
        # (600)/16 = 37.5% → hariç tutulmuş CPU taban çizgisi
        self.assertAlmostEqual(a.baseline.base_cpu_pct, 37.5, delta=0.5)
        self.assertLessEqual(a.baseline.base_cpu_pct, 100.0)


class TestFindings(unittest.TestCase):
    def test_baseline_mem_finding_on_small_machine(self):
        chrome = make_proc("Chrome", 1600, key="chrome", kind="browser")  # 8.5 GiB
        snap = make_snapshot([chrome], ram_gib=8, used_pct=85)  # 6.5 GiB → %81 → crit
        a = analyze(snap, make_hw(ram_gib=8), include_storage=False)
        ids = [f.id for f in a.findings]
        self.assertIn("baseline-mem", ids)

    def test_cloud_sync_high_while_gaming(self):
        od = make_proc("OneDrive", 300, io_w=4.0, key="onedrive", kind="cloud")
        snap = make_snapshot([od, valorant_like()], used_pct=60)
        a = analyze(snap, make_hw(16), include_storage=False)
        f = {x.id: x for x in a.findings}.get("cloud-sync-onedrive")
        self.assertIsNotNone(f)
        self.assertEqual(f.severity, "high")  # oyun açıkken yükselir

    def test_no_findings_in_healthy_state(self):
        proc = make_proc("Spotify", 250, cpu=1, key="spotify", kind="media")
        snap = make_snapshot([proc], used_pct=45, cpu_total=5)
        a = analyze(snap, make_hw(16), include_storage=False)
        hard = [f for f in a.findings if f.severity in ("high", "critical")]
        self.assertEqual(hard, [])

    def test_hdd_upgrade_hint(self):
        snap = make_snapshot([], used_pct=50)
        a = analyze(snap, make_hw(16, hdd=True), include_storage=False)
        self.assertIn("system-hdd", [f.id for f in a.findings])

    def test_swap_pressure(self):
        proc = make_proc("Chrome", 1200, key="chrome", kind="browser")
        snap = make_snapshot([proc], used_pct=70, swap_used_mib=4000, swap_total_mib=8192)
        a = analyze(snap, make_hw(16), include_storage=False)
        self.assertIn("swap-pressure", [f.id for f in a.findings])

    def test_steam_download_note(self):
        steam = make_proc("Steam", 400, io_w=25.0, key="steam", kind="launcher")
        snap = make_snapshot([steam], used_pct=50)
        a = analyze(snap, make_hw(16), include_storage=False)
        self.assertIn("launcher-io-steam", [f.id for f in a.findings])

    def test_power_saver_while_gaming(self):
        game = valorant_like()
        snap = make_snapshot([game], used_pct=60, cpu_total=10)
        snap.power = {"governor": "powersave", "plugged": True}
        a = analyze(snap, make_hw(16, laptop=True), include_storage=False)
        self.assertIn("power-mode", [f.id for f in a.findings])


def ctx_game_running(analysis):
    return analysis.baseline.game_label is not None


if __name__ == "__main__":
    unittest.main()