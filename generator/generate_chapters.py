#!/usr/bin/env python3
"""
generate_chapters.py

Final, corrected, router-compatible generator (stdlib-only).

- Uses Hugging Face router endpoint: https://router.huggingface.co/hf-inference/models/<model>
- Text-generation JSON shape only.
- No external deps (urllib only).
- MOCK_MODE supported.
- Writes to output/<TitleCaseLanguage>/Introduction.md
- Safe retry/backoff and clear Action logs.
"""

from __future__ import annotations

import os
import sys
import json
import time
import random
from pathlib import Path
from datetime import datetime
from urllib import request, error
import yaml
from typing import Optional, Set, Dict, Any

# -------------------- CONFIG PATHS --------------------
ROOT = Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generator"
CONFIG_PATH = GEN_DIR / "config.yaml"

OUTDIR = Path(os.environ.get("OUTDIR", str(ROOT / "output")))
COMPLETED_LOG = ROOT / "completed_languages.txt"

# -------------------- LOAD CONFIG --------------------
if not CONFIG_PATH.exists():
    print(f"ERROR: Missing config file at {CONFIG_PATH}", file=sys.stderr)
    sys.exit(2)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

MODEL_DEFAULT = cfg.get("model", "openai/gpt-oss-20b")
LANGUAGES = cfg.get("languages", [])

# -------------------- ENV VARS --------------------
HF_TOKEN = os.environ.get("HF_API_TOKEN", "").strip()
HF_MODEL = os.environ.get("HF_MODEL", MODEL_DEFAULT).strip()
PREVIEW_LANGUAGE = os.environ.get("PREVIEW_LANGUAGE", "").strip() or None
MOCK_MODE = os.environ.get("MOCK_MODE", "false").lower() in ("1", "true", "yes")

MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 5))
INITIAL_BACKOFF = float(os.environ.get("INITIAL_BACKOFF", 2.0))
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", 60))

if not MOCK_MODE and not HF_TOKEN:
    print("ERROR: HF_API_TOKEN is required.", file=sys.stderr)
    sys.exit(2)

# -------------------- UTILITIES --------------------
def titlecase_lang(lang: str) -> str:
    if not lang:
        return "Unknown"
    return lang[0].upper() + lang[1:]

def safe_filename(name: str) -> str:
    name = name.strip().replace(" ", "_")
    return "".join(c for c in name if c.isalnum() or c in "_-.")[:200]

def read_completed() -> Set[str]:
    if not COMPLETED_LOG.exists():
        return set()
    try:
        return set(x.strip() for x in COMPLETED_LOG.read_text(encoding="utf-8").splitlines() if x.strip())
    except Exception:
        return set()

def append_completed(lang: str) -> None:
    COMPLETED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(COMPLETED_LOG, "a", encoding="utf-8") as f:
        f.write(f"{lang}\n")

def pick_next_language() -> Optional[str]:
    done = read_completed()
    for l in LANGUAGES:
        if l not in done:
            return l
    return None

# -------------------- PROMPT BUILDER --------------------
def build_prompt(language: str, chapter_title: str = "Introduction") -> str:
    date_iso = datetime.utcnow().date().isoformat()
    frontmatter = (
        "---\n"
        f'title: "{chapter_title}"\n'
        f'language: "{language}"\n'
        f'date: "{date_iso}"\n'
        "---\n\n"
    )
    body = (
        f"# {chapter_title}\n\n"
        "Write a complete, production-ready Obsidian Markdown chapter.\n\n"
        "Rules:\n"
        "- Warm, analogy-rich, teen-friendly voice.\n"
        "- Include Spark & Byte dialogue.\n"
        "- Include Mermaid diagrams when useful.\n"
        "- Add code examples with explanations.\n"
        "- Provide 2-3 exercises with collapsible answers.\n"
        "- End with a clear recap and next steps.\n\n"
        "<!-- Begin chapter content -->\n\n"
    )
    return frontmatter + body

# -------------------- HF ROUTER CALL (urllib) --------------------
def hf_call(prompt: str, max_new_tokens: int = 1000, temperature: float = 0.2) -> str:
    if MOCK_MODE:
        # Safe mock output that proves structure only
        return prompt + "\n\n# MOCK OUTPUT\nThis is a mock chapter for testing."

    url = f"https://router.huggingface.co/hf-inference/models/{HF_MODEL}"
    payload: Dict[str, Any] = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_new_tokens,
            "temperature": temperature
        }
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json"
    }

    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = request.Request(url, data=data, headers=headers, method="POST")
            with request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
                try:
                    parsed = json.loads(raw)
                except Exception:
                    # Non-JSON response — return raw body
                    return raw

                # Common router: list of dicts with generated_text
                if isinstance(parsed, list) and parsed:
                    first = parsed[0]
                    if isinstance(first, dict):
                        return first.get("generated_text") or first.get("text") or raw
                    else:
                        return str(first)
                if isinstance(parsed, dict):
                    return parsed.get("generated_text") or parsed.get("text") or raw
                return raw

        except error.HTTPError as he:
            body = he.read().decode("utf-8", errors="ignore")
            print(f"[HF][{attempt}] HTTPError {he.code}: {body}", file=sys.stderr)
            # Fatal statuses
            if he.code in (401, 403, 404):
                raise
            # Retryable statuses
            if he.code in (429, 500, 502, 503):
                sleep = backoff + random.random()
                print(f"[HF] retrying in {sleep:.1f}s", file=sys.stderr)
                time.sleep(sleep)
                backoff *= 2
                continue
            raise
        except error.URLError as ue:
            print(f"[HF][{attempt}] URLError: {ue}", file=sys.stderr)
            sleep = backoff + random.random()
            time.sleep(sleep)
            backoff *= 2
            continue

    raise RuntimeError("Max retries reached while calling Hugging Face router endpoint.")

# -------------------- GENERATION --------------------
def generate_for_language(language: str) -> Path:
    chapter_title = "Introduction"
    prompt = build_prompt(language, chapter_title)
    print(f"[GEN] Sending prompt for language='{language}' (len={len(prompt)})")
    content = hf_call(prompt, max_new_tokens=1200, temperature=0.2)

    lang_folder = OUTDIR / titlecase_lang(language)
    lang_folder.mkdir(parents=True, exist_ok=True)
    out_path = lang_folder / f"{safe_filename(chapter_title)}.md"
    out_path.write_text(content, encoding="utf-8")

    print(f"[GEN] Saved -> {out_path}")
    return out_path

# -------------------- MAIN --------------------
def main() -> int:
    if PREVIEW_LANGUAGE:
        lang = PREVIEW_LANGUAGE
        print(f"[MAIN] PREVIEW_LANGUAGE = {lang}")
    else:
        lang = pick_next_language()
        print(f"[MAIN] next language = {lang}")

    if not lang:
        print("[MAIN] Nothing to generate.")
        return 0

    try:
        generate_for_language(lang)
        if not MOCK_MODE:
            append_completed(lang)
            print(f"[MAIN] marked completed: {lang}")
        else:
            print("[MAIN] MOCK_MODE = True (not marking completed)")
    except Exception as e:
        print(f"[MAIN] ERROR: {e}", file=sys.stderr)
        return 3

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
