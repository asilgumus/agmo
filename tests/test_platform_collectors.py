"""Windows/macOS toplayıcı mantık testleri — OS çağrıları sahte çıktılarla.

Gerçek API koşumu (ctypes/winreg/osascript) CI matrisinde gerçek OS'lerde yapılır
(.github/workflows/ci.yml); bu dosya parsing kararlarını her platformda sınar.
"""
import os
import tempfile
import unittest
from unittest import mock

from agmo.collectors import macos, windows


class FakeRegKey:
    def __init__(self, values: dict):
        self.values = dict(values)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    """winreg API ikizi: OpenKey → bağlam yöneticisi, QueryValueEx/EnumValue."""
    HKEY_CURRENT_USER = "HCU"
    HKEY_LOCAL_MACHINE = "HKLM"

    def __init__(self, mapping: dict):
        self.mapping = mapping  # {(root, path): {değer adı: değer}}

    def OpenKey(self, root, path):
        key = self.mapping.get((root, path))
        if key is None:
            raise OSError("anahtar yok")
        return FakeRegKey(key)

    def QueryValueEx(self, key, name):
        if name not in key.values:
            raise OSError("değer yok")
        return key.values[name], 4

    def EnumValue(self, key, i):
        names = sorted(key.values)
        if i >= len(names):
            raise OSError("bitti")
        return names[i], key.values[names[i]], 1


def _fake_run(outputs: dict):
    def fake(cmd, timeout=8.0):
        c = " ".join(cmd)
        for needle, out in outputs.items():
            if needle in c:
                return out
        return None
    return fake


class TestWindowsParsing(unittest.TestCase):
    def test_powercfg_scheme_parsed(self):
        out = "Güç düzeni GUID: 381b4222-69fa-4f16-ab6c-cb6a9dbb53f8  (Yüksek performans)"
        with mock.patch.object(windows, "run", _fake_run({"powercfg": out})), \
                mock.patch.object(windows, "winreg", None):
            r = windows.collect_extras()
        self.assertEqual(r["power"]["scheme"], "Yüksek performans")
        self.assertNotIn("scheme_hint", r["power"])

    def test_power_saver_hint(self):
        out = "Güç düzeni GUID: 1111  (Güç tasarrufu)"
        with mock.patch.object(windows, "run", _fake_run({"powercfg": out})), \
                mock.patch.object(windows, "winreg", None):
            r = windows.collect_extras()
        self.assertEqual(r["power"]["scheme"], "Güç tasarrufu")
        self.assertEqual(r["power"]["scheme_hint"], "power-saver")

    def test_gamedvr_read(self):
        fake = FakeWinreg({("HCU", r"System\GameConfigStore"): {"GameDVR_Enabled": 1},
                           ("HCU", r"Software\Microsoft\GameBar"): {"AutoGameModeEnabled": 0}})
        with mock.patch.object(windows, "run", _fake_run({})), \
                mock.patch.object(windows, "winreg", fake):
            r = windows.collect_extras()
        self.assertTrue(r["extras"]["gamedvr_enabled"])
        self.assertFalse(r["extras"]["gamemode_enabled"])

    def test_startup_items_merged(self):
        fake = FakeWinreg({("HCU", r"Software\Microsoft\Windows\CurrentVersion\Run"):
                           {"Anki": 1, "Steam": 1},
                           ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"):
                           {"OneDrive": 1}})
        with mock.patch.object(windows, "run", _fake_run({})), \
                mock.patch.object(windows, "winreg", fake):
            r = windows.collect_extras()
        self.assertEqual(r["boot"]["startup_items"], ["Anki", "OneDrive", "Steam"])
        self.assertEqual(r["boot"]["startup_count"], 3)

    def test_missing_keys_do_not_crash(self):
        with mock.patch.object(windows, "run", _fake_run({})), \
                mock.patch.object(windows, "winreg", FakeWinreg({})):
            r = windows.collect_extras()  # hiç anahtar yoksa sessiz boş döner
        self.assertNotIn("gamedvr_enabled", r["extras"])


class TestMacosParsing(unittest.TestCase):
    def test_osascript_frontmost(self):
        with mock.patch.object(macos, "run",
                               _fake_run({"osascript": '4242, "Brave"'})):
            info = macos.get_foreground()
        self.assertIsNotNone(info)
        self.assertEqual(info.pid, 4242)
        self.assertEqual(info.proc_name, "Brave")
        self.assertEqual(info.source, "osascript")

    def test_osascript_garbage_returns_none(self):
        with mock.patch.object(macos, "run", _fake_run({"osascript": ""})):
            self.assertIsNone(macos.get_foreground())

    def test_manual_focus_passthrough(self):
        info = macos.get_foreground("Valorant")
        self.assertEqual(info.label, "Valorant")
        self.assertEqual(info.source, "manual")

    def test_thermal_throttle_detected(self):
        out = "CPU_Speed_Limit = 50\nCPU_Speed_Limit = 50"
        with mock.patch.object(macos, "run", _fake_run({"pmset -g therm": out})):
            m = macos._thermal_state()
        self.assertIsNotNone(m)
        self.assertIn("%50", m)

    def test_no_throttle(self):
        out = "CPU_Speed_Limit = 100\n"
        with mock.patch.object(macos, "run", _fake_run({"pmset -g therm": out})):
            self.assertIsNone(macos._thermal_state())

    def test_spotlight_states(self):
        with mock.patch.object(macos, "run",
                               _fake_run({"mdutil": "/:\n\tIndexing enabled.\n"})):
            self.assertEqual(macos._spotlight_state(), "indexing")
        with mock.patch.object(macos, "run",
                               _fake_run({"mdutil": "/:\n\tIndexing disabled for volume.\n"})):
            self.assertEqual(macos._spotlight_state(), "disabled")

    def test_pmset_lowpowermode(self):
        with mock.patch.object(macos, "run",
                               _fake_run({"pmset": " lowpowermode         1\n"})):
            r = macos.collect_extras()
        self.assertTrue(r["power"]["lowpowermode"])

    def test_launchagents_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            la = os.path.join(tmp, "Library", "LaunchAgents")
            os.makedirs(la)
            for name in ("com.apple.finder.plist", "com.backupd.pv.plist"):
                open(os.path.join(la, name), "w").close()
            with mock.patch.dict(os.environ, {"HOME": tmp}):
                r = macos.collect_extras()
        self.assertEqual(r["boot"]["login_items_count"], 2)


if __name__ == "__main__":
    unittest.main()