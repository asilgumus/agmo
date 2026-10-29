# AGMO — AI Guided Machine Optimizer

Terminale özel, **Windows / macOS / Linux** üçünü destekleyen AI destekli PC analiz ve hızlandırma
aracı. PC'yi yavaşlatan **gerçek nedenleri** bulur; odaktaki oyuna (örn. Valorant) asla
"yavaşlatıcı" demez — onu taban çizgisinden **hariç tutup** kalan süreçlerden çözüm üretir:

> *“Valorant açık; bunu saymazsak RAM kullanımı %32. Yüksek kullanım şuradan geliyor: …”*

## Kurulum & Çalıştırma

Tek bağımlılık `psutil` (Python ≥ 3.9). Yol:

```bash
./run.sh scan                # Linux / macOS  (ilk çalıştırmada .venv kurar)
.\run.ps1 scan               # Windows PowerShell
```

## Komutlar

| Komut | Ne yapar |
|---|---|
| `agmo scan` | Donanım + süreç örneği alır, taban çizgisi + bulgular + AI yorumu basar |
| `agmo scan --focus Valorant` | Oyunu elle tanımlar (odak algılanamadığında); gerçekten açıksa hariç tutulur |
| `agmo scan --offline` | AI katmanını atla, yalnız yerel motor |
| `agmo scan --json` | JSON çıktısı (başka araçlara pipo et) |
| `agmo watch --every 30` | Canlı izleme; ≥300 MiB artan süreçleri işaretler |
| `agmo doctor --ai` | Toplayıcı sağlığı + anahtar/model testi |
| `agmo config --set-key xai-...` veya `AQ.…` | Anahtarı `~/.config/agmo/config.toml` (mod 0600) yazar |
| `agmo kill PID --yes` | Süreç sonlandır — sistem-kritik & anti-cheat **reddedilir** |
| `agmo clean-cache --yes` | Güvenli önbellek temizliği (`~/.cache`, `%TEMP%`, `~/Library/Caches`) |

Ek `scan` bayrakları: `--no-storage` (disk taramasını atla — hızlı), `--no-color`,
`--model gemini-2.0-flash` (modeli sabitle).

## AI Anahtarı (Gemini varsayılan, Grok/xAI alternatif)

Yerel motor anahtarsız da çalışır. AI yorumu için iki sağlayıcı desteklenir; sağlayıcı
**anahtar önekinden otomatik seçilir**, istersen `agmo config --set-provider gemini|xai` ile sabitle.

- **Gemini (Google)** — [aistudio.google.com](https://aistudio.google.com/apikey). Anahtarlar
  `AIza…` önekiyle gelir; Google Code Assist tipi `AQ.…` anahtarları da kabul edilir.
  Öncelik: `GEMINI_API_KEY` → `GOOGLE_API_KEY` → `~/.config/agmo/config.toml`.
- **Grok (xAI)** — [console.x.ai](https://console.x.ai) → API Keys. Anahtarlar daima `xai-`
  önekiyle başlar; konsol arayüzündeki kimlik/dize parçaları (örn. UUID görünümlü "key id")
  **gizli anahtar değildir**. Öncelik: `AGMO_XAI_API_KEY` → `XAI_API_KEY` → `GROK_API_KEY` → dosya.

```bash
export GEMINI_API_KEY="AIza…"   # veya "AQ.…" (Gemini) / "xai-…" (Grok)
agmo config --set-key "AIza…"   # kalıcı (chmod 0600)
agmo config --set-provider gemini  # opsiyonel sabitleme (otomatik algıyı geçersiz kılar)
agmo doctor --ai                # anahtar + model + ping testi
agmo scan --offline             # test etmeden önce AI'sız doğrula
```

Model otomatik seçilir: Gemini için `gemini-3.5-flash` → `gemini-flash-latest` → `gemini-2.5-flash`
→ … (sağlayıcının model listesinden, TTS/görüntü/gemma modelleri dışlanır); Grok için
`grok-4-fast` → `grok-4-1-fast` → `grok-4` → …
Anahtar yoksa/hatalıysa rapor AI bölümü yerine *“AI katmanı çalışmadı”* notuyla **yerel analizle tamamlanır**
— asla kırılmaz.

> Güvenlik: anahtar depoya asla yazılmaz; payload gönderilmeden önce kullanıcı adı/yol bilgisi
> (`/home/…`, `C:\Users\…`) temizlenir.

## “Oyun hariç” yöntemi

1. **Odak algılama** — Hyprland/Sway/GNOME/X11, Windows `GetForegroundWindow`, macOS `frontmost`.
   Wayland'ta algılanamadığında `--focus` ile elle verilir.
2. **Ayrıcalıklı küme** — odaktaki oyun + anti-cheat (oyun kapalıyken bile) + aynı markanın launcher'ı.
   Farklı aile launcher'ları (örn. Riot oyunu açıkken Steam) taban çizgisinde kalır.
3. **Taban çizgisi** — ayrıcalıklı kümenin RAM'i toplanır, CPU'su çekirdek sayısına normalize edilir;
   kalan “PC'yi gerçekten kastıranlar” üzerinden bulgular üretilir.
4. **Donanım kalibrasyonu** — RAM/çekirdek/HDD/ssd/laptop'a göre eşikler değişir
   (8 GiB → %50 uyarı; 32 GiB → %70; HDD sistem diski ayrı bulgu; laptop 90°C termal eşik vb.).

## Testler

```bash
./run.sh -m unittest discover -s tests   # ya da .venv/bin/python -m unittest discover -s tests
```

91 test: sınıflandırıcı tuzakları (Valorant/Vanguard/cod-vs-VSCodium), hariç-tutma matematiği,
eşik kalibrasyonu, bulgu kuralları, payload gizliliği, rapor smoke testleri, sağlayıcı/anahtar
katmanı (Gemini önek algılama, env önceliği, MAX_TOKENS kesilme düşüşü).

## Durum & dürüstlük notu

- **Linux** bu makinede gerçek uçtan uca doğrulandı (Fedora 44, i7-1360P).
- **Windows / macOS** gerçek OS'lerde doğrulandı (CI matrisi yeşil):
  `.github/workflows/ci.yml` her push'ta `ubuntu` + `windows` + `macos` runner'larında
  test paketi + `agmo doctor` + `agmo scan --offline` koşar. Kanıtlanan yollar:
  Win32 odak algılama (`WindowsTerminal.exe`, kaynak: win32), winreg/GameDVR, osascript/pmset,
  sysctl CPU modeli, diskutil SSD tespiti.
  - *Mock testler*: `tests/test_platform_collectors.py` OS çağrılarının parsing mantığını her platformda sınar
    (bu testler zaten gerçek bir bug yakalayıp düzeltti: Spotlight "Indexing disabled" yanlış okuması).
- Bilinen sınırlama: GNOME Wayland oturumunda odak penceresi varsayılan izinlerle okunamayabilir
  (`--focus` alternatifi rapora yazılır).

## Dosya düzeni

```
agmo/
  classify.py      bilgi tabanı (oyun/anticheat/launcher/sistem imzaları, never-kill)
  hardware.py      donanım toplama (CPU/GPU/disk ortam türü/pil; 3 OS)
  analyze.py       taban çizgisi + bulgu kuralları + donanım kalibrasyonu
  ai.py            Gemini/xAI katmanı (JSON şeması, scrub, fallback)
  report.py        terminal raporu + JSON çıktısı
  actions.py       kill / clean-cache (onaylı, never-kill korumalı)
  config.py        anahtar/sağlayıcı/model yapılandırması (env > 0600 dosya)
  collectors/      linux.py · windows.py · macos.py · common.py
tests/             factories + 91 unit test
run.sh / run.ps1   venv önyükleme
```