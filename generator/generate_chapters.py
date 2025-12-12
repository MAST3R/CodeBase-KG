#!/usr/bin/env python3
"""
generate_chapters.py

Clean, HF-text-generation-only generator.

Behavior:
- Uses the Hugging Face Inference API (HTTP) with JSON payload {"inputs": ..., "parameters": {...}}.
- No probing. No conversational fallback. Uses the documented text-generation contract.
- MOCK_MODE for safe testing (no network calls).
- Reads model and languages from generator/config.yaml.
- Writes Markdown to output/<TitleCaseLanguage>/<ChapterTitle>.md
- Appends completed languages (unless MOCK_MODE).
- Retry/backoff for rate limits and transient errors.
"""

from __future__ import annotations

import os
import sys
import time
import random
import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional, Set

import requests

# ---------- CONFIG PATHS ----------
ROOT = Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generator"
CONFIG_PATH = GEN_DIR / "config.yaml"
OUTDIR = Path(os.environ.get("OUTDIR", str(ROOT / "output")))
COMPLETED_LOG = ROOT / "completed_languages.txt"

# ---------- LOAD CONFIG ----------
if not CONFIG_PATH.exists():
    print(f"ERROR: Missing config file at {CONFIG_PATH}", file=sys.stderr)
    sys.exit(2)

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

MODEL_DEFAULT = cfg.get("model", "openai/gpt-oss-20b")
LANGUAGES = cfg.get("languages", [])

# ---------- ENV / FLAGS ----------
HF_TOKEN = os.environ.get("HF_API_TOKEN", "").strip()
HF_MODEL = os.environ.get("HF_MODEL", "").strip() or MODEL_DEFAULT
PREVIEW_LANGUAGE = os.environ.get("PREVIEW_LANGUAGE", "").strip() or None
MOCK_MODE = str(os.environ.get("MOCK_MODE", "false")).lower() in ("1", "true", "yes")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 5))
INITIAL_BACKOFF = float(os.environ.get("INITIAL_BACKOFF", 2.0))
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", 60))

if not MOCK_MODE and not HF_TOKEN:
    print("ERROR: HF_API_TOKEN is required for non-mock runs.", file=sys.stderr)
    sys.exit(2)

# ---------- HELPERS ----------
def read_completed() -> Set[str]:
    if not COMPLETED_LOG.exists():
        return set()
    try:
        with COMPLETED_LOG.open("r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()

def append_completed(language: str) -> None:
    COMPLETED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with COMPLETED_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{language}\n")

def pick_next_language() -> Optional[str]:
    completed = read_completed()
    for lang in LANGUAGES:
        if lang not in completed:
            return lang
    return None

def safe_filename(s: str) -> str:
    s = s.strip().replace(" ", "_")
    keep = "".join(ch for ch in s if ch.isalnum() or ch in ("_", "-", "."))
    return keep[:200]

def language_folder_titlecase(language: str) -> str:
    if not language:
        return "Unknown"
    return language[0].upper() + language[1:]

def save_markdown(language: str, chapter_title: str, content: str) -> Path:
    safe_lang = language_folder_titlecase(language)
    dirpath = OUTDIR / safe_lang
    dirpath.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(chapter_title) + ".md"
    path = dirpath / filename
    path.write_text(content, encoding="utf-8")
    return path

# ---------- PROMPT BUILDER ----------
def build_prompt_for_chapter(language: str, chapter_meta: Dict[str, Any]) -> str:
    title = chapter_meta.get("title", "Introduction")
    date_iso = datetime.utcnow().date().isoformat()
    frontmatter = {
        "title": title,
        "language": language,
        "date": date_iso,
    }
    fm_yaml = "---\n" + "\n".join(f'{k}: "{v}"' for k, v in frontmatter.items()) + "\n---\n\n"
    guidance = (
        "Write a complete, production-ready Obsidian Markdown chapter.\n\n"
        "Style rules:\n"
        "- Warm, analogy-heavy, teen-friendly voice (inverse tone shift as topics progress).\n"
        "- Include a short Spark & Byte dialogue (two characters) that teases the core concept.\n"
        "- Use Mermaid diagrams when helpful (provide the diagram code block).\n"
        "- For code examples: include line-by-line commentary as inline comments or adjacent explanation.\n"
        "- Provide 2-3 practical exercises and hide answers in collapsible sections.\n"
        "- End with a concise recap and recommended next steps.\n"
        "- Do NOT include any meta-text about prompts, 'as an AI', or internal tool details.\n\n"
    )
    footer = "\n\n<!-- Begin chapter content -->\n\n"
    prompt = f"{fm_yaml}# {title}\n\n{guidance}{footer}"
    return prompt

# ---------- HF HTTP CALL (text-generation only) ----------
def hf_textgen_http(prompt: str, max_new_tokens: int = 300, temperature: float = 0.2) -> Dict[str, Any]:
    """
    Call Hugging Face Inference API via HTTP POST using the text-generation contract:
    { "inputs": "...", "parameters": {...} }
    Returns parsed JSON response.
    Raises requests.HTTPError on non-2xx status.
    """
    url = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
        },
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=HTTP_TIMEOUT)
    # raise for HTTP errors (401/403/404 etc.)
    resp.raise_for_status()
    return resp.json()

# ---------- CALL MODEL (retries/backoff) ----------
def call_model(prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> Dict[str, str]:
    """
    Text-generation-only caller via HF HTTP endpoint. Returns {'content': <text>}.
    Retries on rate/timeout; raises for auth/model-not-found errors.
    """
    if MOCK_MODE:
        content = (
            prompt
            + "\n\n# MOCK CHAPTER\n\nThis content was generated in MOCK_MODE for local testing.\n\n"
            "## Example\n\n```python\n# mock example\nprint('hello mock')\n```\n"
        )
        return {"content": content}

    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            data = hf_textgen_http(prompt, max_new_tokens=max_tokens, temperature=temperature)
            # HF commonly returns either a list of dicts or a dict
            text = ""
            if isinstance(data, list) and len(data) > 0:
                first = data[0]
                if isinstance(first, dict):
                    # common key: 'generated_text'
                    text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                else:
                    text = str(first)
            elif isinstance(data, dict):
                # Some models return {'generated_text': '...'} or {'text': '...'}
                if "generated_text" in data or "text" in data or "content" in data:
                    text = data.get("generated_text") or data.get("text") or data.get("content") or str(data)
                elif "results" in data and isinstance(data["results"], list) and data["results"]:
                    first = data["results"][0]
                    if isinstance(first, dict):
                        text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                    else:
                        text = str(first)
                else:
                    # fallback: stringify
                    text = str(data)
            else:
                text = str(data)

            if not isinstance(text, str):
                text = str(text)
            return {"content": text}

        except requests.HTTPError as http_err:
            status = getattr(http_err.response, "status_code", None)
            msg = str(http_err).lower()
            print(f"[HF_HTTP][attempt {attempt}/{MAX_RETRIES}] HTTP error ({status}): {msg}", file=sys.stderr)
            # Fatal: auth or model-not-found
            if status in (401, 403, 404):
                raise
            # Retryable statuses (429, 500, 502, 503)
            if status in (429, 500, 502, 503):
                sleep_time = backoff + random.random()
                print(f"[HF_HTTP] Retryable HTTP status {status}, sleeping {sleep_time:.1f}s...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue
            # Other HTTP statuses: re-raise
            raise
        except requests.RequestException as e:
            msg = str(e).lower()
            print(f"[HF_HTTP][attempt {attempt}/{MAX_RETRIES}] RequestException: {msg}", file=sys.stderr)
            if any(tok in msg for tok in ("timeout", "connection", "temporarily unavailable", "503")):
                sleep_time = backoff + random.random()
                print(f"[HF_HTTP] Transient network error, sleeping {sleep_time:.1f}s...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue
            # For other request errors, retry a few times then raise
            sleep_time = backoff + random.random()
            print(f"[HF_HTTP] Unknown request error, sleeping {sleep_time:.1f}s...", file=sys.stderr)
            time.sleep(sleep_time)
            backoff *= 2
            continue
    raise RuntimeError("Max retries reached while calling HF Inference HTTP API")

# ---------- CORE GENERATION ----------
def generate_for_language(language: str) -> Path:
    chapter_meta = {"title": "Introduction", "notes": "Auto-generated one-chapter run"}
    prompt = build_prompt_for_chapter(language, chapter_meta)
    print(f"[GEN] Sending prompt for language='{language}' (prompt length {len(prompt)} chars)...")
    resp = call_model(prompt, max_tokens=1200, temperature=0.2)
    md = resp.get("content", "")
    # Ensure frontmatter exists
    if not md.strip().startswith("---"):
        md = prompt + md
    path = save_markdown(language, chapter_meta["title"], md)
    print(f"[GEN] Saved chapter to: {path}")
    return path

# ---------- CLI / MAIN ----------
def main() -> int:
    if PREVIEW_LANGUAGE:
        lang = PREVIEW_LANGUAGE
        print(f"[MAIN] PREVIEW_LANGUAGE override detected: {lang}")
    else:
        lang = pick_next_language()
        print(f"[MAIN] Picked next language: {lang}")

    if not lang:
        print("[MAIN] No languages left to process.")
        return 0

    try:
        outpath = generate_for_language(lang)
        if not MOCK_MODE:
            append_completed(lang)
            print(f"[MAIN] Appended '{lang}' to {COMPLETED_LOG}")
        else:
            print("[MAIN] MOCK_MODE ON — not appending completed log.")
    except Exception as e:
        print(f"[MAIN] ERROR during generation: {e}", file=sys.stderr)
        return 3
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
