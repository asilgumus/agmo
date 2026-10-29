"""Shared data model types: hardware, process groups, snapshot, findings.

Tüm katmanlar bu tipler üzerinde konuşur; platform kolektörleri Snapshot
üretilir, analiz motoru Baseline+Finding üretir, AI/rapor katmanı tüketir.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass
class DiskInfo:
    device: str = ""
    mountpoint: str = ""
    fstype: str = ""
    total_gib: float = 0.0
    is_system: bool = False
    medium: Optional[str] = None  # "SSD" | "HDD" | None (bilinmiyor)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Hardware:
    platform: str = "linux"  # linux | windows | macos
    os_pretty: str = ""
    arch: str = ""
    cpu_model: str = ""
    cpu_cores_physical: int = 0
    cpu_cores_logical: int = 0
    ram_total_gib: float = 0.0
    is_laptop: bool = False
    battery: Optional[str] = None
    plugged: Optional[bool] = None
    gpus: List[str] = field(default_factory=list)
    disks: List[DiskInfo] = field(default_factory=list)
    system_disk: Optional[DiskInfo] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def system_disk_medium(self) -> Optional[str]:
        return self.system_disk.medium if self.system_disk else None


@dataclass
class ForegroundInfo:
    pid: Optional[int] = None
    proc_name: str = ""
    label: str = ""
    window_class: str = ""
    title: str = ""
    source: str = ""  # hyprctl|swaymsg|xdotool|win32|osascript|manual
    confidence: str = "high"


@dataclass
class ProcGroup:
    """Aynı uygulamanın süreçleri gruplanır (Chrome ~50 süreç -> tek satır)."""

    names: List[str] = field(default_factory=list)
    label: str = ""
    pids: List[int] = field(default_factory=list)
    cpu_pct: float = 0.0          # sum (per-core scale; N çekirdekte N*100'ü aşabilir)
    mem_mib: float = 0.0
    io_r_mib_s: float = 0.0
    io_w_mib_s: float = 0.0
    threads: int = 0
    cmdline: str = ""             # temsili cmdline (kısaltılmış)
    key: str = "unknown"          # "valorant", "chrome", "searchindexer"...
    kind: str = "unknown"         # game|anticheat|launcher|browser|ide|devvm|av|indexer|cloud|updater|comms|media|system|system-critical|service|unknown
    family: str = ""              # riot|valve|epic|steam... (bileşen eşleştirme için)
    role: str = "background"      # foreground|game|companion|system|self|background
    exempt: bool = False          # taban çizgisinden hariç mi
    gpu_mib: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Snapshot:
    platform: str = "linux"
    ts: str = ""
    uptime_s: float = 0.0
    cpu_total_pct: float = 0.0
    load: tuple = (0.0, 0.0, 0.0)
    mem_used_mib: float = 0.0
    mem_avail_mib: float = 0.0
    mem_total_mib: float = 0.0
    swap_used_mib: float = 0.0
    swap_total_mib: float = 0.0
    disk_read_mib_s: float = 0.0
    disk_write_mib_s: float = 0.0
    disk_busy_pct: Optional[float] = None
    temps: Dict[str, float] = field(default_factory=dict)   # {"cpu": 71.0, "gpu": ...}
    cpu_freq: Dict[str, Optional[float]] = field(default_factory=dict)  # {cur_mhz,min,max,governor?}
    power: Dict[str, Any] = field(default_factory=dict)     # {plugged,battery_pct,scheme,lowpowermode}
    boot: Dict[str, Any] = field(default_factory=dict)      # {boot_s,top_offenders,unit_count,...}
    storage: Dict[str, Any] = field(default_factory=dict)   # {cache_dirs:[{path,size_mib}]}
    extras: Dict[str, Any] = field(default_factory=dict)    # os-özel ham notlar (GameDVR vs.)
    focus: Optional[ForegroundInfo] = None
    procs: List[ProcGroup] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class Fix:
    text: str
    cmd: Optional[str] = None
    os: Optional[str] = None  # linux|windows|macos|any
    risk: str = "safe"        # safe|careful|risky


@dataclass
class Finding:
    id: str
    title: str
    severity: str = "medium"
    category: str = "memory"
    source: str = "local"     # local | ai
    why: str = ""
    evidence: str = ""
    fixes: List[Fix] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "severity": self.severity,
            "category": self.category,
            "source": self.source,
            "why": self.why,
            "evidence": self.evidence,
            "fixes": [{"text": f.text, "cmd": f.cmd, "os": f.os, "risk": f.risk} for f in self.fixes],
        }


@dataclass
class Baseline:
    """Valorant gibi odak oyunu hariç tutulmuş taban çizgisi."""

    game_label: Optional[str] = None
    exempt_mem_mib: float = 0.0
    exempt_cpu_norm_pct: float = 0.0
    mem_used_mib: float = 0.0
    base_mem_mib: float = 0.0
    mem_total_mib: float = 0.0
    mem_pct_raw: float = 0.0
    base_mem_pct: float = 0.0
    mem_avail_gib: float = 0.0
    mem_verdict: str = "normal"   # normal | warn | high | critical
    base_cpu_pct: float = 0.0
    cpu_verdict: str = "normal"
    swap_used_mib: float = 0.0
    swap_total_mib: float = 0.0
    line: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Analysis:
    snapshot: Snapshot
    baseline: Baseline
    findings: List[Finding] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    ai: Optional[Dict[str, Any]] = None  # {model, summary, baseline_note, status}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "findings": [f.to_dict() for f in self.sorted_findings()],
            "notes": list(self.notes),
            "ai": self.ai,
        }

    def sorted_findings(self) -> List[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.id),
        )