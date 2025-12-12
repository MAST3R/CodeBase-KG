"""
generate.py

Generator entrypoint that supports:
- Workflow UI inputs via env:
    * MOCK_MODE (true/false)
    * FORCE_LANGUAGE (language name or empty)
- Fallback to generator/config.yaml for defaults
- Mock-mode using generator.mock_mode.generate_mock_book
- Real generation via OpenAI ChatCompletion when not mocking

Behavior:
- If FORCE_LANGUAGE is provided (non-empty), generate only that language.
- Otherwise pick the next language from languages.txt not present in completed_languages.
- Honors SMALL_LANGUAGES grouping (allow two in one run).
- Writes output/<Language>/book.md and appends completed_languages.
"""

from pathlib import Path
import os
import sys
import time
import json

# Optional imports
try:
    import yaml
except Exception:
    yaml = None

try:
    import openai
except Exception:
    openai = None

BASE_DIR = Path(__file__).resolve().parent.parent

LANG_FILE = BASE_DIR / "languages.txt"
COMPLETED_FILE = BASE_DIR / "completed_languages"
PROMPT_FILE = BASE_DIR / "generator" / "prompts" / "master_prompt.txt"
CONFIG_FILE = BASE_DIR / "generator" / "config.yaml"
OUTPUT_DIR = BASE_DIR / "output"

# Default behavior
SMALL_LANGUAGES = {"Lua", "Nim", "Crystal", "Smalltalk", "Haxe", "Zig", "Racket"}
MAX_SMALL_PER_RUN = 2

# Environment-driven UI inputs (from workflow_dispatch)
ENV_MOCK = os.environ.get("MOCK_MODE", "").strip().lower()
ENV_FORCE_LANG = os.environ.get("FORCE_LANGUAGE", "").strip()

# Normalize mock flag
def env_true(v: str) -> bool:
    return bool(v) and v.lower() in ("1", "true", "yes", "on")

FORCE_LANGUAGE = ENV_FORCE_LANG or None
MOCK_FROM_ENV = env_true(ENV_MOCK)

# OpenAI model env override (optional)
MODEL_ENV = os.environ.get("OPENAI_MODEL")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
if OPENAI_KEY and openai:
    openai.api_key = OPENAI_KEY

# ---------------- helpers ----------------

def log(*parts):
    print("[GEN]", *parts)

def read_list(path: Path):
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]

def write_output(lang: str, content: str):
    out_dir = OUTPUT_DIR / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / "book.md"
    file_path.write_text(content, encoding="utf-8")
    log(f"Wrote {file_path}")

def append_completed(lang: str):
    COMPLETED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COMPLETED_FILE, "a", encoding="utf-8") as f:
        f.write(lang + "\n")
    log(f"Appended {lang} to {COMPLETED_FILE}")

def pick_next(languages, completed):
    for i, lang in enumerate(languages):
        if lang in completed:
            continue
        if lang in SMALL_LANGUAGES:
            group = [lang]
            if i + 1 < len(languages) and languages[i+1] not in completed:
                group.append(languages[i+1])
            return group[:MAX_SMALL_PER_RUN]
        return [lang]
    return []

def load_config():
    cfg = {}
    if CONFIG_FILE.exists() and yaml:
        try:
            cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
            log("Loaded config.yaml")
        except Exception as e:
            log("Warning: failed to parse config.yaml:", e)
    else:
        if CONFIG_FILE.exists() and not yaml:
            log("Warning: config.yaml exists but pyyaml is not installed. Using defaults.")
        else:
            log("No config.yaml found. Using defaults.")
    return cfg

# ---------------- generation ----------------

def build_messages(lang: str, master_prompt: str):
    system_msg = master_prompt
    user_msg = (
        f"Produce the complete encyclopedia for the language '{lang}'. "
        "Output a single Obsidian-ready Markdown file named book.md. "
        "No meta commentary, no prompt leakage."
    )
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

def generate_via_openai(lang: str, master_prompt: str, cfg: dict):
    if openai is None:
        raise RuntimeError("OpenAI package is not installed in this environment.")
    model = cfg.get("model") or MODEL_ENV or "gpt-4o-mini"
    temp = cfg.get("temperature", 0.7)
    max_t = cfg.get("max_tokens", 6000)
    log(f"Requesting model={model} temp={temp} max_tokens={max_t} for {lang}")
    messages = build_messages(lang, master_prompt)
    resp = openai.ChatCompletion.create(
        model=model,
        messages=messages,
        temperature=temp,
        max_tokens=max_t,
    )
    text = resp["choices"][0]["message"]["content"]
    return text

def generate_mock(lang: str, cfg: dict):
    # If config provides a sample path, pass it
    sample_path = None
    try:
        mock_cfg = cfg.get("mock_mode", {}) if cfg else {}
        if mock_cfg and isinstance(mock_cfg, dict):
            sp = mock_cfg.get("sample_output_path") or mock_cfg.get("sample_output", None)
            if sp:
                sample_path = str((BASE_DIR / sp).resolve())
    except Exception:
        sample_path = None

    try:
        from generator.mock_mode import generate_mock_book
    except Exception as e:
        raise RuntimeError(f"mock_mode module not available: {e}")
    log(f"Generating mock book for {lang} (sample_path={sample_path})")
    return generate_mock_book(lang, sample_path)

def generate_for_language(lang: str, master_prompt: str, cfg: dict, mock_override: bool = False):
    # Decide mock mode precedence:
    # 1. MOCK_FROM_ENV (workflow input)
    # 2. mock_override param (if passed)
    # 3. config.yaml mock_mode.enabled
    mock_cfg = cfg.get("mock_mode", {}) if cfg else {}
    cfg_mock_enabled = bool(mock_cfg.get("enabled")) if isinstance(mock_cfg, dict) else False
    use_mock = MOCK_FROM_ENV or mock_override or cfg_mock_enabled

    if use_mock:
        return generate_mock(lang, cfg)
    else:
        return generate_via_openai(lang, master_prompt, cfg)

# ---------------- main ----------------

def main():
    log("Starting generator")
    cfg = load_config()

    # Resolve force language from env or config fallback (we prefer env)
    force_lang = FORCE_LANGUAGE
    if not force_lang and cfg:
        # legacy: allow config to set a default forced language under generator.force_language
        force_lang = cfg.get("force_language") or None

    languages = read_list(LANG_FILE)
    completed = set(read_list(COMPLETED_FILE))

    if not languages:
        log("No languages found in languages.txt - exiting")
        sys.exit(0)

    if PROMPT_FILE.exists():
        master_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    else:
        log("master_prompt.txt not found - cannot proceed")
        sys.exit(1)

    # Build the list of languages to generate this run
    if force_lang:
        # Validate force_lang is in list; if not, still allow it (user override).
        batch = [force_lang]
        log(f"FORCE_LANGUAGE provided: {force_lang}")
    else:
        batch = pick_next(languages, completed)
        if not batch:
            log("All languages completed. Nothing to do.")
            return

    for lang in batch:
        try:
            log(f"Generating language: {lang}")
            content = generate_for_language(lang, master_prompt, cfg, mock_override=False)
            write_output(lang, content)
            append_completed(lang)
            # small polite pause
            time.sleep(1)
        except Exception as e:
            log(f"Error while generating {lang}:", e)
            # don't mark as completed on failure
            continue

    log("Generation run finished")

if __name__ == "__main__":
    main()
