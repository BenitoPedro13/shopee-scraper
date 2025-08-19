import base64
import json
from pathlib import Path

from src.shopee_scraper.cdp.exporter import (
    _loads_body,
    normalize_pdp_record,
    export_pdp_from_jsonl,
    export_search_from_jsonl,
)
from src.shopee_scraper.config import settings


def test__loads_body_plain_and_base64():
    obj = {"x": 1}
    plain = json.dumps(obj)
    assert _loads_body(plain, False) == obj

    b64 = base64.b64encode(plain.encode("utf-8")).decode("ascii")
    assert _loads_body(b64, True) == obj


def test_normalize_pdp_record_minimal():
    body = {
        "data": {
            "item": {
                "item_id": 111,
                "shop_id": 222,
                "title": "Produto X",
                "currency": "BRL",
                "item_rating": {"rating_star": 4.8},
                "categories": [{"display_name": "Geral"}, {"display_name": "Sub"}],
                "product_images": {"images": ["img1.jpg", "img2.jpg"]},
                "product_price": {"price": {"single_value": 123456}},
            }
        }
    }
    row = normalize_pdp_record(body, page_url="https://example", status=200)
    assert row["item_id"] == 111
    assert row["shop_id"] == 222
    assert row["price_min"] == 123456 and row["price_max"] == 123456
    assert row["category_path"] == "Geral > Sub"
    assert row["first_image"] == "img1.jpg"


def test_export_pdp_from_jsonl_end_to_end(tmp_path: Path):
    # Ensure outputs go to tmp
    settings.data_dir = str(tmp_path)
    payload = {
        "data": {"item": {"item_id": 1, "shop_id": 2, "title": "P", "currency": "BRL"}}
    }
    body = json.dumps(payload)
    rec = {"url": "https://x", "status": 200, "headers": {}, "body": body, "base64": False}
    jpath = tmp_path / "cdp_pdp_mock.jsonl"
    jpath.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    json_out, csv_out, rows = export_pdp_from_jsonl(jpath)
    assert json_out.exists() and csv_out.exists()
    assert rows and rows[0]["item_id"] == 1 and rows[0]["shop_id"] == 2


def test_export_search_from_jsonl_items_and_data_items(tmp_path: Path):
    settings.data_dir = str(tmp_path)
    # Case 1: top-level items
    payload1 = {"items": [{"item_basic": {"itemid": 10, "shopid": 20, "name": "A", "price": 100}}]}
    # Case 2: data.items
    payload2 = {"data": {"items": [{"item_id": 11, "shop_id": 21, "title": "B", "price_min": 120}]}}
    rec1 = {"url": "https://x", "status": 200, "headers": {}, "body": json.dumps(payload1), "base64": False}
    rec2 = {"url": "https://x", "status": 200, "headers": {}, "body": json.dumps(payload2), "base64": False}
    jpath = tmp_path / "cdp_search_mock.jsonl"
    jpath.write_text(json.dumps(rec1) + "\n" + json.dumps(rec2) + "\n", encoding="utf-8")

    json_out, csv_out, rows = export_search_from_jsonl(jpath)
    assert json_out.exists() and csv_out.exists()
    # We should have at least 2 normalized rows with URLs built from domain
    assert len(rows) >= 2
    assert all("item_id" in r and "shop_id" in r for r in rows)

