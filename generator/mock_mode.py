"""
mock_mode.py
Utility for running the encyclopedia generator without calling OpenAI.

When mock mode is enabled (via config.yaml), the generator should import
this module and use its `generate_mock_book()` to produce deterministic,
token-free output.

Note:
The main generator currently does not auto-import this. It’s included for
future activation when mock mode becomes part of the workflow again.
"""

from pathlib import Path


MOCK_HEADER = """# MOCK OUTPUT — Example Encyclopedia Chapter

This mock file is produced when mock_mode.enabled = true.

It simulates the structure of a real generated book without calling the API.
"""


def generate_mock_book(language: str, sample_path: str | None = None) -> str:
    """
    Generates a placeholder book.md used for dry runs.

    Parameters:
        language    : Language being “generated”
        sample_path : Optional path to a static mock template

    Returns:
        A deterministic Markdown string.
    """

    if sample_path and Path(sample_path).exists():
        return Path(sample_path).read_text(encoding="utf-8")

    # Minimal deterministic mock structure
    return f"""
# {language} — Mock Encyclopedia

This is a mock generation for **{language}**, used for local testing or CI.

## Introduction
Spark: “Byte, are we really generating a fake version of a full book?”
Byte: “Yes. A lightweight duplicate, but it shows the structure just fine.”

## Basic Concepts
Placeholder examples.

```
print("Mock mode active")
```

## Summary
This mock output allows the generator to run without an API key.
"""
