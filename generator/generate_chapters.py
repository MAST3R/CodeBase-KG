def call_model(prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> dict:
    """
    Robust HF call wrapper that supports both 'text_generation' and
    conversational/chat providers. Returns {'content': <string>}.
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
            # 1) Try text_generation variants (existing behavior)
            try:
                resp = client.text_generation(
                    model=HF_MODEL,
                    inputs=prompt,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=False,
                )
            except TypeError:
                try:
                    resp = client.text_generation(
                        model=HF_MODEL,
                        prompt=prompt,
                        max_new_tokens=max_tokens,
                        temperature=temperature,
                        do_sample=False,
                    )
                except TypeError:
                    try:
                        resp = client.text_generation(prompt, model=HF_MODEL, max_new_tokens=max_tokens)
                    except Exception:
                        resp = None
            except Exception as e:
                # If provider rejects 'text-generation' as a task, capture and fall through.
                err_msg = str(e).lower()
                # common wording contains 'task' and 'conversational' for groq
                if "task" in err_msg and "conversational" in err_msg:
                    # fall through to chat call below
                    resp = None
                else:
                    # re-raise other exceptions to be handled by outer except
                    raise

            # 2) If text_generation didn't return usable resp, try conversational/chat APIs
            if resp is None:
                # Prepare chat messages (system optional, user contains prompt)
                messages = [
                    {"role": "system", "content": "You are a concise, helpful programming teacher."},
                    {"role": "user", "content": prompt},
                ]

                # Try common chat entrypoints in order
                chat_tried = []
                if hasattr(client, "chat"):
                    try:
                        chat_tried.append("chat")
                        resp = client.chat(model=HF_MODEL, messages=messages, max_new_tokens=max_tokens)
                    except Exception:
                        resp = None
                if resp is None and hasattr(client, "conversational"):
                    try:
                        chat_tried.append("conversational")
                        # some versions expect a Conversation object; pass simple inputs where supported
                        resp = client.conversational(model=HF_MODEL, inputs=prompt)
                    except Exception:
                        resp = None
                if resp is None and hasattr(client, "generate"):
                    try:
                        chat_tried.append("generate")
                        resp = client.generate(model=HF_MODEL, prompt=prompt, max_new_tokens=max_tokens)
                    except Exception:
                        resp = None

                if resp is None:
                    # No supported chat/text method returned a response; raise so outer retry logic can handle.
                    raise RuntimeError(f"No supported generation method succeeded. Tried: {chat_tried}")

            # Normalize response into text string
            text = ""

            # Common shapes:
            # - list of dicts: [{'generated_text': '...'}]
            # - dict with 'generated_text' or 'text'
            # - object with .generated_text or .results
            # - chat style: {'choices':[{'message':{'content':'...'}}]} or similar

            if isinstance(resp, list) and len(resp) > 0:
                first = resp[0]
                if isinstance(first, dict):
                    text = first.get("generated_text") or first.get("text") or first.get("content") or str(first)
                else:
                    text = str(first)

            elif isinstance(resp, dict):
                # HF chat-like: choices -> message -> content
                if "choices" in resp and isinstance(resp["choices"], list) and len(resp["choices"]) > 0:
                    choice = resp["choices"][0]
                    # try nested message/content
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
                elif "results" in resp and isinstance(resp["results"], list) and len(resp["results"]) > 0:
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
                    if isinstance(results, list) and len(results) > 0:
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
            print(f"[HF_CALL][attempt {attempt}/{MAX_RETRIES}] Exception: {err_str}", file=sys.stderr)
            msg = err_str.lower()

            # Retry heuristics
            if any(tok in msg for tok in ("rate", "limit", "429", "throttle", "retry", "quota")):
                sleep_time = backoff + random.random()
                print(f"[HF_CALL] Rate/limit hit, sleeping {sleep_time:.1f}s...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue

            if any(tok in msg for tok in ("timeout", "connection", "temporarily unavailable", "503", "service unavailable")):
                sleep_time = backoff + random.random()
                print(f"[HF_CALL] Transient error, sleeping {sleep_time:.1f}s...", file=sys.stderr)
                time.sleep(sleep_time)
                backoff *= 2
                continue

            # Non-retryable
            raise

    raise RuntimeError("Max retries reached while calling model")
