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

