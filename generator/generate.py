"""
generate.py
Main engine for the Programming Encyclopedia Generator.

Responsibilities:
1. Load the static language list (languages.txt).
2. Load completed_languages log.
3. Pick the next language(s) based on resume rules.
4. Load the master_prompt.txt.
5. Call the OpenAI model with correct system + user messages.
6. Write output/<Language>/book.md.
7. Append completed languages.
8. Handle errors safely.

This script must remain deterministic and side-effect minimal.
"""

import os
import sys
import time
from pathlib import Path

try:
    import openai
except ImportError:
    print("Missing dependencies. Install with: pip install openai pyyaml")
    raise

# -----------------------------------------------------------------------------------
# Paths and configuration
# -----------------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

LANG_FILE = BASE_DIR / "languages.txt"
COMPLETED = BASE_DIR / "completed_languages"
PROMPT_FILE = BASE_DIR / "generator" / "prompts" / "master_prompt.txt"
OUTPUT_DIR = BASE_DIR / "output"

# Small languages allowed to be grouped two-per-run
SMALL_LANGUAGES = {
    "Lua", "Nim", "Crystal", "Smalltalk", "Haxe",
    "Zig", "Racket"
}

MAX_SMALL_PER_RUN = 2

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
API_KEY = os.environ.get("OPENAI_API_KEY")

if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY environment variable not set.")

openai.api_key = API_KEY


# -----------------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------------

def read_list(path: Path):
    """ Reads a file, skipping empty lines and comments. """
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def write_output(lang: str, content: str):
    """ Writes output/<Language>/book.md """
    out_dir = OUTPUT_DIR / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / "book.md"
    file_path.write_text(content, encoding="utf-8")
    print(f"[OK] Wrote {file_path}")


def append_completed(lang: str):
    """ Appends generated language to completed_languages """
    with open(COMPLETED, "a", encoding="utf-8") as f:
        f.write(lang + "\n")


def pick_next(languages, completed):
    """
    Determine the next language(s) to generate.

    Rules:
    - If language ∈ SMALL_LANGUAGES, allow generating two in the same run.
    - Otherwise, generate exactly one.
    """
    for lang in languages:
        if lang in completed:
            continue

        if lang in SMALL_LANGUAGES:
            group = [lang]
            idx = languages.index(lang)
            # Try to add the next languages if they are also uncompleted
            if idx + 1 < len(languages) and languages[idx + 1] not in completed:
                group.append(languages[idx + 1])
            return group[:MAX_SMALL_PER_RUN]

        return [lang]

    return []


def build_messages(lang: str, master_prompt: str):
    """
    Build OpenAI messages strictly following the project spec.
    """
    system_msg = master_prompt

    user_msg = (
        f"Produce the complete encyclopedia for the language '{lang}'. "
        f"Output a single Obsidian-ready Markdown file named book.md. "
        f"No meta commentary, no prompt leakage, no explanations of internal rules."
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def generate_for_language(lang: str, master_prompt: str):
    """ Call OpenAI API and retrieve the generated book content """
    print(f"[GPT] Generating: {lang}")
    messages = build_messages(lang, master_prompt)

    response = openai.ChatCompletion.create(
        model=MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=6000
    )

    return response["choices"][0]["message"]["content"]


# -----------------------------------------------------------------------------------
# Main execution
# -----------------------------------------------------------------------------------

def main():
    languages = read_list(LANG_FILE)
    completed = set(read_list(COMPLETED))

    if not languages:
        print("languages.txt is empty. Cannot continue.")
        sys.exit(1)

    if PROMPT_FILE.exists():
        master_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    else:
        print("master_prompt.txt missing.")
        sys.exit(1)

    next_batch = pick_next(languages, completed)

    if not next_batch:
        print("[DONE] All languages completed.")
        return

    for lang in next_batch:
        try:
            text = generate_for_language(lang, master_prompt)
            write_output(lang, text)
            append_completed(lang)
            time.sleep(2)  # polite delay
        except Exception as e:
            print(f"[ERROR] Generation failed for {lang}: {e}")
            # Do not mark as completed
            continue


if __name__ == "__main__":
    main()
