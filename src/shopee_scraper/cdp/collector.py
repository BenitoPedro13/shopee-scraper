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
from tenacity import (
    Retrying,
    stop_after_attempt,
    wait_exponential,
    wait_random,
    retry_if_exception_type,
)

try:
    import pychrome  # type: ignore
except Exception:  # pragma: no cover
    pychrome = None  # defer import error to runtime message

from ..config import settings
from ..utils import ensure_data_dir, mark_session_status, current_profile_name, RateLimiter
from ..logs import log_event, configure_json_logging


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


def _normalize_proxy_for_chrome(url: str) -> str:
    """Chrome's --proxy-server supports http, socks, socks4, socks5.
    Providers often label endpoints as "https" but they are HTTP CONNECT proxies.
    Map https -> http, socks5h -> socks5, socks4a -> socks4.
    """
    try:
        import urllib.parse as _url
        p = _url.urlsplit(url)
        scheme = (p.scheme or "").lower()
        netloc = p.netloc or p.path  # tolerate host:port without scheme
        # Strip credentials if present: user:pass@host:port -> host:port
        if "@" in netloc:
            netloc = netloc.split("@", 1)[1]
        hostport = netloc
        if scheme in ("https",):
            scheme = "http"
        elif scheme in ("socks5h",):
            scheme = "socks5"
        elif scheme in ("socks4a",):
            scheme = "socks4"
        elif scheme == "":
            # Assume http if not specified
            scheme = "http"
        return f"{scheme}://{hostport}".rstrip("/")
    except Exception:
        return url


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
    # Route traffic via proxy if configured
    if settings.proxy_url:
        args.append(f"--proxy-server={_normalize_proxy_for_chrome(settings.proxy_url)}")
    return args


def _accept_language_header(locale_code: str) -> str:
    primary = locale_code
    base = locale_code.split("-")[0]
    if base != primary:
        return f"{primary},{base};q=0.9"
    return f"{primary},{base};q=0.9"


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
        # Signals for health-check/circuit breaker
        self._last_any_network_ts: float = time.time()
        self._last_match_ts: float = 0.0
        self._blocked_by_status: bool = False
        self._blocked_url_hit: Optional[str] = None
        # Minimal counters for metrics
        self._counters: Dict[str, int] = {
            "navigate_attempts": 0,
            "responses_matched": 0,
            "blocked_status_hits": 0,
        }

    def new_tab(self):
        tab = self.browser.new_tab()

        def on_request_will_be_sent(**kwargs):
            req = kwargs.get("request", {})
            url = req.get("url", "")
            request_id = kwargs.get("requestId")
            self._last_any_network_ts = time.time()
            if request_id and self.filters.match(url):
                self._items[request_id] = CapturedItem(
                    request_id=request_id,
                    url=url,
                    status=None,
                    headers={},
                )
                # We consider a match signal as soon as we see a filtered request
                self._last_match_ts = time.time()
                self._counters["responses_matched"] += 1

        def on_response_received(**kwargs):
            request_id = kwargs.get("requestId")
            response = kwargs.get("response", {})
            self._last_any_network_ts = time.time()
            if request_id in self._items:
                self._items[request_id].status = response.get("status")
                # normalize headers to str:str
                hdrs = response.get("headers", {})
                self._items[request_id].headers = {str(k): str(v) for k, v in hdrs.items()}
                # Block signals on throttling/forbidden
                try:
                    st = int(response.get("status") or 0)
                    if st in (403, 429):
                        self._blocked_by_status = True
                        self._counters["blocked_status_hits"] += 1
                except Exception:
                    pass

        def on_loading_finished(**kwargs):
            request_id = kwargs.get("requestId")
            if request_id in self._items:
                try:
                    # Backoff for transient errors while fetching body
                    for attempt in Retrying(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential(multiplier=0.5, min=0.5, max=4) + wait_random(0, 0.5),
                        retry=retry_if_exception_type(Exception),
                        reraise=True,
                    ):
                        with attempt:
                            body_resp = tab.call_method("Network.getResponseBody", requestId=request_id)
                    self._items[request_id].body = body_resp.get("body")
                    self._items[request_id].base64_encoded = bool(body_resp.get("base64Encoded"))
                    self._last_match_ts = time.time()
                except Exception as e:  # pragma: no cover
                    logger.warning(f"Failed to get body for {request_id}: {e}")

        # Detect navigation to block pages (captcha/login)
        def on_frame_navigated(**kwargs):
            try:
                frame = kwargs.get("frame", {})
                url = frame.get("url", "")
                if url:
                    self._last_any_network_ts = time.time()
                    patterns = [
                        r"/verify/captcha",
                        r"/portal/verification",
                        r"/account/login",
                        r"captcha",
                        r"/user/login",
                    ]
                    for p in patterns:
                        if re.search(p, url):
                            self._blocked_url_hit = url
                            break
            except Exception:
                pass

        tab.set_listener("Network.requestWillBeSent", on_request_will_be_sent)
        tab.set_listener("Network.responseReceived", on_response_received)
        tab.set_listener("Network.loadingFinished", on_loading_finished)
        tab.set_listener("Page.frameNavigated", on_frame_navigated)

        tab.start()
        # Enable domains with basic backoff for transient attach errors
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4) + wait_random(0, 0.5),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                tab.call_method("Network.enable")
                tab.call_method("Page.enable")
        # Align headers/timezone
        try:
            al = _accept_language_header(settings.locale)
            tab.call_method("Network.setExtraHTTPHeaders", headers={"Accept-Language": al})
        except Exception:
            pass
        try:
            tab.call_method("Emulation.setTimezoneOverride", timezoneId=settings.timezone_id)
        except Exception:
            pass
        return tab

    # --------------- Health-check & circuit breaker helpers ---------------
    def should_trip_circuit(self, *, inactivity_s: float = 10.0) -> Optional[str]:
        now = time.time()
        # If explicit block indicators seen
        if self._blocked_by_status:
            return "blocked_http_status_403_429"
        if self._blocked_url_hit:
            return f"blocked_url_detected:{self._blocked_url_hit}"
        # If no network activity for prolonged time
        if (now - self._last_any_network_ts) > inactivity_s:
            return "network_inactivity_timeout"
        # If no matches (filtered) for prolonged time after some activity
        if self._last_match_ts == 0.0 and (now - self._last_any_network_ts) > inactivity_s:
            return "no_filtered_matches_timeout"
        return None

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
    # Wait for DevTools endpoint to be ready
    import urllib.request as _u
    import socket as _s
    start = time.time()
    while time.time() - start < 20.0:
        try:
            with _u.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as resp:
                if resp.status == 200:
                    break
        except Exception:
            pass
        time.sleep(0.5)
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
        configure_json_logging()
        collector = CdpCollector(port=port, filters=filters)
        tab = collector.new_tab()

        logger.info(f"Navigating to PDP: {url}")
        # Navigate with backoff
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4) + wait_random(0, 0.5),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                tab.call_method("Page.navigate", url=url)
                collector._counters["navigate_attempts"] += 1

        # Simple dwell until timeout
        session_t0 = time.time()
        t0 = session_t0
        while time.time() - t0 < timeout_s:
            time.sleep(0.25)
            if (time.time() - t0) > 3.0:
                reason = collector.should_trip_circuit(inactivity_s=6.0)
                if reason:
                    log_event("circuit_trip", context="pdp_once", reason=reason)
                    try:
                        mark_session_status(
                            profile=current_profile_name(),
                            status="degraded",
                            reason=reason,
                        )
                    except Exception:
                        pass
                    raise RuntimeError(f"Circuit breaker tripped (PDP): {reason}")

        # Persist results
        data_dir = ensure_data_dir()
        ts = int(time.time())
        out_path = data_dir / f"cdp_pdp_{ts}.jsonl"
        n = collector.dump_items_jsonl(out_path)
        logger.info(f"Captured {n} matching responses → {out_path}")
        log_event(
            "cdp_capture_summary",
            context="pdp_once",
            captured=n,
            duration_s=round(time.time() - session_t0, 3),
            counters=collector._counters,
            output=str(out_path),
        )
        if n <= 0:
            try:
                mark_session_status(
                    profile=current_profile_name(),
                    status="degraded",
                    reason="no_matching_cdp_responses_pdp",
                )
            except Exception:
                pass
            raise RuntimeError("No matching CDP responses captured (PDP). Session marked as degraded.")
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
        configure_json_logging()
        collector = CdpCollector(port=port, filters=filters)
        tab = collector.new_tab()

        q = _url.quote_plus(keyword)
        search_url = f"https://{settings.shopee_domain}/search?keyword={q}"
        logger.info(f"Navigating to Search: {search_url}")
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4) + wait_random(0, 0.5),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                tab.call_method("Page.navigate", url=search_url)

        session_t0 = time.time()
        t0 = session_t0
        while time.time() - t0 < timeout_s:
            time.sleep(0.25)
            if (time.time() - t0) > 3.0:
                reason = collector.should_trip_circuit(inactivity_s=6.0)
                if reason:
                    log_event("circuit_trip", context="search_once", reason=reason)
                    try:
                        mark_session_status(
                            profile=current_profile_name(),
                            status="degraded",
                            reason=reason,
                        )
                    except Exception:
                        pass
                    raise RuntimeError(f"Circuit breaker tripped (Search): {reason}")

        data_dir = ensure_data_dir()
        ts = int(time.time())
        out_path = data_dir / f"cdp_search_{ts}.jsonl"
        n = collector.dump_items_jsonl(out_path)
        logger.info(f"Captured {n} matching responses → {out_path}")
        log_event(
            "cdp_capture_summary",
            context="search_once",
            captured=n,
            duration_s=round(time.time() - session_t0, 3),
            counters=collector._counters,
            output=str(out_path),
        )
        if n <= 0:
            try:
                mark_session_status(
                    profile=current_profile_name(),
                    status="degraded",
                    reason="no_matching_cdp_responses_search",
                )
            except Exception:
                pass
            raise RuntimeError("No matching CDP responses captured (Search). Session marked as degraded.")
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

    # Helper to run a single session over a subset of URLs
    def _run_once(sub: List[str]) -> Path:
        limiter = RateLimiter(settings.requests_per_minute)
        proc = start_chrome_if_requested(port, launch)
        try:
            configure_json_logging()
            collector = CdpCollector(port=port, filters=filters)
            tab = collector.new_tab()
            total = len(sub)
            session_t0 = time.time()
            for i, u in enumerate(sub, start=1):
                try:
                    limiter.acquire()
                    logger.info(f"Navigating PDP: {u}")
                    if on_progress:
                        on_progress("start", {"index": i, "total": total, "url": u})
                    # Navigate with backoff
                    for attempt in Retrying(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential(multiplier=0.5, min=0.5, max=4) + wait_random(0, 0.5),
                        retry=retry_if_exception_type(Exception),
                        reraise=True,
                    ):
                        with attempt:
                            tab.call_method("Page.navigate", url=u)
                            collector._counters["navigate_attempts"] += 1
                except Exception as e:
                    logger.warning(f"Failed to navigate to {u}: {e}")
                    continue
                t0 = time.time()
                while time.time() - t0 < timeout_s:
                    time.sleep(0.25)
                    if (time.time() - t0) > 3.0:
                        reason = collector.should_trip_circuit(inactivity_s=6.0)
                        if reason:
                            log_event("circuit_trip", context="pdp_batch", reason=reason, index=i)
                            try:
                                mark_session_status(
                                    profile=current_profile_name(),
                                    status="degraded",
                                    reason=reason,
                                )
                            except Exception:
                                pass
                            raise RuntimeError(f"Circuit breaker tripped (PDP batch): {reason}")
                time.sleep(max(0.0, pause_s))
                if on_progress:
                    on_progress("done", {"index": i, "total": total, "url": u})
            data_dir = ensure_data_dir()
            ts = int(time.time())
            out_path = data_dir / f"cdp_pdp_batch_{ts}.jsonl"
            n = collector.dump_items_jsonl(out_path)
            logger.info(f"Captured {n} PDP responses in batch → {out_path}")
            log_event(
                "cdp_capture_summary",
                context="pdp_batch",
                captured=n,
                duration_s=round(time.time() - session_t0, 3),
                counters=collector._counters,
                output=str(out_path),
            )
            if n <= 0:
                try:
                    mark_session_status(
                        profile=current_profile_name(),
                        status="degraded",
                        reason="no_matching_cdp_responses_pdp_batch",
                    )
                except Exception:
                    pass
                raise RuntimeError("No matching CDP responses captured in batch (PDP). Session marked as degraded.")
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

    pages_per_session = max(0, int(settings.pages_per_session))
    if launch and pages_per_session and len(urls) > pages_per_session:
        # Split into chunks, run multiple sessions, then merge outputs
        chunk_paths: List[Path] = []
        for i in range(0, len(urls), pages_per_session):
            sub = urls[i : i + pages_per_session]
            chunk_paths.append(_run_once(sub))
            # Cooldown between Chrome sessions to reduce reconnection patterns
            if i + pages_per_session < len(urls):
                from ..utils import jitter_sleep
                jitter_sleep(2.0, 5.0)
        # Concatenate JSONL files
        data_dir = ensure_data_dir()
        ts = int(time.time())
        final_out = data_dir / f"cdp_pdp_batch_{ts}.jsonl"
        with final_out.open("w", encoding="utf-8") as out:
            for pth in chunk_paths:
                out.write(pth.read_text(encoding="utf-8"))
        return final_out
    else:
        return _run_once(urls)


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
    limiter = RateLimiter(settings.requests_per_minute)

    def _run_chunk(chunk_urls: List[str], chunk_index: int, total_chunks: int) -> Path:
        proc = start_chrome_if_requested(port, launch)
        tabs: List = []
        try:
            configure_json_logging()
            collector = CdpCollector(port=port, filters=filters)
            for _ in range(min(concurrency, len(chunk_urls))):
                tabs.append(collector.new_tab())
            total = len(chunk_urls)
            session_t0 = time.time()
            for i in range(0, len(chunk_urls), len(tabs)):
                batch = chunk_urls[i : i + len(tabs)]
                logger.info(f"Chunk {chunk_index}/{total_chunks} → dispatch {len(batch)}")
                for j, u in enumerate(batch):
                    try:
                        limiter.acquire()
                        logger.info(f"→ Tab {j+1}: {u}")
                        if on_progress:
                            on_progress(
                                "start",
                                {
                                    "index": i + j + 1,
                                    "total": total,
                                    "url": u,
                                    "tab": j + 1,
                                    "batch": (i // len(tabs)) + 1,
                                },
                            )
                        for attempt in Retrying(
                            stop=stop_after_attempt(3),
                            wait=wait_exponential(multiplier=0.5, min=0.5, max=4) + wait_random(0, 0.5),
                            retry=retry_if_exception_type(Exception),
                            reraise=True,
                        ):
                            with attempt:
                                tabs[j].call_method("Page.navigate", url=u)
                                collector._counters["navigate_attempts"] += 1
                    except Exception as e:
                        logger.warning(f"Failed to navigate tab {j+1} to {u}: {e}")
                    time.sleep(max(0.0, stagger_s))
                t0 = time.time()
                while time.time() - t0 < timeout_s:
                    time.sleep(0.25)
                    if (time.time() - t0) > 3.0:
                        reason = collector.should_trip_circuit(inactivity_s=6.0)
                        if reason:
                            log_event(
                                "circuit_trip",
                                context="pdp_batch_concurrent",
                                reason=reason,
                                chunk_index=chunk_index,
                            )
                            try:
                                mark_session_status(
                                    profile=current_profile_name(),
                                    status="degraded",
                                    reason=reason,
                                )
                            except Exception:
                                pass
                            raise RuntimeError(f"Circuit breaker tripped (PDP concurrent): {reason}")
                if on_progress:
                    on_progress(
                        "batch_done",
                        {
                            "end_index": i + len(batch),
                            "total": total,
                        },
                    )
            data_dir = ensure_data_dir()
            ts = int(time.time())
            out_path = data_dir / f"cdp_pdp_batch_{ts}.jsonl"
            n = collector.dump_items_jsonl(out_path)
            logger.info(f"Captured {n} PDP responses (concurrent) → {out_path}")
            log_event(
                "cdp_capture_summary",
                context="pdp_batch_concurrent",
                captured=n,
                duration_s=round(time.time() - session_t0, 3),
                counters=collector._counters,
                output=str(out_path),
            )
            if n <= 0:
                try:
                    mark_session_status(
                        profile=current_profile_name(),
                        status="degraded",
                        reason="no_matching_cdp_responses_pdp_concurrent",
                    )
                except Exception:
                    pass
                raise RuntimeError("No matching CDP responses captured (PDP concurrent). Session marked as degraded.")
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

    pages_per_session = max(0, int(settings.pages_per_session))
    if launch and pages_per_session and len(urls) > pages_per_session:
        chunk_paths: List[Path] = []
        total_chunks = (len(urls) + pages_per_session - 1) // pages_per_session
        for cidx, start in enumerate(range(0, len(urls), pages_per_session), start=1):
            chunk = urls[start : start + pages_per_session]
            chunk_paths.append(_run_chunk(chunk, cidx, total_chunks))
            # Cooldown between Chrome sessions
            if start + pages_per_session < len(urls):
                from ..utils import jitter_sleep
                jitter_sleep(2.0, 5.0)
        data_dir = ensure_data_dir()
        ts = int(time.time())
        final_out = data_dir / f"cdp_pdp_batch_{ts}.jsonl"
        with final_out.open("w", encoding="utf-8") as out:
            for pth in chunk_paths:
                out.write(pth.read_text(encoding="utf-8"))
        return final_out
    else:
        return _run_chunk(urls, 1, 1)
