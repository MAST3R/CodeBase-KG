"""
generate_one_chapter.py

Generates ONE fully-featured chapter for a single language and saves it as:
  output/<Language>/chapters/<slugified-chapter-title>.md

Behavior:
- reads master prompt for system context
- builds a user prompt instructing a single chapter output following the project's chapter template:
    Spark & Byte dialogue, Concept, Deep dive, Examples, Line-by-line annotated code, Mermaid diagram, Exercises, Recap.
- honors workflow env overrides:
    FORCE_LANGUAGE (required)
    CHAPTER_TITLE (required)
    MODEL_OVERRIDE, TEMPERATURE_OVERRIDE, MAX_TOKENS_OVERRIDE (optional)
- writes file and exits with success or prints errors for debugging
"""

import os
import re
import json
from pathlib import Path
import sys
import time

# Optional OpenAI import - fail early if missing
try:
    import openai
except Exception as e:
    openai = None

BASE = Path(__file__).resolve().parent.parent
PROMPT_FILE = BASE / "generator" / "prompts" / "master_prompt.txt"
OUTPUT_DIR = BASE / "output"

# ENV inputs from workflow
LANG = os.environ.get("FORCE_LANGUAGE", "").strip()
CHAPTER_TITLE = os.environ.get("CHAPTER_TITLE", "").strip()
MODEL_OVERRIDE = os.environ.get("MODEL_OVERRIDE", "").strip() or None
TEMPERATURE_OVERRIDE = os.environ.get("TEMPERATURE_OVERRIDE", "").strip()
MAX_TOKENS_OVERRIDE = os.environ.get("MAX_TOKENS_OVERRIDE", "").strip()

# Helper: slugify
def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "chapter"

def read_master_prompt():
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return ""

def build_user_prompt(language: str, chapter_title: str) -> str:
    # Instruct the model to produce a single chapter only, follow chapter template.
    return (
        f"Produce a single chapter for the programming-language encyclopedia for '{language}'.\n\n"
        f"The chapter title is: \"{chapter_title}\".\n\n"
        "Constraints:\n"
        "- Output valid Markdown only.\n"
        "- Produce **one** chapter only (do not create multiple chapters or append an appendix).\n"
        "- Start the chapter with a short Spark & Byte dialogue (2-4 lines).\n"
        "- Include: Concept explanation, Deep dive, Multiple examples, At least one block with line-by-line annotated code,\n"
        "  a Mermaid diagram enclosed in <mermaid>...</mermaid>, an Exercises section, and a short Recap.\n"
        "- Use runnable examples where possible and label code blocks with language tags.\n"
        "- Avoid mentioning prompts, system messages, or AI instructions.\n"
        "- Keep output self-contained (no external links required).\n\n"
        "Format requirements:\n"
        "- First line must be a level-1 heading with the chapter title.\n"
        "- Save this single chapter as the entire response (no surrounding explanation).\n\n"
        "Now produce the chapter.\n"
    )

def pick_model_and_params(cfg_model=None):
    model = MODEL_OVERRIDE or cfg_model or "gpt-4o-mini"
    try:
        temp = float(TEMPERATURE_OVERRIDE) if TEMPERATURE_OVERRIDE else 0.7
    except:
        temp = 0.7
    try:
        max_t = int(MAX_TOKENS_OVERRIDE) if MAX_TOKENS_OVERRIDE else 3000
    except:
        max_t = 3000
    return model, temp, max_t

def call_openai(system_prompt: str, user_prompt: str, model: str, temperature: float, max_tokens: int) -> str:
    if openai is None:
        raise RuntimeError("openai package not installed in the Action runner.")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing in environment.")
    openai.api_key = key
    # Use ChatCompletion (older style) — matches generator/generate.py
    resp = openai.ChatCompletion.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp["choices"][0]["message"]["content"]

def save_chapter(language: str, chapter_title: str, text: str) -> Path:
    slug = slugify(chapter_title)
    path = OUTPUT_DIR / language / "chapters"
    path.mkdir(parents=True, exist_ok=True)
    file_path = path / f"{slug}.md"
    file_path.write_text(text, encoding="utf-8")
    return file_path

def main():
    if not LANG:
        print("[ERR] FORCE_LANGUAGE not provided. Aborting.")
        sys.exit(1)
    if not CHAPTER_TITLE:
        print("[ERR] CHAPTER_TITLE not provided. Aborting.")
        sys.exit(1)

    master = read_master_prompt()
    if not master:
        print("[WARN] master_prompt.txt missing or empty. The model will still generate but system context may be limited.")

    user_p = build_user_prompt(LANG, CHAPTER_TITLE)
    model, temp, max_t = pick_model_and_params()

    print(f"[INFO] Model={model} temp={temp} max_tokens={max_t}")
    print(f"[INFO] Requesting chapter: {LANG} / {CHAPTER_TITLE}")

    try:
        text = call_openai(master, user_p, model, temp, max_t)
    except Exception as e:
        print("[ERR] OpenAI call failed:", e)
        sys.exit(1)

    # Basic sanity check: ensure output contains a top-level heading
    if not text.strip().startswith("#"):
        print("[WARN] Output does not start with '#'. Prepending heading.")
        text = f"# {CHAPTER_TITLE}\n\n" + text

    out_path = save_chapter(LANG, CHAPTER_TITLE, text)
    print(f"[OK] Saved chapter to {out_path}")
    # done
    return 0

if __name__ == "__main__":
    main()
