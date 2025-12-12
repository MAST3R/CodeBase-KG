#!/usr/bin/env python3
"""
Hardened groq_generate.py

- Uses environment GROQ_API_KEY (must be set as a secret in Actions)
- Retries network calls with exponential backoff for transient DNS / network errors
- Writes detailed logs to debug-logs/groq-generate-<timestamp>.log
- Writes per-language drafts into output/<Lang>/drafts/
- Does not print secrets to logs
"""

from __future__ import annotations
import os
import sys
import time
import json
import logging
import pathlib
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from requests.exceptions import RequestException, ConnectionError, Timeout, HTTPError
import socket

# ---------- CONFIG ----------
GROQ_ENDPOINT = "https://api.groq.ai/v1/generate"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OUTPUT_DIR = pathlib.Path("output")
DEBUG_DIR = pathlib.Path("debug-logs")
MAX_RETRIES = 5
BASE_BACKOFF = 2.0  # seconds
TIMEOUT = 30  # requests timeout
# list of sample languages to iterate — keep in sync with your repo's logic
LANGUAGES = [
    "Python","C","Java","JavaScript","PHP","C#","C++","TypeScript",
    "Kotlin","Go","Swift","Rust","MATLAB","R","Ruby","Perl","Haskell",
    "Lua","Objective-C","Dart","Bash"
]

# ---------- SETUP ----------
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
log_path = DEBUG_DIR / f"groq-generate-{ts}.log"

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger("groq_generate")
logger.info("Starting groq_generate.py (hardened)")

if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY not set. Calls to Groq will fail unless you set this secret.")

# Helper: safe request with retries/backoff
def post_with_retries(url: str, payload: Dict[str, Any], headers: Dict[str, str], max_retries: int = MAX_RETRIES) -> Optional[requests.Response]:
    attempt = 0
    while attempt < max_retries:
        try:
            attempt += 1
            logger.info("POST attempt %d/%d to %s", attempt, max_retries, url)
            resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            resp.raise_for_status()
            logger.info("HTTP %d received", resp.status_code)
            return resp
        except requests.exceptions.SSLError as e:
            logger.error("SSL error: %s", e)
            logger.debug(traceback.format_exc())
            # SSL is unlikely transient; break
            break
        except (ConnectionError, Timeout) as e:
            logger.warning("Network error on attempt %d: %s", attempt, e)
            logger.debug(traceback.format_exc())
        except HTTPError as e:
            # Server responded with 4xx/5xx; log and decide whether to retry
            logger.error("HTTP error: %s (status %s)", e, getattr(e.response, "status_code", None))
            logger.debug(traceback.format_exc())
            # Retry server errors 5xx, but stop on 4xx
            if 500 <= getattr(e.response, "status_code", 0) < 600:
                pass
            else:
                break
        except RequestException as e:
            # This can include name resolution issues (socket.gaierror)
            logger.warning("RequestException on attempt %d: %s", attempt, e)
            logger.debug(traceback.format_exc())

        backoff = BASE_BACKOFF * (2 ** (attempt - 1))
        jitter = min(5, backoff * 0.1)
        sleep_time = backoff + (jitter * (0.5 - (time.time() % 1)))  # tiny jitter
        logger.info("Sleeping %.2f seconds before retry", sleep_time)
        time.sleep(sleep_time)
    logger.error("All %d attempts failed for %s", max_retries, url)
    return None

# Small helper to write draft file
def write_draft(lang: str, name: str, body: str) -> None:
    out_dir = OUTPUT_DIR / lang / "drafts"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    logger.info("Wrote draft: %s", str(path))

# Safe resolver check (non-blocking)
def check_dns(host: str) -> bool:
    try:
        socket.gethostbyname(host)
        logger.info("Resolved %s via gethostbyname", host)
        return True
    except Exception as e:
        logger.warning("DNS resolution failed for %s: %s", host, e)
        return False

# ---------- MAIN LOOP ----------
def run_generation():
    logger.info("Starting generation loop for %d languages", len(LANGUAGES))
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}" if GROQ_API_KEY else "",
        "Content-Type": "application/json",
    }

    for lang in LANGUAGES:
        logger.info("Generating draft for language: %s", lang)
        # Optional: quick DNS sanity check
        if not check_dns("api.groq.ai"):
            logger.warning("api.groq.ai NOT resolvable from this environment. Retry logic will still run.")
        payload = {
            "model": "gpt-basic",  # replace with actual model key per your app
            "prompt": f"Generate an example and short explanation for {lang}. Keep it concise.",
            "max_tokens": 512,
        }

        resp = post_with_retries(GROQ_ENDPOINT, payload, headers, max_retries=MAX_RETRIES)
        if resp is None:
            # record failure but continue
            logger.error("Groq generation failed for %s after retries", lang)
            write_draft(lang, f"{lang.lower()}-error.txt", f"[ERR] Groq generation failed for {lang} at {datetime.utcnow().isoformat()}Z\nSee debug logs: {log_path}\n")
            continue

        try:
            data = resp.json()
        except Exception as e:
            logger.error("Failed to parse JSON for %s: %s", lang, e)
            write_draft(lang, f"{lang.lower()}-error.txt", f"[ERR] Non-JSON response for {lang}\n{resp.text[:2000]}")
            continue

        # Extract model text (adjust depending on Groq response schema)
        text = None
        # adapt for common response shapes
        if isinstance(data, dict):
            # try common keys
            for k in ("text", "output", "result", "content"):
                if k in data and isinstance(data[k], str):
                    text = data[k]
                    break
            # some APIs nest outputs
            if text is None and "choices" in data and isinstance(data["choices"], list):
                first = data["choices"][0]
                text = first.get("text") or first.get("message") or first.get("output")
        if text is None:
            # fallback to dumping the JSON
            text = json.dumps(data, indent=2)[:10000]

        filename = f"{lang.lower()}-example.md"
        write_draft(lang, filename, text)
        logger.info("Completed generation for %s", lang)

    logger.info("Generation loop finished")

if __name__ == "__main__":
    try:
        run_generation()
    except Exception as e:
        logger.critical("Unhandled exception in groq_generate: %s", e)
        logger.debug(traceback.format_exc())
        # ensure log file exists and show path
        print(f"Debug log: {log_path}", file=sys.stderr)
        sys.exit(1)
    else:
        logger.info("groq_generate.py finished successfully")
