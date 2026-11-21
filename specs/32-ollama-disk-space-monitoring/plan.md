# Plan: Ollama model-store disk-space monitoring

1. Record the issue #32 disk-space safety contract in ADR 0010 and this spec.
2. Add model-store path selection and warning/stop limits to
   `models_policy.json`.
3. Measure available space through the fixed read-only host-probe boundary and
   gate every pull and model load.
4. Preserve and print partial results on a safety stop; mark later models
   untested.
5. Add mocked tests for path selection, measurement, threshold boundaries,
   operation gating, and partial-result preservation.
6. Update developer/testing documentation, traceability, and changelog.
7. Run all documented checks, push the change to PR #33, and verify CI.
