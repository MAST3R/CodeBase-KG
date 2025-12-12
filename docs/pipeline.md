# Encyclopedia Generator — Pipeline Specification

This document describes the full operational pipeline used by the generator,
from GitHub Actions scheduling to final Markdown output.

It exists for developers and maintainers.  
The generator must never reference this file in output.

---

# 1. Overview

The pipeline consists of three layers:

**Layer 1 — GitHub Actions**
- Triggers once per day (or manually via workflow dispatch).
- Sets up Python, installs dependencies.
- Runs `generator/generate.py`.
- Commits output to `output/<Language>/book.md`.

**Layer 2 — Generator Core**
- Reads static language list.
- Reads progress log.
- Picks one or two next languages.
- Loads the master system prompt.
- Requests a full encyclopedia from the model.
- Writes Markdown.
- Appends to progress log.

**Layer 3 — Content Architecture**
- Spark & Byte framing.
- Dynamic chapter discovery.
- Mermaid diagrams.
- Inverse linear tone shift.
- Zero prompt leakage.

---

# 2. Triggering

## 2.1 Automatic
The workflow:
```
cron: "0 2 * * *"
```
runs daily.

GitHub guarantees eventual execution even with temporary outages.

## 2.2 Manual
Developers can trigger manually using:
```
Actions → Generate Encyclopedia → Run workflow
```

---

# 3. Language Selection Logic

```
languages.txt          # master ordered list
completed_languages    # append-only log
```

The generator performs:

1. Read both files.
2. Scan `languages.txt` top-to-bottom.
3. First language not inside `completed_languages` is the next.
4. If the language is in `SMALL_LANGUAGES`, attempt to process two.

This ensures:
- Deterministic progression.
- No duplication.
- Auto-resume after interruption.
- No reliance on timestamps or stateful artifacts.

---

# 4. Prompting Architecture

## 4.1 System Prompt
Loaded from:
```
generator/prompts/master_prompt.txt
```

Controls:
- Tone  
- Chapter structure  
- Mermaid usage  
- Code annotation  
- No meta commentary  
- Dynamic chapter listing  
- Output formatting

This is the “contract” for all generated content.

## 4.2 User Message
Injected automatically with:
- Target language name
- Instructions to produce a single Markdown file named `book.md`

---

# 5. Generation Call

The generator calls the model via:

```
openai.ChatCompletion.create(
    model=MODEL,
    messages=[system, user],
    temperature=0.7,
    max_tokens=6000
)
```

These are the only tunable generation settings stored in config.yaml.

---

# 6. Output Flow

For each language:

```
output/<Language>/book.md
```

Example:
```
output/Python/book.md
output/Rust/book.md
```

If directories do not exist, they are created automatically.

After a successful write:
```
completed_languages += "<Language>"
```

---

# 7. Error Behavior

If:
- the API call fails  
- output cannot be written  
- any exception occurs  

Then:
- The language is NOT appended to `completed_languages`.
- The pipeline halts gracefully.
- Next run retries the same language.

There is no catastrophic failure mode.

---

# 8. Mock Mode (Optional)

If enabled in `config.yaml`:
- OpenAI calls are skipped.
- A deterministic Markdown mock file is produced.
- Helpful for CI tests and offline debugging.

This mode is currently disabled per checkpoint.

---

# 9. Extensibility

The pipeline supports future upgrades:

- Rate-limit-aware segmented generation  
- Partial retries  
- Multi-pass refinement  
- Custom prompt hierarchy  
- Auxiliary tooling (e.g., syntax parsers, diagram generators)

These can be integrated without modifying the core logic.

---

# 10. Final Summary

This pipeline:

- Is deterministic  
- Is self-resuming  
- Avoids accidental duplication  
- Produces complete, high-quality books  
- Runs safely in daily CI  
- Contains no user-facing metadata or prompt leakage  

It is built to run unattended for 1–2 months until all languages are complete.

---

End of pipeline spec.
