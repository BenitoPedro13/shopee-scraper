from __future__ import annotations

import csv
import json
import random
import time
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional

from .config import settings


def jitter_sleep(min_s: Optional[float] = None, max_s: Optional[float] = None) -> None:
    a = min_s if min_s is not None else settings.min_delay
    b = max_s if max_s is not None else settings.max_delay
    time.sleep(random.uniform(a, b))


def ensure_data_dir() -> Path:
    p = Path(settings.data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(rows: List[Mapping[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def write_csv(rows: Iterable[Mapping[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows:
        # create empty file with no headers
        path.touch()
        return
    fieldnames = sorted({k for r in rows for k in r.keys()})
    tmp = path.with_suffix(".tmp.csv")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)
