"""Toplayıcı orkestrasyonu: tek Snapshot üretir (~2.5s tarama penceresi)."""

from __future__ import annotations

import datetime as _dt
import sys
import time
from typing import Optional

import psutil

from agmo.models import Snapshot
from agmo.util import MIB

from . import common

PLATFORM_MAP = {"linux": "linux", "win32": "windows", "darwin": "macos"}


def _platform_module():
    return __import__(f"agmo.collectors.{PLATFORM_MAP.get(sys.platform, 'linux')}", fromlist=["x"])


def collect_snapshot(focus_arg: Optional[str] = None) -> Snapshot:
    snap = Snapshot()
    snap.platform = PLATFORM_MAP.get(sys.platform, sys.platform)
    snap.ts = _dt.datetime.now().isoformat(timespec="seconds")

    psutil.cpu_percent(None)  # kalibrasyon
    snap.procs = common.collect_groups()  # içinde ~1.2s örnekleme yapar
    snap.cpu_total_pct = psutil.cpu_percent(None)

    rps, wps, busy = common.collect_io_counters()
    snap.disk_read_mib_s, snap.disk_write_mib_s, snap.disk_busy_pct = rps, wps, busy

    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    snap.uptime_s = time.time() - psutil.boot_time()
    snap.mem_used_mib = (vm.total - vm.available) / MIB
    snap.mem_avail_mib = vm.available / MIB
    snap.mem_total_mib = vm.total / MIB
    snap.swap_used_mib = sm.used / MIB
    snap.swap_total_mib = sm.total / MIB
    try:
        snap.load = psutil.getloadavg()
    except Exception:
        snap.load = (0.0, 0.0, 0.0)

    snap.temps = common.collect_temps()
    snap.cpu_freq = common.collect_cpu_freq()
    snap.power = common.collect_power()

    snap.focus = _platform_module().get_foreground(focus_arg)
    try:
        extra = _platform_module().collect_extras()
    except Exception:
        extra = {}
    snap.boot = extra.get("boot", {})
    snap.power.update(extra.get("power", {}))
    snap.extras = extra.get("extras", {})
    return snap