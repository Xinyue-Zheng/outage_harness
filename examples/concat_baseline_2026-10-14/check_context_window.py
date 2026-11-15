"""Find the context window that the model endpoint serves.

Edit BASE_URL below, then run:

    python check_context_window.py            asks the server, sends no long prompt
    python check_context_window.py --probe    also sends one over-long prompt

`max_tokens` in the model client is the longest answer the model may write.
It is not the context window. The context window is the most the model can
read in one request, and only the server knows the value it was started with.

The script asks in three ways and prints what it finds:

1. The model list of the OpenAI-compatible API.
2. The native routes of an Ollama server, if the server is one. The model
   tag "name:size" suggests that it is.
3. With --probe: one request that is longer than the model can read, with
   one output token. A server either rejects it and names the limit, or cuts
   the input without an error. In the second case the token count that the
   server reports for the prompt is the size it really read.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE_URL = "http://serverid:number/v1"  # edit: the host of the model client
MODEL = "gpt-oss-safeguard:120b"

CONTEXT_FIELD = re.compile(
    r"context|max_model_len|max_input|n_ctx|num_ctx|window", re.IGNORECASE
)
LIMIT_IN_MESSAGE = re.compile(r"(\d{4,7})\s*tokens")
PROBE_WORDS = 300_000
TIMEOUT_SECONDS = 600


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
    except urllib.error.URLError as error:
        return 0, f"no connection: {error.reason}"


def parse(body: str) -> object:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


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


def openai_model_list(base_url: str) -> None:
    print("1. Model list of the OpenAI-compatible API")
    status, body = call(f"{base_url}/models", None)
    print(f"   GET {base_url}/models -> HTTP {status}")
    parsed = parse(body)
    entries = parsed.get("data") if isinstance(parsed, dict) else None
    if not isinstance(entries, list):
        print(f"   no model list: {body[:300]}")
        return
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") != MODEL:
            continue
        fields = context_fields(entry)
        if not fields:
            print(f"   {MODEL} is listed, with no context length field")
        for path, value in fields:
            print(f"   {path} = {value}")
        return
    print(f"   {MODEL} is not in the list of {len(entries)} models")


def ollama_routes(base_url: str) -> None:
    print("2. Native routes of an Ollama server")
    root = base_url.removesuffix("/v1")
    status, body = call(f"{root}/api/show", {"model": MODEL})
    print(f"   POST {root}/api/show -> HTTP {status}")
    shown = parse(body)
    if status != 200 or not isinstance(shown, dict):
        print("   not an Ollama server, or the route is closed")
        return
    for path, value in context_fields(shown.get("model_info")):
        print(f"   largest context the model supports: {path} = {value}")
    parameters = shown.get("parameters")
    served = [line for line in str(parameters).splitlines() if "num_ctx" in line]
    if served:
        print(f"   context set in the model file: {served[0].strip()}")
    else:
        print("   the model file sets no num_ctx; the server default applies")

    status, body = call(f"{root}/api/ps", None)
    print(f"   GET {root}/api/ps -> HTTP {status}")
    running = parse(body)
    models = running.get("models") if isinstance(running, dict) else None
    if not isinstance(models, list):
        return
    for entry in models:
        if isinstance(entry, dict) and entry.get("name") == MODEL:
            fields = context_fields(entry)
            for path, value in fields:
                print(
                    f"   loaded now with: {path} = {value}   <- the served context window"
                )
            if not fields:
                print(
                    "   the model is loaded; this server version does not report its context"
                )
            return
    print("   the model is not loaded now; send one request and run this again")


def probe(base_url: str) -> None:
    print(f"3. One request of about {PROBE_WORDS} tokens, one output token")
    payload: dict[str, object] = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "a " * PROBE_WORDS}],
        "max_tokens": 1,
    }
    status, body = call(f"{base_url}/chat/completions", payload)
    print(f"   POST {base_url}/chat/completions -> HTTP {status}")
    parsed = parse(body)
    if status >= 400 or status == 0:
        print(f"   {body[:500]}")
        limits = sorted({int(number) for number in LIMIT_IN_MESSAGE.findall(body)})
        if limits:
            print(f"   token counts named in the error: {limits}")
            print(
                "   the context window is the limit the message names, usually the smaller one"
            )
        return
    usage = parsed.get("usage") if isinstance(parsed, dict) else None
    read = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    print(f"   the server accepted the request and reports prompt_tokens = {read}")
    if isinstance(read, int) and read < PROBE_WORDS // 2:
        print(
            f"   it read far less than was sent: it cuts long input without an error at about {read} tokens"
        )
        print(
            "   that number is the context window the model really has on this server"
        )
    else:
        print(
            "   the report does not show a cut; ask the host for the served context length"
        )


def main() -> None:
    if "serverid" in BASE_URL:
        sys.exit("Edit BASE_URL at the top of this file first.")
    base_url = BASE_URL.rstrip("/")
    openai_model_list(base_url)
    print()
    ollama_routes(base_url)
    if "--probe" in sys.argv[1:]:
        print()
        probe(base_url)


if __name__ == "__main__":
    main()
