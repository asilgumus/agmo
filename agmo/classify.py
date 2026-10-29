"""Oyun/uygulama bilgi tabanı: kimin oyuna dahil olduğu, kimin sistemin
kritik parçası olduğu, kimin arka plan gürültüsü olduğu.

Tasarım ilkesi: odaktaki oyun (örn. Valorant) ve zorunlu bileşenleri
(Vanguard, Riot Client) ASLA "yavaşlatıcı" olarak etiketlenmez; onlar
"bilgi amaçlı kaynak tüketimi" olarak raporlanır ve taban çizgisinden
hariç tutulur. Gerçek bulgular kalan süreçlerden çıkarılır.
"""
from __future__ import annotations

import re
from typing import List, Set, Tuple

# ---------------------------------------------------------------- imzalar
# (anahtar, tür, aile, basename kümesi, içerir-öbekleri)
# basename eşleşmesi lowercase; içerir-öbekleri ad/argv üzerinde kelime
# sınırıyla aranır (Linux'ta 15 karakterlik comm kırpılmalarını yakalar).
Signature = Tuple[str, str, str, Set[str], Tuple[str, ...]]

GAMES: List[Signature] = [
    ("valorant", "game", "riot", {"valorant-win64.exe", "valorant-win64.sh", "valorant-win64beta.sh"}, ("valorant",)),
    ("league", "game", "riot", {"leagueclient.exe", "leagueclientux.exe", "league of legends.exe", "leagueclientbox.exe", "lcm.exe"}, ("league of legends", "leagueclient")),
    ("cs2", "game", "valve", {"cs2.exe", "cs2", "cs2_linux", "cs2_osx64", "csgo.exe", "csgo_osx64", "csgo"}, ("counter-strike",)),
    ("ue-shipping", "game", "", set(), ("-win64-shipping",)),  # Unreal Engine oyunları (jenerik)
    ("fortnite", "game", "epic", set(), ("fortniteclient",)),
    ("apex", "game", "ea", {"r5apex.exe", "r5apex_dx12.exe", "r5aapex.exe"}, ("apex legends",)),
    ("cod", "game", "activision", {"cod.exe", "codcw.exe", "cod23-cod.exe", "blackops4.exe", "modernwarfare.exe"}, ("call of duty",)),
    ("gta", "game", "rockstar", {"gta5.exe", "playgtav.exe", "gtavlauncher.exe", "fivem.exe", "rdr2.exe", "rdr2pro.exe"}, ("grand theft auto", "fivem")),
    ("overwatch", "game", "blizzard", {"overwatch.exe"}, ("overwatch",)),
    ("wow", "game", "blizzard", {"wow.exe", "wowclassic.exe", "wow-64.exe"}, ("world of warcraft",)),
    ("dota2", "game", "valve", {"dota2.exe", "dota2", "dota_ui.exe"}, ("dota 2",)),
    ("tf2", "game", "valve", {"hl2.exe", "hl2_linux"}, ("team fortress",)),
    ("rust", "game", "facepunch", {"rustclient.exe", "rustclient"}, ("rustclient",)),
    ("pubg", "game", "krafton", {"tslgame.exe"}, ("pubg", "playerunknown")),
    ("genshin", "game", "hoyoverse", {"genshinimpact.exe", "yuanshen.exe", "starrail.exe", "hkrpg.exe", "zenlesszonezero.exe"}, ("genshin", "star rail", "zenless")),
    ("minecraft", "game", "mojang", {"minecraftlauncher.exe", "minecraftlauncher", "minecraft.exe", "minecraft"}, ("minecraft",)),
    ("roblox", "game", "roblox", {"robloxplayerbeta.exe", "robloxstudio.exe"}, ("roblox",)),
    ("baldurs", "game", "larian", {"bg3.exe", "bg3_dx11.exe", "bg3_lnx.sh"}, ("baldur",)),
    ("eldenring", "game", "fromsoft", {"eldenring.exe"}, ("elden ring",)),
    ("cyberpunk", "game", "cdprojekt", {"cyberpunk2077.exe"}, ("cyberpunk",)),
    ("sims", "game", "ea", {"ts4_x64.exe", "ts4.exe"}, ("the sims",)),
    ("osu", "game", "osu", {"osu!.exe", "osu!lazer.exe", "osu"}, ("osu!",)),
    ("rocketleague", "game", "epic", {"rocketleague.exe"}, ("rocket league",)),
    ("paradox", "game", "paradox", {"stellaris.exe", "hoi4.exe", "victoria3.exe", "ck3.exe", "eu4.exe"}, ("hearts of iron",)),
    ("dbd", "game", "behaviour", {"deadbydaylight.exe"}, ("dead by daylight",)),
    ("warframe", "game", "digitalextremes", {"warframe.x64.exe"}, ("warframe",)),
    ("palworld", "game", "pocketpair", {}, ("palworld",)),
    ("bethesda", "game", "bethesda", {"skyrimse.exe", "skyrim64.exe", "fallout4.exe"}, ("skyrim", "fallout")),
]

ANTICHEAT: List[Signature] = [
    ("vanguard", "anticheat", "riot", {"vgc.exe", "vgc", "vgtray.exe", "vgtray"}, ("vanguard",)),
    ("eac", "anticheat", "ac-eos", {"easyanticheat.exe", "easyanticheat_eos.exe", "easyanticheat"}, ("easyanticheat",)),
    ("battleye", "anticheat", "ac-battleye", {"beservice.exe", "beservice_x64.exe"}, ("battleye",)),
    ("faceit-ac", "anticheat", "faceit", {"faceitclient.exe", "faceitservice.exe"}, ("faceit",)),
]

LAUNCHERS: List[Signature] = [
    ("steam", "launcher", "steam", {"steam.exe", "steam", "steamwebhelper.exe", "steamservice.exe"}, ("steamwebhelper",)),
    ("epic-launcher", "launcher", "epic", {"epicgameslauncher.exe", "epicgameslauncher"}, ()),
    ("riot-client", "launcher", "riot", {"riotclientservices.exe", "riotclientux.exe", "riotclient.exe"}, ("riot client", "riotclient")),
    ("battlenet", "launcher", "blizzard", {"battle.net.exe", "battlenet.exe"}, ("battle.net",)),
    ("ea-app", "launcher", "ea", {"eadesktop.exe", "eabackgroundservice.exe", "origin.exe", "originclient.exe"}, ("ea desktop",)),
    ("ubisoft", "launcher", "ubisoft", {"upc.exe", "ubisoftconnect.exe"}, ("ubisoft connect",)),
]

BROWSERS: List[Signature] = [
    ("chrome", "browser", "google", {"chrome.exe", "chrome", "chromium", "chromium.exe", "chromium-browser", "chrome-sandbox"}, ("google chrome",)),
    ("edge", "browser", "microsoft", {"msedge.exe", "msedge"}, ()),
    ("firefox", "browser", "mozilla", {"firefox.exe", "firefox", "firefox-bin", "firefox-esr"}, ()),
    ("brave", "browser", "brave", {"brave.exe", "brave", "brave-browser"}, ()),
    ("vivaldi", "browser", "vivaldi", {"vivaldi.exe", "vivaldi-bin", "vivaldi-stable"}, ()),
    ("opera", "browser", "opera", {"opera.exe", "opera"}, ()),
    ("arc", "browser", "browsercompany", {"arc.exe", "arc"}, ()),
]

IDE_DEV: List[Signature] = [
    ("vscode", "ide", "microsoft", {"code.exe", "code", "code-oss", "codium", "vscodium.exe", "vscodium"}, ("visual studio code",)),
    ("visualstudio", "ide", "microsoft", {"devenv.exe", "devenv"}, ()),
    ("jetbrains", "ide", "jetbrains", {"idea64.exe", "idea", "pycharm64.exe", "pycharm", "webstorm64.exe", "clion64.exe", "datagrip64.exe", "rider64.exe", "studio64.exe"}, ("jetbrains",)),
    ("clangd", "dev-server", "lsp", {"clangd", "clangd.exe"}, ()),
    ("rust-analyzer", "dev-server", "lsp", {"rust-analyzer"}, ()),
    ("gopls", "dev-server", "lsp", {"gopls"}, ()),
    ("tsserver", "dev-server", "lsp", {"tsserver"}, ()),
    ("pyright", "dev-server", "lsp", {"pyright-langserver"}, ()),
    ("node", "dev-server", "node", {"node.exe", "node"}, ()),
    ("java", "dev-server", "jvm", {"java.exe", "java", "javaw.exe", "javaw"}, ()),
]

DEVVM: List[Signature] = [
    ("docker", "devvm", "docker", {"docker", "docker.exe", "dockerd", "containerd", "com.docker.backend", "com.docker.backend.exe", "docker-desktop", "docker-desktop.exe"}, ()),
    ("wsl", "devvm", "wsl", {"vmmem", "vmmemwsl", "vmmemvsdata", "vmmemcompose", "wsl.exe", "wsl", "wslhost.exe", "wslservice.exe", "wslg.exe"}, ("wsl",)),
    ("qemu", "devvm", "kvm", set(), ("qemu-system",)),
    ("vmware", "devvm", "vmware", {"vmware-vmx", "vmware-vmx.exe", "vmplayer", "vmplayer.exe"}, ()),
    ("virtualbox", "devvm", "oracle", {"virtualboxvm", "virtualboxvm.exe", "virtualbox", "virtualbox.exe"}, ()),
    ("podman", "devvm", "podman", {"podman", "podman.exe"}, ()),
]

AV: List[Signature] = [
    ("defender", "av", "microsoft", {"msmpeng.exe", "msmpeng"}, ("antimalware service executable",)),
    ("defender-ui", "av", "microsoft", {"securityhealthservice.exe", "securityhealthsystray.exe", "mssense.exe"}, ()),
    ("avast", "av", "avast", {"avastsvc.exe", "avastui.exe", "avast"}, ("avast",)),
]

INDEXER: List[Signature] = [
    ("winsearch", "indexer", "microsoft", {"searchindexer.exe", "searchindexer", "searchapp.exe", "searchapp"}, ()),
    ("spotlight", "indexer", "apple", {"mds", "mds_stores", "mdworker", "mdworker_shared", "mdworkerd"}, ("mdworker",)),
    ("apple-photos", "indexer", "apple", {"photoanalysisd", "mediaanalysisd"}, ()),
    ("tracker", "indexer", "gnome", {"localsearch", "localsearch-3", "tracker3", "tracker-miner-fs-3", "tracker-extract-3"}, ("tracker-miner", "localsearch")),
    ("baloo", "indexer", "kde", {"baloo_file", "baloo_file_extractor"}, ("baloo",)),
    ("updatedb", "indexer", "linux", {"updatedb", "updatedb.mlocate", "plocate"}, ()),
]

CLOUD: List[Signature] = [
    ("onedrive", "cloud", "microsoft", {"onedrive.exe", "onedrive"}, ()),
    ("gdrive", "cloud", "google", {"googledrivefs.exe", "googledrivefs"}, ("google drive",)),
    ("dropbox", "cloud", "dropbox", {"dropbox.exe", "dropbox"}, ()),
    ("icloud", "cloud", "apple", {"bird", "clouddocs"}, ()),
    ("nextcloud", "cloud", "nextcloud", {"nextcloud.exe"}, ()),
]

UPDATERS: List[Signature] = [
    ("squirrel-updater", "updater", "generic", {"update.exe", "update"}, ()),  # Electron/Squirrel: Discord, Slack, Brave vb.
    ("mac-updater", "updater", "apple", {"softwareupdated"}, ()),
    ("snapd", "updater", "linux", {"snapd"}, ()),
    ("packagekit", "updater", "linux", {"packagekitd", "packagekit"}, ("packagekit",)),
    ("nvidia-exp", "updater", "nvidia", {"nvcontainer.exe", "nvcontainer"}, ()),
]

COMMS: List[Signature] = [
    ("discord", "comms", "discord", {"discord.exe", "discord"}, ()),
    ("telegram", "comms", "telegram", {"telegram.exe", "telegram-desktop", "telegram desktop"}, ()),
    ("whatsapp", "comms", "meta", {"whatsapp.exe", "whatsapp"}, ()),
    ("signal", "comms", "signal", {"signal.exe", "signal"}, ()),
    ("slack", "comms", "salesforce", {"slack.exe", "slack"}, ()),
    ("teams", "comms", "microsoft", {"teams.exe", "ms-teams"}, ()),
    ("zoom", "comms", "zoom", {"zoom.exe", "zoom"}, ()),
]

MEDIA: List[Signature] = [
    ("spotify", "media", "spotify", {"spotify.exe", "spotify"}, ()),
]

SYSTEM_UI: List[Signature] = [
    ("dwm", "system", "microsoft", {"dwm.exe"}, ()),  # Desktop Window Manager
    ("explorer", "system", "microsoft", {"explorer.exe"}, ()),
    ("widgets", "system", "microsoft", {"widgets.exe", "widgetboard.exe"}, ()),
    ("svchost", "system", "microsoft", {"svchost.exe"}, ()),
    ("msedgewebview", "system", "microsoft", {"msedgewebview2.exe"}, ()),
    ("gnome-shell", "system", "gnome", {"gnome-shell"}, ()),
    ("kwin", "system", "kde", {"kwin_wayland", "kwin_x11", "plasmashell", "kded6", "kded5"}, ()),
    ("waybar", "system", "wayland", {"waybar"}, ()),
    ("hyprland", "system", "wayland", {"hyprland", "hyprpaper", "hyprlock"}, ()),
    ("mac-windowserver", "system", "apple", {"windowserver"}, ()),
    ("mac-ui", "system", "apple", {"dock", "finder", "notificationcenter", "controlcenter"}, ()),
]

SYSTEM_CRITICAL: List[Signature] = [
    ("win-critical", "system-critical", "microsoft", {
        "system", "system idle process", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
        "lsass.exe", "smss.exe", "registry", "memory compression", "fontdrvhost.exe", "conhost.exe",
        "taskhostw.exe", "spoolsv.exe", "wudfhost.exe", "logonui.exe", "sihost.exe", "ctfmon.exe",
        "searchprotocolhost.exe", "searchfilterhost.exe", "runtimebroker.exe", "audiodg.exe",
    }, ()),
    ("linux-core", "system-critical", "linux", {
        "systemd", "systemd-journald", "systemd-udevd", "systemd-logind", "systemd-resolved",
        "systemd-networkd", "systemd-timesyncd", "systemd-oomd", "init", "dbus-daemon",
        "dbus-broker", "dbus", "dbus-broker-launch", "polkitd", "upowerd", "udisksd",
        "networkmanager", "wpa_supplicant", "iwd", "firewalld", "pipewire", "pipewire-pulse",
        "wireplumber", "pulseaudio", "rtkit-daemon", "gdm", "sddm", "lightdm",
        "xdg-desktop-portal", "xdg-desktop-portal-gnome", "xdg-desktop-portal-gtk",
        "xdg-desktop-portal-hyprland", "xdg-desktop-portal-wlr", "gvfsd", "dconf-service",
        "chronyd", "thermald", "xorg", "xwayland", "login", "sshd", "kthreadd", "kernel",
    }, ()),
    ("mac-core", "system-critical", "apple", {
        "launchd", "coreservicesd", "sysmond", "kernel_task", "distnoted", "cfprefsd",
        "securityd", "trustd", "logind",
    }, ()),
]

SERVICE_MISC: List[Signature] = [
    ("cups", "service", "linux", {"cupsd", "cups-browsed", "cups"}, ()),
    ("bluetoothd", "service", "linux", {"bluetoothd"}, ()),
    ("btrfs", "service", "linux", {"btrfs-cleaner", "btrfs-trim", "btrfs-scrub", "btrfs"}, ("btrfs scrub",)),
]

ALL_SIGNATURES: List[Signature] = (
    GAMES + ANTICHEAT + LAUNCHERS + BROWSERS + IDE_DEV + DEVVM + AV + INDEXER
    + CLOUD + UPDATERS + COMMS + MEDIA + SYSTEM_UI + SYSTEM_CRITICAL + SERVICE_MISC
)

NEVER_KILL_KINDS = {"system", "system-critical", "service"}
NEVER_KILL_KEYS = {"vanguard", "eac", "battleye"}  # anti-cheat: kill = ban/çökme riski

# ------------------------------------------------------------ bilgi kartları
KIND_TR = {
    "game": "Oyun",
    "game-suspect": "Oyun olabilir",
    "anticheat": "Anti-cheat",
    "launcher": "Başlatıcı",
    "browser": "Tarayıcı",
    "ide": "Editör/IDE",
    "dev-server": "Geliştirme sunucusu",
    "devvm": "Sanal makine/Konteyner",
    "av": "Antivirüs/Güvenlik",
    "indexer": "Dizinleyici",
    "cloud": "Bulut senkronu",
    "updater": "Güncelleyici",
    "comms": "İletişim",
    "media": "Medya",
    "system": "Sistem arayüzü",
    "system-critical": "Sistem (kritik)",
    "service": "Sistem servisi",
    "unknown": "Bilinmeyen",
}

LABELS = {
    "valorant": "Valorant",
    "vanguard": "Riot Vanguard",
    "riot-client": "Riot Client",
    "league": "League of Legends",
    "ue-shipping": "Unreal Engine oyunu",
    "winsearch": "Windows Search dizinleyici",
    "spotlight": "Spotlight dizinleyici",
    "apple-photos": "Fotoğraf analizi (macOS)",
    "tracker": "LocalSearch/Tracker (GNOME dizinleyici)",
    "baloo": "Baloo (KDE dizinleyici)",
    "defender": "Windows Defender",
    "onedrive": "OneDrive",
    "gdrive": "Google Drive",
    "icloud": "iCloud Drive",
    "dwm": "Desktop Window Manager",
    "gnome-shell": "GNOME Shell",
    "kwin": "KWin/Plasma",
    "mac-windowserver": "WindowServer (macOS)",
    "mac-ui": "macOS arayüzü",
    "wsl": "WSL2 / vmmem",
    "docker": "Docker",
    "steam": "Steam",
    "squirrel-updater": "Electron güncelleyici",
    "msedgewebview": "WebView2 (widget host)",
    "svchost": "Windows hizmet konağı (svchost)",
}

# Uygulama/türlere özel öneri metinleri (bulgu "fixes" alanında kullanılır)
APP_FIX_HINTS = {
    "winsearch": "Ayarlar > Arama > 'Windows Arama'yı geliştir > kapsamdan klasör çıkar; SearchIndexer yeniden dizin oluştururken oyunda stutter tetikleyebilir.",
    "spotlight": "Terminal: `sudo mdutil -i off /` geçici kapama (aramayı tekrar istediğinde `mdutil -i on /`). Yeniden indeksleme CPU+diski tıkayabilir.",
    "tracker": "GNOME dosya araması tracker/localsearch kaynaklarını tüketebilir: indekslenen klasörleri sınırla veya kullanıcı servisine systemd resource limit uygula.",
    "baloo": "Sistem Ayarları > Baloo Dosya Arama > büyük medya klasörlerini hariç tutulanlara ekle veya `balooctl6 suspend`.",
    "defender": "Defender tam tarama sürüyor olabilir. 'Virüs ve tehdit koruması > Tarama seçenekleri' ile taramayı oyun saatlerinin dışına planla; oyun klasörünü istisna ekleme kararı bir güvenlik ticaretidir, önermeyiz.",
    "onedrive": "Bulut simgesine sağ tık > 'Geçici olarak duraklat'; oyun dışı saatlerde devam ettir.",
    "gdrive": "Google Drive uygulamasından senkronizasyonu duraklat.",
    "dropbox": "Dropbox > Preferences > Pause syncing (oyun sırasında).",
    "icloud": "Sistem Ayarları > iCloud > Drive senkronunu geçici duraklat.",
    "dwm": "GPU sürücüsünü güncelle, görünüm efektlerini (şeffaflık/animasyon) azalt; yüksek Hz ekranda tarayıcı GPU hızlandırmayı test et.",
    "gnome-shell": "`gnome-extensions list` ile eklentileri gözden geçir; masaüstü efekti/izleme eklentileri CPU basar.",
    "kwin": "Plasma: pencere efektlerini (blur/şeffaflık) azalt.",
    "mac-windowserver": "Sistem Ayarları > Erişilebilirlik > Görüntü > 'Şeffaflığı azalt' + 'İşlemi azalt'; birleşik pencere sayısını düşür.",
    "wsl": "Dev yapmıyorsan `wsl --shutdown`. Uyarı: açık WSL terminalleri kapanır.",
    "docker": "Docker Desktop çalışıyor: dev yapmıyorsan sistem tepsisinden 'Quit Docker Desktop'.",
    "steam": "Steam arka planda çok disk IO yapıyorsa indirme sürüyor olabilir: Ayarlar > İndirmeler > otomatik güncellemeleri oyun dışı saatlere taşı.",
    "discord": "Discord: Ayarlar > Gelişmiş > Donanım ivmelenmesi ve oyun içi overlay'i kapat.",
    "squirrel-updater": "Electron uygulama güncelleyicisi arka planda indirme yapıyor olabilir; birkaç dakika sonra yeniden ölç.",
    "msedgewebview": "Windows widget paneli WebView2 konaklarını ayakta tutar: görev çubuğuna sağ tık > Widget'ları göster'i kapat.",
    "svchost": "svchost toplamı yüksekse Görev Yöneticisi > Süreçler > svchost'u genişlet, hangi hizmet (wuauserv/BITS/SysMain) bastığına bak; kalıcıysa hizmet bazında ele al.",
    "explorer": "Explorer CPU basıyorsa hızlı erişim klasörlerini azalt, pencere/klasör sayısını makul tut.",
    "spotify": "Arka planda müzik bilinçli olabilir; kalıntı CPU/RAM yüksekse tepsiden tamamen çık.",
    "node": "Arka planda kalmış dev sunucuları (npm/next/webpack) olabilir; kullanmıyorsan terminalde kapat.",
    "java": ["JVM süreci: IntelliJ/Gradle daemon olabilir. Kullanmıyorsan proje kökünde `./gradlew --stop`."],
    "snapd": "snapd arka planda paket yenileme kontrolü yapar; kalıcıysa `snap refresh --hold`.",
    "packagekit": "PackageKit arka planda paket kontrolü yapar; dnf/apt ile çakışırsa `systemctl mask packagekit` (yazılım merkezi etkilenebilir, dikkatli).",
    "btrfs": "Btrfs scrub/TRIM sürüyor olabilir: `journalctl -u btrfs-scrub` ile bak; tamamlanmasını bekle (bakım işi).",
    "apple-photos": "macOS Fotoğraflar kütüphaneyi analiz ediyor; arka planda saatler sürebilir, beklet veya ayarlardan duraklat.",
    "mac-updater": "macOS arka planda güncelleme indiriyor olabilir; istersen otomatik indirmeleri kapatıp manuel yap.",
    "nvidia-exp": "NVIDIA App/GeForce Experience sürücü indirebilir; başlangıç öğelerinden kaldırmak temizlik olur.",
    "telegram": "Telegram arka planda medya indiriyor olabilir: Ayarlar > Gelişmiş > Otomatik medya indirmeyi sınırla.",
    "whatsapp": "WhatsApp masaüstü medya senkronu: otomatik indirmeyi sınırla.",
    "teams": "Teams arka planda ciddi kaynak basan uygulamadır (özellikle klasik Teams); görüşme yoksa tamamen kapat.",
}

# ------------------------------------------------------------- eşleştirme
# (minecraft-savvy: java ailesi adları match_signature içinde sabit tutulur)
JAVA_FAMILY_NAMES = ("java", "javaw", "javaw.exe", "javaws")


def _contains_hit(haystack: str, needle: str) -> bool:
    """"cod" kısa jetonu kelime sınırıyla aranır (VSCodium'u yakalamasın).

    Sınır kontrolü yalnızca harf/rakamla başlayıp biterse uygulanır;
    "-win64-shipping" gibi tireli öbeklere dokunulmaz.
    """
    n = needle.lower()
    pattern = r"(?<![a-z0-9])" if n[0].isalnum() else ""
    pattern += re.escape(n)
    if n[-1].isalnum():
        pattern += r"(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def match_signature(names: Set[str], cmdline: str) -> Tuple[str, str, str]:
    """(key, kind, family) → eşleşme yoksa ("unknown", "unknown", "")."""
    joined = " ".join(n.lower() for n in names)[:400]
    cmd = cmdline.lower()[:2000]

    # java/javaw + minecraft argv -> oyun (yalnız java ailesinde; argv geçişine
    # dokunmayan süreçler 'minecraft' sözüyle oyun sanılmaz)
    java_names = set(JAVA_FAMILY_NAMES)
    if (any(n.lower().split(".")[0] in java_names for n in names)
            and _contains_hit(cmd, "minecraft")):
        return "minecraft", "game", "mojang"

    # tam ad eşleşmesi (öncelikli)
    for key, kind, family, basenames, _contains in ALL_SIGNATURES:
        for name in names:
            if name.lower() in basenames:
                return key, kind, family

    # içerir-öbekleri: yalnızca süreç adları üzerinde (Linux'ta kırpılmış adları
    # yakalar). Komut satırına bakmak — örn. '--focus Valorant' argv'sı taşıyan
    # kabuk sarmalayıcıları yanlışlıkla oyun diye sınıflandırır — bu yüzden kapatıldı.
    for key, kind, family, _basenames, contains in ALL_SIGNATURES:
        for c in contains:
            if _contains_hit(joined, c):
                return key, kind, family
    return "unknown", "unknown", ""


def friendly_label(key: str, raw_name: str, kind: str) -> str:
    if key in LABELS:
        return LABELS[key]
    return raw_name or KIND_TR.get(kind, kind)


def is_never_kill(key: str, kind: str) -> bool:
    return kind in NEVER_KILL_KINDS or key in NEVER_KILL_KEYS