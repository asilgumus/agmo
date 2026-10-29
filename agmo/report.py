"""Terminal raporu (Türkçe, bağımlılıksız ANSI)."""
from __future__ import annotations

import json
import sys
from typing import List

from agmo import classify
from agmo.models import Analysis, Hardware
from agmo.util import fmt_gib

SEV_COLOR = {"critical": "\033[1;31m", "high": "\033[31m", "medium": "\033[33m",
             "low": "\033[36m", "info": "\033[90m"}
SEV_TR = {"critical": "KRİTİK", "high": "YÜKSEK", "medium": "ORTA", "low": "DÜŞÜK", "info": "BİLGİ"}
RISK_TR = {"safe": "güvenli", "careful": "dikkat", "risky": "riskli"}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[90m"


class Ctx:
    def __init__(self, color: bool):
        self.on = color and _supports_color()

    def __call__(self, s: str, code: str) -> str:
        return f"{code}{s}{RESET}" if self.on else s

    def sev(self, sev: str) -> str:
        return self(f"[{SEV_TR.get(sev, sev.upper())}]", SEV_COLOR.get(sev, ""))


def _supports_color() -> bool:
    if sys.platform == "win32":
        return os_supports_ansi()
    if not sys.stdout.isatty():
        return False
    t = __import__("os").environ.get("TERM", "")
    return t != "dumb"


def os_supports_ansi() -> bool:
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        mode = __import__("ctypes").c_uint()
        k32.GetConsoleMode(h, __import__("ctypes").byref(mode))
        k32.SetConsoleMode(h, mode.value | 0x4)
        return True
    except Exception:
        return False


def bar(pct: float, width: int = 16) -> str:
    filled = max(0, min(width, int(round(pct / 100 * width))))
    return "█" * filled + "░" * (width - filled)


def _fmt_uptime(sec: float) -> str:
    d = int(sec // 86400)
    h = int(sec % 86400 // 3600)
    m = int(sec % 3600 // 60)
    return (f"{d}g " if d else "") + (f"{h}s " if h else "") + f"{m}dk"


def render(analysis: Analysis, hw: Hardware, color: bool = True) -> str:
    c = Ctx(color)
    snap = analysis.snapshot
    b = analysis.baseline
    out: List[str] = []

    ver = "0.3.0"
    title = c(f"AGMO v{ver} — AI Guided Machine Optimizer", BOLD)
    out.append(title)
    hw_line = (f"{hw.os_pretty} · {hw.cpu_model} ({hw.cpu_cores_physical}C/{hw.cpu_cores_logical}T) · "
               f"{hw.ram_total_gib:.0f} GiB RAM · "
               f"sistem diski: {(hw.system_disk.medium or 'bilinmiyor') if hw.system_disk else 'bilinmiyor'}"
               + (f" · {', '.join(hw.gpus[:2])}" if hw.gpus and hw.gpus[0] != 'bilinmiyor' else "")
               + (f" · {hw.battery}" if hw.battery else ""))
    out.append(f"{hw_line}")
    out.append(f"Uptime {_fmt_uptime(snap.uptime_s)} · {snap.ts}\n")

    # --- odak/oyun kümesi
    exempt = [g for g in snap.procs if g.exempt and g.role != "self"]
    if exempt:
        out.append(c("🎯 Odak / ayrıcalıklı", BOLD))
        for g in exempt:
            ram = fmt_gib(g.mem_mib)
            cpu = f"%{g.cpu_pct:.0f} CPU"
            kind = classify.KIND_TR.get(g.kind, g.kind)
            line = f"  • {g.label} ({g.names[0]}) — {kind} · {ram} · {cpu}"
            if g.role == "foreground":
                line += c("  ← odaktaki uygulama", "\033[1;36m")
            out.append(line)
            for n in g.notes:
                out.append(f"    {c('·', DIM)} {n}")
        out.append(f"    {c('Bilgi amaçlı toplam:', DIM)} {fmt_gib(b.exempt_mem_mib)} RAM, "
                   f"~%{b.exempt_cpu_norm_pct:.0f} CPU — 'yavaşlatıcı' olarak sayılmadı\n")

    # --- taban çizgisi
    out.append(c("📊 Taban çizgisi" + (" (oyun hariç)" if b.game_label else ""), BOLD))
    cpu_pct = b.base_cpu_pct
    mem_pct = b.base_mem_pct
    swap_pct = b.swap_used_mib / max(1, b.swap_total_mib) * 100 if b.swap_total_mib else 0
    out.append(f"  {b.line}")
    out.append(f"  {'RAM':<5} {bar(mem_pct)} {mem_pct:5.1f}%  "
               f"({fmt_gib(b.base_mem_mib)}/{fmt_gib(b.mem_total_mib)})  {c(b.mem_verdict.upper(), _c_of(b.mem_verdict))}")
    out.append(f"  {'CPU':<5} {bar(cpu_pct)} {cpu_pct:5.1f}%  "
               f"{'(oyun hariç ölçüm)' if b.game_label else '(sistem geneli)'}  {c(b.cpu_verdict.upper(), _c_of(b.cpu_verdict))}")
    if b.swap_total_mib:
        out.append(f"  {'SWAP':<5} {bar(swap_pct)} {swap_pct:5.1f}%  ({fmt_gib(b.swap_used_mib)})")
    if snap.disk_busy_pct is not None:
        dcol = f"{snap.disk_read_mib_s:.0f}↓ / {snap.disk_write_mib_s:.0f}↑ MiB/s · doluluk %{snap.disk_busy_pct:.0f}"
    else:
        dcol = f"{snap.disk_read_mib_s:.0f}↓ / {snap.disk_write_mib_s:.0f}↑ MiB/s"
    out.append(f"  {'DISK':<5}  ----  {dcol}")
    temps = " · ".join(f"{k.upper()} {v:.0f}°C" for k, v in snap.temps.items()) or "okunamadı"
    freq = snap.cpu_freq.get("cur_mhz")
    freq_txt = f" · {freq:.0f} MHz" if freq else ""
    out.append(f"  {'SICAKLIK':<5}  ----  {temps}{freq_txt}")
    out.append("")

    # --- bulgular
    findings = analysis.sorted_findings()
    if findings:
        out.append(c(f"🩺 Bulgular ({len(findings)}):", BOLD))
        for i, f in enumerate(findings, 1):
            sev = c.sev(f.severity)
            src = c("[AI]", "\033[1;35m") if f.source == "ai" else c("[yerel]", DIM)
            out.append(f"  {i}. {sev} {src} {f.title}")
            if f.why:
                out.append(f"     {c('Neden:', DIM)} {f.why}")
            if f.evidence:
                out.append(f"     {c('Kanıt:', DIM)} {f.evidence}")
            for j, fix in enumerate(f.fixes, 1):
                risk = c(RISK_TR.get(fix.risk, fix.risk), "\033[33m") if fix.risk != "safe" else "güvenli"
                os_tag = f" ({fix.os})" if fix.os and fix.os != "any" else ""
                out.append(f"     {c(f'Öneri {j}', DIM)} ({risk}{os_tag}): {fix.text}")
                if fix.cmd:
                    out.append(f"       $ {fix.cmd}")
            out.append("")
    else:
        out.append(c("✅ Belirgin bir sorun bulunamadı — kaynaklar donanım eşiklerinin içinde.", "\033[32m"))
        out.append("")

    # --- AI katmanı
    ai = analysis.ai
    if ai:
        status = ai.get("status")
        if status == "ok":
            model = ai.get("model", "?")
            out.append(c(f"🤖 AI yorumu ({model})", BOLD))
            if ai.get("baseline_note"):
                out.append(f"  {ai['baseline_note']}")
            if ai.get("summary"):
                out.append(f"  {ai['summary']}")
            out.append("")
        elif status == "error":
            out.append(c(f"⚠️ AI katmanı çalışmadı: {ai.get('detail', '')[:200]}", "\033[33m"))
            out.append("   Yerel bulgular yukarıda geçerli.")
        else:  # off
            out.append(c("ℹ️ AI katmanı kapalı (anahtar yok) — yerel analiz yukarıda.", DIM))
            out.append("   Anahtar için: `export XAI_API_KEY=xai-...` veya `agmo config set-key` "
                       "(config.toml, izin 0600).")
    out.append("")

    # --- notlar
    if analysis.notes:
        out.append(c("Notlar:", DIM))
        for n in analysis.notes:
            out.append(f"  {c('·', DIM)} {n}")
    return "\n".join(out)


def _c_of(v: str) -> str:
    return {"normal": "\033[32m", "high": "\033[33m", "critical": "\033[1;31m"}.get(v, "")


def render_json(analysis: Analysis, hw: Hardware) -> str:
    doc = {
        "version": "0.3.0",
        "hardware": hw.to_dict(),
        **analysis.to_dict(),
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)