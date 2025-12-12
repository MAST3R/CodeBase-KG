def call_model(prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> Dict[str, str]:
    """
    Robust HF caller: tries text_generation variants first, then falls back to conversational/chat.
    - If a provider error indicates text-generation is unsupported (e.g. Groq), fall back to chat.
    - If the error is auth/repo-not-found, re-raise immediately so you see the root cause.
    Returns: {"content": "<text>"}
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
            resp = None
            # ---------- Try text_generation (multiple signatures) ----------
            try:
                resp = client.text_generation(model=HF_MODEL, inputs=prompt, max_new_tokens=max_tokens, temperature=temperature, do_sample=False)
            except TypeError:
                # signature mismatch: try alternative param names / positional
                try:
                    resp = client.text_generation(model=HF_MODEL, prompt=prompt, max_new_tokens=max_tokens, temperature=temperature, do_sample=False)
                except TypeError:
                    try:
                        resp = client.text_generation(prompt, model=HF_MODEL, max_new_tokens=max_tokens)
                    except Exception as e_inner:
                        # we'll inspect this exception below and decide whether to fall back
                        err_inner = str(e_inner).lower()
                        # if the provider complains about task/conversational, set resp=None so we fall back
                        if "task" in err_inner and "conversational" in err_inner:
                            resp = None
                        else:
                            # keep the exception to be handled by outer except
                            raise
            except Exception as e_text:
                # Some providers raise non-TypeError exceptions when text-generation is the wrong task.
                msg = str(e_text).lower()
                # If provider explicitly says text-generation not supported, fall back to chat
                if "task" in msg and "conversational" in msg:
                    resp = None
                # If the error indicates auth/model not found, re-raise (fatal)
                elif any(tok in msg for tok in ("401", "repository not found", "not found", "invalid username", "permission")):
                    raise
                else:
                    # For other transient errors, let outer except handle retry/backoff
                    raise

            # ---------- If text_generation produced a response, continue to normalization ----------
            if resp is None:
                # ---------- Fallback: conversational/chat/generic generate ----------
                messages = [
                    {"role": "system", "content": "You are a concise, helpful programming teacher."},
                    {"role": "user", "content": prompt},
                ]
                tried = []
                # Try client.chat
                if hasattr(client, "chat"):
                    tried.append("chat")
                    try:
                        resp = client.chat(model=HF_MODEL, messages=messages, max_new_tokens=max_tokens)
                    except Exception:
                        resp = None
                # Try conversational
                if resp is None and hasattr(client, "conversational"):
                    tried.append("conversational")
                    try:
                        resp = client.conversational(model=HF_MODEL, inputs=prompt)
                    except Exception:
                        resp = None
                # Try generic generate
                if resp is None and hasattr(client, "generate"):
                    tried.append("generate")
                    try:
                        resp = client.generate(model=HF_MODEL, prompt=prompt, max_new_tokens=max_tokens)
                    except Exception:
                        resp = None

                if resp is None:
                    raise RuntimeError(f"No supported generation method succeeded. Tried chat methods: {tried}")

            # ---------- Normalize resp into text ----------
            text = ""

            if isinstance(resp, list) and len(resp) > 0:
                first = resp[0]
                if isinstance(first, dict):
                    text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                else:
                    text = str(first)

            elif isinstance(resp, dict):
                # chat-like: choices -> message -> content
                if "choices" in resp and isinstance(resp["choices"], list) and resp["choices"]:
                    choice = resp["choices"][0]
                    if isinstance(choice, dict):
                        msg = choice.get("message") or {}
                        if isinstance(msg, dict) and msg.get("content"):
                            text = msg.get("content")
                        else:
                            text = choice.get("text") or choice.get("generated_text") or str(choice)
                    else:
                        text = str(choice)
                elif "generated_text" in resp or "text" in resp or "content" in resp:
                    text = resp.get("generated_text") or resp.get("text") or resp.get("content") or str(resp)
                elif "results" in resp and isinstance(resp["results"], list) and resp["results"]:
                    first = resp["results"][0]
                    if isinstance(first, dict):
                        text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                    else:
                        text = str(first)
                else:
                    text = str(resp)

            elif hasattr(resp, "generated_text"):
                text = getattr(resp, "generated_text")

            elif hasattr(resp, "results"):
                try:
                    results = getattr(resp, "results")
                    if isinstance(results, list) and results:
                        first = results[0]
                        if isinstance(first, dict):
                            text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                        else:
                            text = str(first)
                    else:
                        text = str(resp)
                except Exception:
                    text = str(resp)
            else:
                text = str(resp)

            if not isinstance(text, str):
                text = str(text)

            return {"content": text}

        except Exception as e:
            err_str = str(e)
            # log full error for debugging
            print(f"[HF_CALL][attempt {attempt}/{MAX_RETRIES}] Exception: {err_str}", file=sys.stderr)
            lower = err_str.lower()

            # Fatal auth/model errors -> surface immediately
            if any(tok in lower for tok in ("401", "repository not found", "invalid username", "permission", "forbidden")):
                raise

            # Retry on rate/timeout/etc.
            if any(tok in lower for tok in ("rate", "limit", "429", "throttle", "retry", "quota")):
                sleep_time = backoff + random.random()
                print(f"[HF_CALL] Rate/limit hit, sleeping {sleep_time:.1f}s before retry...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue

            if any(tok in lower for tok in ("timeout", "connection", "temporarily unavailable", "503", "service unavailable")):
                sleep_time = backoff + random.random()
                print(f"[HF_CALL] Transient error; sleeping {sleep_time:.1f}s before retry...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue

            # Unhandled non-retryable: raise to propagate
            raise

    raise RuntimeError("Max retries reached while calling model")
