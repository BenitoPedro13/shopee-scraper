from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from loguru import logger

from ..utils import ensure_data_dir, write_csv, write_json


def _loads_body(body: str, base64_flag: bool) -> Optional[dict]:
    try:
        if base64_flag:
            raw = base64.b64decode(body)
            text = raw.decode("utf-8", errors="replace")
        else:
            text = body
        return json.loads(text)
    except Exception as e:
        logger.warning(f"Failed to parse body JSON: {e}")
        return None


def _safe_get(d: dict, path: Iterable[str], default=None):
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _normalize_price(item: dict) -> Tuple[Optional[int], Optional[int]]:
    # Try product_price.price.single_value
    single = _safe_get(item, ["product_price", "price", "single_value"], None)
    if isinstance(single, int):
        return single, single
    # Try price_min/price_max
    pmin = item.get("price_min")
    pmax = item.get("price_max")
    if isinstance(pmin, int) or isinstance(pmax, int):
        return (pmin if isinstance(pmin, int) else None), (pmax if isinstance(pmax, int) else None)
    # Try first model price
    models = item.get("models")
    if isinstance(models, list) and models:
        m0 = models[0]
        if isinstance(m0, dict):
            mp = m0.get("price")
            if isinstance(mp, int):
                return mp, mp
    return None, None


def normalize_pdp_record(body_json: dict, page_url: str, status: Optional[int]) -> Optional[Dict[str, Any]]:
    data = body_json.get("data") if isinstance(body_json, dict) else None
    if not isinstance(data, dict):
        return None
    item = data.get("item")
    if not isinstance(item, dict):
        return None

    item_id = item.get("item_id")
    shop_id = item.get("shop_id")
    title = item.get("title")
    currency = item.get("currency")
    rating = _safe_get(item, ["item_rating", "rating_star"], None)
    shop_location = item.get("shop_location")
    categories = item.get("categories")
    cat_path = None
    if isinstance(categories, list):
        names = [c.get("display_name") for c in categories if isinstance(c, dict) and c.get("display_name")]
        if names:
            cat_path = " > ".join(names)
    images = _safe_get(item, ["product_images", "images"], [])
    if not isinstance(images, list):
        images = []
    first_image = images[0] if images else None

    price_min, price_max = _normalize_price(item)

    row: Dict[str, Any] = {
        "item_id": item_id,
        "shop_id": shop_id,
        "title": title,
        "currency": currency,
        "price_min": price_min,
        "price_max": price_max,
        "rating_star": rating,
        "shop_location": shop_location,
        "category_path": cat_path,
        "first_image": first_image,
        "source_url": page_url,
        "status": status,
    }
    return row


def export_pdp_from_jsonl(jsonl_path: Path) -> Tuple[Path, Path, List[Dict[str, Any]]]:
    """Read a CDP JSONL capture and write normalized JSON/CSV rows.

    Returns (json_out_path, csv_out_path, rows)
    """
    rows: List[Dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception as e:
                logger.warning(f"Skipping invalid JSONL line: {e}\n{line[:200]}")
                continue
            body = rec.get("body")
            base64_flag = bool(rec.get("base64"))
            page_url = rec.get("url")
            status = rec.get("status")
            if not isinstance(body, str):
                continue
            parsed = _loads_body(body, base64_flag)
            if not parsed:
                continue
            row = normalize_pdp_record(parsed, page_url=page_url, status=status)
            if row:
                rows.append(row)

    data_dir = ensure_data_dir()
    stem = jsonl_path.stem  # e.g., cdp_pdp_12345
    json_out = data_dir / f"{stem}_export.json"
    csv_out = data_dir / f"{stem}_export.csv"
    write_json(rows, json_out)
    write_csv(rows, csv_out)
    return json_out, csv_out, rows
