"""macOS özel toplayıcılar: odak uygulama (osascript), Spotlight,
Termal baskı durumu, LaunchAgents.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from agmo.util import run

from agmo.models import ForegroundInfo


def get_foreground(manual: Optional[str] = None) -> Optional[ForegroundInfo]:
    if manual:
        # proc_name verilir: analizde bu addaki süreçle eşleşir (linux kuralı ile aynı)
        return ForegroundInfo(label=manual, proc_name=manual,
                              source="manual", confidence="manual")
    out = run(["osascript", "-e",
               'tell application "System Events" to get {unix id, name} of '
               'first application process whose frontmost is true'], timeout=6)
    if not out or "," not in out:
        return None
    parts = [p.strip().strip('"') for p in out.split(",", 1)]
    if not parts or not parts[0].lstrip("-").isdigit():
        return None
    info = ForegroundInfo(pid=int(parts[0]), proc_name=parts[1] if len(parts) > 1 else "",
                          source="osascript")
    if not info.proc_name and info.pid:
        out2 = run(["ps", "-o", "comm=", "-p", str(info.pid)], timeout=4)
        info.proc_name = (out2 or "").strip().split("/")[-1]
    return info


def _thermal_state() -> Optional[str]:
    out = run(["pmset", "-g", "therm"], timeout=6)
    if out and "CPU_Speed_Limit" in out:
        try:
            for line in out.splitlines():
                if "CPU_Speed_Limit" in line:
                    pct = int(line.split("=")[-1].strip())
                    if pct < 100:
                        return f"CPU hız sınırı %{pct} (throttle aktif)"
        except Exception:
            return None
    return None


def _spotlight_state() -> Optional[str]:
    out = run(["mdutil", "-s", "/"], timeout=6)
    if not out:
        return None
    low = out.lower()
    # sıra önemli: "Indexing disabled" metni 'indexing' sözcüğünü de içerir
    if "disabled" in low:
        return "disabled"
    if "indexing" in low or "reindexing" in low:
        return "indexing"
    return "enabled"


def _launch_agent_dirs() -> List[str]:
    """LaunchAgents dizinleri (testler enjekte edebilir)."""
    return [os.path.expanduser("~/Library/LaunchAgents"), "/Library/LaunchAgents"]


def collect_extras() -> Dict[str, Dict[str, Any]]:
    boot: Dict[str, Any] = {}
    power: Dict[str, Any] = {}
    extras: Dict[str, Any] = {}

    pmset = run(["pmset", "-g"], timeout=6) or ""
    for line in pmset.splitlines():
        if "lowpowermode" in line:
            try:
                power["lowpowermode"] = int(line.strip().split()[-1]) == 1
            except Exception:
                pass
    therm = _thermal_state()
    if therm:
        power["thermal_throttle"] = therm
    sp = _spotlight_state()
    if sp:
        extras["spotlight"] = sp

    agents: List[str] = []
    for d in _launch_agent_dirs():
        try:
            agents += [os.path.basename(f) for f in os.listdir(d) if f.endswith(".plist")]
        except Exception:
            continue
    boot["login_items"] = sorted(set(agents))[:30]
    boot["login_items_count"] = len(set(agents))
    return {"boot": boot, "power": power, "extras": extras}