"""Küçük yardımcılar: güvenli subprocess, boyut biçim, kullanıcı bilgisi sildirme."""
from __future__ import annotations

import os
import re
import subprocess
from typing import List, Optional

MIB = 1024.0 * 1024.0
GIB = MIB * 1024.0


def run(cmd: List[str], timeout: float = 8.0) -> Optional[str]:
    """Komutu çalıştır; stdout döndür, her hata durumunda None (asla patlama)."""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = p.stdout.decode("utf-8", "replace").strip()
        return out if out else None
    except Exception:
        return None


def fmt_gib(mib: float) -> str:
    if abs(mib) >= 1024:
        return f"{mib / 1024:.1f} GiB"
    return f"{mib:.0f} MiB"


def scrub(text: str) -> str:
    """Yollardan kullanıcı adını sil (AI payload'ına gitmeden önce çağrılır)."""
    home = os.path.expanduser("~")
    if home and home != "~":
        text = text.replace(home, "~")
    # kullanıcıya özgü yol segmentleri (harf büyüklüğü fark etmez, herhangi bir ad)
    text = re.sub(r"C:[\\/]Users[\\/][^\\/\s]+",
                  lambda m: "C:\\Users\\USER", text, flags=re.I)
    text = re.sub(r"/Users/[^/\s]+", "/Users/USER", text)
    text = re.sub(r"/home/[^/\s]+", "/home/USER", text)
    return text