"""
generate_one_chapter.py (compatible with openai v0.x and v1.x+)

This script:
- Reads env inputs (FORCE_LANGUAGE, CHAPTER_TITLE, MODEL_OVERRIDE, TEMPERATURE_OVERRIDE, MAX_TOKENS_OVERRIDE)
- Loads master_prompt.txt as the system message if present
- Calls OpenAI using the new client API when available (openai.OpenAI) or falls back to legacy ChatCompletion
- Saves the resulting chapter to output/<Language>/chapters/<slug>.md
- Prints clear logs for debugging in Actions
"""

import os
import re
import sys
from pathlib import Path

# Try importing openai; if missing, we'll error clearly
try:
    import openai
except Exception:
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

def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "chapter"

def read_master_prompt():
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return ""

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

def write_chapter_file(language: str, chapter_title: str, text: str) -> Path:
    slug = slugify(chapter_title)
    path = OUTPUT_DIR / language / "chapters"
    path.mkdir(parents=True, exist_ok=True)
    file_path = path / f"{slug}.md"
    file_path.write_text(text, encoding="utf-8")
    return file_path

def build_messages(system_prompt: str, user_prompt: str):
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

def build_user_prompt(language: str, chapter_title: str) -> str:
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
        "Now produce the chapter."
    )

def call_openai_new_api(system_prompt: str, user_prompt: str, model: str, temperature: float, max_tokens: int) -> str:
    """
    Uses the new openai.OpenAI client (openai>=1.0.0)
    Example usage:
        client = openai.OpenAI(api_key=...)
        response = client.chat.completions.create(model=..., messages=..., temperature=..., max_tokens=...)
    """
    print("[INFO] Using new OpenAI client API (openai>=1.0.0)")

    # Create client instance - some installs expose OpenAI as a class
    # If openai.OpenAI exists, use it. Otherwise if openai has attribute 'OpenAI' or 'OpenAI' callable, try to instantiate.
    client = None
    try:
        if hasattr(openai, "OpenAI"):
            client = openai.OpenAI()
        elif callable(getattr(openai, "OpenAI", None)):
            client = openai.OpenAI()
        else:
            # Some environments require constructing with api_key explicitly
            api_key = os.environ.get("OPENAI_API_KEY")
            client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()
    except Exception as e:
        raise RuntimeError(f"Failed to construct OpenAI client: {e}")

    messages = build_messages(system_prompt, user_prompt)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )

    # Response shape: resp.choices[0].message.content or resp.choices[0].message['content']
    try:
        content = resp.choices[0].message.content
    except Exception:
        # fallback to dict-like access
        try:
            content = resp["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Unexpected response shape from new OpenAI API: {e}")
    return content

def call_openai_legacy(system_prompt: str, user_prompt: str, model: str, temperature: float, max_tokens: int) -> str:
    """
    Uses legacy openai.ChatCompletion.create(...) (openai<1.0)
    """
    print("[INFO] Using legacy openai.ChatCompletion API (openai<1.0)")
    resp = openai.ChatCompletion.create(
        model=model,
        messages=build_messages(system_prompt, user_prompt),
        temperature=temperature,
        max_tokens=max_tokens
    )
    # legacy shape: resp['choices'][0]['message']['content']
    try:
        return resp["choices"][0]["message"]["content"]
    except Exception:
        # attempt object attribute access
        try:
            return resp.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"Unexpected response shape from legacy OpenAI API: {e}")

def call_openai_auto(system_prompt: str, user_prompt: str, model: str, temperature: float, max_tokens: int) -> str:
    """
    Picks the right call depending on installed openai library.
    """
    if openai is None:
        raise RuntimeError("openai package is not installed in the environment.")
    # Prefer new API if available
    if hasattr(openai, "OpenAI"):
        return call_openai_new_api(system_prompt, user_prompt, model, temperature, max_tokens)
    # else, fall back to legacy ChatCompletion if available
    if hasattr(openai, "ChatCompletion"):
        return call_openai_legacy(system_prompt, user_prompt, model, temperature, max_tokens)
    # nothing matched
    raise RuntimeError("OpenAI library installed but no compatible API entry points were found (neither OpenAI nor ChatCompletion were available).")

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

    user_prompt = build_user_prompt(LANG, CHAPTER_TITLE)
    model, temp, max_t = pick_model_and_params()

    print(f"[INFO] Model={model} temp={temp} max_tokens={max_t}")
    print(f"[INFO] Requesting chapter: {LANG} / {CHAPTER_TITLE}")

    try:
        text = call_openai_auto(master, user_prompt, model, temp, max_t)
    except Exception as e:
        print("[ERR] OpenAI call failed:", e)
        # Show hint for migration
        print("\n[HINT] If you're using openai>=1.0.0, ensure the runner has network access and OPENAI_API_KEY set in secrets.")
        print("[HINT] This script supports both legacy and new API shapes; if error persists, paste the full error here.")
        sys.exit(1)

    # Basic sanity check: ensure output contains a top-level heading
    if not text.strip().startswith("#"):
        text = f"# {CHAPTER_TITLE}\n\n" + text

    out_path = write_chapter_file(LANG, CHAPTER_TITLE, text)
    print(f"[OK] Saved chapter to {out_path}")
    return 0

if __name__ == "__main__":
    main()
