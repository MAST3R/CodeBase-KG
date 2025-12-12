import socket
from requests.exceptions import RequestException, ConnectionError, Timeout, HTTPError, SSLError

# --- Tunables (feel free to tweak) ---
MAX_RETRIES = 3                 # fewer retries to avoid long stalls
BASE_BACKOFF = 1.0              # smaller base backoff (seconds)
TOTAL_RETRY_TIMEOUT = 20.0      # total seconds allowed for retries per request
TIMEOUT = 15                    # request timeout seconds

def check_dns(host: str, quick_attempts: int = 2) -> bool:
    """
    Quick, small DNS check that tries socket.gethostbyname a couple times.
    Returns True if host resolves; False immediately on socket.gaierror.
    """
    for i in range(quick_attempts):
        try:
            socket.gethostbyname(host)
            logger.info("Resolved %s on attempt %d/%d", host, i+1, quick_attempts)
            return True
        except socket.gaierror as e:
            logger.debug("DNS attempt %d failed for %s: %s", i+1, host, e)
            # tiny sleep between quick attempts
            time.sleep(0.25)
        except Exception as e:
            logger.debug("Non-gai DNS check exception for %s: %s", host, e)
            break
    logger.warning("DNS resolution not available for %s after %d quick attempts", host, quick_attempts)
    return False

def post_with_retries(url: str, payload: Dict[str, Any], headers: Dict[str, str],
                      max_retries: int = MAX_RETRIES, timeout: int = TIMEOUT,
                      total_timeout: float = TOTAL_RETRY_TIMEOUT) -> Optional[requests.Response]:
    """
    POST with:
    - immediate fast-fail on name resolution (socket.gaierror)
    - limited total retry time so the job won't sleep for minutes
    """
    start_t = time.time()
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            logger.info("POST attempt %d/%d to %s", attempt, max_retries, url)
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            logger.info("HTTP %d received", resp.status_code)
            return resp
        except SSLError as e:
            logger.error("SSL error (not retriable): %s", e)
            logger.debug(traceback.format_exc())
            break
        except HTTPError as e:
            status = getattr(e.response, "status_code", None)
            logger.error("HTTP error status=%s: %s", status, e)
            logger.debug(traceback.format_exc())
            # Retry only on 5xx
            if status and 500 <= status < 600:
                pass
            else:
                break
        except (ConnectionError, Timeout, RequestException) as e:
            # look for underlying name resolution errors and fast-fail
            msg = str(e)
            logger.warning("Network/RequestException on attempt %d: %s", attempt, msg)
            logger.debug(traceback.format_exc())
            # detect name resolution errors quickly and abort retries for this host
            if isinstance(e, RequestException):
                # Some RequestException wrappers hide the underlying socket.gaierror,
                # so inspect the chained exceptions via __context__ or message.
                ctx = getattr(e, "__context__", None)
                if isinstance(ctx, socket.gaierror) or "Name or service not known" in msg or "getaddrinfo" in msg:
                    logger.error("Name resolution failure detected (fast-fail).")
                    return None
            # check elapsed total time
            elapsed = time.time() - start_t
            if elapsed >= total_timeout:
                logger.error("Total retry timeout %.1fs exceeded (elapsed %.1fs). Aborting.", total_timeout, elapsed)
                return None
            # compute backoff but ensure we don't overshoot total_timeout
            backoff = BASE_BACKOFF * (2 ** (attempt - 1))
            remaining = max(0.0, total_timeout - elapsed)
            sleep_time = min(backoff, remaining)
            logger.info("Sleeping %.2f seconds before next try (elapsed %.2f/%.2f).", sleep_time, elapsed, total_timeout)
            time.sleep(sleep_time)
            continue
        except Exception as e:
            logger.error("Unexpected exception during POST: %s", e)
            logger.debug(traceback.format_exc())
            break

    logger.error("All %d attempts exhausted (or aborted) for %s", max_retries, url)
    return None
