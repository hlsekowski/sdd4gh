#!/usr/bin/env python3
"""Plan or safely verify local Ollama model fit for ADR 0010."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "models_policy.json"
CONFIG_PATH = REPO_ROOT / "opencode.json"
REPORT_DIR = REPO_ROOT / ".ollama-model-drift"
GIB = 1024**3
MIB = 1024**2


class SkipCheck(RuntimeError):
    """The check cannot reach a safe, complete conclusion."""


class SafetyStop(RuntimeError):
    """A monitoring trip requires the live run to stop."""


class ModelProbeFailure(RuntimeError):
    """A model did not satisfy a required functionality probe."""


@lru_cache(maxsize=1)
def host_probe_settings() -> dict[str, Any]:
    return load_policy()["ollama"]["safety"]


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot load model policy {path}: {error}") from error
    if not isinstance(policy, dict) or policy.get("schema_version") != 2:
        raise RuntimeError("unsupported models_policy.json schema_version")
    if not isinstance(policy.get("functionalities"), list):
        raise RuntimeError("models_policy.json has no shared functionalities")
    if not isinstance(policy.get("ollama"), dict):
        raise RuntimeError("models_policy.json has no ollama policy")
    return policy


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot load OpenCode config {path}: {error}") from error
    if not isinstance(config, dict):
        raise RuntimeError("opencode.json has no JSON object")
    return config


def ollama_settings(config: dict[str, Any], policy: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    providers = config.get("providers")
    provider = providers.get("ollama") if isinstance(providers, dict) else None
    settings = provider.get("settings") if isinstance(provider, dict) else None
    base_url = settings.get("baseURL") if isinstance(settings, dict) else None
    if not isinstance(base_url, str) or not base_url:
        base_url = policy["ollama"].get("base_url")
    if not isinstance(base_url, str):
        raise RuntimeError("Ollama base_url is missing")
    parsed = urlparse(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("Ollama base_url must be an unauthenticated loopback HTTP URL")
    models = provider.get("models") if isinstance(provider, dict) else None
    return base_url.rstrip("/"), models if isinstance(models, dict) else {}


def configured_context(models: dict[str, Any], policy: dict[str, Any]) -> int:
    contexts = [
        details["limit"]["context"]
        for details in models.values()
        if isinstance(details, dict)
        and isinstance(details.get("limit"), dict)
        and isinstance(details["limit"].get("context"), int)
        and details["limit"]["context"] > 0
    ]
    context = max(contexts, default=0)
    if context == 0:
        context = policy["ollama"]["machine"].get("context_tokens")
    if not isinstance(context, int) or context <= 0:
        raise RuntimeError("no positive Ollama context is configured or set by policy")
    return context


def probe(operation: str) -> str:
    """Run only named read-only host probes and the fixed responsiveness canary."""
    if operation == "system_name":
        return platform.system()
    if operation == "ci_environment":
        return "1" if os.environ.get("CI") else "0"
    if operation == "model_load_opt_in":
        return "1" if os.environ.get("SDD4GH_ALLOW_MODEL_LOAD") == "1" else "0"
    if operation == "self_pid":
        return str(os.getpid())
    if operation == "server_log":
        return read_server_log()
    if operation == "termination_handlers":

        def request_stop(_signum: int, _frame: Any) -> None:
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, request_stop)
        return ""
    commands: dict[str, list[str]] = {
        "ram_bytes": ["/usr/sbin/sysctl", "-n", "hw.memsize"],
        "chip": ["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"],
        "arm64": ["/usr/sbin/sysctl", "-n", "hw.optional.arm64"],
        "macos_version": ["/usr/bin/sw_vers", "-productVersion"],
        "pressure": ["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
        "swap": ["/usr/sbin/sysctl", "-n", "vm.swapusage"],
        "vm_stat": ["/usr/bin/vm_stat"],
        "processes": ["/bin/ps", "-axo", "pid=,lstart=,rss=,comm="],
        "power": ["/usr/bin/pmset", "-g"],
        "battery": ["/usr/bin/pmset", "-g", "batt"],
        "thermal": ["/usr/bin/pmset", "-g", "therm"],
        "true": ["/usr/bin/true"],
        "metal_budget": [
            "/usr/bin/swift",
            "-e",
            "import Metal; if let d = MTLCreateSystemDefaultDevice() "
            "{ print(d.recommendedMaxWorkingSetSize) }",
        ],
    }
    if operation not in commands:
        raise ValueError(f"probe operation is not allow-listed: {operation}")
    try:
        result = subprocess.run(
            commands[operation],
            capture_output=True,
            check=False,
            text=True,
            timeout=host_probe_settings()["host_probe_timeout_seconds"],
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"host probe {operation} failed: {error}") from error
    if result.returncode:
        raise RuntimeError(f"host probe {operation} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def http_json(
    base_url: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float,
    active_connection: list[HTTPConnection] | None = None,
) -> dict[str, Any]:
    parsed = urlparse(base_url)
    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
    if active_connection is not None:
        active_connection.append(connection)
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json", "User-Agent": "sdd4gh-ollama-drift/1"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        connection.request("POST" if body is not None else "GET", path, body, headers)
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Ollama endpoint {path} returned HTTP {response.status}")
        decoded = json.loads(response.read().decode())
        if not isinstance(decoded, dict):
            raise RuntimeError(f"Ollama endpoint {path} returned a non-object response")
        return decoded
    except (OSError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Ollama request {path} failed: {error}") from error
    finally:
        connection.close()
        if active_connection is not None and connection in active_connection:
            active_connection.remove(connection)


def http_text(url: str, *, timeout: float) -> str:
    parsed = urlparse(url)
    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.request("GET", parsed.path + (f"?{parsed.query}" if parsed.query else ""))
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"GET {url} returned HTTP {response.status}")
        return response.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError) as error:
        raise RuntimeError(f"GET {url} failed: {error}") from error
    finally:
        connection.close()


def registry_config(
    registry_url: str, model: str, manifest: dict[str, Any], timeout: float
) -> dict[str, Any]:
    config = manifest.get("config")
    digest = config.get("digest") if isinstance(config, dict) else None
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        return {}
    url = f"{registry_url.rstrip('/')}/{model}/blobs/{digest}"
    parsed = urlparse(url)
    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.request("GET", parsed.path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            return {}
        payload = json.loads(response.read().decode())
        return payload if isinstance(payload, dict) else {}
    except (OSError, TimeoutError, json.JSONDecodeError):
        return {}
    finally:
        connection.close()


class ModelLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.models: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href")
        if not isinstance(href, str):
            return
        match = re.fullmatch(r"/library/([a-zA-Z0-9._-]+)", href)
        if match:
            self.models.add(match.group(1))


def ollama_search_url(search_url: str, cursor: int) -> str:
    separator = "&" if "?" in search_url else "?"
    return f"{search_url}{separator}page={cursor}"


def registry_manifest(
    registry_url: str, model: str, tag: str, timeout: float
) -> tuple[int, dict[str, Any]]:
    url = f"{registry_url.rstrip('/')}/{model}/manifests/{tag}"
    parsed = urlparse(url)
    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.request(
            "GET",
            parsed.path,
            headers={
                "Accept": "application/vnd.docker.distribution.manifest.v2+json, "
                "application/vnd.oci.image.manifest.v1+json",
                "User-Agent": "sdd4gh-ollama-drift/1",
            },
        )
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"registry manifest for {model}:{tag} returned {response.status}")
        manifest = json.loads(response.read().decode())
        return parse_registry_manifest(manifest, model, tag)
    except (OSError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"registry manifest for {model}:{tag} failed: {error}") from error
    finally:
        connection.close()


def parse_registry_manifest(payload: object, model: str, tag: str) -> tuple[int, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RuntimeError(f"registry manifest for {model}:{tag} is malformed")
    layers = payload.get("layers", [])
    size = sum(
        layer["size"]
        for layer in layers
        if isinstance(layer, dict)
        and layer.get("mediaType") == "application/vnd.ollama.image.model"
        and isinstance(layer.get("size"), int)
    )
    if size <= 0:
        raise RuntimeError(f"registry manifest for {model}:{tag} has no layer weights")
    return size, payload


def parse_registry_tags(payload: object, model: str) -> set[str]:
    tags = payload.get("tags") if isinstance(payload, dict) else None
    if not isinstance(tags, list) or not all(
        isinstance(tag, str) and re.fullmatch(r"[a-zA-Z0-9._-]+", tag) for tag in tags
    ):
        raise RuntimeError(f"registry tags for {model} are malformed")
    return set(tags)


def registry_tags(registry_url: str, model: str, timeout: float, page_size: int) -> set[str]:
    next_url = f"{registry_url.rstrip('/')}/{model}/tags/list?n={page_size}"
    tags: set[str] = set()
    visited: set[str] = set()
    while next_url:
        if next_url in visited:
            raise RuntimeError(f"registry tags for {model} repeated a pagination link")
        visited.add(next_url)
        parsed = urlparse(next_url)
        connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
        try:
            connection.request("GET", parsed.path + (f"?{parsed.query}" if parsed.query else ""))
            response = connection.getresponse()
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"registry tags for {model} returned HTTP {response.status}")
            payload = json.loads(response.read().decode())
            tags.update(parse_registry_tags(payload, model))
            link = response.getheader("Link", "")
            match = re.search(r"<([^>]+)>;\s*rel=\"?next\"?", link)
            next_url = urljoin(next_url, match.group(1)) if match else ""
            if next_url:
                next_parsed = urlparse(next_url)
                if next_parsed.scheme != "https" or next_parsed.hostname != "registry.ollama.ai":
                    raise RuntimeError("registry pagination left the official Ollama host")
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            raise RuntimeError(f"registry tags for {model} failed: {error}") from error
        finally:
            connection.close()
    return tags


def discover_models(
    ollama: dict[str, Any], functionalities: list[Any]
) -> dict[str, dict[str, Any]]:
    discovery = ollama.get("discovery")
    if not isinstance(discovery, dict):
        raise RuntimeError("Ollama discovery policy is missing")
    search_url = discovery.get("search_url")
    registry_url = discovery.get("registry_url")
    maximum = discovery.get("max_families")
    timeout = discovery.get("timeout_seconds")
    if (
        not isinstance(search_url, str)
        or not isinstance(registry_url, str)
        or not isinstance(maximum, int)
        or not isinstance(timeout, (int, float))
    ):
        raise RuntimeError("Ollama discovery policy is invalid")
    if (
        urlparse(search_url).scheme != "https"
        or urlparse(search_url).hostname != "ollama.com"
        or urlparse(registry_url).scheme != "https"
        or urlparse(registry_url).hostname != "registry.ollama.ai"
    ):
        raise RuntimeError("Ollama discovery is restricted to the public official catalog")
    names: set[str] = set()
    for page in range(1, int(maximum) + 1):
        parser = ModelLinks()
        parser.feed(http_text(ollama_search_url(search_url, page), timeout=float(timeout)))
        names.update(parser.models)
        if len(names) >= maximum or not parser.models:
            break
    if not names:
        raise SkipCheck("Ollama library discovery returned no models")
    excluded = ollama.get("exclude", {})
    suffixes = excluded.get("tag_suffixes", []) if isinstance(excluded, dict) else []
    ignored = set(ollama.get("ignore", []))
    candidates: dict[str, dict[str, Any]] = {}

    def supported_functionality(model: str) -> bool:
        import fnmatch

        for item in functionalities:
            if not isinstance(item, dict) or not isinstance(item.get("name_patterns"), list):
                continue
            patterns = item["name_patterns"]
            positive = [p for p in patterns if isinstance(p, str) and not p.startswith("!")]
            negative = [p[1:] for p in patterns if isinstance(p, str) and p.startswith("!")]
            if any(fnmatch.fnmatch(model.lower(), pattern.lower()) for pattern in negative):
                continue
            if any(fnmatch.fnmatch(model.lower(), pattern.lower()) for pattern in positive):
                return True
        return False

    for model in sorted(names)[:maximum]:
        if "/" in model or model in ignored or not supported_functionality(model):
            continue
        tag_names = registry_tags(
            registry_url,
            model,
            float(timeout),
            discovery["page_size"],
        )
        if not tag_names:
            raise SkipCheck(f"Ollama registry returned no tags for discovered model {model}")
        for tag in sorted(tag_names):
            if isinstance(suffixes, list) and any(tag.endswith(suffix) for suffix in suffixes):
                continue
            name = f"{model}:{tag}"
            if name in ignored:
                continue
            size, manifest = registry_manifest(registry_url, model, tag, float(timeout))
            details = registry_config(registry_url, model, manifest, float(timeout))
            if size:
                candidates[name] = {
                    "name": name,
                    "weights_bytes": size,
                    "manifest": manifest,
                    "metadata": details,
                    "source": "official-library",
                    "library_url": f"https://ollama.com/library/{model}:{tag}",
                }
    if not candidates:
        raise SkipCheck("Ollama discovery did not produce any verified registry weights")
    return candidates


def installed_models(base_url: str, timeout: float) -> dict[str, dict[str, Any]]:
    response = http_json(base_url, "/api/tags", timeout=timeout)
    models = response.get("models")
    if not isinstance(models, list):
        raise RuntimeError("Ollama /api/tags response has no models list")
    result: dict[str, dict[str, Any]] = {}
    for item in models:
        if (
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("size"), int)
        ):
            result[item["name"]] = item
    return result


def show_model(base_url: str, name: str, timeout: float) -> dict[str, Any]:
    return http_json(base_url, "/api/show", payload={"model": name}, timeout=timeout)


def configured_model_base(base_url: str, name: str, timeout: float) -> str:
    return configured_model_details(base_url, name, timeout)["base_model"]


def configured_model_details(base_url: str, name: str, timeout: float) -> dict[str, Any]:
    try:
        details = show_model(base_url, name, timeout)
    except RuntimeError as error:
        return {
            "base_model": name,
            "baked_context": None,
            "resolution_verified": False,
            "resolution_error": str(error),
        }
    modelfile = details.get("modelfile")
    if isinstance(modelfile, str):
        base_match = re.search(r"(?m)^FROM\s+([^\s]+)", modelfile)
        context_match = re.search(r"(?m)^PARAMETER\s+num_ctx\s+(\d+)", modelfile)
        return {
            "base_model": base_match.group(1).split("/")[-1] if base_match else name,
            "baked_context": int(context_match.group(1)) if context_match else None,
            "resolution_verified": bool(base_match),
        }
    return {
        "base_model": name,
        "baked_context": None,
        "resolution_verified": False,
        "resolution_error": "Ollama /api/show returned no Modelfile",
    }


def system_memory() -> dict[str, Any]:
    memory = int(probe("ram_bytes"))
    chip = probe("chip")
    macos = probe("macos_version")
    arm64 = probe("arm64") == "1"
    return {"ram_bytes": memory, "chip": chip, "macos": macos, "arm64": arm64}


def gpu_budget(
    base_url: str, machine: dict[str, Any], machine_policy: dict[str, Any], timeout: float
) -> tuple[int, str]:
    try:
        ps = http_json(base_url, "/api/ps", timeout=timeout)
        reported = ps.get("gpu_memory_budget")
        if isinstance(reported, int) and reported > 0:
            return reported, "ollama:/api/ps"
    except RuntimeError:
        pass
    try:
        metal = int(probe("metal_budget"))
        if metal > 0:
            return metal, "Metal recommendedMaxWorkingSetSize"
    except (RuntimeError, ValueError):
        pass
    override = machine_policy.get("gpu_budget_gib")
    if isinstance(override, (int, float)) and override > 0:
        return int(float(override) * GIB), "policy override"
    fraction = machine_policy.get("gpu_budget_fallback_fraction")
    if not isinstance(fraction, (int, float)) or fraction <= 0:
        raise RuntimeError("GPU budget fallback fraction is invalid")
    return int(machine["ram_bytes"] * fraction), "policy RAM fraction"


def parse_vm_stat(text: str) -> dict[str, int]:
    page_size_match = re.search(r"page size of (\d+) bytes", text, re.IGNORECASE)
    if not page_size_match:
        raise RuntimeError("cannot determine vm_stat page size")
    page_size = int(page_size_match.group(1))
    result: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"([^:]+):\s+([\d.]+)", line)
        if match:
            result[match.group(1).strip().lower()] = int(float(match.group(2).replace(".", "")))
    return {name: count * page_size for name, count in result.items()}


def reclaimable_bytes(vm_stat: dict[str, int]) -> int:
    return sum(
        amount
        for key, amount in vm_stat.items()
        if any(term in key for term in ("free", "inactive", "speculative", "purgeable"))
    )


def swap_used_bytes(text: str) -> int:
    match = re.search(r"used\s*=\s*([\d.]+)([KMG])", text)
    if not match:
        raise RuntimeError("cannot parse vm.swapusage output")
    multiplier = {"K": 1024, "M": MIB, "G": GIB}[match.group(2)]
    return int(float(match.group(1)) * multiplier)


def model_parameters(model_info: dict[str, Any]) -> tuple[int, int, int, int | None]:
    def value(suffix: str) -> Any:
        if suffix in model_info:
            return model_info[suffix]
        return next(
            (
                item
                for key, item in model_info.items()
                if isinstance(key, str) and key.endswith(f".{suffix}")
            ),
            None,
        )

    layers = value("block_count")
    kv_heads = value("attention.head_count_kv")
    embedding = value("embedding_length")
    attention_heads = value("attention.head_count")
    window = value("attention.sliding_window")

    def positive_integer(value: Any) -> int:
        return value if isinstance(value, int) and value > 0 else 0

    layer_count = positive_integer(layers)
    kv_head_count = positive_integer(kv_heads)
    embedding_size = positive_integer(embedding)
    head_count = positive_integer(attention_heads)
    head_dim = embedding_size // head_count if head_count else 0
    return layer_count, kv_head_count, head_dim, positive_integer(window) or None


def threshold_trip(
    signal_name: str, value: float, safety: dict[str, Any]
) -> tuple[str, str] | None:
    levels = safety["memory_pressure_levels"]
    if signal_name == "pressure":
        if value >= levels["hard"]:
            return "memory_pressure_hard", "hard"
    elif signal_name == "swap_growth_bytes":
        if value >= safety["swap_growth_mib"]["trip"] * MIB:
            return "swap_growth", "soft"
    elif signal_name == "timer_lag_ms":
        if value >= safety["timer_lag_ms"]["stall_seconds"] * 1000:
            return "system_stall", "hard"
        if value >= safety["timer_lag_ms"]["trip"]:
            return "timer_lag", "soft"
    elif signal_name == "spawn_latency_ms":
        if value >= safety["spawn_latency_ms"]["trip"]:
            return "spawn_latency", "soft"
    else:
        raise ValueError(f"unknown monitored signal: {signal_name}")
    return None


def collateral_exit_trip(
    vanished: list[int], pressure: int, swap_growth_bytes: int, safety: dict[str, Any]
) -> bool:
    return bool(vanished) and (
        pressure >= safety["memory_pressure_levels"]["warn"]
        or swap_growth_bytes >= safety["swap_growth_mib"]["warn"] * MIB
    )


def estimate_model(
    *,
    weights_bytes: int,
    model_info: dict[str, Any],
    context: int,
    machine: dict[str, Any],
    machine_policy: dict[str, Any],
    gpu_budget_bytes: int,
) -> dict[str, Any]:
    usable = min(
        gpu_budget_bytes,
        machine["ram_bytes"] - int(machine_policy["os_reserve_gib"] * GIB),
    ) - int(machine_policy["safety_margin_gib"] * GIB)
    runtime = int(machine_policy["runtime_overhead_gib"] * GIB)
    if usable <= 0:
        return {
            "verdict": "reject",
            "reason": "no usable memory remains after OS reserve and safety margin",
            "usable_bytes": usable,
            "estimate_bytes": weights_bytes + runtime,
            "precision": "coarse",
        }
    if weights_bytes > usable:
        return {
            "verdict": "reject",
            "reason": "weights alone exceed usable memory",
            "usable_bytes": usable,
            "estimate_bytes": weights_bytes + runtime,
            "precision": "exact",
        }
    layers, kv_heads, head_dim, window = model_parameters(model_info)
    kv_type = machine_policy.get("kv_cache_type", "f16")
    bytes_per_value = {"f16": 2, "q8_0": 1, "q4_0": 0.5}.get(kv_type)
    if layers and kv_heads and head_dim and bytes_per_value:
        tokens = min(context, window) if window else context
        kv_bytes = math.ceil(2 * layers * kv_heads * head_dim * tokens * bytes_per_value)
        precision = "exact"
    else:
        kv_bytes = 0
        precision = "coarse"
    estimate = weights_bytes + kv_bytes + runtime
    if estimate > usable:
        return {
            "verdict": "reject",
            "reason": "estimated weights, KV cache, and runtime exceed usable memory",
            "usable_bytes": usable,
            "estimate_bytes": estimate,
            "weights_bytes": weights_bytes,
            "kv_cache_bytes": kv_bytes,
            "runtime_overhead_bytes": runtime,
            "precision": precision,
        }
    return {
        "verdict": "candidate",
        "reason": "estimated footprint fits usable memory",
        "usable_bytes": usable,
        "estimate_bytes": estimate,
        "weights_bytes": weights_bytes,
        "kv_cache_bytes": kv_bytes,
        "runtime_overhead_bytes": runtime,
        "precision": precision,
    }


def functionality_prompts(model: str, functionalities: list[Any]) -> list[tuple[str, str]]:
    prompts: list[tuple[str, str]] = []
    lower_name = model.lower()
    for item in functionalities:
        if not isinstance(item, dict) or not isinstance(item.get("name_patterns"), list):
            continue
        patterns = item["name_patterns"]
        positive = [p for p in patterns if isinstance(p, str) and not p.startswith("!")]
        negative = [p[1:] for p in patterns if isinstance(p, str) and p.startswith("!")]
        import fnmatch

        if any(fnmatch.fnmatch(lower_name, p.lower()) for p in negative):
            continue
        if any(fnmatch.fnmatch(lower_name, p.lower()) for p in positive):
            prompt = item.get("smoke_prompt")
            if isinstance(prompt, str):
                prompts.append((str(item.get("id", "general-purpose")), prompt))
    return prompts


def installed_fit_models(
    base_url: str, configured: dict[str, Any], timeout: float
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    installed = installed_models(base_url, timeout)
    details: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for config_name in configured:
        base = configured_model_base(base_url, config_name, timeout)
        aliases[config_name] = base
    for name in set(installed) | set(aliases.values()) | set(configured):
        try:
            details[name] = show_model(base_url, name, timeout)
        except RuntimeError:
            details[name] = {}
    return installed, details


def model_report_entry(
    name: str,
    source: dict[str, Any],
    model_info: dict[str, Any],
    context: int,
    machine: dict[str, Any],
    machine_policy: dict[str, Any],
    budget: int,
) -> dict[str, Any]:
    metadata = source.get("metadata", {})
    details = metadata if isinstance(metadata, dict) else {}
    model_details = details.get("details", {})
    model_details = model_details if isinstance(model_details, dict) else {}
    if not model_info:
        candidate_info = details.get("model_info")
        model_info = candidate_info if isinstance(candidate_info, dict) else {}
    return {
        "name": name,
        "source": source.get("source", "installed"),
        "weights_bytes": source.get("weights_bytes", source.get("size")),
        "context": context,
        "declared_context": details.get(
            "context_length", details.get("max_context_length", "not reported")
        ),
        "parameters": details.get(
            "parameter_size",
            details.get("model_type", model_details.get("parameter_size", "not reported")),
        ),
        "quantization": details.get(
            "quantization_level",
            details.get("file_type", model_details.get("quantization_level", "not reported")),
        ),
        "capabilities": details.get("capabilities", ["tools"]),
        "license": details.get("license", "See model library page"),
        "library_url": source.get("library_url", "not reported"),
        **estimate_model(
            weights_bytes=int(source.get("weights_bytes", source.get("size", 0))),
            model_info=model_info,
            context=context,
            machine=machine,
            machine_policy=machine_policy,
            gpu_budget_bytes=budget,
        ),
    }


def plan_candidates(
    policy: dict[str, Any],
    config: dict[str, Any],
    base_url: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    ollama = policy["ollama"]
    machine_policy = ollama["machine"]
    provider = config["providers"].get("ollama", {})
    configured = provider.get("models", {}) if isinstance(provider, dict) else {}
    if not isinstance(configured, dict):
        configured = {}
    context = configured_context(configured, ollama)
    machine = system_memory()
    budget, budget_source = gpu_budget(base_url, machine, machine_policy, timeout)
    discovered = discover_models(ollama, policy["functionalities"])
    installed, shown = installed_fit_models(base_url, configured, timeout)
    excluded_names = set(ollama.get("ignore", []))
    exclusion_policy = ollama.get("exclude", {})
    tag_suffixes = (
        exclusion_policy.get("tag_suffixes", []) if isinstance(exclusion_policy, dict) else []
    )

    def excluded(name: str, details: dict[str, Any]) -> bool:
        tag = name.rsplit(":", 1)[-1]
        remote = bool(
            isinstance(exclusion_policy, dict)
            and exclusion_policy.get("remote")
            and details.get("remote_host")
        )
        return (
            "/" in name
            or remote
            or name in excluded_names
            or tag == "cloud"
            or any(tag.endswith(suffix) for suffix in tag_suffixes)
        )

    outcomes: dict[str, dict[str, Any]] = {}
    for name, source in installed.items():
        info = shown.get(name, {}).get("model_info", {})
        if not isinstance(info, dict):
            info = {}
        details = {**shown.get(name, {}), **source}
        if excluded(name, details):
            outcomes[name] = {
                "name": name,
                "weights_bytes": source["size"],
                "context": context,
                "verdict": "reject",
                "reason": "model is excluded by provider policy",
                "precision": "exact",
                "estimate_bytes": source["size"],
                "usable_bytes": plan_usable_memory(machine, machine_policy, budget),
            }
        else:
            outcomes[name] = model_report_entry(
                name, source, info, context, machine, machine_policy, budget
            )
    for name, source in discovered.items():
        if excluded(name, {}):
            continue
        if name not in outcomes:
            outcomes[name] = model_report_entry(
                name,
                source,
                {},
                context,
                machine,
                machine_policy,
                budget,
            )
    configured_models = [
        {
            "configured_name": name,
            **configured_model_details(base_url, name, timeout),
        }
        for name in configured
    ]
    configured_bases = {item["base_model"].removesuffix(":latest") for item in configured_models}
    discovered_names = set(discovered)
    candidates = [
        item
        for name, item in outcomes.items()
        if name in discovered_names
        and item["verdict"] == "candidate"
        and name.removesuffix(":latest") not in configured_bases
    ]
    candidates.sort(key=lambda item: item["estimate_bytes"])
    configured_entries: list[dict[str, Any]] = []
    for model in configured_models:
        configured_name = model["configured_name"]
        details = shown.get(configured_name, {})
        model_outcome = outcomes.get(configured_name)
        if model_outcome is None:
            installed_name = (
                configured_name if configured_name in installed else f"{configured_name}:latest"
            )
            model_outcome = outcomes.get(installed_name)
        configured_entries.append(
            {
                **model,
                "resolved_name": configured_name,
                **(
                    model_outcome
                    if model_outcome
                    else {"verdict": "not_tested", "reason": "model is not installed"}
                ),
                "remote_host": details.get("remote_host"),
            }
        )
    unverified = [item["name"] for item in candidates]
    return {
        "machine": {
            "profile": machine_policy["profile"],
            "chip": machine["chip"],
            "macos": machine["macos"],
            "ram_bytes": machine["ram_bytes"],
            "gpu_budget_bytes": budget,
            "gpu_budget_source": budget_source,
            "usable_bytes": min(
                budget,
                machine["ram_bytes"] - int(machine_policy["os_reserve_gib"] * GIB),
            )
            - int(machine_policy["safety_margin_gib"] * GIB),
            "context": context,
        },
        "configured_models": configured_entries,
        "candidates": candidates,
        "unverified_candidates": unverified,
        "outcomes": outcomes,
        "machine_info": machine,
    }


def plan_usable_memory(machine: dict[str, Any], machine_policy: dict[str, Any], budget: int) -> int:
    return min(
        budget,
        machine["ram_bytes"] - int(machine_policy["os_reserve_gib"] * GIB),
    ) - int(machine_policy["safety_margin_gib"] * GIB)


def format_plan(report: dict[str, Any]) -> str:
    lines = ["OLLAMA MODEL DRIFT PLAN", "No model was loaded."]
    machine = report["machine"]
    lines.append(
        f"Machine: {machine['chip']} / macOS {machine['macos']} / "
        f"GPU budget {machine['gpu_budget_bytes'] / GIB:.2f} GiB "
        f"({machine['gpu_budget_source']}) / context {machine['context']}"
    )
    lines.append("MODELS")
    outcomes = report["outcomes"]
    if not outcomes:
        lines.append("(none)")
    for name, result in sorted(outcomes.items()):
        lines.append(
            f"- {name}: {result['verdict']} ({result.get('precision', 'n/a')}, "
            f"estimate={result.get('estimate_bytes', 0) / GIB:.2f} GiB, "
            f"usable={result.get('usable_bytes', 0) / GIB:.2f} GiB): {result['reason']}"
        )
    if report["unverified_candidates"]:
        lines.append("UNVERIFIED CANDIDATES")
        lines.extend(f"- {name}" for name in report["unverified_candidates"])
    return "\n".join(lines)


def parse_processes(text: str) -> dict[int, dict[str, Any]]:
    processes: dict[int, dict[str, Any]] = {}
    for line in text.splitlines():
        fields = line.strip().split(None, 7)
        if len(fields) != 8 or not fields[0].isdigit():
            continue
        pid = int(fields[0])
        processes[pid] = {
            "pid": pid,
            "started": " ".join(fields[1:6]),
            "rss_bytes": int(fields[6]) * 1024,
            "name": Path(fields[7]).name,
        }
    return processes


def read_server_log() -> str:
    path = Path.home() / ".ollama" / "logs" / "server.log"
    try:
        return path.read_text(errors="replace")[-host_probe_settings()["server_log_tail_bytes"] :]
    except OSError:
        return ""


def power_status() -> dict[str, Any]:
    settings = probe("power")
    battery = probe("battery")
    thermal = probe("thermal")
    return {
        "battery": battery,
        "settings": settings,
        "thermal": thermal,
        "low_power_mode": bool(re.search(r"(?im)^\s*lowpowermode\s+1\b", settings)),
        "ac_power": "AC Power" in battery,
    }


def normal_preflight(
    base_url: str,
    policy: dict[str, Any],
    context: int,
    timeout: float,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    machine = system_memory()
    if probe("system_name") != "Darwin" or not machine["arm64"]:
        raise SkipCheck("fit verification requires macOS arm64")
    machine_policy = policy["ollama"]["machine"]
    expected_chip = machine_policy.get("expected_chip")
    expected_ram = machine_policy.get("expected_ram_gib")
    if not isinstance(expected_chip, str) or expected_chip not in machine["chip"]:
        raise SkipCheck("fit verification is limited to the configured reference chip")
    if not isinstance(expected_ram, (int, float)) or not math.isclose(
        machine["ram_bytes"] / GIB, expected_ram, abs_tol=0.5
    ):
        raise SkipCheck("fit verification is limited to the configured reference RAM profile")
    if probe("ci_environment") == "1":
        raise SkipCheck("fit verification is disabled in CI")
    parsed = urlparse(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SkipCheck("fit verification requires a loopback Ollama endpoint")
    power = power_status()
    if power["low_power_mode"]:
        raise SkipCheck("Low Power Mode is enabled; turn it off manually and retry")
    if not power["ac_power"]:
        raise SkipCheck("fit verification requires AC power")
    ps = http_json(base_url, "/api/ps", timeout=timeout)
    loaded = ps.get("models")
    if not isinstance(loaded, list):
        raise SkipCheck("Ollama /api/ps response is invalid")
    if loaded:
        raise SkipCheck("Ollama already has a loaded model; unload it manually and retry")
    safety = policy["ollama"]["safety"]
    baseline_duration = max(
        safety["pressure_normal_seconds"],
        safety["idle_baseline_seconds"],
    )
    baseline_started = time.monotonic()
    canaries: list[dict[str, float]] = []
    while time.monotonic() - baseline_started < baseline_duration:
        pressure = int(probe("pressure"))
        if pressure != safety["memory_pressure_levels"]["normal"]:
            raise SkipCheck("memory pressure is not normal")
        swap = swap_used_bytes(probe("swap"))
        if swap >= safety["max_swap_used_mib"] * MIB:
            raise SkipCheck("swap use exceeds the preflight limit")
        canary = measure_canaries(safety["pressure_sample_seconds"])
        canaries.append(canary)
        if canary["spawn_ms"] >= safety["spawn_latency_ms"]["warn"]:
            raise SkipCheck("process-creation responsiveness is outside the idle baseline")
        if canary["timer_lag_ms"] >= safety["timer_lag_ms"]["warn"]:
            raise SkipCheck("scheduler responsiveness is outside the idle baseline")
    swap = swap_used_bytes(probe("swap"))
    canary = {key: max(sample[key] for sample in canaries) for key in ("spawn_ms", "timer_lag_ms")}
    journal = journal_path()
    if journal.exists() and read_journal(journal).get("started"):
        raise SkipCheck(
            "crash journal contains an unfinished model; use --forget-journal only after review"
        )
    processes = parse_processes(probe("processes"))
    watch_set = {
        pid: item
        for pid, item in processes.items()
        if item["rss_bytes"] >= safety["watch_set_min_rss_mib"] * MIB
        and pid != int(probe("self_pid"))
        and not item["name"].startswith("ollama")
    }
    budget, budget_source = gpu_budget(base_url, machine, policy["ollama"]["machine"], timeout)
    return (
        {
            "machine": machine,
            "context": context,
            "power": power,
            "baseline_swap_bytes": swap,
            "baseline_canaries": canary,
            "gpu_budget_bytes": budget,
            "gpu_budget_source": budget_source,
            "watch_set": [
                {"name": item["name"], "pid": item["pid"], "started": item["started"]}
                for item in watch_set.values()
            ],
            "started_at": timestamp(),
        },
        watch_set,
    )


def measure_canaries(timer_interval: float) -> dict[str, float]:
    started = time.monotonic()
    probe("true")
    spawn_ms = (time.monotonic() - started) * 1000
    timer_started = time.monotonic()
    time.sleep(timer_interval)
    timer_lag_ms = max(
        0.0,
        (time.monotonic() - timer_started - timer_interval) * 1000,
    )
    return {"spawn_ms": spawn_ms, "timer_lag_ms": timer_lag_ms}


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def report_path() -> Path:
    return REPORT_DIR / f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"


def journal_path() -> Path:
    return REPORT_DIR / "crash-journal.json"


def read_journal(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise SkipCheck(f"crash journal cannot be read safely: {error}") from error
    if not isinstance(payload, dict):
        raise SkipCheck("crash journal is not a JSON object; inspect before clearing")
    if payload and "started" not in payload and "finished" not in payload:
        raise SkipCheck(
            "crash journal has an unknown state; inspect it before using --forget-journal"
        )
    return payload


def write_journal(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        json.dump(payload, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def append_timeline(path: Path, sample: dict[str, Any]) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(sample, sort_keys=True) + "\n")
        stream.flush()


class FitMonitor:
    def __init__(
        self,
        *,
        base_url: str,
        policy: dict[str, Any],
        timeline: Path,
        watch_set: dict[int, dict[str, Any]],
        baseline_swap: int,
        active_connection: list[HTTPConnection],
        model: str,
        model_loaded: threading.Event,
    ) -> None:
        self.base_url = base_url
        self.safety = policy["ollama"]["safety"]
        self.timeout = policy["ollama"]["fit"]["request_timeout_seconds"]
        self.max_seconds = policy["ollama"]["fit"]["max_seconds_per_model"]
        self.timeline = timeline
        self.watch_set = watch_set
        self.baseline_swap = baseline_swap
        self.active_connection = active_connection
        self.model = model
        self.model_loaded = model_loaded
        self.stop_event = threading.Event()
        self.trip: dict[str, Any] | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.started = time.monotonic()
        self.pressure_warn_start: float | None = None
        self.timer_trips = 0
        self.spawn_trips = 0
        self.log_offset = 0

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=self.safety["ollama_unresponsive_seconds"])

    def _trip(self, reason: str, severity: str, sample: dict[str, Any]) -> None:
        if self.trip is None:
            self.trip = {"reason": reason, "severity": severity, "at": timestamp()}
        for connection in tuple(self.active_connection):
            connection.close()
        sample["trip"] = self.trip

    def _run(self) -> None:
        interval = self.safety["pressure_sample_seconds"]
        target = time.monotonic() + interval
        last_swap = 0.0
        last_canary = 0.0
        last_ollama = 0.0
        last_log = 0.0
        last_thermal = 0.0
        while not self.stop_event.is_set():
            now = time.monotonic()
            sample: dict[str, Any] = {
                "timestamp": timestamp(),
                "elapsed_seconds": now - self.started,
            }
            if now - self.started >= self.max_seconds:
                self._trip("model_time_limit", "soft", sample)
            lag_ms = max(0, (now - target) * 1000)
            sample["timer_lag_ms"] = lag_ms
            target = now + interval
            try:
                pressure = int(probe("pressure"))
                sample["pressure_level"] = pressure
                levels = self.safety["memory_pressure_levels"]
                pressure_trip = threshold_trip("pressure", pressure, self.safety)
                if pressure_trip:
                    self._trip(*pressure_trip, sample)
                if pressure >= levels["warn"]:
                    if self.pressure_warn_start is None:
                        self.pressure_warn_start = now
                    if now - self.pressure_warn_start >= self.safety["pressure_warn_trip_seconds"]:
                        self._trip("memory_pressure_sustained", "soft", sample)
                else:
                    self.pressure_warn_start = None
                lag_trip = threshold_trip("timer_lag_ms", lag_ms, self.safety)
                if lag_ms >= self.safety["timer_lag_ms"]["trip"]:
                    self.timer_trips += 1
                else:
                    self.timer_trips = 0
                if lag_ms >= self.safety["timer_lag_ms"]["warn"]:
                    sample.setdefault("warnings", []).append("timer_lag")
                if self.timer_trips >= self.safety["timer_lag_ms"]["consecutive"]:
                    self._trip("timer_lag", "soft", sample)
                if lag_trip and lag_trip[0] == "system_stall":
                    self._trip(*lag_trip, sample)
                if now - last_swap >= self.safety["swap_sample_seconds"]:
                    swap = swap_used_bytes(probe("swap"))
                    growth = max(0, swap - self.baseline_swap)
                    sample["swap_used_bytes"] = swap
                    sample["swap_growth_bytes"] = growth
                    swap_trip = threshold_trip("swap_growth_bytes", growth, self.safety)
                    if swap_trip:
                        self._trip(*swap_trip, sample)
                    elif growth >= self.safety["swap_growth_mib"]["warn"] * MIB:
                        sample.setdefault("warnings", []).append("swap_growth")
                    last_swap = now
                if now - last_canary >= self.safety["canary_sample_seconds"]:
                    canary = measure_canaries(self.safety["pressure_sample_seconds"])
                    sample["canaries"] = canary
                    spawn_trip = threshold_trip("spawn_latency_ms", canary["spawn_ms"], self.safety)
                    if canary["spawn_ms"] >= self.safety["spawn_latency_ms"]["trip"]:
                        self.spawn_trips += 1
                    else:
                        self.spawn_trips = 0
                    if canary["spawn_ms"] >= self.safety["spawn_latency_ms"]["warn"]:
                        sample.setdefault("warnings", []).append("spawn_latency")
                    if self.spawn_trips >= self.safety["spawn_latency_ms"]["consecutive"]:
                        self._trip("spawn_latency", "soft", sample)
                    processes = parse_processes(probe("processes"))
                    vanished = [
                        pid
                        for pid, item in self.watch_set.items()
                        if pid not in processes or processes[pid]["started"] != item["started"]
                    ]
                    sample["collateral_exits"] = vanished
                    if collateral_exit_trip(
                        vanished,
                        pressure,
                        sample.get("swap_growth_bytes", 0),
                        self.safety,
                    ):
                        self._trip("collateral_process_exit", "hard", sample)
                    if (
                        spawn_trip
                        and self.spawn_trips >= self.safety["spawn_latency_ms"]["consecutive"]
                    ):
                        self._trip(*spawn_trip, sample)
                    last_canary = now
                if now - last_ollama >= self.safety["ollama_sample_seconds"]:
                    try:
                        ollama_state = http_json(
                            self.base_url,
                            "/api/ps",
                            timeout=self.safety["ollama_unresponsive_seconds"],
                        )
                        if self.model_loaded.is_set():
                            loaded = ollama_state.get("models", [])
                            if not any(
                                isinstance(item, dict)
                                and model_matches(item.get("name"), self.model)
                                for item in loaded
                            ):
                                self._trip("runner_exited", "hard", sample)
                    except RuntimeError:
                        self._trip("ollama_unresponsive", "hard", sample)
                    last_ollama = now
                if now - last_log >= self.safety["log_sample_seconds"]:
                    log = probe("server_log")
                    errors = re.findall(
                        r"(?i)(out of memory|kIOGPUCommandBufferCallbackError[^\s,]*|"
                        r"runner exited)",
                        log[self.log_offset :],
                    )
                    self.log_offset = len(log)
                    if errors:
                        sample["ollama_errors"] = errors
                        self._trip("ollama_or_metal_error", "hard", sample)
                    last_log = now
                if now - last_thermal >= self.safety["thermal_sample_seconds"]:
                    sample["thermal_power"] = {
                        "thermal": probe("thermal"),
                        "power": probe("power"),
                    }
                    last_thermal = now
            except (RuntimeError, ValueError) as error:
                sample["probe_error"] = str(error)
                self._trip("monitor_probe_failed", "hard", sample)
            if sample.get("pressure_level", 0) >= self.safety["collateral_warn_pressure"]:
                sample.setdefault("warnings", []).append("memory_pressure")
            append_timeline(self.timeline, sample)
            if self.trip:
                return
            self.stop_event.wait(max(0, target - time.monotonic()))


def admission_check(
    base_url: str,
    estimate_bytes: int,
    fit_policy: dict[str, Any],
    safety: dict[str, Any],
) -> None:
    loaded = http_json(
        base_url,
        "/api/ps",
        timeout=safety["ollama_unresponsive_seconds"],
    ).get("models")
    if not isinstance(loaded, list) or loaded:
        raise SkipCheck("machine busy: Ollama has a model loaded before admission")
    vm = parse_vm_stat(probe("vm_stat"))
    reclaimable = reclaimable_bytes(vm)
    required = estimate_bytes - int(fit_policy["max_squeeze_gib"] * GIB)
    if reclaimable < max(0, required):
        raise SkipCheck("machine busy: reclaimable memory is below the admission limit")
    if int(probe("pressure")) != safety["memory_pressure_levels"]["normal"]:
        raise SkipCheck("memory pressure changed before model admission")


def tool_probe(
    base_url: str,
    model: str,
    context: int,
    ollama: dict[str, Any],
    active_connection: list[HTTPConnection],
) -> dict[str, Any]:
    response = http_json(
        base_url,
        "/api/chat",
        payload={
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": "Call the echo tool with the text OK."}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "description": "Return the supplied text.",
                        "parameters": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    },
                }
            ],
            "options": {
                "num_ctx": context,
                "num_predict": ollama["fit"]["num_predict"],
            },
        },
        timeout=ollama["fit"]["request_timeout_seconds"],
        active_connection=active_connection,
    )
    message = response.get("message")
    calls = message.get("tool_calls") if isinstance(message, dict) else None
    if not isinstance(calls, list) or not calls:
        raise ModelProbeFailure("tool-call probe returned no well-formed tool_calls")
    if not all(
        isinstance(call, dict)
        and isinstance(call.get("function"), dict)
        and isinstance(call["function"].get("name"), str)
        and isinstance(call["function"].get("arguments"), dict)
        for call in calls
    ):
        raise ModelProbeFailure("tool-call probe returned malformed tool_calls")
    return response


def generation_probe(
    base_url: str,
    model: str,
    prompt: str,
    context: int,
    ollama: dict[str, Any],
    active_connection: list[HTTPConnection],
) -> dict[str, Any]:
    return http_json(
        base_url,
        "/api/generate",
        payload={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": ollama["fit"]["keep_alive"],
            "options": {
                "num_ctx": context,
                "num_predict": ollama["fit"]["num_predict"],
            },
        },
        timeout=ollama["fit"]["request_timeout_seconds"],
        active_connection=active_connection,
    )


def load_model(
    base_url: str,
    model: str,
    context: int,
    ollama: dict[str, Any],
    active_connection: list[HTTPConnection],
    *,
    candidate: bool,
) -> dict[str, Any]:
    if not candidate:
        return generation_probe(base_url, model, "", context, ollama, active_connection)
    return http_json(
        base_url,
        "/api/chat",
        payload={
            "model": model,
            "messages": [{"role": "user", "content": ""}],
            "stream": False,
            "keep_alive": ollama["fit"]["keep_alive"],
            "options": {
                "num_ctx": context,
                "num_predict": ollama["fit"]["num_predict"],
            },
        },
        timeout=ollama["fit"]["request_timeout_seconds"],
        active_connection=active_connection,
    )


def unload_own_model(base_url: str, model: str, timeout: float) -> None:
    http_json(
        base_url,
        "/api/generate",
        payload={"model": model, "prompt": "", "keep_alive": 0, "stream": False},
        timeout=timeout,
    )


def pull_model(base_url: str, model: str, timeout: float) -> None:
    parsed = urlparse(base_url)
    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
    try:
        body = json.dumps({"model": model, "stream": True}).encode()
        connection.request(
            "POST",
            "/api/pull",
            body,
            {"Content-Type": "application/json", "Accept": "application/x-ndjson"},
        )
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Ollama pull for {model} returned HTTP {response.status}")
        for line in response:
            if not line.strip():
                continue
            progress = json.loads(line.decode())
            if isinstance(progress, dict) and progress.get("error"):
                raise RuntimeError(f"Ollama pull for {model} failed: {progress['error']}")
    except (OSError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Ollama pull for {model} failed: {error}") from error
    finally:
        connection.close()


def timeline_summary(path: Path, baseline_swap: int) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            item = json.loads(line)
            if isinstance(item, dict):
                samples.append(item)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read monitoring timeline {path}: {error}") from error
    pressure = [
        item["pressure_level"] for item in samples if isinstance(item.get("pressure_level"), int)
    ]
    swap = [
        item["swap_used_bytes"] for item in samples if isinstance(item.get("swap_used_bytes"), int)
    ]
    warnings = sorted(
        {
            warning
            for item in samples
            for warning in item.get("warnings", [])
            if isinstance(warning, str)
        }
    )
    return {
        "peak_pressure_level": max(pressure) if pressure else None,
        "swap_delta_bytes": max(0, max(swap) - baseline_swap) if swap else 0,
        "warnings": warnings,
    }


def monitor_until_baseline(
    monitor: FitMonitor,
    base_url: str,
    policy: dict[str, Any],
    baseline_swap: int,
) -> bool:
    deadline = time.monotonic() + policy["ollama"]["fit"]["recovery_timeout_seconds"]
    while time.monotonic() < deadline:
        try:
            normal_pressure = (
                int(probe("pressure"))
                == policy["ollama"]["safety"]["memory_pressure_levels"]["normal"]
            )
            stable_swap = swap_used_bytes(probe("swap")) <= baseline_swap
            loaded = http_json(
                base_url,
                "/api/ps",
                timeout=policy["ollama"]["safety"]["ollama_unresponsive_seconds"],
            ).get("models", [])
            if normal_pressure and stable_swap and loaded == []:
                return True
        except (RuntimeError, ValueError):
            pass
        time.sleep(policy["ollama"]["safety"]["pressure_sample_seconds"])
    return False


def live_verify(
    report: dict[str, Any],
    policy: dict[str, Any],
    base_url: str,
    *,
    only: str | None,
    deep: bool,
    allow_pull: bool,
) -> tuple[list[dict[str, Any]], int]:
    ollama = policy["ollama"]
    fit = ollama["fit"]
    context = report["machine"]["context"]
    unresolved = [item for item in report["configured_models"] if not item["resolution_verified"]]
    if unresolved:
        verdicts = [
            {
                "model": item["resolved_name"],
                "verdict": "inconclusive",
                "reason": item.get("resolution_error", "custom model base is unresolved"),
            }
            for item in unresolved
        ]
        verdicts.extend(
            {
                "model": item["name"],
                "verdict": "not_tested",
                "reason": "configured custom model identity is unresolved",
            }
            for item in report["candidates"]
        )
        return verdicts, 2
    existing = [
        item["resolved_name"]
        for item in report["configured_models"]
        if item.get("verdict") == "candidate"
    ]
    candidates = [item["name"] for item in report["candidates"] if item["name"] not in existing]

    def outcome_for(model: str) -> dict[str, Any]:
        configured_result = next(
            (item for item in report["configured_models"] if item["resolved_name"] == model),
            None,
        )
        return configured_result or report["outcomes"].get(model, {})

    models = order_models(existing, candidates, outcome_for)
    if only:
        models = [model for model in models if model == only]
        if not models:
            raise SkipCheck(f"--only model is not a pre-filter candidate: {only}")
    max_models = fit["max_models_per_run"]
    journal = journal_path()
    previous = read_journal(journal)
    suspected = previous.get("started")
    verdicts: list[dict[str, Any]] = []
    if suspected:
        verdicts.append(
            {
                "model": suspected.get("model"),
                "verdict": "suspected_hang",
                "reason": "previous run ended after journaling started",
            }
        )
    models = [model for model in models if not suspected or model != suspected.get("model")]
    for model in models[:max_models]:
        is_existing = model in existing
        attempts = fit["existing_attempts"] if is_existing else fit["candidate_attempts"]
        installed = installed_models(base_url, fit["request_timeout_seconds"])
        if not is_installed(model, installed):
            if not allow_pull:
                verdicts.append(
                    {"model": model, "verdict": "not_tested", "reason": "model is not installed"}
                )
                continue
            try:
                normal_preflight(base_url, policy, context, fit["request_timeout_seconds"])
            except RuntimeError as error:
                raise SkipCheck(
                    f"preflight could not establish a safe baseline before pull: {error}"
                ) from error
            weights = outcome_for(model).get("weights_bytes", 0)
            if weights > fit["max_pull_gib"] * GIB:
                verdicts.append(
                    {"model": model, "verdict": "not_tested", "reason": "model exceeds pull limit"}
                )
                continue
            pull_model(base_url, model, fit["pull_timeout_seconds"])
            installed = installed_models(base_url, fit["request_timeout_seconds"])
            if not is_installed(model, installed):
                raise SkipCheck(f"Ollama pull completed but {model} is not installed")
        attempt = 0
        while attempt < attempts:
            attempt += 1
            try:
                preflight, watch_set = normal_preflight(
                    base_url, policy, context, fit["request_timeout_seconds"]
                )
            except (RuntimeError, ValueError) as error:
                raise SkipCheck(
                    f"preflight could not establish a safe baseline: {error}"
                ) from error
            estimate = outcome_for(model).get("estimate_bytes", 0)
            admission_check(base_url, estimate, fit, ollama["safety"])
            timeline = REPORT_DIR / f"timeline-{model.replace(':', '-')}-{attempt}.jsonl"
            active_connection: list[HTTPConnection] = []
            monitor = FitMonitor(
                base_url=base_url,
                policy=policy,
                timeline=timeline,
                watch_set=watch_set,
                baseline_swap=preflight["baseline_swap_bytes"],
                active_connection=active_connection,
                model=model,
                model_loaded=threading.Event(),
            )
            write_journal(
                journal,
                {
                    "started": {
                        "model": model,
                        "estimate_bytes": estimate,
                        "started_at": timestamp(),
                    }
                },
            )
            loaded = False
            started = time.monotonic()
            result: dict[str, Any] = {"model": model, "attempt": attempt}
            result["preflight"] = preflight
            try:
                if monitor.trip:
                    raise SafetyStop(monitor.trip["reason"])
                monitor.start()
                if monitor.trip:
                    raise SafetyStop(monitor.trip["reason"])
                load_model(
                    base_url,
                    model,
                    context,
                    ollama,
                    active_connection,
                    candidate=not is_existing,
                )
                loaded = True
                monitor.model_loaded.set()
                ps = http_json(base_url, "/api/ps", timeout=fit["request_timeout_seconds"])
                entries = ps.get("models", [])
                if not isinstance(entries, list):
                    raise RuntimeError("Ollama /api/ps has no loaded-model list")
                item = next(
                    (
                        entry
                        for entry in entries
                        if isinstance(entry, dict) and model_matches(entry.get("name"), model)
                    ),
                    {},
                )
                size = item.get("size", 0)
                size_vram = item.get("size_vram", 0)
                context_length = item.get("context_length", 0)
                if not all(
                    isinstance(value, int) and value > 0
                    for value in (size, size_vram, context_length)
                ):
                    raise RuntimeError("Ollama /api/ps omitted loaded-model fit measurements")
                result.update(
                    {
                        "size_bytes": size,
                        "size_vram_bytes": size_vram,
                        "context_length": context_length,
                        "placement": "full_gpu" if size_vram == size else "partial_cpu",
                        "gpu_share": size_vram / size,
                        "headroom_bytes": outcome_for(model).get("usable_bytes", 0) - size_vram,
                        "load_seconds": time.monotonic() - started,
                    }
                )
                probes = functionality_prompts(model, policy["functionalities"])
                probe_results: list[dict[str, Any]] = []
                for functionality, prompt in probes:
                    if monitor.trip:
                        raise SafetyStop(monitor.trip["reason"])
                    generated = retry_in_place(
                        lambda model=model, prompt=prompt, active_connection=active_connection: (
                            generation_probe(
                                base_url,
                                model,
                                prompt,
                                context,
                                ollama,
                                active_connection,
                            )
                        ),
                        fit,
                        monitor,
                        require_response=True,
                    )
                    probe_results.append(
                        {
                            "functionality": functionality,
                            "prompt_passed": bool(generated.get("response")),
                            "prompt_eval_count": generated.get("prompt_eval_count", 0),
                            "eval_count": generated.get("eval_count", 0),
                            "eval_duration": generated.get("eval_duration", 0),
                        }
                    )
                if deep and not monitor.trip:
                    deep_prompt = " ".join(
                        ["context"] * int(context * fit["deep_prefill_fraction"])
                    )
                    generation_probe(
                        base_url, model, deep_prompt, context, ollama, active_connection
                    )
                retry_in_place(
                    lambda model=model, active_connection=active_connection: tool_probe(
                        base_url,
                        model,
                        context,
                        ollama,
                        active_connection,
                    ),
                    fit,
                    monitor,
                )
                result["probes"] = probe_results
                decode_counts = [
                    item["eval_count"]
                    for item in probe_results
                    if isinstance(item.get("eval_count"), int)
                ]
                durations = [
                    item["eval_duration"]
                    for item in probe_results
                    if isinstance(item.get("eval_duration"), int) and item["eval_duration"] > 0
                ]
                tps = (
                    min(
                        count / (duration / 1e9)
                        for count, duration in zip(decode_counts, durations, strict=False)
                    )
                    if decode_counts and durations
                    else 0
                )
                result["decode_tokens_per_second"] = tps
                if monitor.trip:
                    raise SafetyStop(monitor.trip["reason"])
                summary = timeline_summary(timeline, preflight["baseline_swap_bytes"])
                if (
                    result["placement"] == "full_gpu"
                    and context_length >= context
                    and tps >= fit["min_decode_tps"]
                    and not summary["warnings"]
                ):
                    result["verdict"] = "fits"
                else:
                    result["verdict"] = "fits_degraded"
                    result["reason"] = (
                        "partial offload, short context, slow decode, or warning signals"
                    )
            except SafetyStop as error:
                result["verdict"] = (
                    "does_not_fit"
                    if monitor.trip and monitor.trip["severity"] == "hard"
                    else "inconclusive"
                )
                result["reason"] = str(error)
            except ModelProbeFailure as error:
                result["verdict"] = "does_not_fit"
                result["reason"] = str(error)
            except RuntimeError as error:
                result["verdict"] = (
                    "does_not_fit"
                    if (monitor.trip and monitor.trip["severity"] == "hard")
                    or re.search(
                        r"out of memory|insufficient memory|metal",
                        str(error),
                        re.IGNORECASE,
                    )
                    else "inconclusive"
                )
                result["reason"] = str(error)
            finally:
                monitor.stop()
                if not loaded:
                    try:
                        currently_loaded = http_json(
                            base_url, "/api/ps", timeout=fit["request_timeout_seconds"]
                        ).get("models", [])
                        loaded = any(
                            isinstance(item, dict) and model_matches(item.get("name"), model)
                            for item in currently_loaded
                        )
                    except RuntimeError:
                        result["verdict"] = "inconclusive"
                unload_succeeded = not loaded
                if loaded:
                    try:
                        unload_own_model(
                            base_url,
                            model,
                            ollama["safety"]["ollama_unresponsive_seconds"],
                        )
                        unload_succeeded = True
                    except RuntimeError as error:
                        result["unload_error"] = str(error)
                        result["verdict"] = "inconclusive"
                        unload_succeeded = False
                monitor.model_loaded.clear()
                if monitor.trip:
                    result["trip"] = monitor.trip
                try:
                    summary = timeline_summary(timeline, preflight["baseline_swap_bytes"])
                    result.update(summary)
                except RuntimeError as error:
                    result["verdict"] = "inconclusive"
                    result["timeline_error"] = str(error)
                result["timeline"] = str(timeline.relative_to(REPO_ROOT))
                recovered = monitor_until_baseline(
                    monitor, base_url, policy, preflight["baseline_swap_bytes"]
                )
                result["recovered"] = recovered
                if not recovered:
                    result["verdict"] = "inconclusive"
                    result["reason"] = (
                        "machine did not return to baseline; stop and inspect manually"
                    )
                if unload_succeeded:
                    write_journal(
                        journal,
                        {
                            "finished": {
                                "model": model,
                                "finished_at": timestamp(),
                                "verdict": result.get("verdict"),
                            }
                        },
                    )
            verdicts.append(result)
            if (
                (monitor.trip and monitor.trip["severity"] == "hard")
                or not recovered
                or not unload_succeeded
            ):
                for remaining in models[models.index(model) + 1 :]:
                    verdicts.append(
                        {"model": remaining, "verdict": "not_tested", "reason": "safety stop"}
                    )
                return verdicts, 3
            if attempt == attempts and monitor.trip and monitor.trip["severity"] == "soft":
                result["verdict"] = "does_not_fit"
                result["reason"] = monitor.trip["reason"]
            if result.get("verdict") in {"fits", "fits_degraded", "does_not_fit"}:
                break
            if attempt < attempts:
                time.sleep(fit["cooldown_seconds"])
    for model in models[max_models:]:
        verdicts.append(
            {"model": model, "verdict": "not_tested", "reason": "run model limit reached"}
        )
    return verdicts, 0


def order_models(
    configured: list[str],
    candidates: list[str],
    outcome_for: Callable[[str], dict[str, Any]],
) -> list[str]:
    def footprint(name: str) -> int:
        return int(outcome_for(name).get("estimate_bytes", 0))

    return sorted(set(configured), key=footprint) + sorted(candidates, key=footprint)


def model_matches(actual: object, expected: str) -> bool:
    if not isinstance(actual, str):
        return False
    return (
        actual == expected
        or actual == f"{expected}:latest"
        or actual.removesuffix(":latest") == expected.removesuffix(":latest")
    )


def is_installed(model: str, installed: dict[str, Any]) -> bool:
    return model in installed or f"{model}:latest" in installed


def retry_in_place(
    action: Callable[[], dict[str, Any]],
    fit: dict[str, Any],
    monitor: FitMonitor,
    *,
    require_response: bool = False,
) -> dict[str, Any]:
    last_error: RuntimeError | None = None
    for attempt in range(fit["probe_attempts"]):
        if monitor.trip:
            raise SafetyStop(monitor.trip["reason"])
        try:
            response = action()
            if require_response and not response.get("response"):
                raise ModelProbeFailure("functionality probe returned an empty response")
            return response
        except RuntimeError as error:
            last_error = error
            if attempt + 1 < fit["probe_attempts"]:
                time.sleep(fit["cooldown_seconds"])
    if last_error:
        raise last_error
    raise RuntimeError("probe attempt policy allowed no attempts")


def compare_results(report: dict[str, Any], verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = {item["model"]: item for item in verdicts}
    configured = {
        item.get("resolved_name"): item.get("configured_name")
        for item in report["configured_models"]
    }
    additions = []
    for item in verdicts:
        if item.get("verdict") != "fits" or item["model"] in configured:
            continue
        candidate = next(
            (entry for entry in report["candidates"] if entry["name"] == item["model"]),
            {},
        )
        additions.append({**candidate, **item})
    removals = [
        {
            "model": name,
            "verdict": result.get("verdict", "not_tested"),
            "reason": result.get("reason"),
        }
        for name, result in outcomes.items()
        if name in configured and result.get("verdict") in {"does_not_fit", "suspected_hang"}
    ]
    for item in report["configured_models"]:
        if item.get("verdict") == "reject":
            removals.append(
                {
                    "model": item["configured_name"],
                    "verdict": "does_not_fit",
                    "reason": item.get("reason", "pre-filter rejected the configured model"),
                }
            )
    unverified = [
        item["name"]
        for item in report["candidates"]
        if outcomes.get(item["name"], {}).get("verdict")
        not in {"fits", "does_not_fit", "suspected_hang"}
    ]
    unverified.extend(
        item["configured_name"]
        for item in report["configured_models"]
        if (
            not item["resolution_verified"]
            or outcomes.get(item["resolved_name"], {}).get("verdict")
            in {"not_tested", "inconclusive"}
        )
    )
    return {
        "candidates_to_add": additions,
        "candidates_to_remove": removals,
        "unverified_candidates": sorted(set(unverified)),
    }


def save_report(report: dict[str, Any]) -> Path:
    destination = report_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return destination


def forget_journal() -> None:
    path = journal_path()
    if path.exists():
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-fit", action="store_true")
    parser.add_argument("--allow-pull", action="store_true")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--only")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--forget-journal", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.forget_journal:
            forget_journal()
            print("Crash journal cleared.")
            if not (args.verify_fit or probe("model_load_opt_in") == "1"):
                return 0
        policy = load_policy()
        config = load_config()
        ollama = policy["ollama"]
        base_url, configured = ollama_settings(config, policy)
        if probe("system_name") != "Darwin":
            raise SkipCheck("local Ollama fit check requires macOS arm64")
        if probe("arm64") != "1":
            raise SkipCheck("local Ollama fit check requires macOS arm64")
        timeout = ollama["discovery"]["timeout_seconds"]
        try:
            version = http_json(base_url, "/api/version", timeout=timeout)
            plan = plan_candidates(policy, config, base_url, timeout=timeout)
        except RuntimeError as error:
            raise SkipCheck(f"Ollama or model discovery is unavailable: {error}") from error
        report: dict[str, Any] = {
            "schema_version": 1,
            "ollama_version": version.get("version", "unknown"),
            "created_at": timestamp(),
            "plan": plan,
            "machine": plan["machine"],
            "candidates_to_add": [],
            "candidates_to_remove": [],
            "unverified_candidates": plan["unverified_candidates"],
        }
        print(format_plan(plan))
        verify_fit = args.verify_fit or probe("model_load_opt_in") == "1"
        if not verify_fit:
            print("Planning only. No model was loaded; use --verify-fit to opt in.")
            save_report(report)
            return 2
        acknowledgment = " Operator passed --yes." if args.yes else ""
        print(
            "FIT VERIFICATION: save work, use AC power, close memory-heavy apps, "
            f"and leave the machine idle. Press Ctrl-C to stop.{acknowledgment} "
            f"Starting in {ollama['fit']['verification_countdown_seconds']} seconds."
        )
        time.sleep(ollama["fit"]["verification_countdown_seconds"])
        probe("termination_handlers")
        verdicts, safety_exit = live_verify(
            plan,
            policy,
            base_url,
            only=args.only,
            deep=args.deep,
            allow_pull=args.allow_pull,
        )
        report["fit_verdicts"] = verdicts
        compared = compare_results(plan, verdicts)
        report.update(compared)
        destination = save_report(report)
        print(json.dumps(compared, indent=2))
        print(f"Evidence: {destination}")
        if safety_exit:
            print("Safety stop. Inspect evidence and recover the machine manually.")
            return 3
        if compared["candidates_to_add"] or compared["candidates_to_remove"]:
            return 1
        if compared["unverified_candidates"]:
            return 2
        return 0
    except SkipCheck as error:
        print(f"OLLAMA MODEL DRIFT SKIP: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; fit run is stopping. Inspect the ignored evidence directory.")
        return 3
    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        print(f"OLLAMA MODEL DRIFT CHECK FAILED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
