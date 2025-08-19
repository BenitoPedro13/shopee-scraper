from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from rich.console import Console
from rich.table import Table


@dataclass
class Bucket:
    profile: str
    proxy: Optional[str]
    captures_total: int = 0
    captures_ok: int = 0
    captured_items_sum: int = 0
    duration_sum: float = 0.0
    duration_count: int = 0
    navigate_attempts_sum: int = 0
    pages_sum: int = 0
    blocks: int = 0
    block_reasons: Counter = field(default_factory=Counter)

    def success_rate(self) -> float:
        return (self.captures_ok / self.captures_total) if self.captures_total else 0.0

    def avg_duration(self) -> float:
        return (self.duration_sum / self.duration_count) if self.duration_count else 0.0


def _iter_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _event_type(rec: dict) -> Optional[str]:
    # Prefer explicit 'event' field (used by log_event), fallback to 'message'
    if isinstance(rec.get("event"), str):
        return rec.get("event")
    msg = rec.get("message") or rec.get("text")
    if isinstance(msg, str):
        return msg
    return None


def aggregate_metrics(
    path: Path,
    *,
    since_ts: Optional[int] = None,
    profile_filter: Optional[str] = None,
    proxy_filter: Optional[str] = None,
) -> Tuple[Dict[Tuple[str, Optional[str]], Bucket], Bucket]:
    buckets: Dict[Tuple[str, Optional[str]], Bucket] = {}
    overall = Bucket(profile="(all)", proxy=None)
    now = int(time.time())
    min_ts = since_ts or 0
    for rec in _iter_jsonl(path):
        ts = int(rec.get("ts") or now)
        if ts < min_ts:
            continue
        profile = rec.get("profile") or "default"
        proxy = rec.get("proxy")
        if profile_filter and str(profile) != profile_filter:
            continue
        if proxy_filter and str(proxy) != proxy_filter:
            continue
        etype = _event_type(rec)
        key = (str(profile), str(proxy) if proxy is not None else None)
        if key not in buckets:
            buckets[key] = Bucket(profile=key[0], proxy=key[1])
        b = buckets[key]
        # Summaries
        if etype == "cdp_capture_summary":
            captured = int(rec.get("captured") or 0)
            duration = float(rec.get("duration_s") or 0.0)
            counters = rec.get("counters") or {}
            navigate_attempts = int(counters.get("navigate_attempts", 0)) if isinstance(counters, dict) else 0
            pages = int(rec.get("pages") or 0)

            b.captures_total += 1
            overall.captures_total += 1
            if captured > 0:
                b.captures_ok += 1
                overall.captures_ok += 1
            b.captured_items_sum += captured
            overall.captured_items_sum += captured

            b.duration_sum += duration
            b.duration_count += 1
            overall.duration_sum += duration
            overall.duration_count += 1

            b.navigate_attempts_sum += navigate_attempts
            overall.navigate_attempts_sum += navigate_attempts

            b.pages_sum += pages
            overall.pages_sum += pages

        elif etype == "circuit_trip":
            reason = rec.get("reason") or "unknown"
            b.blocks += 1
            b.block_reasons[str(reason)] += 1
            overall.blocks += 1
            overall.block_reasons[str(reason)] += 1

    return buckets, overall


def render_report(
    buckets: Dict[Tuple[str, Optional[str]], Bucket],
    overall: Bucket,
    *,
    console: Optional[Console] = None,
) -> None:
    console = console or Console()
    # Summary table
    table = Table(title="CDP Metrics Summary")
    table.add_column("Profile")
    table.add_column("Proxy", overflow="fold")
    table.add_column("Captures", justify="right")
    table.add_column("OK", justify="right")
    table.add_column("Success %", justify="right")
    table.add_column("Items", justify="right")
    table.add_column("Avg dur (s)", justify="right")
    table.add_column("Blocks", justify="right")
    table.add_column("NavAtt", justify="right")
    table.add_column("Pages", justify="right")

    # Sort by blocks desc then success asc
    for (_, b) in sorted(buckets.items(), key=lambda kv: (-kv[1].blocks, kv[1].success_rate())):
        table.add_row(
            b.profile,
            str(b.proxy or "-")[:60],
            str(b.captures_total),
            str(b.captures_ok),
            f"{b.success_rate()*100:.1f}",
            str(b.captured_items_sum),
            f"{b.avg_duration():.2f}",
            str(b.blocks),
            str(b.navigate_attempts_sum),
            str(b.pages_sum),
        )

    console.print(table)

    # Overall
    o = overall
    console.print(
        f"Overall: captures={o.captures_total} ok={o.captures_ok} success={o.success_rate()*100:.1f}% "
        f"items={o.captured_items_sum} avg_dur={o.avg_duration():.2f}s blocks={o.blocks}"
    )

    # Top block reasons
    if overall.blocks:
        t2 = Table(title="Top block reasons", show_edge=False)
        t2.add_column("Reason")
        t2.add_column("Count", justify="right")
        for reason, cnt in overall.block_reasons.most_common(10):
            t2.add_row(reason, str(cnt))
        console.print(t2)


def run_report(
    path: Path,
    *,
    hours: int = 0,
    profile: Optional[str] = None,
    proxy: Optional[str] = None,
) -> None:
    since_ts = None
    if hours and hours > 0:
        since_ts = int(time.time()) - hours * 3600
    buckets, overall = aggregate_metrics(path, since_ts=since_ts, profile_filter=profile, proxy_filter=proxy)
    render_report(buckets, overall)


def export_metrics(
    path: Path,
    *,
    hours: int = 0,
    profile: Optional[str] = None,
    proxy: Optional[str] = None,
    out_csv: Optional[Path] = None,
    out_json: Optional[Path] = None,
) -> Tuple[Path, Path]:
    since_ts = None
    if hours and hours > 0:
        since_ts = int(time.time()) - hours * 3600
    buckets, overall = aggregate_metrics(path, since_ts=since_ts, profile_filter=profile, proxy_filter=proxy)

    # Prepare rows
    rows = []
    for (_, b) in buckets.items():
        rows.append({
            "profile": b.profile,
            "proxy": b.proxy,
            "captures_total": b.captures_total,
            "captures_ok": b.captures_ok,
            "success_rate": round(b.success_rate(), 4),
            "captured_items_sum": b.captured_items_sum,
            "avg_duration_s": round(b.avg_duration(), 3),
            "blocks": b.blocks,
            "navigate_attempts_sum": b.navigate_attempts_sum,
            "pages_sum": b.pages_sum,
            "block_reasons": dict(b.block_reasons),
        })
    overall_row = {
        "captures_total": overall.captures_total,
        "captures_ok": overall.captures_ok,
        "success_rate": round(overall.success_rate(), 4),
        "captured_items_sum": overall.captured_items_sum,
        "avg_duration_s": round(overall.avg_duration(), 3),
        "blocks": overall.blocks,
        "navigate_attempts_sum": overall.navigate_attempts_sum,
        "pages_sum": overall.pages_sum,
        "block_reasons": dict(overall.block_reasons),
    }

    # Write outputs
    out_dir = (out_csv or out_json or Path("data/metrics_summary.csv")).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_csv or (out_dir / "metrics_summary.csv")
    json_path = out_json or (out_dir / "metrics_summary.json")

    # CSV: flatten block_reasons to JSON string
    import csv as _csv
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "profile",
            "proxy",
            "captures_total",
            "captures_ok",
            "success_rate",
            "captured_items_sum",
            "avg_duration_s",
            "blocks",
            "navigate_attempts_sum",
            "pages_sum",
            "block_reasons",
        ]
        w = _csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            r2 = dict(r)
            r2["block_reasons"] = json.dumps(r2.get("block_reasons", {}), ensure_ascii=False)
            w.writerow(r2)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump({"rows": rows, "overall": overall_row}, f, ensure_ascii=False, indent=2)

    return csv_path, json_path
