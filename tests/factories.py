"""Sentetik Hardware/Snapshot üreteci (analiz motoru unit testleri için)."""
from __future__ import annotations

from typing import List, Optional

from agmo.models import DiskInfo, Hardware, ProcGroup, Snapshot


def make_hw(ram_gib: float = 16.0, cores_logical: int = 8, hdd: bool = False,
            laptop: bool = False) -> Hardware:
    hw = Hardware()
    hw.platform = "linux"
    hw.os_pretty = "TestOS 1.0"
    hw.cpu_model = "Test CPU"
    hw.cpu_cores_physical = max(1, cores_logical // 2)
    hw.cpu_cores_logical = cores_logical
    hw.ram_total_gib = ram_gib
    hw.gpus = ["Intel GPU"]
    med = "HDD" if hdd else "SSD"
    d = DiskInfo(device="/dev/sda1", mountpoint="/", fstype="ext4",
                 total_gib=500.0, is_system=True, medium=med)
    hw.disks = [d]
    hw.system_disk = d
    hw.is_laptop = laptop
    hw.plugged = True
    return hw


def make_proc(label: str, mem_mib: float, cpu: float = 0.0,
              key: str = "unknown", kind: str = "unknown", family: str = "",
              io_w: float = 0.0, io_r: float = 0.0, names: Optional[List[str]] = None,
              pids: Optional[List[int]] = None, gpu_mib: float = 0.0,
              cmdline: str = "") -> ProcGroup:
    g = ProcGroup(label=label, names=names or [label.lower()])
    g.mem_mib = mem_mib
    g.cpu_pct = cpu
    g.key = key
    g.kind = kind
    g.family = family
    g.io_w_mib_s = io_w
    g.io_r_mib_s = io_r
    g.pids = pids or [123, 124, 125, 126]
    g.gpu_mib = gpu_mib or None
    g.threads = 4
    g.cmdline = cmdline
    return g


def make_snapshot(procs: List[ProcGroup], ram_gib: float = 16.0, used_pct: float = 70.0,
                  cpu_total: float = 20.0, swap_used_mib: float = 0.0, swap_total_mib: float = 0.0,
                  disk_w: float = 0.0, disk_r: float = 0.0, disk_busy: Optional[float] = 0.0,
                  temps: Optional[dict] = None, focus=None, **extra) -> Snapshot:
    snap = Snapshot()
    snap.platform = "linux"
    snap.ts = "2026-10-28T20:00:00"
    snap.uptime_s = 3600
    total_mib = ram_gib * 1024
    snap.mem_total_mib = total_mib
    snap.mem_used_mib = total_mib * used_pct / 100
    snap.mem_avail_mib = total_mib - snap.mem_used_mib
    snap.swap_used_mib = swap_used_mib
    snap.swap_total_mib = swap_total_mib
    snap.cpu_total_pct = cpu_total
    snap.load = (1.0, 1.0, 1.0)
    snap.disk_write_mib_s = disk_w
    snap.disk_read_mib_s = disk_r
    snap.disk_busy_pct = disk_busy
    snap.temps = temps or {}
    snap.focus = focus
    snap.procs = procs
    for k, v in extra.items():
        setattr(snap, k, v)
    return snap