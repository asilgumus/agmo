"""AGMO komut satırı arayüzü.

Kullanım:
  agmo scan [--focus VALORANT] [--json] [--offline] [--no-storage] [--model ad]
  agmo watch [--every 30]
  agmo doctor [--ai]
  agmo config --show | --set-key | --set-provider gemini | --set-model grok-4-fast
  agmo kill <pid> [--yes]
  agmo clean-cache [--yes]
"""
from __future__ import annotations

import argparse
import json
import io
import sys
import time
from typing import List, Optional

from agmo import __version__, analyze as analyze_mod
from agmo.actions import cache_report, clean_cache, kill_pid
from agmo.ai import enrich, provider_of
from agmo.collectors import collect_snapshot
from agmo.config import get_ai_config, set_config
from agmo.hardware import collect as collect_hardware
from agmo.models import Analysis, Hardware, ProcGroup
from agmo.report import render, render_json
from agmo.util import fmt_gib


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agmo",
                                description="AGMO — AI Guided Machine Optimizer")
    p.add_argument("--version", action="version", version=f"agmo {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="tek tarama: topla, analiz et, raporla")
    s.add_argument("--focus", help="odak/oyun uygulamasını elle belirt (örn. --focus Valorant)")
    s.add_argument("--json", action="store_true", help="makine-okur JSON çıktı")
    s.add_argument("--offline", action="store_true", help="AI katmanını atla (yalnız yerel analiz)")
    s.add_argument("--no-storage", action="store_true", help="önbellek boyut taramasını atla (daha hızlı)")
    s.add_argument("--model", help="AI modeli (örn. gemini-3.5-flash, grok-4-fast); varsayılan: auto")
    s.add_argument("--no-color", action="store_true")

    w = sub.add_parser("watch", help="sürekli izleme (bellek kaçışı/sürücü tespiti)")
    w.add_argument("--every", type=int, default=30, help="saniyede bir örnek (vars. 30)")
    w.add_argument("--no-color", action="store_true")

    d = sub.add_parser("doctor", help="toplayıcı/ayar sağlık kontrolü")
    d.add_argument("--ai", action="store_true", help="AI uç noktasını da dene")
    d.add_argument("--no-color", action="store_true")

    c = sub.add_parser("config", help="API anahtarı/sağlayıcı/model ayarı")
    c.add_argument("--show", action="store_true")
    c.add_argument("--set-key", metavar="XAI_OR_GEMINI_KEY")
    c.add_argument("--set-provider", metavar="PROVIDER", help="gemini | xai (boşsa önekten otomatik)")
    c.add_argument("--set-model", metavar="MODEL")

    k = sub.add_parser("kill", help="süreç sonlandır (onaylı; kritik/anti-cheat reddedilir)")
    k.add_argument("pid", type=int)
    k.add_argument("--yes", action="store_true")

    cc = sub.add_parser("clean-cache", help="güvenli önbellek temizliği (onaylı)")
    cc.add_argument("--yes", action="store_true")
    return p


def _do_scan(args) -> int:
    hw = collect_hardware()
    print_brief = lambda msg: print(msg, file=sys.stderr) if args.json else print(msg)
    if not args.json:
        print("AGMO ölçüm alıyor (~3s)...", flush=True)
    snap = collect_snapshot(args.focus)
    print_brief("Yerel analiz...")
    analysis = analyze_mod.analyze(snap, hw, include_storage=not args.no_storage)

    if not args.offline:
        cfg = get_ai_config()
        if args.model:
            cfg["model"] = args.model
        if cfg.get("api_key"):
            print_brief(f"AI yorumu isteniyor ({provider_of(cfg)})...")
        analysis = enrich(analysis, hw, cfg)

    if args.json:
        print(render_json(analysis, hw))
    else:
        print(render(analysis, hw, color=not args.no_color))
    return 0


def _do_watch(every: int, color: bool = True) -> int:
    from agmo.models import Hardware as _H
    base_hw: Optional[_H] = None
    base_mem: dict = {}
    first = True
    try:
        while True:
            hw = collect_hardware()
            snap = collect_snapshot(None)  # watch: odak yok, hızlı mod
            analysis = analyze_mod.analyze(snap, hw, include_storage=False)
            b = analysis.baseline
            label = b.game_label or "odak yok"
            moved = []
            for g in snap.procs:
                key = (g.label or g.names[0] if g.names else "?").lower()
                if key in base_mem:
                    delta = g.mem_mib - base_mem[key]
                    if delta >= 300:
                        moved.append(f"{g.label} +{delta:.0f} MiB")
                base_mem[key] = g.mem_mib
            if first:
                print(f"[watch] ilk örnek alındı — her {every}s bir ölçüm. Ctrl+C ile çık.", flush=True)
                first = False
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] RAM {fmt_gib(b.base_mem_mib)} (%{b.base_mem_pct:.0f}) · "
                  f"CPU ~%{b.base_cpu_pct:.0f} · {label} · "
                  f"{len(analysis.findings)} bulgu", flush=True)
            for m in moved[:3]:
                print(f"    ↑ {m} (bellek büyümesi dikkat)", flush=True)
            time.sleep(max(5, every))
    except KeyboardInterrupt:
        print("\n[watch] kapatıldı.")
        return 0


def _do_doctor(color: bool = True, with_ai: bool = False) -> int:
    import psutil
    print(f"agmo {__version__} doktor raporu")
    print(f"  platform      : {sys.platform}")
    try:
        hw = collect_hardware()
        print(f"  donanim       : {hw.os_pretty} | {hw.cpu_cores_physical}C/{hw.cpu_cores_logical}T | "
              f"{hw.ram_total_gib:.0f} GiB | sistem disk: {hw.system_disk.medium}")
        print(f"  gpu           : {', '.join(hw.gpus)}")
        print(f"  pil           : {hw.battery or 'yok'}")
    except Exception as e:
        print(f"  donanim       : HATA {e}")
    try:
        temps = psutil.sensors_temperatures()
        print(f"  sicaklik      : {'var (' + ', '.join(sorted(temps))[:60] + ')' if temps else 'okunamıyor'}")
    except Exception:
        print("  sicaklik      : desteklenmiyor")
    try:
        from agmo.collectors import _platform_module
        m = _platform_module().collect_extras()
        print(f"  os-ekstralar  : boot={bool(m.get('boot'))}, power={bool(m.get('power'))}, "
              f"extras={list((m.get('extras') or {}).keys())[:4]}")
    except Exception as e:
        print(f"  os-ekstralar  : HATA {e}")
    try:
        focus = _platform_module().get_foreground(None)
        print(f"  odak_algılama : {focus.proc_name or focus.label or 'BULUNAMADI'} "
              f"(kaynak: {focus.source})" if focus else "  odak_algılama : BULUNAMADI (compositor/izin)")
    except Exception as e:
        print(f"  odak_algılama : HATA {e}")

    cfg = get_ai_config()
    if cfg.get("api_key"):
        k = str(cfg["api_key"])
        prov = provider_of(cfg)
        if k.startswith(("xai-", "AQ.", "AIza")):
            shape = f"{k[:4]}… öneki ✓ ({prov})"
        else:
            shape = f"UYARI: bilinmeyen önek — sağlayıcı varsayılanı '{prov}' ile denenecek"
        print(f"  ai_anahtar    : var ({shape})")
    else:
        print("  ai_anahtar    : yok (AI katmanı kapalı kalacak)")
    if with_ai and cfg.get("api_key"):
        print("  ai_ping       : deneniyor...", flush=True)
        t0 = time.time()
        try:
            from agmo.ai import ping as ai_ping
            out = ai_ping(cfg)
            print(f"  ai_ping       : OK {out} ({time.time() - t0:.1f}s)")
        except Exception as e:
            print(f"  ai_ping       : HATA {e}")
    return 0


def _do_config(args) -> int:
    if args.show:
        cfg = get_ai_config()
        k = cfg.get("api_key")
        print(f"provider : {cfg.get('provider') or 'otomatik (anahtar önekinden)'}")
        if cfg.get("base_url"):
            print(f"base_url : {cfg.get('base_url')}")
        print(f"model    : {cfg.get('model')}")
        print(f"api_key  : {'ayarı var (' + str(k)[:8] + '……)' if k else 'yok'}")
        return 0
    if args.set_key or args.set_model or args.set_provider:
        path = set_config(api_key=args.set_key, model=args.set_model,
                          provider=args.set_provider)
        print(f"Ayar yazıldı: {path} (izin 0600)")
        return 0
    print("Ne yapacaksın? --show | --set-key | --set-provider | --set-model")
    return 1


def _utf8_console() -> None:
    """Windows konsolu cp1252'deyken Türkçe karakterler print'i patlatır
    (UnicodeEncodeError). Akışları UTF-8'e zorla; olmazsa hataları bas yerine
    sessiz düş (rapor asla çökmesin)."""
    if sys.platform != "win32" or not isinstance(sys.stdout, io.TextIOBase):
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


def main(argv: Optional[List[str]] = None) -> None:
    _utf8_console()
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "scan":
            code = _do_scan(args)
        elif args.cmd == "watch":
            code = _do_watch(args.every)
        elif args.cmd == "doctor":
            code = _do_doctor(color=not args.no_color, with_ai=args.ai)
        elif args.cmd == "config":
            code = _do_config(args)
        elif args.cmd == "kill":
            code = 0 if "sonlandırıldı" in kill_pid(args.pid, yes=args.yes) else 1
        elif args.cmd == "clean-cache":
            print(clean_cache(sys.platform.replace("win32", "windows").replace("darwin", "macos"),
                              yes=args.yes))
            code = 0
        else:  # pragma: no cover
            code = 1
    except KeyboardInterrupt:
        code = 130
        print("\nkesildi.", file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    main()