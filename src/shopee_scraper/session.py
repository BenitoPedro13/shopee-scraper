"""Session and browser context helpers for Phase 1.

Implements:
- Headful login flow that saves storage_state.json
- Creation of an authenticated browser/context for scraping
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from playwright.sync_api import sync_playwright, Browser, BrowserContext

from .config import settings


def storage_state_path() -> Path:
    return Path(settings.storage_state)


def ensure_data_dirs() -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.user_data_dir).mkdir(parents=True, exist_ok=True)


def _ensure_playwright_browsers_path() -> None:
    """Ensure Playwright resolves browsers from local workspace if available.

    If `.pw-browsers/` exists in the project root, set PLAYWRIGHT_BROWSERS_PATH
    to that absolute path when not already defined in the environment.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    local = Path(".pw-browsers").resolve()
    if local.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local)


def login_and_save_session() -> None:
    """Open a headful Chromium with a persistent user-data dir for manual login.

    Steps:
    - Launch persistent context (headful by default) with locale/timezone/proxy
    - Open Shopee domain homepage
    - User performs login manually (OTP/CAPTCHA as needed)
    - Press Enter in terminal to persist cookies to storage_state.json
    """
    ensure_data_dirs()
    _ensure_playwright_browsers_path()
    state_path = storage_state_path()

    with sync_playwright() as p:
        launch_kwargs = {
            "headless": settings.headless,
            "locale": settings.locale,
            "timezone_id": settings.timezone_id,
        }
        if settings.proxy_url:
            launch_kwargs["proxy"] = {"server": settings.proxy_url}

        if settings.browser_executable_path:
            print(f"[Login] Using executable: {settings.browser_executable_path}")
            context = p.chromium.launch_persistent_context(
                user_data_dir=settings.user_data_dir,
                executable_path=settings.browser_executable_path,
                **launch_kwargs,
            )
        elif settings.browser_channel:
            print(f"[Login] Using channel: {settings.browser_channel}")
            context = p.chromium.launch_persistent_context(
                user_data_dir=settings.user_data_dir,
                channel=settings.browser_channel,
                **launch_kwargs,
            )
        else:
            print("[Login] Using bundled Chromium")
            context = p.chromium.launch_persistent_context(
                user_data_dir=settings.user_data_dir,
                **launch_kwargs,
            )
        try:
            page = context.new_page()
            page.goto(f"https://{settings.shopee_domain}/", wait_until="networkidle")
            print("\n[Login] Um navegador foi aberto. Faça login na Shopee.")
            print("Depois de concluir o login (e ver a home autenticada), volte ao terminal.")
            input("Pressione Enter para salvar a sessão...")
            context.storage_state(path=str(state_path))
            print(f"[Login] Sessão salva em: {state_path}")
        finally:
            context.close()


def create_authenticated_context() -> Tuple[Browser, BrowserContext]:
    """Create a Chromium browser and authenticated context from storage_state.

    Returns (browser, context). Caller should close both after use.
    """
    ensure_data_dirs()
    _ensure_playwright_browsers_path()
    state_path = storage_state_path()
    if not state_path.exists():
        raise FileNotFoundError(
            f"Storage state não encontrado em '{state_path}'. Rode 'python cli.py login' primeiro."
        )

    p = sync_playwright().start()
    launch_kwargs = {"headless": settings.headless}
    if settings.proxy_url:
        launch_kwargs["proxy"] = {"server": settings.proxy_url}
    if settings.browser_executable_path:
        print(f"[Search] Using executable: {settings.browser_executable_path}")
        browser = p.chromium.launch(executable_path=settings.browser_executable_path, **launch_kwargs)
    elif settings.browser_channel:
        print(f"[Search] Using channel: {settings.browser_channel}")
        browser = p.chromium.launch(channel=settings.browser_channel, **launch_kwargs)
    else:
        print("[Search] Using bundled Chromium")
        browser = p.chromium.launch(**launch_kwargs)

    context_kwargs = {
        "storage_state": str(state_path),
        "locale": settings.locale,
        "timezone_id": settings.timezone_id,
    }
    context = browser.new_context(**context_kwargs)
    return browser, context


def _build_chromium_args() -> list[str]:
    args: list[str] = []
    # Help some embedded widgets (e.g., CAPTCHA) that rely on 3P cookies
    if settings.disable_3pc_phaseout:
        args.append("--test-third-party-cookie-phase-out=false")
    # Some evasions (use judiciously; Playwright already masks webdriver)
    args.append("--disable-blink-features=AutomationControlled")
    return args


def _accept_language_header(locale_code: str) -> str:
    # Simple mapping: "pt-BR,pt;q=0.9"
    primary = locale_code
    base = locale_code.split("-")[0]
    if base != primary:
        return f"{primary},{base};q=0.9"
    return f"{primary},{base};q=0.9"


def create_search_context() -> Tuple[Browser | None, BrowserContext, callable]:
    """Create a context for search with optional persistent profile reuse.

    Returns (browser_or_none, context, close_fn).
    close_fn will properly dispose resources regardless of mode.
    """
    ensure_data_dirs()
    _ensure_playwright_browsers_path()
    state_path = storage_state_path()
    if not state_path.exists():
        raise FileNotFoundError(
            f"Storage state não encontrado em '{state_path}'. Rode 'python cli.py login' primeiro."
        )

    p = sync_playwright().start()
    launch_kwargs = {
        "headless": settings.headless,
        "args": _build_chromium_args(),
    }
    if settings.proxy_url:
        launch_kwargs["proxy"] = {"server": settings.proxy_url}

    accept_lang = _accept_language_header(settings.locale)

    if settings.use_persistent_context_for_search:
        # Reuse the same persistent user profile to keep fingerprint/session aligned
        if settings.browser_executable_path:
            print(f"[Search] Using executable (persistent): {settings.browser_executable_path}")
            context = p.chromium.launch_persistent_context(
                user_data_dir=settings.user_data_dir,
                executable_path=settings.browser_executable_path,
                locale=settings.locale,
                timezone_id=settings.timezone_id,
                **launch_kwargs,
            )
        elif settings.browser_channel:
            print(f"[Search] Using channel (persistent): {settings.browser_channel}")
            context = p.chromium.launch_persistent_context(
                user_data_dir=settings.user_data_dir,
                channel=settings.browser_channel,
                locale=settings.locale,
                timezone_id=settings.timezone_id,
                **launch_kwargs,
            )
        else:
            print("[Search] Using bundled Chromium (persistent)")
            context = p.chromium.launch_persistent_context(
                user_data_dir=settings.user_data_dir,
                locale=settings.locale,
                timezone_id=settings.timezone_id,
                **launch_kwargs,
            )

        # Align headers like Accept-Language
        context.set_extra_http_headers({"Accept-Language": accept_lang})

        def _close():
            try:
                context.close()
            finally:
                p.stop()

        return None, context, _close

    # Non-persistent mode (default prior behavior): load storage_state into a fresh context
    if settings.browser_executable_path:
        print(f"[Search] Using executable: {settings.browser_executable_path}")
        browser = p.chromium.launch(executable_path=settings.browser_executable_path, **launch_kwargs)
    elif settings.browser_channel:
        print(f"[Search] Using channel: {settings.browser_channel}")
        browser = p.chromium.launch(channel=settings.browser_channel, **launch_kwargs)
    else:
        print("[Search] Using bundled Chromium")
        browser = p.chromium.launch(**launch_kwargs)

    context_kwargs = {
        "storage_state": str(state_path),
        "locale": settings.locale,
        "timezone_id": settings.timezone_id,
        "extra_http_headers": {"Accept-Language": accept_lang},
    }
    context = browser.new_context(**context_kwargs)

    def _close():
        try:
            context.close()
        finally:
            try:
                browser.close()
            finally:
                p.stop()

    return browser, context, _close
