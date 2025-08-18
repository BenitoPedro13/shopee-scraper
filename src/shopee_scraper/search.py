"""Search page scraping for Phase 1 (basic extraction)."""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import quote_plus

from playwright.sync_api import TimeoutError as PWTimeoutError
from playwright.sync_api import Page

from .config import settings
from .session import create_search_context
from .utils import ensure_data_dir, jitter_sleep, write_csv, write_json


def _is_captcha_gate(page: Page) -> bool:
    try:
        url = page.url or ""
    except Exception:
        url = ""
    if "/verify/captcha" in url:
        return True
    try:
        # Look for common CAPTCHA hints (heuristic, may evolve)
        has_iframe = page.locator("iframe[src*='captcha'], iframe[src*='challenge']").first.is_visible(timeout=1000)
        has_turnstile = page.locator("input[name='cf-turnstile-response']").first.is_visible(timeout=1000)
        has_text = page.get_by_text("verifique se você é humano", exact=False).first.is_visible(timeout=1000)
        return bool(has_iframe or has_turnstile or has_text)
    except Exception:
        return False


def _type_like_human(page: Page, selector: str, text: str) -> None:
    # Focus and type with small random delay per character
    page.click(selector, delay=100)
    for ch in text:
        page.keyboard.type(ch, delay=80)
    jitter_sleep(0.3, 0.8)


def search_products(keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Navigate to search results and extract product cards.

    Notes:
    - Shopee é altamente dinâmico; seletores podem variar.
    - Usamos alguns seletores comuns com fallbacks.
    - Realizamos scroll incremental para carregar mais itens até `limit`.
    """
    browser, context, close_fn = create_search_context()
    page = context.new_page()

    results: List[Dict[str, Any]] = []
    try:
        # Humanized navigation: land on homepage, then use the UI search box
        homepage = f"https://{settings.shopee_domain}/"
        page.goto(homepage, wait_until="networkidle")
        jitter_sleep(1.2, 2.4)

        if _is_captcha_gate(page):
            print("[Search] CAPTCHA detectado após abrir a home. Resolva manualmente na janela." )
            try:
                input("Pressione Enter após resolver o CAPTCHA...")
            except EOFError:
                pass

        # Try common selectors for the search input
        input_selectors = [
            "input[type='search']",
            "input[name='keyword']",
            "input.shopee-searchbar-input__input",
            "input[placeholder*='Buscar']",
            "input[placeholder*='busca']",
        ]

        found = False
        for sel in input_selectors:
            try:
                page.wait_for_selector(sel, timeout=5000)
                _type_like_human(page, sel, keyword)
                page.keyboard.press("Enter")
                found = True
                break
            except PWTimeoutError:
                continue
        if not found:
            # Fallback: direct URL navigation
            url = f"https://{settings.shopee_domain}/search?keyword={quote_plus(keyword)}"
            page.goto(url, wait_until="networkidle")

        jitter_sleep(1.0, 2.0)

        if _is_captcha_gate(page):
            print("[Search] CAPTCHA detectado na página de busca. Resolva manualmente na janela.")
            try:
                input("Pressione Enter após resolver o CAPTCHA...")
            except EOFError:
                pass

        try:
            page.wait_for_selector(".shopee-search-item-result__item, [data-sqe='item']", timeout=25000)
        except PWTimeoutError:
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

            if _is_captcha_gate(page):
                print("[Search] CAPTCHA detectado durante o scroll. Resolva manualmente para continuar.")
                try:
                    input("Pressione Enter após resolver o CAPTCHA...")
                except EOFError:
                    pass

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
        close_fn()
