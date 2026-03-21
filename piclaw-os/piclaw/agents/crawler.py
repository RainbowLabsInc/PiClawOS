"""
PiClaw OS – WebCrawler Sub-Agent
Runs as piclaw-crawler systemd service (same user as mainagent).
Orchestrated by mainagent via jobs.db.

Capabilities:
  - Single-shot crawl with summarisation
  - Recurring (cron/interval) crawl → result in memory + Telegram notify
  - until_found mode: repeat until pattern match, then stop + alert
  - Shares SmartRouter with mainagent via API call to localhost:7842
    (no direct import – mainagent may be in a different process)

Timing constraints:
  Per-request timeout:  15s
  Per-page timeout:     15s
  Per-job hard timeout: job.timeout_sec (default 300s / 5 min)
  Overlap guard:        a job cannot start a new run if previous still running
"""

import asyncio
import logging
import re
import signal
import sys
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse

import aiohttp

from piclaw.agents.ipc import (
    CrawlJob,
    CrawlMode,
    JobStatus,
    write_job_result,
    update_job_status,
    list_jobs,
    get_job,
    init_jobs_db,
)
from piclaw.config import load as load_cfg, CONFIG_DIR
from piclaw.memory.store import write_fact
from piclaw.taskutils import create_background_task

log = logging.getLogger("piclaw.agents.crawler")

REQUEST_TIMEOUT = 15  # seconds per HTTP request
PAGE_TIMEOUT = 15  # seconds per page processing
API_PORT = 7842  # mainagent API for LLM access
POLL_INTERVAL = 10  # seconds between job queue polls
CRAWL_LOG_DIR = CONFIG_DIR / "logs" / "crawler"


# ── HTML text extractor ───────────────────────────────────────────


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts, self._skip = [], False
        self._links = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True
        if tag == "a":
            href = dict(attrs).get("hre", "")
            if href and not href.startswith("#"):
                self._links.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            t = data.strip()
            if t:
                self._parts.append(t)

    @property
    def text(self) -> str:
        return " ".join(self._parts)[:12000]

    @property
    def links(self) -> list[str]:
        return self._links


# ── Crawler core ──────────────────────────────────────────────────


class WebCrawler:
    def __init__(self):
        self._running_jobs: set[str] = set()
        self._scheduler_tasks: dict[str, asyncio.Task] = {}
        self._stop_event = asyncio.Event()
        CRAWL_LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ── HTTP helpers ─────────────────────────────────────────────

    async def _fetch(
        self, session: aiohttp.ClientSession, url: str
    ) -> tuple[str, str, list[str]]:
        """Fetch a URL, return (text, final_url, links)."""
        # (v0.18) Try Tandem Browser first if it looks like a complex site or fallback
        try:
            from piclaw.tools import tandem

            if tandem.TOKEN_FILE.exists():
                log.debug(
                    "Tandem Browser detected – using for enhanced crawling: %s", url
                )
                # Note: This is a simplified integration. For production, we'd
                # manage tab IDs more strictly.
                await tandem.browser_open(url, focus=False)
                await asyncio.sleep(3)  # Wait for JS to render
                snap_raw = await tandem.browser_snapshot(compact=True)
                # We return the snapshot as text. Tandem doesn't return links in compact snap yet
                # in a way we can easily use here without more parsing logic.
                if not snap_raw.startswith("[ERROR]"):
                    return f"[TANDEM SNAPSHOT]\n{snap_raw}", url, []
        except Exception as _te:
            log.debug("Tandem fetch attempt failed: %s", _te)

        # Standard aiohttp fallback
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                allow_redirects=True,
                max_redirects=5,
            ) as resp:
                resp.raise_for_status()
                ct = resp.content_type or ""
                raw = await resp.text(errors="replace")
                final_url = str(resp.url)

                if "html" in ct:
                    p = _TextExtractor()
                    p.feed(raw)
                    # Resolve relative links
                    base = (
                        f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"
                    )
                    abs_links = []
                    for link in p.links:
                        if link.startswith("http"):
                            abs_links.append(link)
                        elif link.startswith("/"):
                            abs_links.append(base + link)
                    return p.text, final_url, abs_links[:50]
                else:
                    return raw[:8000], final_url, []
        except Exception as e:
            return f"[FETCH ERROR] {e}", url, []

    # ── LLM summarisation via mainagent API ───────────────────────

    async def _summarise(self, query: str, content: str) -> str:
        """Ask mainagent's LLM (via REST) to summarise crawl results."""
        prompt = (
            f"You crawled the web for: '{query}'\n\n"
            f"Content found:\n{content[:6000]}\n\n"
            "Summarise the most relevant findings in 3-5 bullet points. "
            "Be specific with dates, numbers and names. "
            "If nothing relevant was found, say so clearly."
        )
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"http://localhost:{API_PORT}/api/chat_raw",
                    json={"prompt": prompt},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as r:
                    if r.status == 200:
                        d = await r.json()
                        return d.get("reply", "")
        except Exception as _e:
            log.debug("LLM summary call failed: %s", _e)
        # Fallback: return trimmed raw content
        return f"[No LLM available – raw]\n{content[:1500]}"

    # ── Single crawl run ──────────────────────────────────────────

    async def run_job(self, job: CrawlJob) -> str:
        """Execute one crawl run. Returns summary string."""
        if job.id in self._running_jobs:
            return "[SKIPPED] Previous run still in progress."
        self._running_jobs.add(job.id)

        try:
            return await asyncio.wait_for(
                self._do_crawl(job),
                timeout=job.timeout_sec,
            )
        except asyncio.TimeoutError:
            msg = f"[TIMEOUT] Job exceeded {job.timeout_sec}s"
            log.warning(msg)
            return msg
        except Exception as e:
            log.error("Job %s failed: %s", job.id, e, exc_info=True)
            return f"[ERROR] {e}"
        finally:
            self._running_jobs.discard(job.id)

    async def _do_crawl(self, job: CrawlJob) -> str:
        log.info("Starting crawl job %s: '%s'", job.id, job.query)
        update_job_status(job.id, JobStatus.RUNNING)

        # Build seed URL list
        seeds = list(job.urls) if job.urls else []
        if not seeds:
            # Use search engine as seed
            query_enc = job.query.replace(" ", "+")
            seeds = [
                f"https://duckduckgo.com/html/?q={query_enc}",
                f"https://search.brave.com/search?q={query_enc}",
            ]

        headers = {"User-Agent": "PiClaw-Crawler/1.0 (Raspberry Pi research bot)"}
        all_text = []
        pages_done = 0
        found_match = ""

        async with aiohttp.ClientSession(headers=headers) as session:
            queue = list(seeds[: job.max_pages])
            visited: set[str] = set()

            while queue and pages_done < job.max_pages:
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)

                text, final_url, links = await self._fetch(session, url)
                if text and not text.startswith("[FETCH ERROR]"):
                    all_text.append(f"=== {final_url} ===\n{text}")
                    pages_done += 1
                    log.debug("  Crawled: %s (%s chars)", final_url, len(text))

                    # until_found check
                    if job.mode == CrawlMode.UNTIL_FOUND and job.until_pattern:
                        if re.search(job.until_pattern, text, re.IGNORECASE):
                            found_match = (
                                f"Pattern '{job.until_pattern}' found at {final_url}"
                            )
                            log.info(found_match)
                            break

                    # Depth expansion
                    if job.max_depth > 1:
                        same_domain = [
                            l
                            for l in links
                            if urlparse(l).netloc == urlparse(url).netloc
                            and l not in visited
                        ]
                        queue.extend(same_domain[:3])

        combined = "\n\n".join(all_text)
        summary = await self._summarise(job.query, combined)

        # Persist to memory
        write_fact(
            content=f"Web crawl '{job.query}' ({datetime.now().strftime('%Y-%m-%d')}): {summary}",
            category="fact",
            tags=["webcrawl", job.query.split()[0]],
        )
        write_job_result(job.id, pages_done, summary, combined, found_match)

        # Log
        log_path = (
            CRAWL_LOG_DIR / f"{job.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )
        log_path.write_text(
            f"# Crawl: {job.query}\n"
            f"Date: {datetime.now().isoformat()}\n"
            f"Pages: {pages_done}\n\n"
            f"## Summary\n{summary}\n\n"
            f"## Raw\n{combined[:20000]}"
        )

        status = JobStatus.DONE if not found_match else JobStatus.DONE
        update_job_status(job.id, status, result=summary[:500])

        result_msg = summary
        if found_match:
            result_msg = f"✅ {found_match}\n\n{summary}"

        return result_msg

    # ── Scheduler: recurring + until_found ───────────────────────

    def schedule_job(self, job: CrawlJob):
        """Start a background task for recurring/until_found jobs."""
        if job.id in self._scheduler_tasks:
            return
        task = asyncio.create_task(self._job_loop(job), name=f"crawl-{job.id}")
        self._scheduler_tasks[job.id] = task

    async def _job_loop(self, job: CrawlJob):
        while not self._stop_event.is_set():
            # Determine sleep interval
            if job.interval_sec:
                sleep = job.interval_sec
            elif job.cron:
                sleep = self._cron_next_seconds(job.cron)
            else:
                break  # no schedule, single run already done

            log.info("Job %s sleeping %ss until next run", job.id, sleep)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep)
                break  # stop event fired
            except asyncio.TimeoutError:
                pass  # normal: time to run

            fresh = get_job(job.id)
            if not fresh or fresh.status == JobStatus.CANCELLED:
                log.info("Job %s cancelled, stopping loop.", job.id)
                break

            result = await self.run_job(fresh)

            # Notify via Telegram if configured
            if fresh.notify_chat and result:
                await self._telegram_notify(
                    chat_id=fresh.notify_chat,
                    text=f"🕷 Crawl result for '{fresh.query}':\n\n{result[:3800]}",
                )

            # Stop if until_found matched
            if fresh.mode == CrawlMode.UNTIL_FOUND and "found at" in result:
                log.info("until_found condition met for job %s, stopping.", fresh.id)
                break

    # ── Telegram notify ───────────────────────────────────────────

    async def _telegram_notify(self, chat_id: str, text: str):
        cfg = load_cfg()
        token = cfg.telegram.token
        if not token:
            return
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            async with aiohttp.ClientSession() as s:
                for chunk in [text[i : i + 4096] for i in range(0, len(text), 4096)]:
                    await s.post(
                        url,
                        json={
                            "chat_id": chat_id,
                            "text": chunk,
                            "parse_mode": "Markdown",
                        },
                    )
        except Exception as e:
            log.error("Telegram notify failed: %s", e)

    # ── Cron helper ───────────────────────────────────────────────

    def _cron_next_seconds(self, cron: str) -> int:
        """Approximate next-run seconds for simple cron expressions."""
        try:
            from croniter import croniter
            from datetime import datetime as dt

            nxt = croniter(cron, dt.now()).get_next(dt)
            return max(1, int((nxt - dt.now()).total_seconds()))
        except ImportError:
            # Fallback: parse hour/minute fields only
            parts = cron.split()
            if len(parts) >= 2:
                try:
                    m = int(parts[0]) if parts[0] != "*" else 0
                    h = int(parts[1]) if parts[1] != "*" else 0
                    now = datetime.now()
                    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    if target <= now:
                        target += timedelta(
                            days=1
                        )  # timedelta statt .day+1 (kein overflow am Monatsende)
                    return max(60, int((target - now).total_seconds()))
                except Exception as _e:
                    log.debug("schedule time parse: %s", _e)
            return 3600  # default 1 hour

    # ── Main daemon loop ──────────────────────────────────────────

    async def run_daemon(self):
        """Main loop: poll jobs.db for pending jobs."""
        init_jobs_db()
        log.info("PiClaw WebCrawler daemon started.")

        # Re-schedule any surviving recurring jobs
        for job in list_jobs():
            if job.mode != CrawlMode.ONCE and job.status not in (
                JobStatus.CANCELLED,
                JobStatus.FAILED,
            ):
                log.info("Resuming recurring job: %s '%s'", job.id, job.query)
                self.schedule_job(job)

        while not self._stop_event.is_set():
            # Pick up new PENDING + ONCE jobs
            for job in list_jobs(status=JobStatus.PENDING):
                if job.mode == CrawlMode.ONCE:
                    create_background_task(self._run_and_notify(job))
                else:
                    self.schedule_job(job)

            await asyncio.sleep(POLL_INTERVAL)

    async def _run_and_notify(self, job: CrawlJob):
        result = await self.run_job(job)
        if job.notify_chat:
            await self._telegram_notify(
                chat_id=job.notify_chat,
                text=f"🕷 *Crawl done*: '{job.query}'\n\n{result[:3800]}",
            )

    def stop(self):
        self._stop_event.set()


# ── Entrypoint ────────────────────────────────────────────────────


def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(CONFIG_DIR / "logs" / "crawler.log")),
        ],
    )
    crawler = WebCrawler()

    def _sig(*_):
        crawler.stop()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    asyncio.run(crawler.run_daemon())


if __name__ == "__main__":
    run()
