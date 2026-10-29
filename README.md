# AGMO

Windows, macOS ve Linux'ta çalışan PC analiz aracı. Donanımı ve süreçleri ölçer, PC'yi
gerçekten yavaşlatan şeyi bulur, düzeltme önerir. Tek bağımlılığı `psutil`.

Odakta bir oyun açıkken oyunu suçlamaz. Valorant açıkken "oyun yavaşlatıyor" demek yerine
şunu söyler:

> Valorant hariç RAM %46 — buna Brave'ın tuttuğu 3.4 GiB ve arka plandaki senkronlar
> sebep olabilir.

## Nasıl çalışır

1. **Donanım** — CPU, GPU, disk ortam türü (HDD/SSD), pil, RAM; üç OS için ayrı toplayıcı.
2. **Ölçüm** — süreç snapshot'ı + odak algılama (Wayland/Hyprland/GNOME, Windows win32, macOS frontmost).
3. **Taban çizgisi** — odaktaki oyun + anti-cheat (oyun kapalıyken bile) + aynı markanın
   launcher'ı hariç tutulur; bulgular kalan süreçlerden üretilir.
4. **AI yorumu** — ölçümler Gemini'ye gider, Türkçe yorum döner. Anahtar yoksa veya API
   hata verirse rapor yerel bulgularla tamamlanır; asla kırılmaz.

Eşikler donanıma göre kalibre edilir: 8 GiB'de %50 RAM uyarıyken 32 GiB'de normaldir,
HDD sistem diski ayrı bulgudur, laptop'ta termal eşik düşüktür.

## Kurulum ve kullanım

Python 3.9+ gerekir.

```
./run.sh scan      # Linux / macOS — ilk çalıştırmada .venv kurar
.\run.ps1 scan     # Windows PowerShell
```

Diğer komutlar:

| Komut | Ne yapar |
|---|---|
| `agmo scan --focus Valorant` | Odak algılanamadığında oyunu elle belirtir |
| `agmo scan --offline` | Yalnız yerel motor, AI yok |
| `agmo scan --json` | Makine-okur çıktı |
| `agmo watch` | Canlı izleme; hızla büyüyen süreçleri işaretler |
| `agmo doctor` | Toplayıcı ve ayar sağlık kontrolü |
| `agmo kill PID --yes` | Süreç sonlandırır; sistem-kritik ve anti-cheat reddedilir |
| `agmo clean-cache --yes` | Güvenli önbellek temizliği |

## AI anahtarı (opsiyonel)

Gemini varsayılan sağlayıcıdır; Grok (xAI) da desteklenir. Sağlayıcı anahtar önekinden
algılanır: `AIza…`/`AQ.…` → Gemini, `xai-…` → Grok.

```
export GEMINI_API_KEY="…"        # oturum içi
agmo config --set-key "…"        # kalıcı; ~/.config/agmo/config.toml, izin 0600
agmo doctor --ai                 # anahtar + model + ping testi
```

Anahtar depoya yazılmaz; AI'ya gönderilen payload'da kullanıcı adı ve yol bilgileri
temizlenir.

## Testler

91 unit test ve her push'ta üç OS'te (ubuntu/windows/macos) koşan GitHub Actions
matrisi — gerçek platform kod yolları CI'da doğrulanır, sadece mocking değildir.

```
./run.sh -m unittest discover -s tests
```

## Lisans

MIT. Ayrıntılar için [LICENSE](LICENSE).