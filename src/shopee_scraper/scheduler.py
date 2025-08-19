from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .utils import ensure_data_dir
from .logs import log_event
from .cdp.collector import (
    collect_search_once,
    collect_search_paged,
    collect_search_all,
    collect_pdp_batch,
    collect_pdp_batch_concurrent,
)
from .cdp.exporter import export_search_from_jsonl, export_pdp_from_jsonl


@dataclass
class Task:
    id: str
    kind: str  # cdp_search | cdp_search_all | cdp_enrich
    params: Dict[str, Any]
    status: str  # pending | running | completed | failed
    attempts: int
    max_attempts: int
    created_ts: int
    updated_ts: int
    result: Dict[str, Any]
    error: Optional[str]

    def path(self) -> Path:
        qdir = ensure_data_dir() / "queue" / "tasks"
        qdir.mkdir(parents=True, exist_ok=True)
        return qdir / f"{self.id}.json"

    def save(self) -> None:
        self.updated_ts = int(time.time())
        p = self.path()
        tmp = p.with_suffix(".tmp.json")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        tmp.replace(p)


def _new_task(kind: str, params: Dict[str, Any], *, max_attempts: int = 2) -> Task:
    now = int(time.time())
    return Task(
        id=str(uuid.uuid4()),
        kind=kind,
        params=params,
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
        created_ts=now,
        updated_ts=now,
        result={},
        error=None,
    )


def add_task(kind: str, params: Dict[str, Any], *, max_attempts: int = 2) -> Task:
    t = _new_task(kind, params, max_attempts=max_attempts)
    t.save()
    logger.info(f"Queue: added task {t.kind} id={t.id}")
    return t


def load_tasks(status_filter: Optional[str] = None) -> List[Task]:
    qdir = ensure_data_dir() / "queue" / "tasks"
    if not qdir.exists():
        return []
    out: List[Task] = []
    for p in sorted(qdir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            t = Task(**data)
            if status_filter and t.status != status_filter:
                continue
            out.append(t)
        except Exception:
            continue
    return out


def _run_task(t: Task) -> Task:
    t.status = "running"
    t.attempts += 1
    t.save()
    log_event("queue_task_start", id=t.id, kind=t.kind)
    t0 = time.time()
    try:
        if t.kind == "cdp_search":
            keyword = t.params["keyword"]
            launch = bool(t.params.get("launch", True))
            timeout_s = float(t.params.get("timeout_s", 20.0))
            pages = int(t.params.get("pages", 1))
            start_page = int(t.params.get("start_page", 0))
            auto_export = bool(t.params.get("auto_export", True))
            if pages and pages > 1:
                jsonl = collect_search_paged(keyword, pages, start_page=start_page, launch=launch, timeout_s=timeout_s)
            else:
                jsonl = collect_search_once(keyword, launch=launch, timeout_s=timeout_s)
            t.result["jsonl"] = str(jsonl)
            if auto_export:
                j, c, rows = export_search_from_jsonl(jsonl)
                t.result.update({"export_json": str(j), "export_csv": str(c), "export_count": len(rows)})

        elif t.kind == "cdp_search_all":
            keyword = t.params["keyword"]
            launch = bool(t.params.get("launch", True))
            timeout_s = float(t.params.get("timeout_s", 10.0))
            start_page = int(t.params.get("start_page", 0))
            max_pages = int(t.params.get("max_pages", 100))
            auto_export = bool(t.params.get("auto_export", True))
            jsonl = collect_search_all(keyword, launch=launch, timeout_s=timeout_s, start_page=start_page, max_pages=max_pages)
            t.result["jsonl"] = str(jsonl)
            if auto_export:
                j, c, rows = export_search_from_jsonl(jsonl)
                t.result.update({"export_json": str(j), "export_csv": str(c), "export_count": len(rows)})

        elif t.kind == "cdp_enrich":
            # Enriquecer um export de busca usando PDP batch (serial ou concorrente)
            input_path = t.params.get("input_path")
            launch = bool(t.params.get("launch", True))
            timeout_s = float(t.params.get("timeout_s", 8.0))
            pause_s = float(t.params.get("pause_s", 0.5))
            concurrency = int(t.params.get("concurrency", 0))
            stagger_s = float(t.params.get("stagger_s", 1.0))

            # Carregar URLs do export
            import csv
            import json as _json
            from pathlib import Path as _Path

            if input_path is None:
                # encontrar último export de busca
                import glob, os
                candidates = sorted(
                    glob.glob("data/cdp_search_*_export.json") + glob.glob("data/cdp_search_*_export.csv"),
                    key=os.path.getmtime,
                    reverse=True,
                )
                if not candidates:
                    raise FileNotFoundError("Nenhum export de busca encontrado (data/cdp_search_*_export.*)")
                input_path = candidates[0]
            in_path = _Path(input_path)
            if not in_path.exists():
                raise FileNotFoundError(str(in_path))

            def _load_rows(p: _Path):
                if p.suffix.lower() == ".json":
                    return _json.loads(p.read_text(encoding="utf-8"))
                rows = []
                with p.open("r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        rows.append(r)
                return rows

            rows = _load_rows(in_path)
            urls = [r.get("url") for r in rows if r.get("url")]
            if not urls:
                raise ValueError("Nenhuma URL de produto encontrada no export de busca.")

            if concurrency and concurrency > 1:
                jsonl = collect_pdp_batch_concurrent(urls, launch=launch, timeout_s=timeout_s, stagger_s=stagger_s, concurrency=concurrency)
            else:
                jsonl = collect_pdp_batch(urls, launch=launch, timeout_s=timeout_s, pause_s=pause_s)
            t.result["jsonl"] = str(jsonl)
            j, c, pdp_rows = export_pdp_from_jsonl(jsonl)
            t.result.update({"export_json": str(j), "export_csv": str(c), "export_count": len(pdp_rows)})

        else:
            raise ValueError(f"Unknown task kind: {t.kind}")

        t.status = "completed"
        t.result["duration_s"] = round(time.time() - t0, 3)
        log_event("queue_task_done", id=t.id, kind=t.kind, status=t.status, result=t.result)
        t.save()
        return t
    except Exception as e:
        t.error = str(e)
        if t.attempts >= t.max_attempts:
            t.status = "failed"
        else:
            t.status = "pending"  # requeue
        log_event("queue_task_error", id=t.id, kind=t.kind, error=t.error, attempts=t.attempts, status=t.status)
        t.save()
        return t


def run_once(max_tasks: int = 0) -> int:
    """Run pending tasks sequentially once. Returns number of tasks attempted."""
    pending = load_tasks(status_filter="pending")
    if max_tasks > 0:
        pending = pending[:max_tasks]
    count = 0
    for t in pending:
        _run_task(t)
        count += 1
    return count

