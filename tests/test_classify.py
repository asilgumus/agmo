"""Sınıflandırıcı bilgi tabanı testleri (oyun-duyarlı tespit)."""
import unittest

from agmo import classify


class TestGames(unittest.TestCase):
    def test_valorant(self):
        self.assertEqual(classify.match_signature({"VALORANT-Win64.exe"}, "")[0:2],
                         ("valorant", "game"))
        self.assertEqual(classify.match_signature({"valorant-win64"}, "")[0], "valorant")

    def test_valve_games(self):
        self.assertEqual(classify.match_signature({"cs2"}, "")[0], "cs2")
        self.assertEqual(classify.match_signature({"dota_ui.exe"}, "")[0], "dota2")

    def test_unreal_generic(self):
        self.assertEqual(classify.match_signature({"MyGame-Win64-Shipping.exe"}, "")[0],
                         "ue-shipping")
        self.assertEqual(classify.match_signature({"MyGame-Win64-Shipping"}, "")[1], "game")

    def test_cod_is_not_vscode(self):
        # "cod" substring tuzagına düşmemeli
        self.assertNotEqual(classify.match_signature({"VSCodium"}, "")[0], "cod")
        self.assertEqual(classify.match_signature({"cod.exe"}, "")[0], "cod")
        self.assertEqual(classify.match_signature({"Code.exe"}, "")[0], "vscode")

    def test_minecraft_java(self):
        k, kind, _ = classify.match_signature({"javaw.exe"},
                                              "javaw -Xmx4G net.minecraft.client.Main")
        self.assertEqual((k, kind), ("minecraft", "game"))

    def test_java_without_minecraft_is_dev(self):
        k, kind, _ = classify.match_signature({"java"}, "java -jar gradle-runner.jar")
        self.assertEqual(kind, "dev-server")

    def test_cmdline_mention_is_not_enough(self):
        # kabuk sarmalayıcının argv'sında 'Valorant' geçmesi onu oyun yapmaz
        # (gerçek hata: bu süreç hariç tutulup 'Valorant hariç' etiketi taşıyordu)
        k, kind, _ = classify.match_signature({"zsh"}, "./run.sh scan --focus Valorant")
        self.assertNotEqual(kind, "game")

    def test_java_minecraft_argv_still_game(self):
        k, kind, _ = classify.match_signature({"java"},
                                              "java -Xmx2G -cp mods net.minecraft.launchwrapper")
        self.assertEqual((k, kind), ("minecraft", "game"))


class TestCompanions(unittest.TestCase):
    def test_vanguard(self):
        k, kind, family = classify.match_signature({"vgc.exe"}, "")
        self.assertEqual((k, kind, family), ("vanguard", "anticheat", "riot"))

    def test_riot_client(self):
        k, kind, family = classify.match_signature({"RiotClientServices.exe"}, "")
        self.assertEqual((k, kind, family), ("riot-client", "launcher", "riot"))

    def test_steam(self):
        k, kind, family = classify.match_signature({"steamwebhelper.exe"}, "")
        self.assertEqual((k, kind), ("steam", "launcher"))

    def test_never_kill(self):
        self.assertTrue(classify.is_never_kill("vanguard", "anticheat"))
        self.assertTrue(classify.is_never_kill("x", "system-critical"))
        self.assertFalse(classify.is_never_kill("chrome", "browser"))


class TestBackgroundKinds(unittest.TestCase):
    def test_defender(self):
        self.assertEqual(classify.match_signature({"MsMpEng.exe"}, "")[1], "av")

    def test_winsearch(self):
        self.assertEqual(classify.match_signature({"SearchIndexer.exe"}, "")[0], "winsearch")

    def test_tracker_truncated(self):
        # Linux 15 karakterlik comm kırpılması: tracker-miner-fs-3 -> tracker-miner-f
        k, kind, _ = classify.match_signature({"tracker-miner-f"}, "")
        self.assertEqual((k, kind), ("tracker", "indexer"))

    def test_localsearch(self):
        self.assertEqual(classify.match_signature({"localsearch-3"}, "")[0], "tracker")

    def test_onedrive(self):
        self.assertEqual(classify.match_signature({"OneDrive.exe"}, "")[1], "cloud")

    def test_critical_system(self):
        self.assertEqual(classify.match_signature({"svchost.exe"}, "")[1], "system")
        self.assertEqual(classify.match_signature({"systemd-journald"}, "")[1],
                         "system-critical")


if __name__ == "__main__":
    unittest.main()