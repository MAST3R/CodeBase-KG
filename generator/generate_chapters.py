#!/usr/bin/env python3
"""
generate_chapters.py

FINAL VERSION — Hugging Face ROUTER endpoint
- Works with new HF routing system
- NO external dependencies (urllib only)
- Text-generation JSON format ONLY
- MOCK_MODE supported
- Writes to output/<TitleCaseLanguage>/Introduction.md
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

cfg = yaml.safe_load(open(CONFIG_PATH, "r", encoding="utf-8"))

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
    return lang[:1].upper() + lang[1:] if lang else "Unknown"

def safe_filename(name: str) -> str:
    name = name.strip().replace(" ", "_")
    return "".join(c for c in name if c.isalnum() or c in "_-.")[:200]

def read_completed():
    if not COMPLETED_LOG.exists():
        return set()
    try:
        return set(x.strip() for x in COMPLETED_LOG.read_text().splitlines() if x.strip())
    except:
        return set()

def append_completed(lang: str):
    COMPLETED_LOG.write_text(
        (COMPLETED_LOG.read_text() if COMPLETED_LOG.exists() else "") + f"{lang}\n",
        encoding="utf-8"
    )

def pick_next_language():
    done = read_completed()
    for l in LANGUAGES:
        if l not in done:
            return l
    return None

# -------------------- PROMPT BUILDER --------------------
def build_prompt(language: str, chapter_title="Introduction") -> str:
    date_iso = datetime.utcnow().date().isoformat()

    frontmatter = (
        "---\n"
        f'title: "{chapter_title}"\n'
        f'language: "{language}"\n'
        f'date: "{date_iso}"\n'
        "---\n\n"
    )

    content = (
        f"# {chapter_title}\n\n"
        "Write a complete, production-ready Obsidian Markdown chapter.\n\n"
        "Rules:\n"
        "- Warm, analogy-rich, teen-friendly voice.\n"
        "- Include Spark & Byte dialogue.\n"
        "- Include Mermaid diagrams when useful.\n"
        "- Add code examples with explanations.\n"
        "- Include exercises with collapsible answers.\n"
        "- End with a recap.\n\n"
        "<!-- Begin chapter content -->\n\n"
    )

    return frontmatter + content

# -------------------- HF ROUTER CALL --------------------
de
