"""Windows özel toplayıcılar: odak pencere (Win32 API), güç planı,
Game DVR/GameBar ve başlangıç öğeleri (registry).
"""
from __future__ import annotations

import ctypes
import os
from typing import Any, Dict, List, Optional

from agmo.models import ForegroundInfo
from agmo.util import run

try:
    import psutil
except Exception:
    psutil = None

try:
    import winreg
except ImportError:
    winreg = None


def get_foreground(manual: Optional[str] = None) -> Optional[ForegroundInfo]:
    if manual:
        # proc_name verilir: analizde bu addaki süreçle eşleşir (linux kuralı ile aynı)
        return ForegroundInfo(label=manual, proc_name=manual,
                              source="manual", confidence="manual")
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        info = ForegroundInfo(pid=int(pid.value) if pid.value else None,
                              source="win32", title=buf.value[:120])
        if info.pid and psutil:
            try:
                info.proc_name = psutil.Process(info.pid).name()
            except Exception:
                pass
        return info
    except Exception:
        return None


def _reg_dword(root: int, path: str, name: str) -> Optional[int]:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(root, path) as k:
            v, _t = winreg.QueryValueEx(k, name)
            if isinstance(v, int):
                return v
    except Exception:
        pass
    return None


def _run_key_names(root: int, path: str) -> List[str]:
    out: List[str] = []
    if winreg is None:
        return out
    try:
        with winreg.OpenKey(root, path) as k:
            i = 0
            while True:
                try:
                    name, _v, _t = winreg.EnumValue(k, i)
                    out.append(name)
                    i += 1
                except OSError:
                    break
    except Exception:
        pass
    return out


def collect_extras() -> Dict[str, Dict[str, Any]]:
    power: Dict[str, Any] = {}
    extras: Dict[str, Any] = {}
    boot: Dict[str, Any] = {}

    out = run(["powercfg", "/getactivescheme"], timeout=6)
    if out:
        name = out.split("(", 1)[-1].strip().rstrip(")")
        power["scheme"] = name
        if "power saver" in name.lower() or "tasarruf" in name.lower() or "pil" in name.lower():
            power["scheme_hint"] = "power-saver"

    HCU = winreg.HKEY_CURRENT_USER if winreg else None
    if HCU is not None:
        gamedvr = _reg_dword(HCU, r"System\GameConfigStore", "GameDVR_Enabled")
        if gamedvr is not None:
            extras["gamedvr_enabled"] = bool(gamedvr)
        gamemode = _reg_dword(HCU, r"Software\Microsoft\GameBar", "AutoGameModeEnabled")
        if gamemode is not None:
            extras["gamemode_enabled"] = bool(gamemode)
        autogamebar = _reg_dword(HCU, r"Software\Microsoft\GameBar", "AllowAutoGameCapture")
        if autogamebar is not None:
            extras["gamebar_autocapture"] = bool(autogamebar)

        run_hkcu = _run_key_names(HCU, r"Software\Microsoft\Windows\CurrentVersion\Run")
        run_hklm = []
        if winreg:
            try:
                run_hklm = _run_key_names(winreg.HKEY_LOCAL_MACHINE,
                                          r"Software\Microsoft\Windows\CurrentVersion\Run")
            except Exception:
                run_hklm = []
        boot["startup_items"] = sorted(set(run_hkcu + run_hklm))[:30]
        boot["startup_count"] = len(set(run_hkcu + run_hklm))

    temp = os.environ.get("TEMP") or r"C:\Windows\Temp"
    extras["temp_dir"] = temp
    return {"boot": boot, "power": power, "extras": extras}