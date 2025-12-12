#!/usr/bin/env python3
"""
generate_chapters.py

One-call-per-chapter generator using Hugging Face InferenceClient.

Behavior summary:
- Uses generator/config.yaml for static language list and model name.
- One chapter per run (or PREVIEW_LANGUAGE if provided).
- MOCK_MODE: when true, produces synthetic content (no HF calls, no log append).
- Writes Markdown to output/<Language>/Introduction.md
- Appends completed language to completed_languages.txt (unless MOCK_MODE).
- Retries with exponential backoff on rate-limit-like errors.
- Robust handling of multiple huggingface_hub client signatures and response shapes.

Env vars:
- HF_API_TOKEN         (required for non-mock runs)
- HF_MODEL             (optional; falls back to config.yaml model)
- PREVIEW_LANGUAGE     (optional; forces that language instead of picking next)
- MOCK_MODE            ("true"/"1"/"yes" toggles mock)
- MAX_RETRIES          (default 5)
- INITIAL_BACKOFF      (seconds, default 2.0)
- OUTDIR               (optional override; default ./output)
"""

from __future__ import annotations

import os
import sys
import time
import json
import random
import yaml
from pathlib import Path
from datetime import datetime
from typing import Any, Dict

# Optional import for huggingface_hub InferenceClient
try:
    from huggingface_hub import InferenceClient
except Exception:
    InferenceClient = None  # will raise if used in non-mock mode

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

MODEL_DEFAULT = cfg.get("model", "gpt-oss-20b")
LANGUAGES = cfg.get("languages", [])

# ---------- ENV / FLAGS ----------
HF_TOKEN = os.environ.get("HF_API_TOKEN", "").strip()
HF_MODEL = os.environ.get("HF_MODEL", "").strip() or MODEL_DEFAULT
PREVIEW_LANGUAGE = os.environ.get("PREVIEW_LANGUAGE", "").strip() or None
MOCK_MODE = str(os.environ.get("MOCK_MODE", "false")).lower() in ("1", "true", "yes")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 5))
INITIAL_BACKOFF = float(os.environ.get("INITIAL_BACKOFF", 2.0))
SAFETY_MARGIN = int(os.environ.get("SAFETY_MARGIN", 1))

if not MOCK_MODE and not HF_TOKEN:
    print("ERROR: HF_API_TOKEN is required for non-mock runs.", file=sys.stderr)
    sys.exit(2)

# ---------- HF CLIENT ----------
client = None
if not MOCK_MODE:
    if InferenceClient is None:
        raise RuntimeError("huggingface_hub not installed. Please pip install --upgrade huggingface_hub")
    try:
        client = InferenceClient(token=HF_TOKEN)
    except Exception as e:
        print(f"ERROR: Failed to initialize InferenceClient: {e}", file=sys.stderr)
        raise

# ---------- UTIL FUNCTIONS ----------
def read_completed() -> set[str]:
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

def pick_next_language() -> str | None:
    completed = read_completed()
    for lang in LANGUAGES:
        if lang not in completed:
            return lang
    return None

def safe_filename(s: str) -> str:
    s = s.strip().replace(" ", "_")
    keep = "".join(ch for ch in s if ch.isalnum() or ch in ("_", "-", "."))
    return keep[:200]

def save_markdown(language: str, chapter_title: str, content: str) -> Path:
    safe_lang = safe_filename(language)
    dirpath = OUTDIR / safe_lang
    dirpath.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(chapter_title) + ".md"
    path = dirpath / filename
    path.write_text(content, encoding="utf-8")
    return path

# ---------- PROMPT BUILDER ----------
def build_prompt_for_chapter(language: str, chapter_meta: Dict[str, Any]) -> str:
    """
    Build the full plaintext prompt to send to the model.
    This contains the YAML frontmatter + guidance and constraints.
    """
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
        "- Do NOT include any meta-text about prompts, 'as an AI', or internal tool details.\n"
        "- Output must be valid Markdown and suitable for Obsidian (YAML frontmatter + headings).\n\n"
    )

    footer = "\n\n<!-- Begin chapter content -->\n\n"

    prompt = f"{fm_yaml}# {title}\n\n{guidance}{footer}"
    return prompt

# ---------- MODEL CALLER (robust) ----------
def call_model(prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> Dict[str, str]:
    """
    Robust HF call wrapper. Tries multiple invocation forms and normalizes responses.
    Returns {'content': <string>}.
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
            resp = None

            # Attempt 1: client.text_generation with 'inputs'
            try:
                resp = client.text_generation(
                    model=HF_MODEL,
                    inputs=prompt,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=False,
                )
            except TypeError:
                # Attempt 2: 'prompt' param
                try:
                    resp = client.text_generation(
                        model=HF_MODEL,
                        prompt=prompt,
                        max_new_tokens=max_tokens,
                        temperature=temperature,
                        do_sample=False,
                    )
                except TypeError:
                    # Attempt 3: positional call
                    try:
                        resp = client.text_generation(prompt, model=HF_MODEL, max_new_tokens=max_tokens)
                    except TypeError:
                        # Attempt 4: generic 'generate' if present
                        if hasattr(client, "generate"):
                            try:
                                resp = client.generate(model=HF_MODEL, prompt=prompt, max_new_tokens=max_tokens)
                            except Exception:
                                resp = None
                        else:
                            resp = None

            if resp is None:
                raise RuntimeError("No valid response from HF client invocation attempts")

            # Normalize response into text
            text = ""

            # Case A: list-of-dicts (common)
            if isinstance(resp, list) and len(resp) > 0:
                first = resp[0]
                if isinstance(first, dict):
                    text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                else:
                    text = str(first)

            # Case B: dict-like
            elif isinstance(resp, dict):
                # support {'generated_text': ...} or {'results':[...]}
                if "generated_text" in resp or "text" in resp or "content" in resp:
                    text = resp.get("generated_text") or resp.get("text") or resp.get("content") or str(resp)
                elif "results" in resp and isinstance(resp["results"], list) and len(resp["results"]) > 0:
                    first = resp["results"][0]
                    if isinstance(first, dict):
                        text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                    else:
                        text = str(first)
                else:
                    text = str(resp)

            # Case C: object attribute
            elif hasattr(resp, "generated_text"):
                text = getattr(resp, "generated_text")

            # Case D: object with 'results' attribute
            elif hasattr(resp, "results"):
                try:
                    results = getattr(resp, "results")
                    if isinstance(results, list) and len(results) > 0:
                        first = results[0]
                        if isinstance(first, dict):
                            text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                        else:
                            text = str(first)
                    else:
                        text = str(resp)
                except Exception:
                    text = str(resp)

            else:
                text = str(resp)

            if not isinstance(text, str):
                text = str(text)

            return {"content": text}

        except Exception as e:
            err_str = str(e)
            print(f"[HF_CALL][attempt {attempt}/{MAX_RETRIES}] Exception: {err_str}", file=sys.stderr)

            msg = err_str.lower()

            # Retryable heuristics
            if any(tok in msg for tok in ("rate", "limit", "429", "throttle", "retry", "quota")):
                sleep_time = backoff + random.random()
                print(f"[HF_CALL] Rate/limit hit, sleeping {sleep_time:.1f}s before retry...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue

            if any(tok in msg for tok in ("timeout", "connection", "temporarily unavailable", "503", "service unavailable")):
                sleep_time = backoff + random.random()
                print(f"[HF_CALL] Transient error; sleeping {sleep_time:.1f}s before retry...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue

            # Non-retryable error: re-raise after logging
            raise

    raise RuntimeError("Max retries reached while calling model")

# ---------- CORE GENERATION ----------
def generate_for_language(language: str) -> Path:
    """
    Generate one chapter for the given language and save it to disk.
    Returns the written Path.
    """
    chapter_meta = {"title": "Introduction", "notes": "Auto-generated one-chapter run (expand later)"}
    prompt = build_prompt_for_chapter(language, chapter_meta)

    print(f"[GEN] Sending prompt for language='{language}' (prompt length {len(prompt)} chars)...")

    resp = call_model(prompt)
    md = resp.get("content", "")

    # If the model didn't supply frontmatter, ensure file has frontmatter from builder
    if not md.strip().startswith("---"):
        md = prompt + md

    path = save_markdown(language, chapter_meta["title"], md)
    return path

# ---------- CLI / MAIN ----------
def main() -> int:
    # Decide language
    if PREVIEW_LANGUAGE:
        lang = PREVIEW_LANGUAGE
        print(f"[MAIN] PREVIEW_LANGUAGE override detected: {lang}")
    else:
        lang = pick_next_language()
        print(f"[MAIN] Picked next language: {lang}")

    if not lang:
        print("[MAIN] All languages appear to be completed. Nothing to do.")
        return 0

    try:
        outpath = generate_for_language(lang)
        print(f"[MAIN] Saved chapter to: {outpath}")
        if not MOCK_MODE:
            append_completed(lang)
            print(f"[MAIN] Appended '{lang}' to {COMPLETED_LOG}")
        else:
            print("[MAIN] MOCK_MODE is ON — not appending to completed log.")
    except Exception as e:
        print(f"[MAIN] ERROR during generation: {e}", file=sys.stderr)
        return 3

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
