# Spec: Ollama model drift

## Goal

Provide an opt-in, developer-only check that reports local Ollama models which
fit the configured OpenCode context and the supported reference machine. The
check is observational by default and never changes OpenCode, operating-system,
or Ollama configuration.

## Functional requirements

1. Load a version-2 `models_policy.json`. Share the coding, cybersecurity and
   general-purpose functionality definitions between providers; the Ollama
   policy defines its required capabilities, exclusions, discovery, machine,
   fit and safety settings.
2. Discover only bounded official Ollama library models matching the requested
   tool capability. Enumerate model tags from each official library tag page;
   obtain exact weight sizes from registry manifests without downloading model
   layers. Exclude cloud, remote, MLX and community models, and honor the
   explicit ignore list. Follow a policy-bounded number of HTTPS redirects
   only when they remain on the official `ollama.com` host. If a family
   exceeds the policy tag bound or discovery fails, return `skip`, never an
   incomplete or empty successful discovery.
3. Read machine RAM, chip, macOS version, power state, and GPU memory budget
   without privilege. Resolve the budget in this order: Ollama-reported budget,
   Metal recommended working-set size, policy override, then the policy
   fraction of RAM. Report which source was used. Derive tested context from
   the largest `limit.context` configured for Ollama in `opencode.json`.
4. Pre-filter without loading models. Estimate weights, context-dependent KV
   cache and runtime overhead when metadata permits. Account for layer count,
   KV-head count, head dimension, sliding-window attention and KV type.
   Unknown metadata uses a documented coarse estimate; candidates with no
   available architecture metadata are compared using weights alone and are
   marked coarse. Reject a model only when its weights alone exceed usable
   memory or a complete estimate exceeds usable memory. The configured
   `gemma4-12b-32k` reference model must be a candidate on the policy reference
   profile.
5. Compare model identity after resolving configured custom variants through
   `/api/show` Modelfile metadata. Report `candidates_to_add`,
   `candidates_to_remove`, and `unverified_candidates`; configured models
   that do not fit or meet policy are reported for removal, while unverified
   candidates prevent a pass.
6. Default invocation and the pytest live test perform discovery and planning
   only. Loading requires explicit `--verify-fit` or
   `SDD4GH_ALLOW_MODEL_LOAD=1`; the live test is marked `live` and is not part
   of default pytest or CI.
7. Before a live load, require macOS arm64, loopback Ollama URL, non-CI,
   explicit consent, AC/battery and Low Power Mode observation, empty
   `/api/ps`, stable normal pressure, low swap, healthy responsiveness
   canaries, and a clean crash journal. Refuse the run if preflight fails.
8. Use a single fixed-allow-list probe wrapper for every OS/process interaction.
   It may only perform the read-only probes in this specification and issue
   the test's own bounded Ollama requests, cancel its own request, and unload
   only a model this run loaded. It must not signal, kill, suspend, renice,
   elevate privilege, change settings, create/remove/copy models, or pull
   without `--allow-pull`.
9. Record a flushed JSONL monitoring timeline and a fsynced crash journal
   outside tracked files. Monitor pressure, swap growth, timer lag, process
   creation latency, watched-process exits, Ollama health, Ollama/Metal errors,
   placement, and thermal/power status. A trip stops requests, unloads only the
   run's own model, observes recovery, and leaves remaining models untested.
   No automated system recovery is permitted.
10. Test configured models before candidates, ordered by estimated footprint;
    cap the run at policy `max_models_per_run`. Configured models receive the
    policy number of retries for soft trips or inconclusive outcomes after
    cooldown and fresh preflight; candidates receive one attempt. Never retry
    a hard trip or suspected hang. Journal each load as started before it and
    finished after unloading.
11. Classify live results as `fits`, `fits_degraded`, `does_not_fit`,
    `suspected_hang`, `inconclusive`, or `not_tested`. Only fully GPU-resident,
    probe-passing models with sufficient context, decode rate, no trip, and no
    warn-level signal are `fits`. Degraded configured models are warnings, not
    removal candidates.
12. Return exit codes 0 for no drift, 1 for drift, 2 for skip/inconclusive, and
    3 for a safety stop. Reports include machine and Ollama versions, GPU-budget
    source, estimates, tested context, probe results, load time, throughput,
    peak pressure, swap delta, and memory headroom. Never modify `opencode.json`.
13. Use only the Python standard library. Tests use saved fixtures and mocks;
    no automated test loads a model or accesses a live endpoint.

## Policy decisions and calibration

The policy values in `models_policy.json` are initial operating limits from
issue #31, not experimentally validated guarantees. They are read from policy
and are not duplicated as numeric thresholds in code. The optional live test
must be supervised on AC power with work saved and memory-heavy applications
closed before the first run. Calibration findings may change policy values in
a later reviewed change.

The v1 reference profile is MacBook Air, Apple M4, 16 GiB unified memory.
Other machine profiles are out of scope. An Ollama-reported GPU budget is used
only when its response provides an unambiguous numeric budget; otherwise the
next source is tried. Metal budget probing is best-effort and unprivileged.
Policy override and RAM-fraction fallback are explicit reportable sources.

When remote architecture metadata cannot be read safely without downloading
weights, the model receives a coarse weights-only fit estimate. This may leave
models unverified; the check must not convert missing metadata or failed
discovery into a pass.

## Out of scope

- Applying candidates or changing `opencode.json`.
- Other machine profiles, cloud/community/MLX models, quality benchmarking, or
  GPU-side UI-stutter detection.
- Changing GPU memory limits, system settings, or other applications' state.
- Automatic model pulling unless the operator explicitly supplies
  `--allow-pull`.

## Traceability

- Source issue: [#31](https://github.com/hlsekowski/sdd4gh/issues/31)
- Decision: [ADR 0010](../../docs/adr/0010-opencode-coding-agent.md)
- Implementation: [`scripts/check_ollama_model_drift.py`](../../scripts/check_ollama_model_drift.py)
- Unit tests: [`test_check_ollama_model_drift.py`](../../tests/unit/scripts/test_check_ollama_model_drift.py)
- Supervised live test: [`test_ollama_model_drift.py`](../../tests/live/test_ollama_model_drift.py)
