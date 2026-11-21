#!/usr/bin/env python3
"""Report NVIDIA model candidates for the opt-in OpenCode drift check."""

from __future__ import annotations

import fnmatch
import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "models_policy.json"
CONFIG_PATH = REPO_ROOT / "opencode.json"


def load_policy(path: Path = POLICY_PATH) -> dict:
    try:
        policy = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot load model policy {path}: {error}") from error
    if policy.get("schema_version") != 2:
        raise RuntimeError("unsupported models_policy.json schema_version")
    if not isinstance(policy.get("nvidia"), dict):
        raise RuntimeError("models_policy.json has no nvidia policy")
    if not isinstance(policy.get("functionalities"), list):
        raise RuntimeError("models_policy.json has no shared functionalities")
    return policy


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        config = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot load OpenCode config {path}: {error}") from error
    if not isinstance(config, dict):
        raise RuntimeError("opencode.json has no JSON object")
    return config


def configured_nvidia_models(config: dict) -> set[str]:
    providers = config.get("providers")
    if not isinstance(providers, dict):
        return set()
    nvidia = providers.get("nvidia")
    if not isinstance(nvidia, dict):
        return set()
    models = nvidia.get("models")
    if not isinstance(models, dict):
        return set()
    return {model_id for model_id in models if isinstance(model_id, str)}


def catalog_model_ids(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    data = payload.get("data")
    if not isinstance(data, list):
        return set()
    return {
        item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def catalog_entries(payload: object) -> dict[str, dict]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if not isinstance(data, list):
        return {}
    entries: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if isinstance(model_id, str):
            entries[model_id] = item
    return entries


def matches_functionality(model_id: str, functionality: dict) -> bool:
    patterns = functionality.get("name_patterns")
    if not isinstance(patterns, list):
        return False

    positive = [
        pattern for pattern in patterns if isinstance(pattern, str) and not pattern.startswith("!")
    ]
    negative = [
        pattern[1:] for pattern in patterns if isinstance(pattern, str) and pattern.startswith("!")
    ]
    if negative and any(fnmatch.fnmatch(model_id.lower(), pattern.lower()) for pattern in negative):
        return False
    if not positive:
        return False
    return any(fnmatch.fnmatch(model_id.lower(), pattern.lower()) for pattern in positive)


def matched_models(model_ids: set[str], policy: dict) -> set[str]:
    functionalities = policy.get("functionalities")
    if not isinstance(functionalities, list):
        return set()
    matched: set[str] = set()
    for model_id in model_ids:
        if any(
            isinstance(functionality, dict) and matches_functionality(model_id, functionality)
            for functionality in functionalities
        ):
            matched.add(model_id)
    return matched


def read_api_key(path_value: object) -> str:
    if not isinstance(path_value, str) or not path_value:
        return ""
    path = Path(path_value).expanduser()
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def http_json(
    url: str,
    *,
    api_key: str = "",
    timeout: int = 60,
    method: str = "GET",
    payload: dict | None = None,
) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "sdd4gh-model-drift/1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"NVIDIA request failed for {url}: {error}") from error


def http_text(url: str, *, timeout: int = 60) -> str:
    request = Request(url, headers={"User-Agent": "sdd4gh-model-drift/1"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"NVIDIA request failed for {url}: {error}") from error


def discover_catalog(nvidia_policy: dict, api_key: str) -> tuple[set[str], dict[str, dict]]:
    catalog_url = nvidia_policy.get("catalog_url")
    if not isinstance(catalog_url, str):
        raise RuntimeError("NVIDIA catalog_url is missing")
    try:
        timeout = nvidia_policy.get("smoke", {}).get("timeout_seconds", 60)
        payload = http_json(catalog_url, api_key=api_key, timeout=timeout)
    except RuntimeError:
        payload = None

    if isinstance(payload, dict):
        entries = catalog_entries(payload)
        if entries:
            return set(entries), entries

    build_url = nvidia_policy.get("build_catalog_url")
    if not isinstance(build_url, str):
        raise RuntimeError("NVIDIA catalog discovery failed and build_catalog_url is missing")
    timeout = nvidia_policy.get("smoke", {}).get("timeout_seconds", 60)
    text = http_text(build_url, timeout=timeout)
    ids = set(
        re.findall(
            r"\b(?:nvidia|meta|mistralai|google|qwen|microsoft)/[a-zA-Z0-9_.-]+",
            text,
        )
    )
    if not ids:
        raise RuntimeError("NVIDIA catalog discovery failed: neither source returned model IDs")
    return ids, {model_id: {"id": model_id, "source": "build_catalog"} for model_id in ids}


def smoke_with_retries(
    model_id: str,
    smoke: Callable[[], bool],
    *,
    attempts: int,
    delay_seconds: float,
) -> bool:
    del model_id
    for attempt in range(1, attempts + 1):
        try:
            if smoke():
                return True
        except (RuntimeError, TimeoutError):
            pass
        if attempt < attempts:
            time.sleep(delay_seconds)
    return False


def chat_smoke(
    model_id: str,
    prompt: str,
    nvidia_policy: dict,
    api_key: str,
) -> Callable[[], bool]:
    chat_url = nvidia_policy.get("chat_url")
    smoke_policy = nvidia_policy.get("smoke")
    if not isinstance(chat_url, str) or not isinstance(smoke_policy, dict):
        raise RuntimeError("NVIDIA chat smoke policy is incomplete")

    def run() -> bool:
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": smoke_policy.get("temperature", 0),
            "max_tokens": smoke_policy.get("max_tokens", 64),
        }
        response = http_json(
            chat_url,
            api_key=api_key,
            timeout=int(smoke_policy.get("timeout_seconds", 60)),
            method="POST",
            payload=payload,
        )
        choices = response.get("choices")
        return isinstance(choices, list) and len(choices) > 0

    return run


def compare_candidates(
    configured: set[str],
    discovered: set[str],
    smoke_passed: set[str],
) -> tuple[set[str], set[str]]:
    to_add = smoke_passed - configured
    to_remove = configured - (discovered & smoke_passed)
    return set(to_add), set(to_remove)


def candidate_details(
    model_id: str,
    entries: dict[str, dict],
) -> dict:
    entry = entries.get(model_id, {})
    context = entry.get("context_length") or entry.get("context") or entry.get("max_input_tokens")
    output = entry.get("output_limit") or entry.get("max_output_tokens") or entry.get("output")
    name = entry.get("name") or entry.get("display_name") or model_id
    details = {
        "name": name if isinstance(name, str) else model_id,
        "context": context if isinstance(context, int) else "not reported by catalog",
        "output": output if isinstance(output, int) else "not reported by catalog",
        "source": entry.get("source", "integrate.api.nvidia.com/v1/models"),
    }
    return details


def format_report(
    to_add: set[str],
    to_remove: set[str],
    details: dict[str, dict],
) -> str:
    lines = ["NVIDIA MODEL DRIFT REPORT"]
    lines.append("CANDIDATES_TO_ADD")
    if not to_add:
        lines.append("(none)")
    for model_id in sorted(to_add):
        item = details.get(model_id, {})
        lines.append(
            f"- {model_id}: name={item.get('name', model_id)}, "
            f"context={item.get('context', 'not reported')}, "
            f"output={item.get('output', 'not reported')}, "
            f"source=https://build.nvidia.com/{model_id}"
        )
    lines.append("CANDIDATES_TO_REMOVE")
    if not to_remove:
        lines.append("(none)")
    for model_id in sorted(to_remove):
        lines.append(f"- {model_id}")
    return "\n".join(lines)


def main() -> int:
    try:
        policy = load_policy()
        nvidia_policy = policy["nvidia"]
        api_key = read_api_key(nvidia_policy.get("api_key_file"))
        if not api_key:
            raise RuntimeError(
                "NVIDIA API key not found in ~/.secrets/nvidia_key; "
                "the live drift check requires the existing free-tier credential"
            )

        config = load_config()
        configured = configured_nvidia_models(config)
        discovered, entries = discover_catalog(nvidia_policy, api_key)
        matched = matched_models(discovered, policy)

        smoke_policy = nvidia_policy.get("smoke")
        if not isinstance(smoke_policy, dict):
            raise RuntimeError("NVIDIA smoke policy is incomplete")
        timeout_delay = float(smoke_policy.get("delay_seconds", 2))
        candidate_attempts = int(smoke_policy.get("candidate_attempts", 3))
        existing_attempts = int(smoke_policy.get("existing_attempts", 5))

        smoke_passed: set[str] = set()
        prompt_by_model: dict[str, str] = {}
        functionalities = policy.get("functionalities", [])
        for model_id in matched:
            prompt = "Answer with exactly the word OK."
            for functionality in functionalities:
                if isinstance(functionality, dict) and matches_functionality(
                    model_id, functionality
                ):
                    prompt = str(functionality.get("smoke_prompt", prompt))
                    break
            prompt_by_model[model_id] = prompt

            attempts = existing_attempts if model_id in configured else candidate_attempts
            passed = smoke_with_retries(
                model_id,
                chat_smoke(model_id, prompt, nvidia_policy, api_key),
                attempts=attempts,
                delay_seconds=timeout_delay,
            )
            if passed:
                smoke_passed.add(model_id)

        to_add, to_remove = compare_candidates(configured, discovered, smoke_passed)
        # Configured models absent from discovery or present but unmatched by
        # policy are still checked if catalog discovery includes them.
        for model_id in configured & discovered:
            if model_id not in prompt_by_model:
                prompt = "Answer with exactly the word OK."
                attempts = existing_attempts
                passed = smoke_with_retries(
                    model_id,
                    chat_smoke(model_id, prompt, nvidia_policy, api_key),
                    attempts=attempts,
                    delay_seconds=timeout_delay,
                )
                if passed:
                    smoke_passed.add(model_id)
        to_add, to_remove = compare_candidates(configured, discovered, smoke_passed)

        details = {model_id: candidate_details(model_id, entries) for model_id in to_add}
        report = format_report(to_add, to_remove, details)
        print(report)
        return 1 if to_add or to_remove else 0
    except RuntimeError as error:
        print(f"NVIDIA MODEL DRIFT CHECK FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
