# Programming Encyclopedia Generator

This project automatically generates a full, Obsidian-ready programming encyclopedia for ~60 languages.  
Each GitHub Actions run processes exactly one language (or two for smaller ones), saves progress, and resumes automatically until all languages are complete.

---

## 📌 How It Works

1. `languages.txt` defines a static ordered list of ~60 languages.
2. `completed_languages` logs which languages are already generated.
3. `generator/generate.py`:
   - Reads the next unfinished language.
   - Applies the master prompt.
   - Calls the OpenAI API.
   - Saves `output/<Language>/book.md`.
   - Appends the language to `completed_languages`.
4. GitHub Actions runs this script daily.

---

## 🚀 Local Development

### 1. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate
```

### 2. Install dependencies
```bash
pip install openai pyyaml
```

### 3. Set your API key
```bash
export OPENAI_API_KEY="sk-..."
```

### 4. Run the generator manually
```bash
python generator/generate.py
```

---

## 🧩 GitHub Actions

The workflow file is located at:

```
.github/workflows/generate.yml
```

It:
- Runs daily at 02:00 UTC
- Installs dependencies
- Executes the generator
- Commits newly generated content

Add `OPENAI_API_KEY` to your repository secrets before enabling the workflow.

---

## 📂 Project Structure

```
repo-root/
│-- languages.txt
│-- completed_languages
│-- README.md
│-- .github/workflows/generate.yml
│-- generator/
│     ├── generate.py
│     ├── prompts/
│     │       └── master_prompt.txt
│     └── utils/ (optional extensions)
│-- output/
      └── <Language>/
            └── book.md
```

---

## 🔒 Important Notes

- Never reorder `languages.txt` once generation begins.
- Obsidian-ready Markdown only. No internal prompt leakage allowed.
- The generator restarts reliably even after API errors or partial runs.

---

## 📘 Goal

By the end of the run cycle (1–2 months), the repository will contain:
```
output/
   Python/book.md
   JavaScript/book.md
   ...
   Zig/book.md
   Makefile/book.md
```

Each a complete, deeply explained, analogy-rich, diagram-equipped programming encyclopedia chapter collection.
