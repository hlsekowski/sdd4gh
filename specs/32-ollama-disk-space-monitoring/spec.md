# Spec: Ollama model-store disk-space monitoring

## Goal

Protect the filesystem used by Ollama model storage during supervised fit
verification. This extends issue #31 without changing the planning-only
behavior or modifying any files on the monitored volume.

## Functional requirements

1. Resolve the Ollama model-store directory in this order: explicit
   `ollama.model_store_path` policy value, the `OLLAMA_MODELS` environment
   variable, then `~/.ollama/models`. Record the resolved path and source in
   fit evidence. If Ollama has a separate environment, the operator must set
   the policy override to its actual model-store directory. Do not inspect
   another process's command line or environment.
2. Measure the directory's filesystem using the standard-library `statvfs`
   operation. Available bytes are `f_bavail * f_frsize`; total bytes are
   `f_blocks * f_frsize`; available percentage is available bytes divided by
   total bytes. Do not use a fixed-size estimate or inspect unrelated volumes.
3. Before each model pull and each model load, take a fresh measurement.
   Missing, inaccessible, invalid, or zero-capacity measurements stop the run
   before the operation; never assume that the disk is safe.
4. Read thresholds from `models_policy.json`. At 20% or less, but above 15%,
   emit a warning and continue. At 15% or less, stop with safety exit code 3;
   the stop takes precedence over the warning threshold.
5. On a stop, print and save completed model results and the disk measurement
   that caused the stop. Mark the current and remaining models `not_tested`;
   do not discard earlier results. The ignored report remains the source of
   full evidence.
6. Disk monitoring is fit-verification-only. It does not modify, delete, or
   reclaim files, and it does not run in default planning or ordinary pytest.
7. Thresholds are policy values, not duplicated in implementation code. Use
   only the Python standard library.

## Out of scope

- Monitoring unrelated mounted volumes.
- Estimating future model download size or blocking solely on an expected
  download footprint.
- Deleting Ollama models, logs, caches, or other files to recover space.
- Continuous disk sampling during model generation; checks occur before
  storage-affecting pulls and loads.

## Traceability

- Source issue: [#32](https://github.com/hlsekowski/sdd4gh/issues/32)
- Parent behavior: [Ollama model-drift spec](../31-ollama-model-drift/spec.md)
- Decision: [ADR 0010](../../docs/adr/0010-opencode-coding-agent.md)
- Implementation: [`scripts/check_ollama_model_drift.py`](../../scripts/check_ollama_model_drift.py)
- Unit tests: [`test_check_ollama_model_drift.py`](../../tests/unit/scripts/test_check_ollama_model_drift.py)
