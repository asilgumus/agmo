"""Donanım profili: OS, CPU, RAM, GPU, disk tipi (SSD/HDD), pil."""
from __future__ import annotations

import os
import platform
import re
import sys
from typing import Dict, List, Optional

import psutil

from agmo.models import DiskInfo, Hardware
from agmo.util import run

PLATFORMS = {"linux": "linux", "win32": "windows", "darwin": "macos"}


def platform_name() -> str:
    return PLATFORMS.get(sys.platform, sys.platform)


def os_pretty() -> str:
    if sys.platform == "linux":
        try:
            with open("/etc/os-release", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
        return platform.platform()
    if sys.platform == "win32":
        v = platform.win32_ver()
        return f"Windows {v[0]} ({v[2]})".strip()
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}".strip()
    return platform.platform()


def _cpu_model() -> str:
    if sys.platform == "linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.lower().startswith(("model name", "hardware")):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return platform.processor() or "bilinmiyor"
    if sys.platform == "win32":
        out = run(["powershell", "-NoProfile", "-Command",
                   "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"], timeout=12)
        if out:
            return out.strip().replace("(R)", "").replace("(TM)", "")
        return platform.processor() or "bilinmiyor"
    if sys.platform == "darwin":
        return run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "Apple Silicon"
    return "bilinmiyor"


def _gpus() -> List[str]:
    gpus: List[str] = []
    out = run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=6)
    if out:
        gpus += [l.strip() for l in out.splitlines() if l.strip()]
    if sys.platform == "linux":
        for card in sorted(os.listdir("/sys/class/drm")):
            if not card.startswith("card") or "-" in card:
                continue
            try:
                with open(f"/sys/class/drm/{card}/device/uevent", encoding="utf-8", errors="replace") as f:
                    drv = ""
                    vendor = ""
                    for line in f:
                        if line.startswith("DRIVER="):
                            drv = line.split("=", 1)[1].strip()
                        elif line.startswith("PCI_ID="):
                            vendor = line.split("=", 1)[1].split(":")[0].lower()
                    known = {"i915": "Intel", "xe": "Intel", "amdgpu": "AMD", "nouveau": "NVIDIA",
                             "nvidia": "NVIDIA", "radeon": "AMD", "vkms": None, "vc4": "Broadcom",
                             "v3d": "Broadcom", "panfrost": "Mali", "msm": "Adreno"}
                    if drv in known and known[drv] and not gpus:
                        gpus.append(f"{known[drv]} GPU ({drv})" + (f" [{vendor}]" if vendor else ""))
            except Exception:
                continue
    elif sys.platform == "win32":
        out = run(["powershell", "-NoProfile", "-Command",
                   "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                  timeout=12)
        if out:
            gpus += [l.strip() for l in out.splitlines() if l.strip()]
    elif sys.platform == "darwin":
        out = run(["system_profiler", "SPDisplaysDataType"], timeout=10)
        if out:
            for line in out.splitlines():
                s = line.strip()
                if s.startswith("Chipset Model:") or s.startswith("Graphics/Displays"):
                    n = s.split(":", 1)[-1].strip()
                    if n and n not in gpus and n != "Graphics/Displays":
                        gpus.append(n)
    if not gpus:
        gpus = ["bilinmiyor"]
    return gpus


_PARTITION_RX = re.compile(r"(nvme\d+n\d+|mmcblk\d+)p\d+$")


def _strip_partition(name: str) -> Optional[str]:
    """/dev/sda1 -> sda, nvme0n1p2 -> nvme0n1, mmcblk0p1 -> mmcblk0"""
    m = _PARTITION_RX.match(name)
    if m:
        return m.group(1)
    m = re.match(r"([a-z]+[a-z]\d*)\d+$", name)  # sda1 -> sda
    if m and not name.startswith(("loop", "ram", "zram", "dm-", "md")):
        return m.group(1)
    return None


def _rotational_linux(device: str) -> Optional[str]:
    """/sys/block/<disk>/queue/rotational okur; HDD/SSD veya None."""
    b = os.path.basename(device)
    parent = b
    try:  # partition ise slaves altında gerçek disk adı vardır
        slaves = os.listdir(f"/sys/class/block/{b}/slaves")
        if slaves:
            parent = slaves[0]
    except Exception:
        parent = _strip_partition(b) or b
    try:
        with open(f"/sys/block/{parent}/queue/rotational", encoding="ascii") as f:
            return "HDD" if f.read().strip() == "1" else "SSD"
    except Exception:
        return None


def _disk_media_windows() -> List[str]:
    out = run(["powershell", "-NoProfile", "-Command",
               "Get-PhysicalDisk | Select-Object -ExpandProperty MediaType"], timeout=12)
    if not out:
        return []
    return [l.strip() for l in out.splitlines() if l.strip()]


def _disk_media_macos() -> Optional[str]:
    out = run(["diskutil", "info", "/"], timeout=8)
    if out:
        for line in out.splitlines():
            if "Solid State" in line:
                return "SSD" if line.strip().endswith("Yes") else "HDD"
    return "SSD"  # Apple Silicon iç disk her zaman SSD


def collect() -> Hardware:
    hw = Hardware()
    hw.platform = platform_name()
    hw.os_pretty = os_pretty()
    hw.arch = platform.machine() or "?"

    vm = psutil.virtual_memory()
    hw.ram_total_gib = vm.total / (1024 ** 3)
    hw.cpu_model = _cpu_model()
    hw.cpu_cores_logical = psutil.cpu_count(logical=True) or 1
    hw.cpu_cores_physical = psutil.cpu_count(logical=False) or hw.cpu_cores_logical

    bat = None
    try:
        bat = psutil.sensors_battery()
    except Exception:
        bat = None
    if bat is not None:
        hw.is_laptop = True
        state = "fişte" if bat.power_plugged else "pil"
        hw.battery = f"%{int(bat.percent)} ({state})"
        hw.plugged = bool(bat.power_plugged)

    hw.gpus = _gpus()

    # diskler
    try:
        parts = psutil.disk_partitions(all=False)
    except Exception:
        parts = []
    for p in parts:
        med: Optional[str] = None
        if hw.platform == "linux":
            med = _rotational_linux(p.device)
        elif hw.platform == "macos" and p.mountpoint == "/":
            med = _disk_media_macos()
        try:
            usage = psutil.disk_usage(p.mountpoint)
            total = usage.total / (1024 ** 3)
        except Exception:
            total = 0.0
        is_system = (p.mountpoint == "/" or
                     (hw.platform == "windows" and p.mountpoint.upper().rstrip("\\") ==
                      os.environ.get("SystemDrive", "C:").upper().rstrip("\\")))
        d = DiskInfo(device=p.device, mountpoint=p.mountpoint, fstype=p.fstype,
                     total_gib=round(total, 1), is_system=is_system, medium=med)
        hw.disks.append(d)
    hw.system_disk = next((d for d in hw.disks if d.is_system), None)

    if hw.platform == "windows" and hw.disks:
        meds = _disk_media_windows()
        uniq = {m for m in meds if m in ("SSD", "HDD")}
        if len(uniq) == 1:
            m = uniq.pop()
            for d in hw.disks:
                d.medium = m
    if hw.platform == "macos" and hw.system_disk:
        hw.system_disk.medium = hw.system_disk.medium or "SSD"
    return hw