"""Linux özel toplayıcılar: odak pencere compositor'a göre, gücü, açılışı.

Odak tespit önceliği: Hyprland > Sway > KDE (kdotool benzeri yok) >
GNOME (Shell.Eval kapalıysa alınamaz) > X11 (xdotool). Bulunamazsa None —
analiz motoru 'odak bilinmiyor' moduna döner.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

from agmo.models import ForegroundInfo
from agmo.util import run


def _hyprland_focus() -> Optional[ForegroundInfo]:
    out = run(["hyprctl", "activewindow", "-j"], timeout=3)
    if not out:
        return None
    try:
        d = json.loads(out)
    except Exception:
        return None
    if not d or (isinstance(d, dict) and not d.get("class") and not d.get("title")):
        return None
    return ForegroundInfo(
        pid=d.get("pid"),
        proc_name=str(d.get("class", "")),
        window_class=str(d.get("class", "")),
        title=str(d.get("title", ""))[:120],
        source="hyprctl",
    )


def _sway_focus() -> Optional[ForegroundInfo]:
    out = run(["swaymsg", "-t", "get_tree"], timeout=4)
    if not out:
        return None
    try:
        tree = json.loads(out)
    except Exception:
        return None

    def walk(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if node.get("focused") and not node.get("nodes"):
            return node
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            r = walk(child)
            if r:
                return r
        return None

    n = walk(tree)
    if not n:
        return None
    props = n.get("window_properties", {}) or {}
    return ForegroundInfo(
        pid=n.get("pid"),
        proc_name=str(props.get("class") or n.get("app_id") or ""),
        window_class=str(props.get("class") or n.get("app_id") or ""),
        title=str(n.get("name", ""))[:120],
        source="swaymsg",
    )


def _gnome_eval_focus() -> Optional[ForegroundInfo]:
    """GNOME Shell.Eval yalnızca EvalEnabled kurulumlarda çalışır; hızlı deneme."""
    out = run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell",
               "--object-path", "/org/gnome/Shell",
               "--method", "org.gnome.Shell.Eval",
               "global.workspace_manager.get_active_workspace()"
               ".get_active_window()?.get_wm_class() || ''"], timeout=4)
    if not out or not out.startswith("(true"):
        return None
    cls = out[out.find("("):].rsplit(",", 1)[-1].strip().strip(")'\" ")
    if not cls:
        return None
    return ForegroundInfo(proc_name=cls, window_class=cls, source="gnome-eval", confidence="high")


def _win_pid_via_xprop(win_id: str) -> tuple[Optional[int], str]:
    """xprop ile _NET_WM_PID ve WM_CLASS çek (xdotool pid XWayland'da eksik olabilir)."""
    out = run(["xprop", "-id", win_id], timeout=4)
    if not out:
        return None, ""
    pid = None
    cls = ""
    for line in out.splitlines():
        if line.startswith("_NET_WM_PID"):
            tail = line.rsplit("=", 1)[-1].strip()
            try:
                pid = int(tail.split(",")[0].strip())
            except ValueError:
                pid = None
        elif line.startswith("WM_CLASS"):
            # WM_CLASS(STRING) = "app", "App"
            parts = [p.strip().strip('"') for p in line.rsplit("=", 1)[-1].split(",")]
            if parts:
                cls = parts[0].lower()
    return pid, cls


def _match_by_title(title: str) -> Optional[int]:
    """Pencere başlığını adı/cmd'si ile eşleyerek PID tahmin eder (düşük güven)."""
    if not title or len(title) < 4:
        return None
    t = title[:60].lower()
    import psutil
    best: tuple = (None, 0)
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info.get("name") or "").lower()
            if not name or name in ("python3", "python"):
                continue
            cmd = " ".join(p.info.get("cmdline") or []).lower()[:200]
            score = 0
            if name and name in t:
                score += 3
            key = name.split(".")[0]
            if len(key) > 3 and key in t:
                score += 2
            if name and t.split(" ")[0] in cmd and name in cmd:
                score += 1
            if score > best[1]:
                best = (p.pid, score)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return best[0] if best[1] >= 2 else None


def _x11_focus() -> Optional[ForegroundInfo]:
    win = run(["xdotool", "getactivewindow"], timeout=3)
    if not win:
        return None
    win = win.strip()
    pid_out = run(["xdotool", "getwindowpid", win], timeout=3)
    name_out = run(["xdotool", "getwindowname", win], timeout=3)
    pid: Optional[int] = None
    try:
        pid = int(pid_out.strip()) if pid_out else None
    except ValueError:
        pid = None
    cls = ""
    if pid is None:
        pid, cls = _win_pid_via_xprop(win)
    info = ForegroundInfo(pid=pid, window_class=cls, source="xdotool",
                          title=(name_out or "")[:120])
    if pid:
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as f:
                info.proc_name = f.read().strip() or info.proc_name
        except Exception:
            pass
        info.confidence = "high"
        return info
    if info.title:
        guess = _match_by_title(info.title)
        if guess:
            info.pid = guess
            try:
                with open(f"/proc/{guess}/comm", encoding="utf-8", errors="replace") as f:
                    info.proc_name = f.read().strip()
            except Exception:
                pass
            info.confidence = "low"
            return info
    return None


def get_foreground(manual: Optional[str] = None) -> Optional[ForegroundInfo]:
    if manual:
        # proc_name verilir: analizde bu addaki süreç gerçekten varsa odakla eşleşir
        return ForegroundInfo(label=manual, proc_name=manual,
                              source="manual", confidence="manual")
    for fn in (_hyprland_focus, _sway_focus, _gnome_eval_focus, _x11_focus):
        try:
            info = fn()
        except Exception:
            info = None
        if info:
            return info
    return None


def _governor() -> Optional[str]:
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", encoding="ascii") as f:
            return f.read().strip()
    except Exception:
        return None


def _freq_bounds() -> tuple[Optional[int], Optional[int]]:
    lo = hi = None
    try:
        base = "/sys/devices/system/cpu/cpu0/cpufreq"
        with open(f"{base}/scaling_cur_freq", encoding="ascii") as f:
            lo = int(f.read().strip()) // 1000  # kHz -> MHz
        with open(f"{base}/cpuinfo_max_freq", encoding="ascii") as f:
            hi = int(f.read().strip()) // 1000
    except Exception:
        pass
    # amd/p-state boost limiti ayrıca amd_pstate limitleriyle değişebilir; kabaca yeter
    return lo, hi


def _boot_info() -> Dict[str, Any]:
    boot: Dict[str, Any] = {}
    total = run(["systemd-analyze"], timeout=8)
    if total:
        m = re.search(r"userspace.*?(\d+\.?\d*)s", total)
        if m:
            boot["boot_s"] = float(m.group(1))
        boot["raw"] = total[:160]
    blame = run(["systemd-analyze", "blame", "--no-pager"], timeout=10)
    if blame:
        offs: List[tuple] = []
        for line in blame.splitlines():
            m = re.match(r"\s*([\d\.m]+min?[\d\.s]*)\s+(\S+)", line)
            if not m:
                continue
            raw = m.group(1)
            try:
                mins = 0.0
                mm = re.match(r"(?:(\d+)(?:\.(\d+))?min)\s+([\d\.]+)s", raw)
                if mm:
                    mins = float(mm.group(1)) + (float(mm.group(2)) / 60 if mm.group(2) else 0)
                    sec = mins * 60 + float(mm.group(3))
                else:
                    sec = float(raw.replace("s", ""))
            except Exception:
                continue
            offs.append((m.group(2), sec))
        offsets = [x for x in offs if x[1] >= 2.0][:6]
        if offsets:
            boot["top_offenders"] = offsets
    return boot


def _service_counts() -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    out = run(["systemctl", "list-unit-files", "--state=enabled", "--type=service",
               "--no-legend"], timeout=8)
    if out is not None:
        d["enabled_system_units"] = [l.split()[0] for l in out.splitlines() if l.split()] or []
        d["enabled_system_count"] = len(d["enabled_system_units"])
    out = run(["systemctl", "--user", "list-unit-files", "--state=enabled",
               "--type=service", "--no-legend"], timeout=8)
    if out is not None:
        d["enabled_user_units"] = [l.split()[0] for l in out.splitlines() if l.split()] or []
        d["enabled_user_count"] = len(d["enabled_user_units"])
    out = run(["journalctl", "--disk-usage"], timeout=8)
    if out:
        m = re.search(r"take up ([\d\.]+[KMG]?)", out)
        if m:
            d["journal_usage"] = m.group(0)[:80]
    return d


def collect_extras() -> Dict[str, Dict[str, Any]]:
    boot = _boot_info()
    svc = _service_counts()
    boot.update({k: v for k, v in svc.items() if k not in ("journal_usage",)})
    boot["journal_usage"] = svc.get("journal_usage")
    lo, hi = _freq_bounds()
    gov = _governor()
    power = {"governor": gov}
    extras = {}
    if lo:
        extras["cpu_freq_now_mhz"] = lo
    if hi:
        extras["cpu_freq_max_mhz"] = hi
    # GNOME Shell.Eval kapalı olabilir — raporda belirt
    if os.environ.get("XDG_CURRENT_DESKTOP", "").lower().find("gnome") >= 0:
        extras["focus_note"] = "GNOME Wayland: odak penceresi CLI'dan okunamadıysa analiz 'odak bilinmiyor' moduna düşer"
    return {"boot": boot, "power": power, "extras": extras}