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
| `agmo config --set-key xai-...` | Anahtarı `~/.config/agmo/config.toml` (mod 0600) yazar |
| `agmo kill PID --yes` | Süreç sonlandır — sistem-kritik & anti-cheat **reddedilir** |
| `agmo clean-cache --yes` | Güvenli önbellek temizliği (`~/.cache`, `%TEMP%`, `~/Library/Caches`) |

Ek `scan` bayrakları: `--no-storage` (disk taramasını atla — hızlı), `--no-color`,
`--model grok-4-fast` (modeli sabitle).

## Grok (xAI) Anahtarı

Yerel motor anahtarsız da çalışır; AI yorumu için **gerçek gizli anahtar** gerekir —
[console.x.ai](https://console.x.ai) → API Keys. Anahtarlar daima `xai-` önekiyle başlar;
konsol arayüzündeki kimlik/dize parçaları (örn. UUID görünümlü "key id") **gizli anahtar değildir**.

Tanımlama sırası: `AGMO_XAI_API_KEY` → `XAI_API_KEY` → `GROK_API_KEY` → `~/.config/agmo/config.toml`.

```bash
export XAI_API_KEY="xai-…"      # oturum içi
agmo config --set-key "xai-…"   # kalıcı (chmod 0600)
agmo scan --offline             # test etmeden önce AI'sız doğrula
```

Model otomatik seçilir (`grok-4-fast` → `grok-4-1-fast` → `grok-4` → …, `/v1/models` listesinden).
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

49 test: sınıflandırıcı tuzakları (Valorant/Vanguard/cod-vs-VSCodium), hariç-tutma matematiği,
eşik kalibrasyonu, bulgu kuralları, payload gizliliği, rapor smoke testleri.

## Durum & dürüstlük notu

- **Linux** bu makinede gerçek uçtan uca doğrulandı (Fedora 44, i7-1360P).
- **Windows / macOS** iki yolla test edilir:
  - *CI*: `.github/workflows/ci.yml` push'ta `windows-latest` + `macos-latest` (gerçek OS) runner'larında
    test paketi + `agmo doctor` + `agmo scan --offline` koşar — ctypes/winreg/osascript yolları gerçekten çalışır.
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
  ai.py            xAI/Grok katmanı (JSON şeması, scrub, fallback)
  report.py        terminal raporu + JSON çıktısı
  actions.py       kill / clean-cache (onaylı, never-kill korumalı)
  config.py        anahtar/model yapılandırması (env > 0600 dosya)
  collectors/      linux.py · windows.py · macos.py · common.py
tests/             factories + 49 unit test
run.sh / run.ps1   venv önyükleme
```