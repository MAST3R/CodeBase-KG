"""
generator/groq_generate.py

Bulk draft generator using Groq API.

Behavior:
- If FORCE_LANGUAGE env var provided, generate for that language only.
- Otherwise iterate languages.txt.
- Writes drafts to output/<Language>/drafts/<slug>.md
- Writes metadata per draft with estimated token count to output/<Language>/drafts/meta/<slug>.json

Environment:
- GROQ_API_KEY (secret)
- FORCE_LANGUAGE (optional)
- PARALLELISM (optional int)
- GROQ_MODEL (optional)
"""

import os, sys, json, time, math, concurrent.futures, textwrap, re
from pathlib import Path
import requests

BASE = Path(__file__).resolve().parent.parent
LANG_FILE = BASE / "languages.txt"
PROMPT_FILE = BASE / "generator" / "prompts" / "master_prompt.txt"
OUTPUT_DIR = BASE / "output"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
FORCE_LANGUAGE = os.environ.get("FORCE_LANGUAGE", "").strip() or None
PARALLELISM = int(os.environ.get("PARALLELISM", "4"))
GROQ_MODEL = os.environ.get("GROQ_MODEL") or "mixtral-8x7b"

def slugify(s):
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "draft"

def read_master_prompt():
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return "You are an expert programming encyclopedia writer."

def read_languages():
    if not LANG_FILE.exists():
        return []
    return [ln.strip() for ln in LANG_FILE.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]

def estimate_tokens(text):
    # crude estimate: 1 token ≈ 0.75 words -> use words*1.3 as rough tokens OR use tiktoken if available
    words = len(text.split())
    return int(words * 1.3 + 100)  # some headroom

def call_groq(prompt, model, max_tokens=5000, temperature=0.7):
    url = "https://api.groq.ai/v1/generate"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    r = requests.post(url, headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    js = r.json()
    # adjust extraction depending on Groq response shape
    text = js.get("text") or js.get("output") or ""
    if not text:
        # attempt common shapes
        choices = js.get("choices")
        if choices:
            text = choices[0].get("text") or choices[0].get("output") or ""
    return text or ""

def make_draft_for_language(lang):
    master = read_master_prompt()
    user_prompt = (
        f"{master}\n\nProduce a detailed draft for the encyclopedia for language: {lang}.\n"
        "Include chapters, but output only a single representative chapter draft as Markdown titled 'DRAFT: Example Chapter'.\n"
        "This is a draft -- we will later polish and split.\n"
    )
    try:
        text = call_groq(user_prompt, GROQ_MODEL, max_tokens=5000, temperature=0.7)
    except Exception as e:
        print("[ERR] Groq call failed for", lang, e)
        text = f"# {lang} — Draft failed\n\nGroq call failed: {e}"
    slug = slugify(f"{lang}-example")
    out_dir = OUTPUT_DIR / lang / "drafts"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{slug}.md"
    md_path.write_text(text, encoding="utf-8")
    meta = {
        "language": lang,
        "slug": slug,
        "estimated_tokens": estimate_tokens(text),
        "model": GROQ_MODEL,
        "timestamp": int(time.time())
    }
    meta_dir = out_dir / "meta"
    meta_dir.mkdir(exist_ok=True, parents=True)
    (meta_dir / f"{slug}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("[OK] Wrote draft:", md_path)
    return md_path, meta

def main():
    langs = read_languages()
    if FORCE_LANGUAGE:
        langs = [FORCE_LANGUAGE]
    if not langs:
        print("[ERR] No languages found.")
        return 1
    # parallelize language drafts
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        futures = [ex.submit(make_draft_for_language, l) for l in langs]
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print("[ERR] draft task failed:", e)
    print("[DONE] Groq drafting finished.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
