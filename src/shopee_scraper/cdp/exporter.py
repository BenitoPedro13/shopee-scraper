from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from loguru import logger

from ..utils import ensure_data_dir, write_csv, write_json
from ..schemas import SearchItem, PdpItem, deduplicate_models
from ..config import settings


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


def normalize_pdp_record(body_json: dict, page_url: str, status: Optional[int]) -> Optional[PdpItem]:
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

    try:
        return PdpItem(
            item_id=item_id,
            shop_id=shop_id,
            title=title,
            currency=currency,
            price_min=price_min,
            price_max=price_max,
            rating_star=rating,
            shop_location=shop_location,
            category_path=cat_path,
            first_image=first_image,
            source_url=page_url,
            status=status,
        )
    except Exception as e:
        logger.warning(f"Failed to build PdpItem: {e}")
        return None


def export_pdp_from_jsonl(jsonl_path: Path) -> Tuple[Path, Path, List[Dict[str, Any]]]:
    """Read a CDP JSONL capture and write normalized JSON/CSV rows.

    Returns (json_out_path, csv_out_path, rows)
    """
    models: List[PdpItem] = []
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
            row_model = normalize_pdp_record(parsed, page_url=page_url, status=status)
            if row_model:
                models.append(row_model)

    # Deduplicate by (shop_id, item_id)
    models = deduplicate_models(models)

    # Serialize to rows
    rows: List[Dict[str, Any]] = [m.model_dump() for m in models]

    data_dir = ensure_data_dir()
    stem = jsonl_path.stem  # e.g., cdp_pdp_12345
    json_out = data_dir / f"{stem}_export.json"
    csv_out = data_dir / f"{stem}_export.csv"
    write_json(rows, json_out)
    write_csv(rows, csv_out)
    return json_out, csv_out, rows


# ----------------------- SEARCH EXPORT (CDP) -----------------------

def _find_search_items(payload: Any) -> List[dict]:
    # Try common structures: top-level 'items', nested 'items', or 'data.items'
    if isinstance(payload, dict):
        for key in ("items",):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        data = payload.get("data")
        if isinstance(data, dict):
            v = data.get("items")
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def _normalize_search_item(entry: dict) -> SearchItem:
    base = entry.get("item_basic") if isinstance(entry.get("item_basic"), dict) else entry
    item_id = base.get("itemid") or base.get("item_id")
    shop_id = base.get("shopid") or base.get("shop_id")
    title = base.get("name") or base.get("title")
    currency = base.get("currency")
    price_min = base.get("price_min") or base.get("price")
    price_max = base.get("price_max") or base.get("price")
    sold = base.get("historical_sold") or base.get("sold")
    shop_location = base.get("shop_location")

    url = None
    if shop_id and item_id:
        url = f"https://{settings.shopee_domain}/product/{shop_id}/{item_id}"

    return SearchItem(
        item_id=item_id,
        shop_id=shop_id,
        title=title,
        currency=currency,
        price_min=price_min,
        price_max=price_max,
        sold=sold,
        shop_location=shop_location,
        url=url,
    )


def export_search_from_jsonl(jsonl_path: Path) -> Tuple[Path, Path, List[Dict[str, Any]]]:
    models: List[SearchItem] = []
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
            if not isinstance(body, str):
                continue
            parsed = _loads_body(body, base64_flag)
            if not parsed:
                continue
            items = _find_search_items(parsed)
            for it in items:
                try:
                    models.append(_normalize_search_item(it))
                except Exception as e:
                    logger.warning(f"Skipping invalid search item: {e}")

    # Deduplicate by (shop_id, item_id)
    models = deduplicate_models(models)

    rows: List[Dict[str, Any]] = [m.model_dump() for m in models]

    data_dir = ensure_data_dir()
    stem = jsonl_path.stem  # e.g., cdp_search_12345
    json_out = data_dir / f"{stem}_export.json"
    csv_out = data_dir / f"{stem}_export.csv"
    write_json(rows, json_out)
    write_csv(rows, csv_out)
    return json_out, csv_out, rows
