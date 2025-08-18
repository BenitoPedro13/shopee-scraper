"""Search page scraping for Phase 1 (basic extraction)."""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import quote_plus

from playwright.sync_api import TimeoutError as PWTimeoutError

from .config import settings
from .session import create_authenticated_context
from .utils import ensure_data_dir, jitter_sleep, write_csv, write_json


def search_products(keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Navigate to search results and extract product cards.

    Notes:
    - Shopee é altamente dinâmico; seletores podem variar.
    - Usamos alguns seletores comuns com fallbacks.
    - Realizamos scroll incremental para carregar mais itens até `limit`.
    """
    url = f"https://{settings.shopee_domain}/search?keyword={quote_plus(keyword)}"
    browser, context = create_authenticated_context()
    page = context.new_page()

    results: List[Dict[str, Any]] = []
    try:
        page.goto(url, wait_until="networkidle")
        try:
            page.wait_for_selector(".shopee-search-item-result__item, [data-sqe='item']", timeout=20000)
        except PWTimeoutError:
            # pode ser login wall ou bloqueio
            raise RuntimeError("Não foi possível carregar resultados de busca (login wall/CAPTCHA?).")

        def extract() -> List[Dict[str, Any]]:
            return page.eval_on_selector_all(
                ".shopee-search-item-result__item, [data-sqe='item']",
                """
                (nodes) => nodes.map(n => {
                  const a = n.querySelector('a');
                  const titleEl = n.querySelector('[data-sqe="name"], [data-sqe="title"], a[title]');
                  const priceEl = n.querySelector('[data-sqe="price"]');
                  const soldEl = n.querySelector('[data-sqe="sold"]');
                  const shopEl = n.querySelector('[data-sqe="shopname"], [data-sqe="shop"]');
                  return {
                    title: titleEl ? titleEl.textContent.trim() : null,
                    price: priceEl ? priceEl.textContent.trim() : null,
                    sold: soldEl ? soldEl.textContent.trim() : null,
                    shop: shopEl ? shopEl.textContent.trim() : null,
                    url: a && a.href ? a.href : null,
                  };
                })
                """,
            )

        # Scroll/load loop
        max_scrolls = 12
        for i in range(max_scrolls):
            current = extract()
            # dedup by url/title combo
            seen = {(r.get("url"), r.get("title")) for r in results}
            for r in current:
                key = (r.get("url"), r.get("title"))
                if key not in seen and r.get("url"):
                    results.append(r)
                    seen.add(key)
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
            # try to scroll to load more
            page.evaluate("window.scrollBy(0, document.body.scrollHeight);")
            jitter_sleep()

        # Trim to limit
        results = results[:limit]

        # Persist outputs
        data_dir = ensure_data_dir()
        safe_kw = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in keyword.strip())
        json_path = data_dir / f"search_{safe_kw}.json"
        csv_path = data_dir / f"search_{safe_kw}.csv"
        write_json(results, json_path)
        write_csv(results, csv_path)
        return results
    finally:
        try:
            context.close()
        finally:
            browser.close()

