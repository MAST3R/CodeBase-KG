#!/usr/bin/env python3
"""
generate_chapters.py
One-call-per-chapter generator using Hugging Face InferenceClient.

Behavior:
- Uses generator/config.yaml for static language list and model name.
- One chapter per run (or preview_language if provided).
- MOCK_MODE: when true, produces synthetic content (no HF calls, no log append).
- Writes Markdown to output/<Language>/*.md
- Appends completed language to completed_languages.txt (unless MOCK_MODE).
- Retries with exponential backoff on rate-limit-like errors.

Env vars read:
- HF_API_TOKEN         (required for real runs)
- HF_MODEL             (optional; falls back to config.yaml model)
- PREVIEW_LANGUAGE     (optional; forces that language instead of picking next)
- MOCK_MODE            ("true"/"1"/"yes" toggles mock)
- MAX_RETRIES          (default 5)
- INITIAL_BACKOFF      (seconds, default 2.0)
- SAFETY_MARGIN        (unused directly but kept for parity with workflow)
- OUTDIR               (optional override; default ./output)
"""

import os
import sys
import time
import json
import random
import yaml
from pathlib import Path
from datetime import datetime

try:
    from huggingface_hub import InferenceClient
except Exception:
    InferenceClient = None  # we'll error later if needed

ROOT = Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generator"
CONFIG_PATH = GEN_DIR / "config.yaml"
OUTDIR = Path(os.environ.get("OUTDIR", str(ROOT / "output")))
COMPLETED_LOG = ROOT / "completed_languages.txt"

# Load config
if not CONFIG_PATH.exists():
    print(f"ERROR: Missing config file at {CONFIG_PATH}", file=sys.stderr)
    sys.exit(2)

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

MODEL_DEFAULT = cfg.get("model", "gpt-oss-20b")
LANGUAGES = cfg.get("languages", [])

# Env / settings
HF_TOKEN = os.environ.get("HF_API_TOKEN")
HF_MODEL = os.environ.get("HF_MODEL", MODEL_DEFAULT)
PREVIEW_LANGUAGE = os.environ.get("PREVIEW_LANGUAGE", "").strip() or None
MOCK_MODE = str(os.environ.get("MOCK_MODE", "false")).lower() in ("1", "true", "yes")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 5))
INITIAL_BACKOFF = float(os.environ.get("INITIAL_BACKOFF", 2.0))
SAFETY_MARGIN = int(os.environ.get("SAFETY_MARGIN", 1))

if not MOCK_MODE and not HF_TOKEN:
    print("ERROR: HF_API_TOKEN is required for non-mock runs.", file=sys.stderr)
    sys.exit(2)

# Initialize HF client only if needed
client = None
if not MOCK_MODE:
    if InferenceClient is None:
        raise RuntimeError("huggingface_hub not installed. pip install huggingface_hub")
    client = InferenceClient(token=HF_TOKEN)


def read_completed():
    if not COMPLETED_LOG.exists():
        return set()
    try:
        with COMPLETED_LOG.open("r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()


def append_completed(language):
    COMPLETED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with COMPLETED_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{language}\n")


def pick_next_language():
    completed = read_completed()
    for lang in LANGUAGES:
        if lang not in completed:
            return lang
    return None


def build_prompt_for_chapter(language, chapter_meta):
    """
    Construct the prompt for one chapter. This adheres to the user's desired style:
    - Warm, analogy-rich, teen-friendly (inverse tone shift)
    - Spark & Byte dialogues
    - Mermaid diagrams when helpful
    - Line-by-line code commentary, exercises, recap
    Output must be valid Markdown with a YAML frontmatter.
    """
    title = chapter_meta.get("title", "Introduction")
    date_iso = datetime.utcnow().date().isoformat()
    frontmatter = {
        "title": title,
        "language": language,
        "date": date_iso,
    }
    fm_yaml = "---\n" + "\n".join(f"{k}: \"{v}\"" for k, v in frontmatter.items()) + "\n---\n\n"
    guidance = (
        "Write a complete, production-ready Obsidian Markdown chapter. "
        "Style: warm, analogy-heavy, teen-friendly; include brief Spark & Byte dialogues, "
        "Mermaid diagrams where helpful, line-by-line code commentary for any code blocks, "
        "practical exercises with answers hidden in collapsible sections, and a short recap. "
        "Do NOT include any meta-text about prompts or 'as an AI'. Use idiomatic examples for the language. "
    )
    body = f"{fm_yaml}# {title}\n\n{guidance}\n\n<!-- Begin chapter content -->\n\n"
    return body


def call_model(prompt, max_tokens=1500, temperature=0.2):
    """
    Call HF InferenceClient with retries. Returns a dict with key 'content'.
    """
    if MOCK_MODE:
        # Synthetic minimal content for testing
        content = (
            prompt
            + "\n\n# MOCK CHAPTER\n\nThis content was generated in MOCK_MODE for local testing.\n\n"
            "## Example\n\n```python\n# mock example\nprint('hello mock')\n```\n"
        )
        return {"content": content}

    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Use text_generation endpoint (client API may vary by hub version)
            resp = client.text_generation(
                model=HF_MODEL,
                inputs=prompt,
                max_new_tokens=max_tokens,
                temperature=temperature,
                do_sample=False,
            )
            # Normalize response
            if isinstance(resp, list) and len(resp) > 0:
                text = resp[0].get("generated_text") or resp[0].get("text") or str(resp[0])
                return {"content": text}
            if hasattr(resp, "generated_text"):
                return {"content": resp.generated_text}
            # Fallback
            return {"content": str(resp)}
        except Exception as e:
            msg = str(e).lower()
            # Rate limit / retryable heuristics
            if any(tok in msg for tok in ("rate", "limit", "429", "throttle", "retry")):
                sleep_time = backoff + random.random()
                print(f"Rate/limit hit (attempt {attempt}/{MAX_RETRIES}), sleeping {sleep_time:.1f}s...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue
            # Other transient network errors (simple heuristic)
            if any(tok in msg for tok in ("timeout", "connection", "temporarily unavailable", "503")):
                sleep_time = backoff + random.random()
                print(f"Transient error (attempt {attempt}/{MAX_RETRIES}): {msg[:120]}... sleeping {sleep_time:.1f}s", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue
            # Unrecoverable
            raise
    raise RuntimeError("Max retries reached while calling model")


def safe_filename(s: str):
    s = s.strip().replace(" ", "_")
    keep = "".join(ch for ch in s if ch.isalnum() or ch in ("_", "-", "."))
    return keep[:200]


def save_markdown(language, chapter_title, content):
    safe_lang = safe_filename(language)
    dirpath = OUTDIR / safe_lang
    dirpath.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(chapter_title) + ".md"
    path = dirpath / filename
    path.write_text(content, encoding="utf-8")
    return path


def generate_for_language(language):
    chapter_meta = {"title": "Introduction", "notes": "Auto-generated one-chapter run (expand later)"}
    prompt = build_prompt_for_chapter(language, chapter_meta)
    resp = call_model(prompt)
    md = resp.get("content", "")
    # Ensure frontmatter exists; if liveresponse lacks, we still write what we have
    if not md.strip().startswith("---"):
        md = build_prompt_for_chapter(language, chapter_meta) + md
    path = save_markdown(language, chapter_meta["title"], md)
    return path


def main():
    if PREVIEW_LANGUAGE:
        lang = PREVIEW_LANGUAGE
    else:
        lang = pick_next_language()

    if not lang:
        print("All languages appear to be completed. Nothing to do.")
        return 0

    print(f"Starting generation for: {lang} (MOCK={MOCK_MODE})")
    try:
        outpath = generate_for_language(lang)
        print(f"Saved chapter to: {outpath}")
        if not MOCK_MODE:
            append_completed(lang)
            print(f"Appended '{lang}' to {COMPLETED_LOG}")
    except Exception as e:
        print(f"ERROR during generation: {e}", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
