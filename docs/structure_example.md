# Example Book Structure (Reference Only)

This file shows the expected *shape* of a generated encyclopedia book.
It is NOT used by the generator itself and must not be included in output folders.

---

# Title of the Language Encyclopedia
Short, 1–3 sentence description of what the book covers.

---

## Core Chapter Template

### Spark & Byte Dialogue
Spark: “Byte, why does this chapter exist?”  
Byte: “To illuminate a corner of the language.”

### Concept Explanation
Clear introduction of the topic.

### Deep Dive
Detailed internal mechanics, theoretical notes, runtime behavior,
or compilation details depending on the language.

### Examples
```
# language-specific example
```

### Line-by-line Commentary
- Explain each line
- Highlight key syntax decisions
- Provide analogies when needed

### Mermaid Diagram
```
<mermaid>
flowchart TD
    A[Input] --> B[Parser]
    B --> C[Execution Model]
</mermaid>
```

### Exercises
- Build something
- Modify an example
- Diagnose deliberate errors

### Recap
Short closure summarizing the chapter.

---

## Appendix Template

### Syntax Quick Reference
List of the most used language constructs.

### Tooling & Ecosystem
Compiler/interpreter notes, package manager overview, testing tools.

### Debugging Tips
Common pitfalls, runtime messages, traps beginners fall into.

### FAQ
Short answers to practical questions without fluff.

---

## Rules Reminder (for developers)
- Chapters are discovered dynamically by the model.
- No numbering.
- No meta commentary.
- One Markdown file per language.

---

End of reference.
