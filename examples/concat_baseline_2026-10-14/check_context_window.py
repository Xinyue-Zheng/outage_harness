"""Find the context window that an OpenAI-compatible endpoint serves for a model.

Set these environment variables, then run the file:

    LLM_BASE_URL   the base URL your client uses, for example https://host/v1
    LLM_MODEL      the model name your client sends
    LLM_API_KEY    optional

Step 1 asks the endpoint for its model list and prints every field that
looks like a context length. It sends no prompt.

Step 2 runs only with --probe. It sends one request that is far too long,
with one output token, and prints the error message. Most servers answer
with the limit in that message. Use it only if step 1 shows nothing.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

CONTEXT_FIELD = re.compile(
    r"context|max_model_len|max_input|n_ctx|window", re.IGNORECASE
)
LIMIT_IN_MESSAGE = re.compile(r"(\d{4,7})\s*tokens")
PROBE_WORDS = 1_000_000
TIMEOUT_SECONDS = 120


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Set the environment variable {name}.")
    return value


def call(url: str, payload: dict[str, object] | None) -> tuple[int, str]:
    """Send a GET, or a POST when a payload is given. Return the status and the body text."""
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("LLM_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def context_fields(value: object, path: str = "") -> list[tuple[str, object]]:
    """Every (path, value) in a JSON value whose key looks like a context length."""
    found: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            if CONTEXT_FIELD.search(str(key)) and not isinstance(item, dict | list):
                found.append((here, item))
            found.extend(context_fields(item, here))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(context_fields(item, f"{path}[{index}]"))
    return found


def list_models(base_url: str, model: str) -> None:
    status, body = call(f"{base_url}/models", None)
    print(f"GET {base_url}/models -> HTTP {status}")
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError:
        print(body[:500])
        return
    entries = parsed.get("data", []) if isinstance(parsed, dict) else []
    if not isinstance(entries, list):
        entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        marker = "  <- your model" if entry.get("id") == model else ""
        print(f"model: {entry.get('id')}{marker}")
        for path, value in context_fields(entry):
            print(f"    {path} = {value}")
    if not entries:
        print("The answer has no model list. First 500 characters:")
        print(body[:500])


def probe(base_url: str, model: str) -> None:
    payload: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": "a " * PROBE_WORDS}],
        "max_tokens": 1,
    }
    status, body = call(f"{base_url}/chat/completions", payload)
    print(
        f"POST {base_url}/chat/completions with about {PROBE_WORDS} tokens -> HTTP {status}"
    )
    print(body[:800])
    limits = sorted({int(number) for number in LIMIT_IN_MESSAGE.findall(body)})
    if status >= 400 and limits:
        print(f"Token counts named in the error: {limits}")
        print(
            "The context window is the limit the message names, usually the smaller number."
        )
    elif status < 400:
        print(
            "The endpoint accepted the request. It may cut long input without an error."
        )
        print("Ask the host of the model for the served context length.")


def main() -> None:
    base_url = required_env("LLM_BASE_URL").rstrip("/")
    model = required_env("LLM_MODEL")
    list_models(base_url, model)
    if "--probe" in sys.argv[1:]:
        print()
        probe(base_url, model)


if __name__ == "__main__":
    main()
