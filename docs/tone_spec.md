# Tone Specification — Programming Encyclopedia Generator

This document defines the stylistic, tonal, and narrative rules that every
generated encyclopedia must follow.  
It exists for developers only.  
Generated books must never refer to this file or these rules.

---

# 1. Narrative Voice

The encyclopedia uses a **single clean narrator voice**:
- Warm, confident, intelligent.
- No artificial cheerfulness.
- No classroom clichés.
- Uses analogies when helpful, especially on deeper or abstract topics.

Tone starts out clear and technical, then gradually warms as chapters progress.

This progression is called the **Inverse Linear Tone Shift**.

---

# 2. Inverse Linear Tone Shift

As the book moves from beginner → intermediate → advanced concepts:

- The writing becomes slightly more conversational.
- Metaphors and analogies become more frequent.
- Explanations grow more story-like without losing rigor.
- Complexity increases but intimidation decreases.
- Byte becomes more encouraging.
- Spark becomes more insightful.

The shift must be smooth, not abrupt.

---

# 3. Spark & Byte

## Spark
- The curious learner.
- Asks clear, motivated questions.
- Not childish. Not comic-relief.
- Represents reader curiosity.

## Byte
- The experienced guide.
- Answers concisely with clarity and confidence.
- Encourages exploration.
- Provides conceptual framing.

### Dialogue Rules
- Every chapter begins with a short Spark↔Byte exchange.
- Never exceed 4–6 lines.
- Dialogue sets thematic tone for the chapter.
- Avoid jokes that feel like filler.

Example pattern:
```
Spark: “Why does this feature matter for real programs?”
Byte: “Because it shapes how your code behaves under pressure.”
```

---

# 4. Chapter Structure Reinforcement

Every chapter must include:

1. Spark–Byte opening dialogue
2. Concept explanation (plain language)
3. Deep dive, including internals
4. Examples with **annotated code**
5. **One Mermaid diagram**, topic-dependent
6. Exercises section with practical tasks
7. Recap summarizing the chapter

Chapters must be discovered by the model per language.  
No fixed list.  
No numbering.

---

# 5. Mermaid Diagram Rules

Diagrams must be enclosed:

```
<mermaid>
diagram here
</mermaid>
```

Types:
- flowcharts
- state diagrams
- process diagrams
- memory/heap references (abstracted)
- concurrency models
- module resolution flows

Avoid overcomplexity.  
Diagrams must illuminate rather than overwhelm.

---

# 6. Analogy Rules

Analogies should:
- Clarify abstract ideas.
- Be embedded naturally.
- Never break immersion.
- Avoid clichés.
- Avoid references to AI or models.

Good analogies:
- “Think of a module as a well-organized workshop.”
- “The type checker acts like a strict but fair editor.”

Bad analogies:
- Anything childish.
- Anything referencing machines writing the book.

---

# 7. Explanation Rules

Explanations must:
- Start with the practical.
- Transition into internals.
- Reinforce intuition before correctness.
- Avoid academic fluff.

Line-by-line code explanations must highlight:
- syntax roles
- flow
- hidden gotchas
- conceptual mapping

---

# 8. Exercises & Recaps

## Exercises:
- 3 to 6 tasks per chapter.
- Practical, not theoretical.
- Encourage modification, debugging, building, or extension.

## Recap:
- 3–5 sentences.
- Summarize insights, not just repeat content.
- Prepare the reader for the next topic.

---

# 9. Zero Prompt Leakage

Never produce:
- “As an AI…”
- “Based on instructions…”
- “This was generated using…”
- “System prompt says…”
- Or anything that breaks the illusion of a handcrafted book.

All books must read as if written by a single, coherent human author.

---

# 10. Final Notes

Tone must feel:
- confident but not arrogant
- warm but not casual
- insightful but not verbose

The reader should feel guided, not lectured.

---

End of tone specification.
