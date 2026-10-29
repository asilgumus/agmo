"""Güvenli aksiyonlar: önbellek taraması/temizliği, süreç sonlandırma.

İlke: AGMO asla onaysız yıkıcı işlem yapmaz; kill ve clean-cache her zaman
onay ister. Diğer öneriler komut/Arayüz talimatı olarak basılır.
"""
from __future__ import annotations

import os
import time
from typing import Callable, Dict, List, Optional

import psutil

from agmo import classify
from agmo.util import fmt_gib


def _cache_dirs(platform: str) -> List[Dict[str, str]]:
    home = os.path.expanduser("~")
    if platform == "windows":
        local = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        temp = os.environ.get("TEMP", os.path.join(local, "Temp"))
        dirs = [
            {"path": temp, "label": "Kullanıcı Temp", "level": "safe"},
            {"path": os.path.join(local, "pip", "cache"), "label": "pip önbelleği", "level": "safe"},
        ]
        dirs.append({"path": r"C:\Windows\Temp", "label": "Sistem Temp (yönetici gerekir)",
                     "level": "careful"})
        return dirs
    if platform == "macos":
        return [
            {"path": os.path.join(home, "Library", "Caches"), "label": "Kullanıcı önbellekleri", "level": "safe"},
            {"path": os.path.join(home, ".Trash"), "label": "Çöp kutusu", "level": "careful"},
        ]
    return [
        {"path": os.path.join(home, ".cache"), "label": "Kullanıcı önbellekleri (~/.cache)", "level": "safe"},
        {"path": os.path.join(home, ".local", "share", "Trash", "files"),
         "label": "Çöp kutusu (dosyalar)", "level": "careful"},
    ]


def dir_size_mib(path: str, deadline_s: float = 8.0) -> Optional[float]:
    """Scandir ile hızlı boyut; süre aşarsa kısmi sonuç (None değil) döndürür."""
    total = 0
    entries_seen = 0
    stop_at = time.monotonic() + deadline_s
    stack = [path]
    try:
        while stack:
            p = stack.pop()
            now = time.monotonic()
            if now > stop_at and stack:
                return total / (1024 * 1024)  # kısmi
            try:
                with os.scandir(p) as it:
                    for e in it:
                        entries_seen += 1
                        if entries_seen > 400_000:
                            return total / (1024 * 1024)
                        try:
                            if e.is_symlink():
                                continue
                            if e.is_dir(follow_symlinks=False):
                                stack.append(e.path)
                            else:
                                total += e.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except (PermissionError, NotADirectoryError, OSError):
                continue
    except Exception:
        return None
    return total / (1024 * 1024)


def cache_report(platform: str) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    for d in _cache_dirs(platform):
        size = dir_size_mib(d["path"]) if os.path.isdir(d["path"]) else None
        out.append({"path": d["path"], "label": d["label"], "level": d["level"],
                    "size_mib": round(size, 1) if size is not None else None})
    return out


def clean_cache(platform: str, yes: bool = False) -> str:
    """'safe' seviyeli önbellekleri onaylı temizler. Döndürülen metin özet."""
    report = cache_report(platform)
    lines = ["Önbellek taraması:"]
    targets: List[str] = []
    for r in report:
        size = r["size_mib"]
        txt = fmt_gib(size) if size is not None else "ölçülemedi"
        lines.append(f"  - [{r['level']}] {r['label']}: {txt} ({r['path']})")
        if r["level"] == "safe" and size and size > 50:
            targets.append(str(r["path"]))
    if not targets:
        lines.append("Temizlenecek yeterli büyüklükte güvenli önbellek yok.")
        return "\n".join(lines)
    if not yes:
        ans = input(f"Şunların İÇERİĞİ silinecek: {targets}\nOnaylıyor musun? (y/N) ").strip().lower()
        if ans not in ("y", "yes", "e", "evet"):
            lines.append("Vazgeçildi.")
            return "\n".join(lines)
    freed = 0.0
    for t in targets:
        before = None
        freed_dir = _purge_contents(t)
        freed += freed_dir
    lines.append(f"Temizlendi: ~{fmt_gib(freed)} serbest bırakıldı.")
    return "\n".join(lines)


def _purge_contents(path_dir: str) -> float:
    """Klasörü kaldırmadan içeriğini siler; kilitli dosyaları atlar."""
    import shutil

    total_before = dir_size_mib(path_dir, deadline_s=6.0) or 0.0
    removed = 0.0
    try:
        with os.scandir(path_dir) as it:
            entries = [e.path for e in it if not e.is_symlink()]
        for e in entries:
            try:
                if os.path.isdir(e):
                    # çok büyük alt ağaçlar için shutil rmtree (onaylı akışta)
                    shutil.rmtree(e, ignore_errors=True)
                else:
                    os.remove(e)
            except OSError:
                continue
    except OSError:
        pass
    after = dir_size_mib(path_dir, deadline_s=6.0) or 0.0
    removed = max(0.0, total_before - after)
    return removed


def kill_pid(pid: int, yes: bool = False) -> str:
    """Onaylı süreç sonlandırma; sistem kritik ve anti-cheat süreçleri reddeder."""
    try:
        proc = psutil.Process(pid)
        name = proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return f"PID {pid} bulunamadı veya erişilemedi."
    cmdline = ""
    try:
        cmdline = " ".join(proc.cmdline())[:200]
    except Exception:
        pass
    key, kind, family = classify.match_signature({name}, cmdline)
    if classify.is_never_kill(key, kind):
        return (f"REDDEDİLDİ: {name} ({key or kind}) sistem-kritik/anti-cheat bileşeni. "
                f"Bu süreci sonlandırmak sistemi/oyunu bozar — AGMO bunu yapmaz.")
    if not yes:
        ans = input(f"{name} (PID {pid}) sonlandırılacak. Onaylıyor musun? (y/N) ").strip().lower()
        if ans not in ("y", "yes", "e", "evet"):
            return "Vazgeçildi."
    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        return f"{name} (PID {pid}) sonlandırıldı."
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        return f"Sonlandırılamadı: {e}"