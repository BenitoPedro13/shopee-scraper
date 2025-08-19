from __future__ import annotations

from typing import Optional, Tuple

from pydantic import BaseModel, Field, field_validator


def _to_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int,)):
            return v
        if isinstance(v, float):
            return int(v)
        s = str(v).strip()
        if s.isdigit():
            return int(s)
    except Exception:
        return None
    return None


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", ".")
        return float(s)
    except Exception:
        return None


class SearchItem(BaseModel):
    item_id: Optional[int] = Field(default=None)
    shop_id: Optional[int] = Field(default=None)
    title: Optional[str] = None
    currency: Optional[str] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    sold: Optional[int] = None
    shop_location: Optional[str] = None
    url: Optional[str] = None

    @field_validator("item_id", "shop_id", "price_min", "price_max", "sold", mode="before")
    @classmethod
    def _intify(cls, v):
        return _to_int(v)

    def key(self) -> Optional[Tuple[int, int]]:
        if self.shop_id is None or self.item_id is None:
            return None
        return (self.shop_id, self.item_id)


class PdpItem(BaseModel):
    item_id: Optional[int] = Field(default=None)
    shop_id: Optional[int] = Field(default=None)
    title: Optional[str] = None
    currency: Optional[str] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    rating_star: Optional[float] = None
    shop_location: Optional[str] = None
    category_path: Optional[str] = None
    first_image: Optional[str] = None
    source_url: Optional[str] = None
    status: Optional[int] = None

    @field_validator("item_id", "shop_id", "price_min", "price_max", "status", mode="before")
    @classmethod
    def _intify(cls, v):
        return _to_int(v)

    @field_validator("rating_star", mode="before")
    @classmethod
    def _floatify(cls, v):
        return _to_float(v)

    def key(self) -> Optional[Tuple[int, int]]:
        if self.shop_id is None or self.item_id is None:
            return None
        return (self.shop_id, self.item_id)


def deduplicate_models(models):
    seen = set()
    out = []
    for m in models:
        k = m.key()
        if k is None:
            out.append(m)
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(m)
    return out

