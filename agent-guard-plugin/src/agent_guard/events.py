from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import events_path


def append_event(root_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    enriched = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    with events_path(root_dir).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(enriched) + "\n")
    return enriched
