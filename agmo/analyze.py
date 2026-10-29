"""Yerel analiz motoru.

Ana fikir — "oyun hariç taban çizgisi":
  1) Odaktaki oyun + bileşenleri (anticheat, aynı markanın başlatıcısı)
     exemption listesine girer.
  2) RAM/CPU taban çizgisi bu süreçler hariç hesaplanır:
        base_mem = kullanılan RAM - hariç tutulanların RSS toplamı
        base_cpu = (hariç tutulanların dışındaki CPU toplamı) / çekirdek sayısı
  3) Eşikler donanıma göre kalibre edilir (8 GiB != 64 GiB; HDD != SSD).
  4) Kalan süreçlerden bulgular çıkar; oyuna dair bağlam ise "bilgi" olur.

Analiz motoru AI olmadan da çalışır; AI katmanı bu yapıyı zenginleştirir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from agmo import classify
from agmo.models import Analysis, Baseline, Finding, Fix, Hardware, ProcGroup, Snapshot
from agmo.util import fmt_gib

GAME_GPU_MIB = 1200.0  # bilinmeyen süreç bu VRAM'i kullanıyorsa oyun olabilir


# ------------------------------------------------------------- eşikler
@dataclass
class Thresholds:
    mem_warn: float = 60.0
    mem_crit: float = 78.0
    mem_avail_crit_gib: float = 1.2
    cpu_warn: float = 60.0
    cpu_crit: float = 85.0
    disk_w_warn_mib_s: float = 30.0
    disk_busy_warn: float = 85.0
    temp_warn: float = 85.0
    temp_crit: float = 95.0
    swap_warn_pct: float = 15.0
    hdd_system: bool = False


def thresholds(hw: Hardware) -> Thresholds:
    t = Thresholds()
    ram = hw.ram_total_gib
    if ram <= 8:
        t.mem_warn, t.mem_crit = 50.0, 66.0
    elif ram >= 64:
        t.mem_warn, t.mem_crit = 76.0, 88.0
    elif ram >= 32:
        t.mem_warn, t.mem_crit = 70.0, 84.0
    if hw.cpu_cores_logical <= 6:
        t.cpu_warn, t.cpu_crit = 52.0, 80.0
    if hw.is_laptop:
        t.temp_warn = 90.0  # laptop CPU'ları sıcak çalışır
    sm = hw.system_disk_medium
    t.hdd_system = (sm == "HDD")
    t.disk_w_warn_mib_s = 6.0 if t.hdd_system else 30.0
    return t


# ------------------------------------------------------- rol atama
@dataclass
class Context:
    ts: Thresholds
    hw: Hardware
    exempt: List[ProcGroup] = field(default_factory=list)
    others: List[ProcGroup] = field(default_factory=list)
    game_running: bool = False
    game_keys: List[str] = field(default_factory=list)
    focus_group: Optional[ProcGroup] = None


def _group_of_pid(procs: List[ProcGroup], pid: Optional[int]) -> Optional[ProcGroup]:
    if pid is None:
        return None
    for g in procs:
        if pid in g.pids:
            return g
    return None


def _group_of_name(procs: List[ProcGroup], name: str) -> Optional[ProcGroup]:
    low = (name or "").lower()
    if not low:
        return None
    for g in procs:
        for n in g.names:
            nl = n.lower()
            if nl == low or low in nl or nl in low:
                return g
    return None


def assign_roles(snap: Snapshot, hw: Hardware) -> Context:
    """Gruplara role/exempt atar, Context döndürür."""
    import psutil

    ctx = Context(ts=thresholds(hw), hw=hw)

    self_name = psutil.Process().name().lower()
    for g in snap.procs:
        if any(n.lower() == self_name for n in g.names):
            g.role = "self"
            g.exempt = True
            g.notes.append("AGMO'nun kendisi")

    if snap.focus:
        fg = _group_of_pid(snap.procs, snap.focus.pid) or _group_of_name(snap.procs, snap.focus.proc_name)
        if fg and fg.role != "self":
            fg.role = "foreground"
            ctx.focus_group = fg

    # oyunlar
    game_families = set()
    for g in snap.procs:
        if g.kind == "game" and g.role != "self":
            if g.role != "foreground":
                g.role = "game"
            g.exempt = True
            ctx.game_running = True
            if g.key not in ctx.game_keys:
                ctx.game_keys.append(g.key)
            if g.family:
                game_families.add(g.family)
            g.notes.append("oyun — analizden hariç")

    # GPU kullanan listede olmayan süreç -> oyun olabilir
    for g in snap.procs:
        if g.kind == "unknown" and g.role != "self":
            if (g.gpu_mib or 0) > GAME_GPU_MIB and g.cpu_pct > 3:
                g.kind = "game-suspect"
                g.exempt = True
                if g.role != "foreground":
                    g.role = "game"
                ctx.game_running = True
                g.notes.append("GPU tüketen oyun-benzeri süreç — hariç tutuldu "
                               "(--focus ile adını onaylarsın)")

    # anticheat: oyun kapalıyken bile servisi ayakta olabilir
    for g in snap.procs:
        if g.kind == "anticheat":
            g.role = "companion"
            g.exempt = True
            label = classify.friendly_label(g.key, g.label, g.kind)
            if not ctx.game_running:
                g.notes.append(f"{label} çalışıyor (oyun kapalı) — servis bileşeni; "
                               "kapatma önerilmez, bilgi amaçlı")

    # launcher: yalnızca aynı markanın oyunu çalışıyorsa hariç
    for g in snap.procs:
        if g.kind == "launcher":
            if g.family and g.family in game_families:
                g.role = "companion"
                g.exempt = True
                g.notes.append("oyunun başlatıcısı — hariç")
            else:
                if g.role != "foreground":
                    g.role = "background"

    for g in snap.procs:
        if g.kind in ("system", "system-critical", "service") and g.role == "background":
            g.role = "system"

    ctx.exempt = [g for g in snap.procs if g.exempt and g.role != "self"]
    ctx.others = [g for g in snap.procs if not g.exempt and g.role != "self"]
    return ctx


# ---------------------------------------------------------- taban çizgisi
def baseline(snap: Snapshot, ctx: Context) -> Baseline:
    b = Baseline()
    if ctx.game_running:
        games = [g for g in snap.procs if g.kind in ("game", "game-suspect")
                 and g.role != "self"]
        if ctx.focus_group and ctx.focus_group.kind in ("game", "game-suspect"):
            b.game_label = ctx.focus_group.label
        elif games:
            # odak algılanamadı/odak oyun değil: en büyük kaynak tüketen oyunu yaz
            primary = max(games, key=lambda g: (g.mem_mib, g.gpu_mib or 0))
            b.game_label = primary.label
    cores = max(1, ctx.hw.cpu_cores_logical)
    b.exempt_mem_mib = sum(g.mem_mib for g in ctx.exempt)
    b.exempt_cpu_norm_pct = round(min(100.0, sum(g.cpu_pct for g in ctx.exempt) / cores), 1)

    b.mem_used_mib = snap.mem_used_mib
    b.mem_total_mib = snap.mem_total_mib
    b.mem_pct_raw = round(snap.mem_used_mib / max(1.0, snap.mem_total_mib) * 100, 1)
    b.base_mem_mib = max(0.0, snap.mem_used_mib - b.exempt_mem_mib)
    b.base_mem_pct = round(b.base_mem_mib / max(1.0, snap.mem_total_mib) * 100, 1)
    b.mem_avail_gib = snap.mem_avail_mib / 1024

    other_cpu_sum = sum(g.cpu_pct for g in ctx.others)
    b.base_cpu_pct = round(min(100.0, other_cpu_sum / cores), 1)
    b.cpu_verdict = _verdict(b.base_cpu_pct, ctx.ts.cpu_warn, ctx.ts.cpu_crit)

    t = ctx.ts
    if b.mem_avail_gib <= t.mem_avail_crit_gib or b.base_mem_pct >= t.mem_crit:
        b.mem_verdict = "critical"
    elif b.base_mem_pct >= t.mem_warn:
        b.mem_verdict = "high"
    else:
        b.mem_verdict = "normal"
    b.swap_used_mib = snap.swap_used_mib
    b.swap_total_mib = snap.swap_total_mib

    parts = [f"RAM: {fmt_gib(b.base_mem_mib)} / {fmt_gib(b.mem_total_mib)} (%{b.base_mem_pct:.0f})"]
    parts.append(f"CPU{' (oyun hariç)' if b.game_label else ''}: ~%{b.base_cpu_pct:.0f}")
    if b.game_label:
        parts.insert(0, f"{b.game_label} hariç")
    b.line = " — ".join(parts) + f" → RAM {b.mem_verdict.upper()}, CPU {b.cpu_verdict.upper()}"
    return b


def _verdict(v: float, warn: float, crit: float) -> str:
    if v >= crit:
        return "critical"
    if v >= warn:
        return "high"
    return "normal"


def _top(lst: List[ProcGroup], keyfn, n: int) -> List[ProcGroup]:
    return sorted([x for x in lst if keyfn(x) > 0], key=keyfn, reverse=True)[:n]


def _fix_for(g: ProcGroup) -> List[Fix]:
    hint = classify.APP_FIX_HINTS.get(g.key)
    if not hint:
        return []
    if isinstance(hint, list):
        return [Fix(text=h) for h in hint]
    risk = "careful" if g.kind == "devvm" else "safe"
    os_hint = {"wsl": "windows"}.get(g.key)
    return [Fix(text=hint, risk=risk, os=os_hint)]


def _inv_fix(g: ProcGroup, platform: str) -> List[Fix]:
    if platform == "windows":
        return [Fix(text=f"Görev Yöneticisi > Ayrıntılar > {g.label} > 'Konumu aç' ile dosya yolunu doğrula; tanıdık değilse üretici sitesinden araştır.", risk="safe")]
    if platform == "macos":
        return [Fix(text=f"Etkinlik İzleyici > {g.label} > 'Örnek Al' ile kim açtı/yolunu incele; güvenmiyorsan başlatma öğelerinden kaldır.", risk="safe")]
    return [Fix(text=f"`ps aux | grep -i {g.names[0]}` ile komut/yolunu incele; tanıdık değilse yürütülebilir dosyanın yolunu izle.", risk="safe")]


SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def _add(findings: List[Finding], f: Finding) -> None:
    if f.severity not in SEV_RANK:
        f.severity = "medium"
    if not any(x.id == f.id for x in findings):
        findings.append(f)


# ------------------------------------------------------------ bulgu kuralları
def run_rules(snap: Snapshot, ctx: Context, b: Baseline,
              include_storage: bool = True) -> Tuple[List[Finding], List[str]]:
    findings: List[Finding] = []
    notes: List[str] = []
    t = ctx.ts
    oth = ctx.others

    # --- RAM taban çizgisi
    if b.mem_verdict in ("high", "critical"):
        top_mem = _top(oth, lambda g: g.mem_mib, 4)
        ev = ", ".join(f"{g.label} {fmt_gib(g.mem_mib)} ({classify.KIND_TR.get(g.kind, g.kind)})"
                       for g in top_mem)
        fixes: List[Fix] = []
        for g in top_mem[:2]:
            fixes += _fix_for(g)[:1]
        _add(findings, Finding(
            id="baseline-mem",
            title=(f"Oyun hariç RAM yüksek: %{b.base_mem_pct:.0f}" if ctx.game_running
                   else f"RAM kullanımı yüksek: %{b.base_mem_pct:.0f}"),
            severity=b.mem_verdict, category="memory",
            why=("Odaktaki oyun hariç tutuldu; geri kalan süreçlerin RAM kullanımı makul kapasiteyi aşıyor."
                 if ctx.game_running else
                 "Oyun dışı süreçlerin RAM kullanımı makul kapasiteyi aşıyor; sistem sayfalamaya başlayabilir."),
            evidence=ev or "süreç ölçümü alınamadı",
            fixes=fixes or [
                Fix(text="Kullanılmayan programları kapat; başlangıç öğelerini devre dışı bırak."),
                Fix(text="RAM ≤ 8 GiB ise tarayıcı sekme sayısını ve ağır uygulamaları oyun dışı saatlere planla."),
            ],
        ))

    # --- CPU taban çizgisi
    if b.base_cpu_pct >= t.cpu_warn:
        top_cpu = _top(oth, lambda g: g.cpu_pct, 4)
        ev = ", ".join(f"{g.label} %{g.cpu_pct:.0f} CPU" for g in top_cpu)
        fixes = []
        for g in top_cpu[:2]:
            fixes += _fix_for(g)[:1]
        _add(findings, Finding(
            id="baseline-cpu",
            title=(f"Oyun hariç CPU yüksek: ~%{b.base_cpu_pct:.0f}" if ctx.game_running
                   else f"CPU kullanımı yüksek: ~%{b.base_cpu_pct:.0f}"),
            severity=("high" if b.base_cpu_pct >= t.cpu_crit else "medium"),
            category="cpu",
            why="Odak oyun hariç tutuldu; arka plan süreçlerinin toplam CPU'su yüksek, oyun başlarken/çalışırken stutter yapar."
                if ctx.game_running else
                "Arka plan süreçlerinin toplam CPU'su yüksek; sistem genelinde gecikme yapar.",
            evidence=ev or "n/a",
            fixes=fixes or [Fix(text="Bu rapordaki CPU tüketicisini bul; gereksizse kapat, gerekiyorsa işini bitirmeye bırak.")],
        ))

    # --- mutlak düşük kullanılabilir RAM
    if b.mem_avail_gib < t.mem_avail_crit_gib:
        _add(findings, Finding(
            id="mem-avail-low",
            title=f"Kullanılabilir RAM kritik: {b.mem_avail_gib:.1f} GiB",
            severity="high", category="memory",
            why="Sistem anlık tahsislerde alan bulamamaya başlar; takılma ve sayfalama artar.",
            evidence=f"kullanılabilir {b.mem_avail_gib:.2f} / {fmt_gib(b.mem_total_mib)}",
            fixes=[Fix(text="Oyun/uygulama dışındaki büyük RAM tüketicilerini kapat.")],
        ))

    # --- tarayıcı
    for g in oth:
        if g.kind == "browser" and g.mem_mib > max(900.0, b.mem_total_mib * 0.07):
            _add(findings, Finding(
                id="browser-tabs",
                title=f"{g.label} yüksek RAM: {fmt_gib(g.mem_mib)} (~{len(g.pids)} süreç)",
                severity="medium", category="memory",
                why="Arka plan sekmeleri RAM/işlemci tutar; sayfalar çoğaldıkça maliyet büyür.",
                evidence=f"süreç sayısı ≈ {len(g.pids)}",
                fixes=[Fix(text="Kullanılmayan sekmeleri kapat / sekme gruplarına al; tarayıcının bellek tasarrufu (uyku sekme) özelliğini aç.")],
            ))

    # --- bulut senkronu
    for g in oth:
        io = g.io_w_mib_s + g.io_r_mib_s
        if g.kind == "cloud" and io > 1.5:
            title = f"{g.label} senkronizasyonu disk IO yapıyor ({g.io_w_mib_s:.1f} MiB/s yazma)"
            if ctx.game_running:
                title += " — oyun sırasında stutter kaynağı olabilir"
            _add(findings, Finding(
                id=f"cloud-sync-{g.key}",
                title=title,
                severity=("high" if ctx.game_running else "medium"),
                category="disk",
                why="Senkron istemcileri disk ve ağ üzerinde çalışır; oyun sırasında IO kapışıldığında FPS takılması tetiklenir.",
                evidence=f"io {io:.1f} MiB/s (yazma {g.io_w_mib_s:.1f})",
                fixes=_fix_for(g) or [Fix(text="Uygulamanın tepsisi menüsünden senkronizasyonu geçici duraklat.")],
            ))

    # --- başlatıcı indirmesi
    for g in oth:
        if g.kind == "launcher" and g.io_w_mib_s > 5:
            _add(findings, Finding(
                id=f"launcher-io-{g.key}",
                title=f"{g.label} arka planda indirme yapıyor ({g.io_w_mib_s:.0f} MiB/s yazma)",
                severity=("low" if ctx.game_running else "medium"),
                category="disk",
                why="Mağaza güncellemeleri diski meşgul eder; oyun sırasında ertelemek FPS ve yükleme sürelerini iyileştirir.",
                evidence=f"yazma {g.io_w_mib_s:.1f} MiB/s",
                fixes=_fix_for(g) or [Fix(text="Mağaza ayarlarından indirmeyi sınırla/planla.")],
            ))

    # --- dizinleyiciler
    for g in oth:
        if g.kind == "indexer" and (g.cpu_pct > 5 or g.mem_mib > 300):
            _add(findings, Finding(
                id=f"indexer-{g.key}",
                title=f"{g.label} kaynak kullanıyor (CPU %{g.cpu_pct:.0f}, {fmt_gib(g.mem_mib)})",
                severity="medium", category="cpu",
                why="Dizinleyiciler dosya sistemi tarar; disk ve CPU işgal eder, arka planda stutter üretir.",
                evidence=f"cpu %{g.cpu_pct:.1f}, mem {fmt_gib(g.mem_mib)}",
                fixes=_fix_for(g) or [Fix(text="Dizin kapsamını sınırla (büyük medya klasörlerini hariç tut).")],
            ))

    # --- antivirüs
    for g in oth:
        if g.kind == "av" and (g.cpu_pct > 10 or g.mem_mib > 250):
            _add(findings, Finding(
                id=f"av-{g.key}",
                title=f"{g.label} yoğun çalışıyor (CPU %{g.cpu_pct:.0f}, {fmt_gib(g.mem_mib)})",
                severity="medium", category="cpu",
                why="Tam tarama veya davranış analizi sürüyor olabilir; oyun sırasında çerçeve çöküşü yapar.",
                evidence=f"cpu %{g.cpu_pct:.1f}",
                fixes=_fix_for(g) or [Fix(text="Zamanlanmış taramaları oyun dışı saatlere taşı.", risk="careful")],
            ))

    # --- VM / konteyner
    for g in oth:
        if g.kind == "devvm" and (g.mem_mib > 1500 or g.cpu_pct > 8):
            _add(findings, Finding(
                id=f"devvm-{g.key}",
                title=f"{g.label} çalışıyor ({fmt_gib(g.mem_mib)} RAM, CPU %{g.cpu_pct:.0f})",
                severity=("high" if ctx.game_running else "medium"),
                category="memory",
                why="VM/WSL/konteyner backend'i kalıcı RAM ve disk IO tutar; dev oturumu bitmişse boşta kaynak yer.",
                evidence="süreç grubu aktif",
                fixes=_fix_for(g) or [Fix(text="Dev yapmıyorsan VM/motoru kapat.", risk="careful")],
            ))

    # --- kompositör
    for g in oth:
        if g.kind == "system" and g.key in ("dwm", "gnome-shell", "kwin", "mac-windowserver") \
                and g.cpu_pct > 8:
            _add(findings, Finding(
                id=f"compositor-{g.key}",
                title=f"{g.label} yüksek CPU (%{g.cpu_pct:.0f})",
                severity="medium", category="cpu",
                why="Pencere yöneticisi ekran kompozisyonu yapar; efektler/animasyonlar/sürücü sorunları CPU'sunu şişirir.",
                evidence=f"cpu %{g.cpu_pct:.1f}",
                fixes=_fix_for(g) or [Fix(text="Masaüstü efektlerini azalt, GPU sürücüsünü güncelle.")],
            ))

    # --- bilinmeyen yoğun süreç
    for g in _top(oth, lambda g: g.cpu_pct + g.mem_mib / 300, 2):
        if g.kind == "unknown" and (g.cpu_pct > 15 or g.mem_mib > 800):
            _add(findings, Finding(
                id=f"unknown-{g.names[0].lower()}",
                title=f"Tanımsız yoğun süreç: {g.label} (CPU %{g.cpu_pct:.0f}, {fmt_gib(g.mem_mib)})",
                severity="medium", category="cpu",
                why="İmzası bilinmeyen süreç önemli kaynak tüketiyor; kökeni doğrulanmalı (güncelleyici/mining/hata).",
                evidence=f"cmd: {g.cmdline[:160]}",
                fixes=_inv_fix(g, snap.platform),
            ))

    # --- disk doluluk / yazıcılar
    if snap.disk_busy_pct is not None and snap.disk_busy_pct >= t.disk_busy_warn and not ctx.game_running:
        wr = _top(oth, lambda g: g.io_w_mib_s + g.io_r_mib_s, 3)
        ev = ", ".join(f"{g.label} {g.io_w_mib_s + g.io_r_mib_s:.1f} MiB/s" for g in wr)
        _add(findings, Finding(
            id="disk-busy",
            title=f"Sistem diski meşgul (doluluk tahmini %{snap.disk_busy_pct:.0f})",
            severity="medium", category="disk",
            why="Disk kuyruğu dolu olduğunda her şey yavaşlar; oyun kapalıyken bu yoğunluk arka plan işlerinden gelir.",
            evidence=ev or "süreç bazlı IO ölçülemedi",
            fixes=[Fix(text="Yoğun yazan süreçleri kapat; büyük kopya/senkron işlerini oyun dışına planla.")],
        ))
    for g in _top(oth, lambda g: g.io_w_mib_s, 1):
        if g.io_w_mib_s >= t.disk_w_warn_mib_s and g.kind not in ("launcher", "cloud"):
            _add(findings, Finding(
                id=f"heavy-writer-{g.names[0].lower()}",
                title=f"{g.label} diske yoğun yazıyor: {g.io_w_mib_s:.0f} MiB/s",
                severity="medium", category="disk",
                why="Sürekli yoğun yazma diski işgal eder; HDD'de sistem genelinde yavaşlama yapar.",
                evidence=f"yazma {g.io_w_mib_s:.1f} MiB/s",
                fixes=_fix_for(g) or [Fix(text="Sürecin ne yazdığını doğrula (log/indirme/derleme); kalıcıysa hedefi SSD'ye veya kapsam dışına taşı.")],
            ))

    # --- sistem diski HDD (daimi bulgu)
    if t.hdd_system:
        _add(findings, Finding(
            id="system-hdd",
            title="Sistem diski HDD",
            severity="high", category="configuration",
            why="OS HDD üzerindeyse tüm açılışlar ve sayfalama yavaştır; donanım düzeyindeki en büyük hızlanma noktasıdır (yazılım ayarıyla tam giderilmez).",
            evidence="rotational=1",
            fixes=[Fix(text="En etkili yükseltme: OS + oyunları NVMe/SSD'ye taşı.", risk="careful"),
                   Fix(text="HDD kaçınılmazsa: arka plan dizinleyici/senkron gürültüsünü kapat, sayfa dosyasını ayrı SSD'ye al.")],
        ))

    # --- swap baskısı
    if b.swap_total_mib > 10 and b.swap_used_mib / b.swap_total_mib * 100 >= t.swap_warn_pct:
        sev = "high" if b.mem_avail_gib < 1.5 else "medium"
        _add(findings, Finding(
            id="swap-pressure",
            title=f"Swap baskısı: {fmt_gib(b.swap_used_mib)} / {fmt_gib(b.swap_total_mib)} kullanılmış",
            severity=sev, category="memory",
            why="Swap uzun süre yüksekse RAM kapasitesi yetersiz; sayfalama diski meşgul eder.",
            evidence=f"swap %{b.swap_used_mib / max(1, b.swap_total_mib) * 100:.0f}, kullanılabilir RAM {b.mem_avail_gib:.1f} GiB",
            fixes=[Fix(text="RAM tüketenleri kapat; kalıcıysa RAM yükseltme veya daha az arka plan uygulaması değerlendir.")],
        ))

    # --- termal
    cpu_temp = snap.temps.get("cpu")
    if cpu_temp:
        if cpu_temp >= t.temp_crit:
            _add(findings, Finding(
                id="thermal-critical", title=f"CPU sıcaklığı çok yüksek: {cpu_temp:.0f}°C",
                severity="critical", category="thermal",
                why="Termal kısılma frekansları düşürür; FPS çöker. Soğutma bakımı gerekir.",
                evidence=f"cpu {cpu_temp:.0f}°C",
                fixes=[Fix(text="Fan profili agresif yap, laptop'ta soğutucu, kasa temizliği/termal macun kontrolü.")],
            ))
        elif cpu_temp >= t.temp_warn:
            _add(findings, Finding(
                id="thermal-warn", title=f"CPU sıcaklığı yüksek: {cpu_temp:.0f}°C",
                severity="medium", category="thermal",
                why="Uzun vadede termal kısılma (throttle) frekansları düşürür.",
                evidence=f"cpu {cpu_temp:.0f}°C (eşik {t.temp_warn:.0f})",
                fixes=[Fix(text="Fan profili agresif moda al; iç temizlik, termal macun kontrolü.")],
            ))
    gpu_temp = snap.temps.get("gpu")
    if gpu_temp and gpu_temp >= 90:
        _add(findings, Finding(
            id="thermal-gpu", title=f"GPU sıcaklığı yüksek: {gpu_temp:.0f}°C",
            severity="medium", category="thermal",
            why="GPU termal kısıtlaması çerçeve düşüşü yapar.",
            evidence=f"gpu {gpu_temp:.0f}°C",
            fixes=[Fix(text="Fan eğrisini artır; kasa hava akışı ve toz temizliği.")],
        ))

    # --- frekans kısıtı
    cur = snap.cpu_freq.get("cur_mhz")
    mx = snap.cpu_freq.get("max_mhz")
    if cur and mx and mx > 800:
        ratio = cur / mx
        if ratio < 0.45 and b.base_cpu_pct > t.cpu_warn:
            _add(findings, Finding(
                id="cpu-frequency-limited",
                title=f"Yük altında düşük frekans ({cur:.0f} / {mx:.0f} MHz)",
                severity="medium", category="power",
                why="Yükte frekans beklenenden düşük: güç planı/termal/BIOS sınırı olabilir.",
                evidence=f"freq %{ratio * 100:.0f}, CPU %{b.base_cpu_pct:.0f}",
                fixes=[Fix(text="Güç planını performans yap (Win: Yüksek performans; Linux: governor performance; mac: lowpowermode kapalı).")],
            ))

    # --- güç planı (oyun sırasında tasarruf modu)
    gov = snap.power.get("governor")
    scheme = snap.power.get("scheme", "")
    lowpower = snap.power.get("lowpowermode")
    if ctx.game_running and ((gov and "powersave" in gov.lower()) or lowpower is True
                             or "power saver" in scheme.lower()):
        _add(findings, Finding(
            id="power-mode",
            title="Oyun açıkken güç tasarrufu modu aktif",
            severity="high", category="power",
            why="Güç tasarrufu/pil modu CPU/GPU frekansını kısıtlar; oyunda belirgin FPS düşüşü yapar.",
            evidence=f"governor={gov or '-'} scheme={scheme or '-'} lowpower={lowpower}",
            fixes=[Fix(text="Oyun sırasında güç planını Performans yap (pildeysen fişa bas).")],
        ))

    # --- açılış maliyeti
    boot_s = snap.boot.get("boot_s") or 0
    offenders = snap.boot.get("top_offenders") or []
    if boot_s > 40 or any(s >= 8 for _u, s in offenders[:3]):
        bad = ", ".join(f"{u} {s:.0f}s" for u, s in offenders[:3]) or "systemd-analyze blame ile incele"
        _add(findings, Finding(
            id="boot-slow", title=f"Açılış yavaş (userspace {boot_s:.0f}s)",
            severity="medium", category="boot",
            why="Açılışta uzun süren servisler hem açılışı hem ilk dakikaların yavaşlığını açıklar.",
            evidence=bad,
            fixes=[Fix(text="Gereksiz servisleri kapat: `systemctl disable <servis> --now` (ağ/yazdırma gibi kritikleri hariç tut).", risk="careful", os="linux"),
                   Fix(text="Görev Yöneticisi > Başlangıç etkisi sütununa göre devre dışı bırak.", os="windows"),
                   Fix(text="Sistem Ayarları > Genel > Giriş Öğeleri'ni gözden geçir.", os="macos")],
        ))
    su_count = snap.boot.get("startup_count")
    if isinstance(su_count, int) and su_count > 10:
        items = snap.boot.get("startup_items") or []
        _add(findings, Finding(
            id="startup-items", title=f"Başlangıç öğeleri fazla: {su_count}",
            severity="medium", category="boot",
            why="Açılışta otomatik başlayan programlar ilk dakikalarda RAM/IO kapışırlar.",
            evidence=", ".join(str(x) for x in items[:6]),
            fixes=[Fix(text="Görev Yöneticisi > Başlangıç uygulamaları > gereksizleri devre dışı bırak.", os="windows")],
        ))
    li_count = snap.boot.get("login_items_count")
    if isinstance(li_count, int) and li_count > 15:
        _add(findings, Finding(
            id="login-items", title=f"Giriş öğeleri fazla: {li_count} LaunchAgent",
            severity="medium", category="boot",
            why="Girişte otomatik açılan agent'lar kaynak tutar, açılışı geciktirir.",
            evidence=", ".join(str(x) for x in (snap.boot.get("login_items") or [])[:6]),
            fixes=[Fix(text="Sistem Ayarları > Genel > Giriş Öğeleri; komutla: `launchctl unload ~/Library/LaunchAgents/<ad>.plist`.", risk="careful", os="macos")],
        ))

    # --- GameDVR / Game Mode (Windows + oyun context)
    if snap.platform == "windows" and ctx.game_running:
        ex = snap.extras
        if ex.get("gamedvr_enabled") or ex.get("gamebar_autocapture"):
            _add(findings, Finding(
                id="gamedvr", title="GameDVR arka plan kaydı açık (oyun sırasında)",
                severity="medium", category="configuration",
                why="Xbox Game Bar arka plan kaydı her kareyi kodlamak zorunda kalır; bilinen FPS düşürücüsü.",
                evidence="registry: GameDVR_Enabled / AllowAutoGameCapture",
                fixes=[Fix(text="Ayarlar > Xbox Oyun Çubuğu > arka plan kaydını kapat; Oyun Modu'nun AÇIK kalması avantajdır.", os="windows")],
            ))
        if ex.get("gamemode_enabled") is False:
            _add(findings, Finding(
                id="gamemode-off", title="Windows Oyun Modu kapalı (oyun sırasında)",
                severity="low", category="configuration",
                why="Oyun Modu güncellemeleri erteler ve oyuna kaynak önceliği verir.",
                evidence="registry: AutoGameModeEnabled=0",
                fixes=[Fix(text="Ayarlar > Oyun > Oyun Modu > Açık.", os="windows")],
            ))

    # --- önbellek temizliği
    if include_storage:
        from agmo.actions import cache_report
        rep = cache_report(snap.platform)
        total_mib = sum(r["size_mib"] or 0 for r in rep)
        if total_mib > 8 * 1024:
            _add(findings, Finding(
                id="storage-cache",
                title=f"Önbellek/Temp birikimi: {fmt_gib(total_mib)}",
                severity="low", category="storage",
                why="Büyük önbellekler disk alanı yer; SSD'de GC baskısını artırır. Bakım iyi pratiktir.",
                evidence=", ".join(f"{r['path']}: {fmt_gib(r['size_mib'])}" for r in rep if r["size_mib"])[:220],
                fixes=[Fix(text="`agmo clean-cache` ile onaylı temizlik (yalnızca kullanıcı önbellekleri).")],
            ))

    # --- linux journal
    ju = snap.boot.get("journal_usage")
    if snap.platform == "linux" and ju:
        import re
        m = re.search(r"([\d\.]+)\s*([GM])", str(ju))
        if m and m.group(2) == "G" and float(m.group(1)) >= 4:
            _add(findings, Finding(
                id="journal-size",
                title=f"journald günlükleri büyük: {m.group(1)}GB",
                severity="low", category="storage",
                why="Büyümüş journal disk yer tutar, journald yazma yükünü artırır.",
                evidence=str(ju),
                fixes=[Fix(text="`journalctl --vacuum-size=500M`; kalıcı: /etc/systemd/journald.conf'ta SystemMaxUse=500M.", os="linux")],
            ))
    return findings, notes


# ------------------------------------------------------------- ana giriş
def analyze(snap: Snapshot, hw: Hardware, include_storage: bool = True) -> Analysis:
    ctx = assign_roles(snap, hw)
    b = baseline(snap, ctx)
    findings, notes = run_rules(snap, ctx, b, include_storage=include_storage)

    if not snap.focus and not ctx.game_running:
        notes.append("Odak penceresi algılanamadı (compositor/izin kısıtı) — "
                     "`agmo scan --focus <uygulama adı>` ile elle belirtebilirsin; "
                     "bu durumda oyun-hariç analiz bilinen oyun imzalarına göre uygulanır.")
    if snap.focus and snap.focus.source == "manual" and not ctx.game_running:
        notes.append(f"'{snap.focus.label}' etiketi verildi ama şu an bu adda bir süreç "
                     f"bulunamadı — hariç tutulacak grup yok, taban çizgisi tüm süreçleri içerir.")
    if snap.extras.get("focus_note"):
        notes.append(str(snap.extras["focus_note"]))
    return Analysis(snapshot=snap, baseline=b, findings=findings, notes=notes)