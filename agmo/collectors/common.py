"""Çekirdek telemetri: psutil ile süreç grupları + kaynak sayımları.

İki geçişli örnekleme: ilkinde CPU sayacı kalibre edilir ve IO okunur,
SAMPLE_INTERVAL bekleme sonrası ikinci geçişte delta'lar hesaplanır.
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Tuple

import psutil

from agmo import classify
from agmo.models import ForegroundInfo, ProcGroup
from agmo.util import MIB, run

SAMPLE_INTERVAL = 1.2  # saniye


def _proc_io(proc: psutil.Process) -> Tuple[Optional[int], Optional[int]]:
    try:
        io = proc.io_counters()
        return io.read_bytes, io.write_bytes
    except Exception:  # macOS AccessDenied / kısa süreç ölümleri
        return None, None


def _gpu_pid_mem() -> Dict[int, float]:
    """nvidia-smi varsa pid -> VRAM MiB haritası (oyun-benzeri tespit için)."""
    out = run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
               "--format=csv,noheader,nounits"], timeout=5)
    mapping: Dict[int, float] = {}
    if out:
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2 and parts[0].isdigit():
                mapping[int(parts[0])] = float(parts[1] or 0)
    return mapping


def _scan_self_tree() -> Set[int]:
    """AGMO'nun kendisi ve ata süreci (kabuk sarmalayıcıları) — ölüm kirliliği oluşturur,
    gruplardan tamamen çıkarılır (argv'da 'Valorant' geçen run.sh komutu gibi)."""
    skip = {os.getpid()}
    try:
        cur = psutil.Process(os.getpid()).parent()
        while cur is not None:
            skip.add(cur.pid)
            cur = cur.parent()
    except Exception:
        pass
    return skip


def collect_groups() -> List[ProcGroup]:
    """Tüm süreçleri ad bazında gruplar, sınıflandırır (role henüz atanmaz)."""
    pids_io: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
    procs: List[psutil.Process] = []
    t0 = time.monotonic()
    skip_pids = _scan_self_tree()
    for p in psutil.process_iter(["name"]):
        try:
            if p.pid in skip_pids:
                continue
            p.cpu_percent(None)  # 0.0 döner, sayaç kalibrasyonu
            pids_io[p.pid] = _proc_io(p)
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    time.sleep(SAMPLE_INTERVAL)
    dt = max(0.1, time.monotonic() - t0)

    groups: Dict[str, ProcGroup] = {}
    gpu_map = _gpu_pid_mem()
    for p in procs:
        try:
            name = (p.info.get("name") or "?" or "?") if p.info else p.name()
            cpu = p.cpu_percent(None)
            mem = p.memory_info().rss / MIB
            try:
                threads = p.num_threads() or 0
            except Exception:
                threads = 0
            cmdline = ""
            try:
                cl = p.cmdline()
                cmdline = " ".join(str(x) for x in cl)[:300]
            except Exception:
                pass
            io_r = io_w = 0.0
            try:
                rb, wb = _proc_io(p)
                b0 = pids_io.get(p.pid, (None, None))
                if rb is not None and b0[0] is not None:
                    io_r = max(0.0, (rb - b0[0]) / dt / MIB)
                    io_w = max(0.0, (wb - b0[1]) / dt / MIB)
            except Exception:
                pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        key = name.lower()
        g = groups.get(key)
        if g is None:
            g = ProcGroup(label=name, names=[name])
            g.cpu_pct = 0.0
            g.cmdline = cmdline
            groups[key] = g
        g.cpu_pct += cpu
        g.mem_mib += mem
        g.io_r_mib_s += io_r
        g.io_w_mib_s += io_w
        g.threads += threads
        if p.pid not in g.pids:
            g.pids.append(p.pid)
        if gpu_map and p.pid in gpu_map:
            g.gpu_mib = (g.gpu_mib or 0.0) + gpu_map[p.pid]

    out = list(groups.values())
    for g in out:
        g.key, g.kind, g.family = classify.match_signature(set(g.names), g.cmdline)
        g.label = classify.friendly_label(g.key, g.label.split(",")[0], g.kind)
    out.sort(key=lambda x: (x.mem_mib + x.cpu_pct * 8 + (x.gpu_mib or 0)), reverse=True)
    return out


def collect_temps() -> Dict[str, float]:
    """Best-effort sıcaklık: {cpu, gpu}. Yoksa boş sözlük."""
    temps: Dict[str, float] = {}
    try:
        d = psutil.sensors_temperatures() or {}
    except Exception:
        d = {}
    for pref in ("k10temp", "zenpower", "coretemp", "cpu_thermal", "cpu-thermal",
                 "x86_pkg_temp", "acpitz", "soc_thermal"):
        if pref in d and d[pref]:
            temps["cpu"] = max(t.current for t in d[pref] if t.current)
            break
    for pref in ("amdgpu", "nouveau", "radeon"):
        if pref in d and d[pref]:
            temps["gpu"] = max(t.current for t in d[pref] if t.current)
            break
    if not d:
        out = run(["nvidia-smi", "--query-gpu=temperature.gpu",
                   "--format=csv,noheader,nounits"], timeout=5)
        if out and out.strip():
            try:
                temps["gpu"] = float(out.splitlines()[0].strip())
            except ValueError:
                pass
    return temps


def collect_cpu_freq() -> Dict[str, Optional[float]]:
    """MHz cinsinden {cur(=çekirdeklerin ortalama anlık), max}."""
    freq: Dict[str, Optional[float]] = {}
    try:
        cf = psutil.cpu_freq()
        if cf and cf.current:
            freq["cur_mhz"] = cf.current
            freq["max_mhz"] = cf.max or None
    except Exception:
        pass
    return freq


def collect_io_counters() -> Tuple[float, float, Optional[float]]:
    """(read MiB/s, write MiB/s, busy%) toplam disk IO — delta üzerinden.
    busy% yalnızca read/write time alanı veren platformlarda (Linux/Win).
    """
    try:
        c0 = psutil.disk_io_counters(perdisk=False)
    except Exception:
        c0 = None
    if c0 is None:
        return 0.0, 0.0, None
    time.sleep(SAMPLE_INTERVAL)
    try:
        c1 = psutil.disk_io_counters(perdisk=False)
    except Exception:
        return 0.0, 0.0, None
    if c1 is None:
        return 0.0, 0.0, None
    dt = SAMPLE_INTERVAL
    rps = max(0.0, (c1.read_bytes - c0.read_bytes) / dt / MIB)
    wps = max(0.0, (c1.write_bytes - c0.write_bytes) / dt / MIB)
    busy = None
    try:
        busy = min(100.0, ((c1.read_time - c0.read_time) + (c1.write_time - c0.write_time)) / (dt * 10.0))
    except Exception:  # macOS: read_time alanı yok
        busy = None
    return rps, wps, busy


def collect_power() -> Dict[str, object]:
    p: Dict[str, object] = {}
    try:
        bat = psutil.sensors_battery()
        if bat:
            p["battery_pct"] = round(bat.percent, 1)
            p["plugged"] = bool(bat.power_plugged)
    except Exception:
        pass
    return p