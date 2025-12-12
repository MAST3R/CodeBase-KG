"""
rate_limit.py
Lightweight helper for retrying API calls safely.

This module is INCLUDED in the project structure,
but the main generator currently does NOT import or use it
because rate-limit splitting is paused by user instruction.

When re-enabled, generate.py can wrap API calls with:
    rate_limit.safe_call(api_function)

"""

import time
import random


class RateLimitError(Exception):
    pass


def safe_call(fn, *, attempts=3, min_wait=1, max_wait=3):
    """
    Wrap an OpenAI API call with retry logic.

    Parameters:
        fn        : Callable that performs the API request
        attempts  : Maximum retry attempts
        min_wait  : Minimum wait time between retries
        max_wait  : Maximum wait time between retries

    Returns:
        The function output if successful.

    Raises:
        RateLimitError after exhausting attempts.
    """

    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_error = e
            wait_time = random.uniform(min_wait, max_wait)
            print(f"[RateLimit] Error on attempt {attempt}/{attempts}: {e}")
            print(f"[RateLimit] Waiting {wait_time:.2f}s before retry...")
            time.sleep(wait_time)

    raise RateLimitError(
        f"Failed after {attempts} attempts. Last error: {last_error}"
    )
