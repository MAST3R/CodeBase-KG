"""
generator/gemini_polish.py

Polish drafts using Google Gemini (Generative Language API) with safety caps.

Environment:
- GOOGLE_ACCESS_TOKEN (set by auth action or via env)
- GEMINI_MODEL (optional; default gemini-2.5-flash)
- BATCH_SIZE (k) default 1
- REQUESTS_PER_DAY_OVERRIDE (optional)
- GEMINI_RPD, GEMINI_RPM, GEMINI_TPM must be set in env or defaulted in workflow

Behavior:
- Find drafts in output/<lang>/drafts/*.md with meta/*.json
- Compute safe requests_per_day_effective (RPD_safe = RPD-1, etc)
- Batch drafts into groups of k and send up to requests_per_day_effective requests
- Write polished files to output/<lang>/final/<slug>.md
- Log errors to output/errors/
- Do not mark anything as 'completed' automatically; just write polished outputs.
"""

import os, sys, json, time, math, glob, re
from pathlib import Path
import requests

BASE = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE / "output"

# env inputs
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
GOOGLE_ACCESS_TOKEN = os.environ.get("GOOGLE_ACCESS_TOKEN")  # set by auth step
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "1"))
REQUESTS_PER_DAY_OVERRIDE = os.environ.get("REQUESTS_PER_DAY_OVERRIDE") or None

# Limits: pick up from env or defaults; the workflow sets these for you
GEMINI_RPD = int(os.environ.get("GEMINI_RPD", "20"))
GEMINI_RPM = int(os.environ.get("GEMINI_RPM", "5"))
GEMINI_TPM = int(os.environ.get("GEMINI_TPM", "250000"))

# safety -1 margin
RPD_safe = max(1, GEMINI_RPD - 1)
RPM_safe = max(1, GEMINI_RPM - 1)
TPM_safe = max(1, GEMINI_TPM - 1)

# helper
def slugify(s):
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "chap"

def read_pending_drafts():
    # find all meta jsons and pair with drafts
    metas = list((OUTPUT_DIR).glob("**/drafts/meta/*.json"))
    items = []
    for m in metas:
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
            lang = data.get("language")
            slug = data.get("slug")
            draft_path = m.parent.parent / f"{slug}.md"
            if draft_path.exists():
                items.append({
                    "lang": lang,
                    "slug": slug,
                    "draft": str(draft_path),
                    "estimated_tokens": int(data.get("estimated_tokens", 2000)),
                    "meta": str(m)
                })
        except Exception as e:
            print("[WARN] Bad meta:", m, e)
    # sort for deterministic processing
    return sorted(items, key=lambda x: (x["lang"], x["slug"]))

def batch_items(items, k):
    for i in range(0, len(items), k):
        yield items[i:i+k]

def build_polish_prompt(batch):
    # combine multiple drafts into one prompt for batch polish
    combined = []
    for item in batch:
        text = Path(item["draft"]).read_text(encoding="utf-8")
        combined.append(f"### DRAFT START ({item['lang']}/{item['slug']})\n{text}\n### DRAFT END\n")
    instructions = (
        "You are an expert editor. For each DRAFT block above, produce a polished, final Markdown chapter."
        " Keep chapter formatting, add Spark & Byte dialogue, Mermaid diagram placeholders if needed, exercises, examples, and a concise recap."
        " Output polished chapters in the same order as the drafts, separated by a clear marker: ===POLISHED=== between chapters."
    )
    return instructions + "\n\n" + "\n\n".join(combined)

def call_gemini(prompt, model, max_tokens=3000, temperature=0.65):
    if not GOOGLE_ACCESS_TOKEN:
        raise RuntimeError("GOOGLE_ACCESS_TOKEN missing in environment.")
    url = f"https://generativelanguage.googleapis.com/v1beta2/models/{model}:generateText"
    headers = {"Authorization": f"Bearer {GOOGLE_ACCESS_TOKEN}", "Content-Type": "application/json; charset=utf-8"}
    payload = {
        "prompt": {"text": prompt},
        "temperature": temperature,
        "maxOutputTokens": max_tokens
    }
    r = requests.post(url, headers=headers, json=payload, timeout=300)
    if r.status_code == 200:
        return r.json()
    else:
        # return full body for logging
        raise RuntimeError(f"Gemini API error {r.status_code}: {r.text}")

def extract_polished_texts(resp_json, expected_count):
    # Gemini returns text in resp_json['candidates'][0]['content'] or similar
    # We will try a few patterns
    texts = []
    # try modern shape
    if "candidates" in resp_json:
        for c in resp_json["candidates"]:
            # find text parts
            t = ""
            if isinstance(c.get("content"), dict):
                # search for 'text' fields inside content
                for part in c["content"].get("parts", []):
                    t += part.get("text", "")
            else:
                t = c.get("content", "")
            texts.append(t)
    # fallback: top-level output
    if not texts and "output" in resp_json:
        texts.append(str(resp_json["output"]))
    # If we couldn't split, attempt to split by our marker
    out = []
    joined = "\n".join([t for t in texts]) if texts else ""
    if "===POLISHED===" in joined:
        parts = joined.split("===POLISHED===")
        out = [p.strip() for p in parts if p.strip()]
    else:
        # try naive split by headings
        out = [joined.strip()]
    # ensure we have expected_count elements
    if len(out) < expected_count:
        # pad with the whole joined text for each missing item
        while len(out) < expected_count:
            out.append(joined.strip())
    return out[:expected_count]

def write_polished(batch, polished_texts):
    for item, text in zip(batch, polished_texts):
        out_dir = OUTPUT_DIR / item["lang"] / "final"
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"{item['slug']}.md"
        file_path.write_text(text, encoding="utf-8")
        print("[OK] Wrote polished:", file_path)

def log_error(item_batch, err):
    log_dir = OUTPUT_DIR / "errors"
    log_dir.mkdir(parents=True, exist_ok=True)
    fname = log_dir / f"gemini-error-{int(time.time())}.json"
    payload = {"error": str(err), "batch": item_batch}
    fname.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("[ERR] Logged error to", fname)

def estimate_tokens_for_batch(batch):
    return sum(int(it["estimated_tokens"]) for it in batch)

def compute_effective_daily_requests(k, t_avg):
    # tokens per request = k * t_avg
    tokens_per_request = k * t_avg
    max_req_per_min_by_tpm = TPM_safe // tokens_per_request if tokens_per_request>0 else RPM_safe
    max_req_per_min = min(RPM_safe, max_req_per_min_by_tpm)
    daily_capacity_via_minute = max_req_per_min * 60 * 24
    requests_per_day_effective = min(RPD_safe, daily_capacity_via_minute)
    return int(requests_per_day_effective)

def main():
    items = read_pending_drafts()
    if not items:
        print("[INFO] No drafts found to polish.")
        return 0

    # allow override from workflow
    if REQUESTS_PER_DAY_OVERRIDE:
        try:
            requests_per_day_effective = int(REQUESTS_PER_DAY_OVERRIDE)
        except:
            requests_per_day_effective = RPD_safe
    else:
        # estimate average t_avg from first few items
        sample = items[:10]
        t_avg = int(sum(i["estimated_tokens"] for i in sample)/len(sample)) if sample else 2000
        requests_per_day_effective = compute_effective_daily_requests(BATCH_SIZE, t_avg)

    print(f"[INFO] RPD_safe={RPD_safe} RPM_safe={RPM_safe} TPM_safe={TPM_safe}")
    print(f"[INFO] Batch size={BATCH_SIZE} requests/day effective={requests_per_day_effective}")

    # limit requests this run
    requests_allowed = max(1, int(requests_per_day_effective))
    batches = list(batch_items(items, BATCH_SIZE))
    sent = 0

    for batch in batches:
        if sent >= requests_allowed:
            print("[INFO] Reached today's allowed requests:", sent)
            break
        try:
            est_tokens = estimate_tokens_for_batch(batch)
            # respect per-request token guard: if too large, reduce batch to 1
            if est_tokens > (TPM_safe // max(1, RPM_safe)):
                print("[WARN] Batch tokens high:", est_tokens, "Reducing to single-item batch.")
                batch = [batch[0]]
            prompt = build_polish_prompt(batch)
            resp = call_gemini(prompt, GEMINI_MODEL, max_tokens=3000, temperature=0.65)
            polished_texts = extract_polished_texts(resp, len(batch))
            write_polished(batch, polished_texts)
            sent += 1
            # small sleep to avoid hitting RPM bursts
            time.sleep(1.0)
        except Exception as e:
            print("[ERR] Exception during polish:", e)
            log_error([b for b in batch], str(e))
            # stop further requests for today if quota-like error
            if "429" in str(e) or "quota" in str(e).lower():
                print("[WARN] Quota-like error encountered — stopping polish for today.")
                break
            # otherwise continue to next batch
            continue

    print(f"[DONE] Polishing run complete. Sent {sent} requests.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
