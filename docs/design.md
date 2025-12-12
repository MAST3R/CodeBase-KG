# Encyclopedia Generator — System Design Overview

This document explains the architecture of the multi-language encyclopedia generator and the reasoning behind each component.

---

## 🎯 Purpose

Create a fully automated, resumable, OpenAI-powered generator that:
- Produces one complete encyclopedia per programming language.
- Runs daily through GitHub Actions.
- Maintains progress automatically.
- Generates deeply structured, analogy-rich, diagram-supported Markdown books.
- Avoids prompt leakage and remains stable for 1–2 months of continuous operation.

---

## 🧱 High-Level Architecture

```
languages.txt
completed_languages
generator/
    generate.py
    prompts/
        master_prompt.txt
    utils/
        rate_limit.py
        logger.py
    mock_mode.py
output/
    <Language>/
        book.md
.github/
    workflows/
        generate.yml
```

Each component has one job and one job only.

---

## 🧠 Core Workflow

1. **Static Language List**  
   A deterministic list of ~60 languages.  
   Immutable for the entire duration of the project.

2. **Progress Tracking**  
   `completed_languages` is appended after each successful generation.  
   If a GitHub Action run is interrupted, the system resumes automatically next time.

3. **Selection Logic**  
   A single language is picked unless it belongs to the *SMALL_LANGUAGES* set,
   in which case two may be processed.

4. **Generation Pipeline**  
   `generate.py`:
   - Builds system message from master_prompt.txt  
   - Provides language name to the model  
   - Requests a full encyclopedia from the model  
   - Writes Markdown  
   - Appends progress log

5. **Automatic Publishing**  
   The GitHub Action:
   - Runs daily
   - Executes the generator
   - Commits only when changes exist

---

## 🧩 Prompt Architecture

- The **system prompt** (master_prompt.txt) defines:
  - Writing tone  
  - Structure rules  
  - Spark & Byte dialogues  
  - Mermaid diagram requirement  
  - Inverse linear tone shift  
  - Zero prompt leakage  
  - Dynamic chapter discovery  
  - Appendix rules  

- The **user message** specifies:
  - The language to generate  
  - Requirements for a single Obsidian-ready Markdown file  

This separation ensures predictability and prevents content drift.

---

## 🪄 Style Enforcement

The tone must shift gradually from:
- technical → warm, analogy-driven

Every chapter must follow the structured template:
- Dialogue  
- Explanation  
- Deep dive  
- Examples  
- Annotated code  
- One Mermaid diagram  
- Exercises  
- Recap  

This produces consistent books across all languages.

---

## 🔁 Resume & Stability Logic

### Why a progress log?
Because GitHub Actions may:
- timeout  
- rate-limit  
- hit transient errors  
- fail mid-run  

Appending after success ensures no duplication.

### Deterministic selection
The language order never changes, so:
- There is no race condition  
- No need for complex state machines  
- No reliance on timestamps  

---

## ☁️ Future Extensions (Frozen)

These features exist in the repo but remain inactive:
- rate-limit split mode  
- extended retry wrappers  
- mock mode activation  

They can be re-enabled without restructuring the project.

---

## 🧪 Testing

Mock mode provides a deterministic output:
- Allows CI to validate file structure  
- Does not use tokens  
- Does not require API keys  

---

## 🔐 Safety Rules Summary

- Never leak prompts.  
- Never mention models or system messages.  
- Always produce one Markdown file.  
- Never include internal instructions.  
- Maintain stylistic consistency.

---

End of design overview.
