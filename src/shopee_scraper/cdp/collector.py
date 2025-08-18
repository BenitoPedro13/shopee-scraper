from __future__ import annotations

import json
import os
import platform
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from loguru import logger

try:
    import pychrome  # type: ignore
except Exception:  # pragma: no cover
    pychrome = None  # defer import error to runtime message

from ..config import settings
from ..utils import ensure_data_dir


def _default_chrome() -> Optional[str]:
    system = platform.system().lower()
    candidates: List[str] = []
    if system == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "windows":
        candidates = [
            r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def _build_launch_cmd(port: int) -> List[str]:
    exe = settings.browser_executable_path or _default_chrome()
    if not exe:
        raise RuntimeError(
            "Chrome executable not found. Set BROWSER_EXECUTABLE_PATH in .env or install Chrome."
        )
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={settings.user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    # Some CAPTCHA widgets require 3P cookies
    if settings.disable_3pc_phaseout:
        args.append("--test-third-party-cookie-phase-out=false")
    return args


@dataclass
class CdpFilters:
    url_regexes: List[re.Pattern] = field(default_factory=list)

    @classmethod
    def from_patterns(cls, patterns: Iterable[str]) -> "CdpFilters":
        return cls([re.compile(p) for p in patterns])

    def match(self, url: str) -> bool:
        return any(r.search(url) for r in self.url_regexes)


@dataclass
class CapturedItem:
    request_id: str
    url: str
    status: Optional[int]
    headers: Dict[str, str]
    body: Optional[str] = None
    base64_encoded: bool = False


class CdpCollector:
    def __init__(self, port: int, filters: CdpFilters) -> None:
        if pychrome is None:
            raise RuntimeError(
                "pychrome is not installed. Add it to requirements and pip install."
            )
        self.port = port
        self.browser = pychrome.Browser(url=f"http://127.0.0.1:{port}")
        self.filters = filters
        self._items: Dict[str, CapturedItem] = {}

    def new_tab(self):
        tab = self.browser.new_tab()

        def on_request_will_be_sent(**kwargs):
            req = kwargs.get("request", {})
            url = req.get("url", "")
            request_id = kwargs.get("requestId")
            if request_id and self.filters.match(url):
                self._items[request_id] = CapturedItem(
                    request_id=request_id,
                    url=url,
                    status=None,
                    headers={},
                )

        def on_response_received(**kwargs):
            request_id = kwargs.get("requestId")
            response = kwargs.get("response", {})
            if request_id in self._items:
                self._items[request_id].status = response.get("status")
                # normalize headers to str:str
                hdrs = response.get("headers", {})
                self._items[request_id].headers = {str(k): str(v) for k, v in hdrs.items()}

        def on_loading_finished(**kwargs):
            request_id = kwargs.get("requestId")
            if request_id in self._items:
                try:
                    body_resp = tab.call_method("Network.getResponseBody", requestId=request_id)
                    self._items[request_id].body = body_resp.get("body")
                    self._items[request_id].base64_encoded = bool(body_resp.get("base64Encoded"))
                except Exception as e:  # pragma: no cover
                    logger.warning(f"Failed to get body for {request_id}: {e}")

        tab.set_listener("Network.requestWillBeSent", on_request_will_be_sent)
        tab.set_listener("Network.responseReceived", on_response_received)
        tab.set_listener("Network.loadingFinished", on_loading_finished)

        tab.start()
        tab.call_method("Network.enable")
        tab.call_method("Page.enable")
        return tab

    def dump_items_jsonl(self, path: Path) -> int:
        count = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for item in self._items.values():
                rec = {
                    "url": item.url,
                    "status": item.status,
                    "headers": item.headers,
                    "body": item.body,
                    "base64": item.base64_encoded,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                count += 1
        return count


def start_chrome_if_requested(port: int, launch: bool) -> Optional[subprocess.Popen]:
    if not launch:
        return None
    cmd = _build_launch_cmd(port)
    logger.info(f"Launching Chrome: {' '.join(shlex.quote(c) for c in cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # give Chrome a moment to open the debugging endpoint
    time.sleep(1.5)
    return proc


def collect_pdp_once(url: str, launch: bool = False, timeout_s: float = 20.0) -> Path:
    """Launch/attach to Chrome via CDP, navigate to PDP, capture matching API responses.

    Returns path to the JSONL file with captured records.
    """
    port = int(os.environ.get("CDP_PORT", "9222"))
    # Default filter for Shopee PDP get_pc; allow override via env CDP_FILTER_PATTERNS
    default_patterns = [r"/api/v4/pdp/get_pc"]
    env_patterns = os.environ.get("CDP_FILTER_PATTERNS")
    patterns = [p.strip() for p in env_patterns.split(",") if p.strip()] if env_patterns else default_patterns

    filters = CdpFilters.from_patterns(patterns)
    proc = start_chrome_if_requested(port, launch)
    try:
        collector = CdpCollector(port=port, filters=filters)
        tab = collector.new_tab()

        logger.info(f"Navigating to PDP: {url}")
        tab.call_method("Page.navigate", url=url)

        # Simple dwell until timeout
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            time.sleep(0.25)

        # Persist results
        data_dir = ensure_data_dir()
        ts = int(time.time())
        out_path = data_dir / f"cdp_pdp_{ts}.jsonl"
        n = collector.dump_items_jsonl(out_path)
        logger.info(f"Captured {n} matching responses → {out_path}")
        return out_path
    finally:
        try:
            if 'tab' in locals():
                tab.stop()
        except Exception:
            pass
        try:
            if proc is not None:
                proc.terminate()
        except Exception:
            pass


def collect_search_once(keyword: str, launch: bool = False, timeout_s: float = 20.0) -> Path:
    """Launch/attach to Chrome via CDP, navigate to a search URL, capture listing API responses.

    Returns path to the JSONL file with captured records.
    """
    import urllib.parse as _url

    port = int(os.environ.get("CDP_PORT", "9222"))
    # Default filters for Shopee search/listing APIs; override via CDP_FILTER_PATTERNS
    default_patterns = [
        r"/api/v4/search/",
        r"/api/v2/search_items",
        r"/api/v4/recommend/",
    ]
    env_patterns = os.environ.get("CDP_FILTER_PATTERNS")
    patterns = [p.strip() for p in env_patterns.split(",") if p.strip()] if env_patterns else default_patterns

    filters = CdpFilters.from_patterns(patterns)
    proc = start_chrome_if_requested(port, launch)
    try:
        collector = CdpCollector(port=port, filters=filters)
        tab = collector.new_tab()

        q = _url.quote_plus(keyword)
        search_url = f"https://{settings.shopee_domain}/search?keyword={q}"
        logger.info(f"Navigating to Search: {search_url}")
        tab.call_method("Page.navigate", url=search_url)

        t0 = time.time()
        while time.time() - t0 < timeout_s:
            time.sleep(0.25)

        data_dir = ensure_data_dir()
        ts = int(time.time())
        out_path = data_dir / f"cdp_search_{ts}.jsonl"
        n = collector.dump_items_jsonl(out_path)
        logger.info(f"Captured {n} matching responses → {out_path}")
        return out_path
    finally:
        try:
            if 'tab' in locals():
                tab.stop()
        except Exception:
            pass
        try:
            if proc is not None:
                proc.terminate()
        except Exception:
            pass


def launch_chrome_for_login(timeout_open_s: Optional[float] = None, port: Optional[int] = None) -> None:
    """Launch a real Chrome with the project user-data dir and remote debugging enabled.

    Use this to perform manual login in a real browser profile used by CDP capture.
    Keeps the browser open until the user closes it or the optional timeout elapses.
    """
    p = int(os.environ.get("CDP_PORT", str(port or 9222)))
    proc = start_chrome_if_requested(p, launch=True)
    logger.info(
        "Chrome launched with user profile. Log in to Shopee in the opened browser."
    )
    if timeout_open_s is None:
        input("Press Enter here after finishing login to close Chrome...")
    else:
        logger.info(f"Keeping Chrome open for ~{timeout_open_s}s")
        time.sleep(timeout_open_s)
    try:
        if proc is not None:
            proc.terminate()
    except Exception:
        pass


from typing import Callable, Optional


def collect_pdp_batch(
    urls: List[str],
    launch: bool = False,
    timeout_s: float = 12.0,
    pause_s: float = 0.5,
    on_progress: Optional[Callable[[str, Dict[str, object]], None]] = None,
) -> Path:
    """Capture PDP API responses for multiple product URLs in a single CDP session.

    Returns path to a single JSONL file with all captured records.
    """
    if not urls:
        raise ValueError("No URLs provided for PDP batch capture.")

    port = int(os.environ.get("CDP_PORT", "9222"))
    default_patterns = [r"/api/v4/pdp/get_pc"]
    env_patterns = os.environ.get("CDP_FILTER_PATTERNS")
    patterns = [p.strip() for p in env_patterns.split(",") if p.strip()] if env_patterns else default_patterns

    filters = CdpFilters.from_patterns(patterns)
    proc = start_chrome_if_requested(port, launch)
    try:
        collector = CdpCollector(port=port, filters=filters)
        tab = collector.new_tab()

        total = len(urls)
        for idx, u in enumerate(urls, start=1):
            try:
                logger.info(f"Navigating PDP: {u}")
                if on_progress:
                    on_progress("start", {"index": idx, "total": total, "url": u})
                tab.call_method("Page.navigate", url=u)
            except Exception as e:
                logger.warning(f"Failed to navigate to {u}: {e}")
                continue
            t0 = time.time()
            while time.time() - t0 < timeout_s:
                time.sleep(0.25)
            time.sleep(pause_s)
            if on_progress:
                on_progress("done", {"index": idx, "total": total, "url": u})

        data_dir = ensure_data_dir()
        ts = int(time.time())
        out_path = data_dir / f"cdp_pdp_batch_{ts}.jsonl"
        n = collector.dump_items_jsonl(out_path)
        logger.info(f"Captured {n} PDP responses in batch → {out_path}")
        return out_path
    finally:
        try:
            if 'tab' in locals():
                tab.stop()
        except Exception:
            pass


def collect_pdp_batch_concurrent(
    urls: List[str],
    *,
    launch: bool = False,
    timeout_s: float = 8.0,
    stagger_s: float = 1.0,
    concurrency: int = 4,
    on_progress: Optional[Callable[[str, Dict[str, object]], None]] = None,
) -> Path:
    """Capture PDP API responses for multiple product URLs using multiple tabs concurrently.

    Schedules navigation in batches of size `concurrency`, staggering each tab by `stagger_s` seconds,
    and waiting `timeout_s` after dispatching a batch.
    """
    if not urls:
        raise ValueError("No URLs provided for PDP batch capture.")
    if concurrency < 1:
        concurrency = 1

    port = int(os.environ.get("CDP_PORT", "9222"))
    default_patterns = [r"/api/v4/pdp/get_pc"]
    env_patterns = os.environ.get("CDP_FILTER_PATTERNS")
    patterns = [p.strip() for p in env_patterns.split(",") if p.strip()] if env_patterns else default_patterns

    filters = CdpFilters.from_patterns(patterns)
    proc = start_chrome_if_requested(port, launch)
    tabs: List = []
    try:
        collector = CdpCollector(port=port, filters=filters)
        # Pre-create tabs up to concurrency
        for _ in range(concurrency):
            tabs.append(collector.new_tab())

        # Dispatch in batches
        total = len(urls)
        for i in range(0, len(urls), concurrency):
            batch = urls[i : i + concurrency]
            logger.info(f"Batch {i//concurrency + 1}: navigating {len(batch)} PDPs")
            for j, u in enumerate(batch):
                try:
                    logger.info(f"→ Tab {j+1}: {u}")
                    if on_progress:
                        on_progress(
                            "start",
                            {
                                "index": i + j + 1,
                                "total": total,
                                "url": u,
                                "tab": j + 1,
                                "batch": (i // concurrency) + 1,
                            },
                        )
                    tabs[j].call_method("Page.navigate", url=u)
                except Exception as e:
                    logger.warning(f"Failed to navigate tab {j+1} to {u}: {e}")
                time.sleep(max(0.0, stagger_s))
            # dwell to allow API responses to arrive
            t0 = time.time()
            while time.time() - t0 < timeout_s:
                time.sleep(0.25)
            if on_progress:
                on_progress(
                    "batch_done",
                    {
                        "end_index": i + len(batch),
                        "total": total,
                        "batch": (i // concurrency) + 1,
                    },
                )

        data_dir = ensure_data_dir()
        ts = int(time.time())
        out_path = data_dir / f"cdp_pdp_batch_{ts}.jsonl"
        n = collector.dump_items_jsonl(out_path)
        logger.info(f"Captured {n} PDP responses (concurrent) → {out_path}")
        return out_path
    finally:
        for t in tabs:
            try:
                t.stop()
            except Exception:
                pass
        try:
            if proc is not None:
                proc.terminate()
        except Exception:
            pass
        try:
            if proc is not None:
                proc.terminate()
        except Exception:
            pass
