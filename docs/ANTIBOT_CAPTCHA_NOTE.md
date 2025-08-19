Context
- Phase: We are in Phase 1 (MVP – headful login + persisted session).
- Observation: After login, Shopee often redirects to /verify/captcha and/or shows “Erro de Carregamento”. Using a normal desktop browser manually may work, but automation and even headful Playwright can still be flagged.

Why this happens (updated understanding)
- ML‑powered detection: Shopee reportedly uses reinforcement‑learning models that adapt quickly to new bot tactics by correlating behavioral, timing, and fingerprint signals.
- Dynamic security SDK: A proprietary JS security library runs continuously in-page, generating dynamic cryptographic headers (e.g., af-ac-enc-dat, x-sap-* family, x-csrftoken, x-sz-sdk-version) tied to device fingerprint, timing, and session state.
- Device fingerprinting: WebGL/Canvas/Audio/RTC, font lists, Accept‑Language/timezone/user‑agent consistency, hardware/JS performance, and plugin surface are profiled to derive a unique device hash.
- Automation/tooling detection: Framework artifacts and non‑human behavior (perfect timings, no mouse micros, deterministic scrolls) raise risk scores. Even when WebDriver is masked, Playwright/Selenium patterns can still be detectable.

Why traditional methods fail
- Naked HTTP (requests) cannot execute the security SDK JS, so dynamic headers/tokens are missing and requests get blocked immediately.
- Classic automation (Selenium/Puppeteer/Playwright) may still be fingerprinted due to runtime modifications and behavior signatures.

Three viable approaches (prioritized)
1) Browser Engine Interception (CDP): Drive a real Chrome via Chrome DevTools Protocol, load PDP/search normally, and capture background API calls (e.g., /api/v4/pdp/get_pc) from the Network domain without injecting detectable automation logic.
2) Native App API Interception: Reverse engineer the official mobile app and intercept its API requests to extract product data server responses.
3) Mobile Browser Emulation: Use an Android emulator (e.g., Genymotion) with logged‑in Chrome; capture traffic via ADB/system‑level inspection while interacting like a real user.

Immediate direction for this project
- Adopt CDP interception for data collection while keeping human UX flows. This means launching real Chrome with remote debugging, connecting via CDP, and filtering network events for relevant API responses.

Concrete CDP plan (Approach 1)
- Launch Chrome with remote debugging: chrome --remote-debugging-port=9222 using a persistent profile aligned to region.
- Connect via CDP client (e.g., pychrome/pycdp) and enable Network domain (requestWillBeSent, responseReceived, loadingFinished).
- Navigate to Shopee PDP/search using realistic behavior in the UI.
- Filter relevant endpoints (e.g., /api/v4/pdp/get_pc and related) and extract response bodies with Network.getResponseBody.
- Maintain Accept‑Language and timezone alignment; avoid clearing cookies during a run but support strategic cache/cookie clears between sessions.

Operational mitigations that still matter
- Geo/IP hygiene: Use country‑aligned, stable residential/mobile proxies; avoid mid‑session IP changes; one IP per profile.
- Human behavior: Realistic mouse/move/scroll/typing patterns and dwell times; occasional backward scrolls and pauses.
- Cookie/3P cookies: Ensure third‑party cookies and consent states aren’t blocked; if needed, launch flags to disable 3P cookie phaseout for CAPTCHA widgets.
- Session isolation: One Chrome profile per session; recycle instances after N pages to avoid pattern accumulation.
- Reverse‑engineering loop: Periodically review security JS changes, dynamic header requirements, endpoint variations, and adapt filters.

Revised next steps checklist
1) Switch target to CDP interception:
   - Install a CDP client (e.g., pychrome) and add a CDP helper module in this repo.
   - Start Chrome with --remote-debugging-port=9222 using the same regional profile and proxy.
2) Keep HEADLESS=false and real Chrome (BROWSER_CHANNEL=chrome or explicit path). Ensure 3P cookies not broken (consider phaseout flag if necessary).
3) Implement a minimal CDP collector that:
   - Opens a new tab, enables Network domain, navigates to a PDP, captures /api/v4/pdp/get_pc responses, and writes JSON to data/.
4) Humanize navigation before opening PDPs: home → category → product; random dwell and scroll.
5) If CDP approach degrades (blocks increase over time), plan fallbacks:
   - Native app API interception track.
   - Android emulator + mobile Chrome + ADB capture track.

Notes on scope & ethics
- Shopee’s defenses evolve; any working approach may degrade over months due to adaptive ML. Maintain multiple tracks in parallel.
- Respect ToS/robots, rate‑limit conservatively, avoid PII, and use data responsibly.
