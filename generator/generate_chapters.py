def call_model(prompt, max_tokens=1500, temperature=0.2):
    """
    Robust HF call wrapper that tries a few different invocation signatures
    to support different huggingface_hub versions. Returns a dict with key 'content'.
    """
    if MOCK_MODE:
        content = (
            prompt
            + "\n\n# MOCK CHAPTER\n\nThis content was generated in MOCK_MODE for local testing.\n\n"
            "## Example\n\n```python\n# mock example\nprint('hello mock')\n```\n"
        )
        return {"content": content}

    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Try common calling styles in order of likelihood
            try:
                # older/newer variants sometimes accept 'inputs'
                resp = client.text_generation(
                    model=HF_MODEL,
                    inputs=prompt,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=False,
                )
            except TypeError:
                # fallback to 'prompt' param name
                try:
                    resp = client.text_generation(
                        model=HF_MODEL,
                        prompt=prompt,
                        max_new_tokens=max_tokens,
                        temperature=temperature,
                        do_sample=False,
                    )
                except TypeError:
                    # Some client versions expose a simple callable or slightly different name.
                    # Try a generic call without named param (positional)
                    resp = client.text_generation(prompt, model=HF_MODEL, max_new_tokens=max_tokens)

            # Normalize response objects to extract the generated text
            text = ""
            if isinstance(resp, list) and len(resp) > 0:
                # common shape: [{"generated_text": "..."}]
                first = resp[0]
                if isinstance(first, dict):
                    text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                else:
                    text = str(first)
            elif hasattr(resp, "generated_text"):
                text = getattr(resp, "generated_text")
            elif isinstance(resp, dict) and ("generated_text" in resp or "text" in resp):
                text = resp.get("generated_text") or resp.get("text") or str(resp)
            else:
                # Fallback to stringifying the response
                text = str(resp)

            return {"content": text}

        except Exception as e:
            msg = str(e).lower()
            # Rate limit / retryable heuristics
            if any(tok in msg for tok in ("rate", "limit", "429", "throttle", "retry")):
                sleep_time = backoff + random.random()
                print(f"Rate/limit hit (attempt {attempt}/{MAX_RETRIES}), sleeping {sleep_time:.1f}s...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue
            if any(tok in msg for tok in ("timeout", "connection", "temporarily unavailable", "503")):
                sleep_time = backoff + random.random()
                print(f"Transient error (attempt {attempt}/{MAX_RETRIES}): {msg[:120]}... sleeping {sleep_time:.1f}s", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue
            # Unrecoverable
            raise
    raise RuntimeError("Max retries reached while calling model")
