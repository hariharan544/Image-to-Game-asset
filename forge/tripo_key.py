"""Where Forge gets the Tripo API key.

Order (first hit wins):
  1. TRIPO_API_KEY (environment or .env)
  2. the Tripo CLI login: `tripo login` stores the key in ~/.tripo/config.json
     ({"active_profile": name, "profiles": {name: {"api_key", "region"}}}; TRIPO_HOME and
     TRIPO_PROFILE are honoured exactly like the CLI does)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


def cli_config_path() -> Path:
    return Path(os.environ.get("TRIPO_HOME") or Path.home() / ".tripo") / "config.json"


def resolve() -> tuple[Optional[str], str, str]:
    """Returns (api_key, region "ov"|"cn", source description)."""
    env = os.environ.get("TRIPO_API_KEY", "").strip()
    if env:
        return env, os.environ.get("TRIPO_REGION", "ov"), "TRIPO_API_KEY"
    path = cli_config_path()
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "ov", "none"
    name = os.environ.get("TRIPO_PROFILE") or cfg.get("active_profile") or "default"
    prof = (cfg.get("profiles") or {}).get(name) or {}
    if not prof and name == "default" and cfg.get("api_key"):        # CLI 0.1 layout
        prof = {"api_key": cfg["api_key"], "region": cfg.get("region")}
    key = prof.get("api_key")
    if not key:
        return None, "ov", "none"
    return key, prof.get("region") or "ov", f"Tripo CLI login (profile '{name}')"
