#!/usr/bin/env python3
"""
generate_chapters.py

Full, self-contained generator for one chapter per run.

Features:
- Hybrid autodetect: probes provider capability and uses the appropriate call style.
- Supports text-generation and conversational/chat providers with robust fallbacks.
- MOCK_MODE for safe testing (no HF calls).
- Reads model and languages from generator/config.yaml.
- Writes Markdown to output/<LanguageTitleCase>/<ChapterTitle>.md
- Appends completed languages to completed_languages.txt (unless MOCK_MODE).
- Clear Action-friendly logging, retries, and safe commits-ready outputs.

Environment variables:
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
import random
import yaml
import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional, List, Set

# Optional imports for huggingface_hub
try:
    from huggingface_hub import InferenceClient, HfApi
except Exception:
    InferenceClient = None
    HfApi = None  # Metadata probe will skip if unavailable

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

if not MOCK_MODE and not HF_TOKEN:
    print("ERROR: HF_API_TOKEN is required for non-mock runs.", file=sys.stderr)
    sys.exit(2)

# ---------- HF CLIENT ----------
client = None
hf_api = None
if not MOCK_MODE:
    if InferenceClient is None:
        raise RuntimeError("huggingface_hub is not installed. Please pip install --upgrade huggingface_hub")
    try:
        client = InferenceClient(token=HF_TOKEN)
    except Exception as e:
        print(f"ERROR: Failed to initialize InferenceClient: {e}", file=sys.stderr)
        raise
    try:
        if HfApi is not None:
            hf_api = HfApi()
    except Exception:
        hf_api = None

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
    # Create Title Case folder (e.g., "python" -> "Python", "c++" -> "C++")
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
        "- Do NOT include any meta-text about prompts, 'as an AI', or internal tool details.\n"
        "- Output must be valid Markdown and suitable for Obsidian (YAML frontmatter + headings).\n\n"
    )
    footer = "\n\n<!-- Begin chapter content -->\n\n"
    prompt = f"{fm_yaml}# {title}\n\n{guidance}{footer}"
    return prompt

# ---------- PROVIDER PROBE (hybrid autodetect) ----------
def probe_provider_support(timeout_sec: int = 6) -> str:
    """
    Probe the model/provider to detect whether 'text-generation' or 'conversational' is supported.
    Returns one of: 'text-generation', 'conversational', or 'unknown'
    """
    # 1) Try model metadata via HfApi if available
    try:
        if hf_api is not None:
            info = hf_api.model_info(HF_MODEL, token=HF_TOKEN)
            pipeline_tag = getattr(info, "pipeline_tag", None)
            if pipeline_tag:
                pt = pipeline_tag.lower()
                if "text-generation" in pt or "text_generation" in pt or "textgen" in pt:
                    return "text-generation"
                if "conversational" in pt or "chat" in pt:
                    return "conversational"
    except Exception:
        # ignore metadata probe failures; we'll try runtime probe
        pass

    # 2) Runtime lightweight probe: attempt a very tiny text_generation call
    if client is None:
        return "unknown"
    try:
        # Use a tiny prompt and set a low timeout via the client if supported
        try:
            probe_resp = client.text_generation(model=HF_MODEL, inputs="Hello", max_new_tokens=1, temperature=0.0)
            # If we get a result, assume text-generation supported
            if probe_resp is not None:
                return "text-generation"
        except Exception as e:
            msg = str(e).lower()
            if "conversational" in msg or "task" in msg and "conversational" in msg:
                return "conversational"
            # provider-specific messages may vary; continue to chat probe
    except Exception:
        pass

    # 3) Try a tiny conversational call to see if that works
    try:
        if hasattr(client, "chat"):
            try:
                chat_resp = client.chat(model=HF_MODEL, messages=[{"role":"user","content":"hi"}], max_new_tokens=1)
                if chat_resp is not None:
                    return "conversational"
            except Exception:
                pass
        if hasattr(client, "conversational"):
            try:
                conv_resp = client.conversational(model=HF_MODEL, inputs="hi")
                if conv_resp is not None:
                    return "conversational"
            except Exception:
                pass
    except Exception:
        pass

    return "unknown"

# ---------- MODEL CALLER (hybrid autodetect + robust fallbacks) ----------
def call_model(prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> Dict[str, str]:
    """
    Hybrid caller: uses provider probe to choose the best API, with robust fallbacks.
    Returns {'content': <string>}.
    """
    if MOCK_MODE:
        content = (
            prompt
            + "\n\n# MOCK CHAPTER\n\nThis content was generated in MOCK_MODE for local testing.\n\n"
            "## Example\n\n```python\n# mock example\nprint('hello mock')\n```\n"
        )
        return {"content": content}

    # Probe what the provider supports (cached per run)
    provider_mode = probe_provider_support()
    print(f"[HF_CALL] Provider probe suggests: {provider_mode}")

    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = None

            # Decide primary method
            primary_try_text = provider_mode != "conversational"

            # First attempt: text-generation (if sensible)
            if primary_try_text:
                try:
                    resp = client.text_generation(model=HF_MODEL, inputs=prompt, max_new_tokens=max_tokens, temperature=temperature, do_sample=False)
                except TypeError:
                    # try alternate signature
                    try:
                        resp = client.text_generation(model=HF_MODEL, prompt=prompt, max_new_tokens=max_tokens, temperature=temperature, do_sample=False)
                    except Exception as e:
                        msg = str(e).lower()
                        if "conversational" in msg or "task" in msg and "conversational" in msg:
                            resp = None
                        else:
                            raise
                except Exception as e:
                    msg = str(e).lower()
                    if "conversational" in msg or ("task" in msg and "conversational" in msg):
                        resp = None
                    elif any(tok in msg for tok in ("401", "repository not found", "permission", "invalid username")):
                        raise
                    else:
                        raise

            # If text-generation not used or failed, try chat/conversational
            if resp is None:
                tried = []
                if hasattr(client, "chat"):
                    tried.append("chat")
                    try:
                        resp = client.chat(model=HF_MODEL, messages=[{"role":"system","content":"You are a concise, helpful teacher."},{"role":"user","content":prompt}], max_new_tokens=max_tokens)
                    except Exception:
                        resp = None
                if resp is None and hasattr(client, "conversational"):
                    tried.append("conversational")
                    try:
                        resp = client.conversational(model=HF_MODEL, inputs=prompt)
                    except Exception:
                        resp = None
                if resp is None and hasattr(client, "generate"):
                    tried.append("generate")
                    try:
                        resp = client.generate(model=HF_MODEL, prompt=prompt, max_new_tokens=max_tokens)
                    except Exception:
                        resp = None

                if resp is None:
                    raise RuntimeError(f"No supported generation method succeeded. Tried: {tried}")

            # Normalize
            text = ""
            if isinstance(resp, list) and resp:
                first = resp[0]
                if isinstance(first, dict):
                    text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                else:
                    text = str(first)
            elif isinstance(resp, dict):
                if "choices" in resp and isinstance(resp["choices"], list) and resp["choices"]:
                    choice = resp["choices"][0]
                    if isinstance(choice, dict):
                        msg = choice.get("message") or {}
                        if isinstance(msg, dict) and msg.get("content"):
                            text = msg.get("content")
                        else:
                            text = choice.get("text") or choice.get("generated_text") or str(choice)
                    else:
                        text = str(choice)
                elif "generated_text" in resp or "text" in resp or "content" in resp:
                    text = resp.get("generated_text") or resp.get("text") or resp.get("content") or str(resp)
                elif "results" in resp and isinstance(resp["results"], list) and resp["results"]:
                    first = resp["results"][0]
                    if isinstance(first, dict):
                        text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                    else:
                        text = str(first)
                else:
                    text = str(resp)
            elif hasattr(resp, "generated_text"):
                text = getattr(resp, "generated_text")
            elif hasattr(resp, "results"):
                try:
                    results = getattr(resp, "results")
                    if isinstance(results, list) and results:
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
            lower = err_str.lower()
            if any(tok in lower for tok in ("401", "repository not found", "invalid username", "permission", "forbidden")):
                raise
            if any(tok in lower for tok in ("rate", "limit", "429", "throttle", "retry", "quota")):
                sleep_time = backoff + random.random()
                print(f"[HF_CALL] Rate/limit hit, sleeping {sleep_time:.1f}s before retry...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue
            if any(tok in lower for tok in ("timeout", "connection", "temporarily unavailable", "503", "service unavailable")):
                sleep_time = backoff + random.random()
                print(f"[HF_CALL] Transient error; sleeping {sleep_time:.1f}s before retry...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue
            raise

    raise RuntimeError("Max retries reached while calling model")

# ---------- CORE GENERATION ----------
def generate_for_language(language: str) -> Path:
    chapter_meta = {"title": "Introduction", "notes": "Auto-generated one-chapter run"}
    prompt = build_prompt_for_chapter(language, chapter_meta)
    print(f"[GEN] Sending prompt for language='{language}' (prompt length {len(prompt)} chars)...")
    resp = call_model(prompt)
    md = resp.get("content", "")
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
