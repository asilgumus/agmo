"""AGMO ayarları: API anahtarı/model. Öncelik:

1. Çevre değişkeni: AGMO_XAI_API_KEY > XAI_API_KEY > GROK_API_KEY
2. Ayar dosyası: ~/.config/agmo/config.toml  ([ai] api_key, model)

Anahtar ASLA repoya/veri dosyalarına yazılmaz; dosyada tutulursa izin 0600 olur.
"""
from __future__ import annotations

import os
import stat
from typing import Dict, Optional

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", "agmo", "config.toml")
DEFAULT_BASE_URL = "https://api.x.ai"
DEFAULT_MODEL = "auto"  # /v1/models'tan otomatik seç


def _read_file_config() -> Dict[str, str]:
    try:
        import tomllib
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        ai = data.get("ai", {}) or {}
        return {k.lower(): str(v) for k, v in ai.items() if v}
    except Exception:
        # tomllib yoksa (py<3.11) basit satır okuma
        out: Dict[str, str] = {}
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.split("=", 1)
                        out[k.strip().lower()] = v.strip().strip("\"'").rstrip()
        except Exception:
            pass
        return out


def get_ai_config() -> Dict[str, Optional[str]]:
    file_cfg = _read_file_config()
    key = (os.environ.get("AGMO_XAI_API_KEY") or os.environ.get("XAI_API_KEY")
           or os.environ.get("GROK_API_KEY")
           or file_cfg.get("api_key") or None)
    model = os.environ.get("AGMO_MODEL") or file_cfg.get("model") or DEFAULT_MODEL
    base = os.environ.get("AGMO_XAI_BASE") or file_cfg.get("base_url") or DEFAULT_BASE_URL
    return {"api_key": key, "model": model, "base_url": base.rstrip("/")}


def set_config(api_key: Optional[str] = None, model: Optional[str] = None) -> str:
    """Ayar dosyasına yazar (0600)."""
    cfg = get_ai_config()
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    lines = ["[ai]"]
    new_key = api_key if api_key is not None else cfg.get("api_key")
    new_model = model if model is not None else cfg.get("model")
    if new_key:
        lines.append(f'api_key = "{new_key}"')
    if new_model and new_model != DEFAULT_MODEL:
        lines.append(f'model = "{new_model}"')
    body = "\n".join(lines) + "\n"
    fd_path = CONFIG_PATH
    tmp = fd_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, fd_path)
    return CONFIG_PATH