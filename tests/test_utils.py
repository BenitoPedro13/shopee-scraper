from pathlib import Path
from src.shopee_scraper.utils import write_json, write_csv


def test_write_json_and_csv(tmp_path: Path):
    rows = [
        {"b": 2, "a": 1},
        {"a": 3, "c": 4},
    ]
    json_path = tmp_path / "out.json"
    csv_path = tmp_path / "out.csv"

    write_json(rows, json_path)
    assert json_path.exists()
    assert json_path.read_text(encoding="utf-8").strip().startswith("[")

    write_csv(rows, csv_path)
    content = csv_path.read_text(encoding="utf-8").splitlines()
    # header should include all keys sorted
    assert content[0].split(",") == sorted({k for r in rows for k in r.keys()})
    # number of data lines equals rows length
    assert len(content) == len(rows) + 1

