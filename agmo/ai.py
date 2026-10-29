"""AI katmanı: Grok (xAI) ile telemetri yorumlatma + yerel analiza düşüş.

- Anahtar: env (AGMO_XAI_API_KEY/XAI_API_KEY/GROK_API_KEY) veya config.toml
- Model: "auto" ise /v1/models'tan tercih sırasına göre seçilir
- Çıktı: katı JSON şeması; ayrıştırma başarısızsa yerel bulgular kullanılır
- Payload hiçbir zaman kullanıcı yolunu içermez (scrub edilir)
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from agmo import classify
from agmo.config import DEFAULT_MODEL
from agmo.models import Analysis, Finding, Fix, Hardware, Snapshot
from agmo.util import fmt_gib, scrub

MODEL_PREFERENCE = [
    "grok-4-fast", "grok-4-1-fast", "grok-4", "grok-code-fast", "grok-3-mini", "grok-3",
]

SYSTEM_PROMPT = """Sen AGMO adlı aracın analiz motorusun: Linux/Windows/macOS makinelerinden \
gelen performans telemetrisini yorumluyorsun ve kullanıcıya TÜRKÇE öneri veriyorsun.
Çıktı: SADECE geçerli JSON (markdown yok, yorum yok).

Zorunlu kurallar:
1. "exempt" listesindeki süreçler (odaktaki oyun/uygulama ve bileşenleri) ASLA bir
   bulgu/suçlamaya dönüştürülmez. Onlar için en fazla "kaynak tüketimi özeti" yazarsın.
2. Donanım bağlamına göre kalibre et: 8 GiB'de %65 RAM kritiktir, 32+ GiB'de normaldir;
   sistem diski HDD ise disk iyileştirmeleri en yüksek önceliktir; 4 çekirdekte arka plan
   yükü ciddi bir maliyettir.
3. "valorant açıkken (oyun hariç) RAM %X — sebep adayları Y" tarzı analiz et; oyuna değil,
   çevresindeki arka plan işlerine (senkron, tarama, VM, güncelleme) odaklan.
4. Her bulgu için somut, uygulanabilir adımlar ver (Arayüz yolu veya komut) + risk etiketi.
5. Emin olmadığın yerde tahmin yürütme yerine 'izlenmesi gereken ölçüm' öner.

JSON şeması:
{
  "baseline_note": "taban çizgisi (oyun hariç kaynaklar) hakkında tek cümle yorum",
  "summary": "2-4 cümle genel durum",
  "findings": [
    {
      "title": "kısa başlık",
      "severity": "low|medium|high|critical",
      "category": "memory|cpu|disk|network|thermal|power|boot|storage|configuration",
      "why": "neden yavaşlık kaynağı",
      "evidence": "ölçüm/kanıt",
      "fix_steps": ["adım 1", "adım 2"],
      "risk": "safe|careful|risky"
    }
  ]
}
En fazla 6 bulgu; şüphesiz, ölçüme dayalı yaz."""


def build_payload(snap: Snapshot, hw: Hardware, analysis: Analysis) -> str:
    b = analysis.baseline
    excluded = [g for g in snap.procs if g.key and (g.kind in ("game", "game-suspect", "anticheat") or g.exempt)]
    others = [g for g in snap.procs if g.key and not g.exempt]

    def proc_row(g):
        return {
            "ad": scrub(g.label),
            "tur": classify.KIND_TR.get(g.kind, g.kind),
            "cpu_pct": round(g.cpu_pct, 1),
            "ram_mib": round(g.mem_mib, 0),
            "io_yaz_mibs": round(g.io_w_mib_s, 1),
            "io_okuma_mibs": round(g.io_r_mib_s, 1),
            "vram_mib": round(g.gpu_mib or 0, 0),
            "pid": len(g.pids),
            "cmd": scrub(g.cmdline[:120]),
        }

    top_mem = sorted(others, key=lambda g: g.mem_mib, reverse=True)[:12]
    top_cpu = sorted(others, key=lambda g: g.cpu_pct, reverse=True)[:8]
    seen = {id(g) for g in top_mem}
    top_cpu = [g for g in top_cpu if id(g) not in seen]

    payload = {
        "platform": snap.platform,
        "donanim": {
            "os": hw.os_pretty,
            "cpu": hw.cpu_model,
            "cekirdek": f"{hw.cpu_cores_physical}C/{hw.cpu_cores_logical}T",
            "ram_gib": round(hw.ram_total_gib, 1),
            "laptop": hw.is_laptop,
            "guc": hw.battery,
            "gpu": hw.gpus[:2],
            "sistem_diski": (hw.system_disk.medium or "bilinmiyor") if hw.system_disk else "bilinmiyor",
            "diskler": [{"mount": d.mountpoint, "tip": d.medium or "?", "gb": d.total_gib}
                        for d in hw.disks[:4]],
        },
        "taban_cizgisi": {
            "oyun_haric_ram_mib": round(b.base_mem_mib, 0),
            "ram_toplam_mib": round(b.mem_total_mib, 0),
            "oyun_haric_ram_pct": b.base_mem_pct,
            "kullanilabilir_ram_gib": round(b.mem_avail_gib, 2),
            "oyun_haric_cpu_pct": b.base_cpu_pct,
            "swap_kullanilan_mib": round(b.swap_used_mib, 0),
        },
        "odak_oyun": {
            "calisiyor": analysis.baseline.game_label is not None,
            "ad": scrub(analysis.baseline.game_label or ""),
            "kaynak_tuketimi": [
                {"ad": scrub(ex.label), "tur": classify.KIND_TR.get(ex.kind, ex.kind),
                 "ram_mib": round(ex.mem_mib, 0), "cpu_pct": round(ex.cpu_pct, 1),
                 "not": "; ".join(ex.notes)[:150]}
                for ex in excluded[:6]
            ],
        },
        "kaynaklar": {
            "cpu_total_pct": round(snap.cpu_total_pct, 1),
            "disk_okuma_mibs": round(snap.disk_read_mib_s, 1),
            "disk_yazma_mibs": round(snap.disk_write_mib_s, 1),
            "disk_doluluk_pct": snap.disk_busy_pct,
            "sicakliklar": snap.temps,
            "cpu_freq_mhz": {k: (round(v) if isinstance(v, (int, float)) else v) for k, v in snap.cpu_freq.items()},
            "guc": {k: scrub(str(v)) for k, v in snap.power.items() if v is not None},
            "acilis": {k: scrub(str(v)) for k, v in snap.boot.items() if v},
            "load": [round(x, 2) for x in snap.load[:3]],
            "uptime_s": round(snap.uptime_s),
        },
        "oyun_haric_surecler": [proc_row(g) for g in (top_mem + top_cpu)],
        "yerel_bulgular": [
            {"id": f.id, "baslik": f.title, "seviye": f.severity, "neden": f.why[:200],
             "kanit": scrub(f.evidence[:160])}
            for f in analysis.sorted_findings()
        ],
        "notlar": [scrub(n)[:200] for n in analysis.notes],
    }
    return json.dumps(payload, ensure_ascii=False)


def _http_detail(e: urllib.error.HTTPError) -> str:
    try:
        body = e.read().decode("utf-8", "replace")[:200]
    except Exception:
        body = ""
    if body:
        return f"HTTP {e.code}: {body}"
    return f"HTTP {e.code}"


def resolve_model(base: str, key: str, configured: str) -> str:
    if configured and configured != DEFAULT_MODEL:
        return configured
    try:
        req = urllib.request.Request(
            f"{base}/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        for pref in MODEL_PREFERENCE:
            for mid in ids:
                if mid.startswith(pref) or pref in mid:
                    return mid
        for mid in ids:
            if "grok" in mid:
                return mid
        raise ValueError("listed model bulunamadı")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"model listesi alınamadı ({_http_detail(e)})") from e
    except Exception as e:
        raise RuntimeError(f"model seçilemedi: {e}") from e


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except Exception:
        pass
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except Exception:
            return None
    return None


def _valid_sev(s: Any) -> str:
    s = str(s).lower()
    return s if s in ("low", "medium", "high", "critical") else "medium"


def enrich(analysis: Analysis, hw: Hardware, cfg: Dict[str, Optional[str]]
           ) -> Analysis:
    """AI katmanını çalıştır; sonuç Analysis.ai + AI bulgular olarak eklenir.

    API yoksa/hatalıysa status="error" olur ve yerel bulgular korunur.
    """
    key = cfg.get("api_key")
    base = cfg.get("base_url") or "https://api.x.ai"
    if not key:
        analysis.ai = {"status": "off",
                       "detail": "AI anahtarı tanımlı değil — yerel analiz gösteriliyor. "
                                 "Anahtarı XAI_API_KEY ortam değişkeni veya ~/.config/agmo/config.toml ile ver."}
        return analysis
    try:
        model = resolve_model(base, key, str(cfg.get("model") or DEFAULT_MODEL))
    except Exception as e:
        analysis.ai = {"status": "error", "detail": str(e)}
        return analysis

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_payload(analysis.snapshot, hw, analysis)},
        ],
        "temperature": 0.2,
        "max_tokens": 1800,
        "response_format": {"type": "json_object"},
    }
    content = None
    detail = ""
    for attempt in (0, 1):
        try:
            req = urllib.request.Request(
                f"{base}/v1/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            content = data["choices"][0]["message"]["content"]
            detail = ""
            break
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                err = {}
            msg = str(err.get("error", {}).get("message") or err.get("error") or e)[:300]
            if e.code == 400 and attempt == 0 and "response_format" in msg:
                body.pop("response_format", None)  # bazı modellerde desteklenmez
                continue
            detail = f"HTTP {e.code}: {msg}"
            break
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
            detail = f"bağlantı/yanıt hatası: {e}"
            break

    analysis.ai = {"status": "ok" if content else "error",
                   "model": model, "detail": detail}
    if not content:
        return analysis
    parsed = _extract_json(content)
    if not isinstance(parsed, dict):
        analysis.ai["detail"] = "AI yanıtı JSON ayrıştıramadı; yerel bulgular korunuyor."
        return analysis
    analysis.ai["summary"] = str(parsed.get("summary", ""))[:1200]
    analysis.ai["baseline_note"] = str(parsed.get("baseline_note", ""))[:600]

    got = parsed.get("findings")
    if isinstance(got, list):
        count = 0
        for f in got[:6]:
            if not isinstance(f, dict) or not f.get("title"):
                continue
            try:
                risk_val = str(f.get("risk", "safe")).lower()
                risk = risk_val if risk_val in ("safe", "careful", "risky") else "safe"
                analysis.findings.append(Finding(
                    id=f"ai-{count}",
                    title=str(f["title"])[:160],
                    severity=_valid_sev(f.get("severity")),
                    category=str(f.get("category", "cpu"))[:24],
                    source="ai",
                    why=str(f.get("why", ""))[:600],
                    evidence=str(f.get("evidence", ""))[:400],
                    fixes=[Fix(text=str(s)[:300], risk=risk)
                           for s in (f.get("fix_steps") or [])[:5] if s],
                ))
                count += 1
            except Exception:
                continue
    return analysis