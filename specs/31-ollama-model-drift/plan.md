# Plan: Ollama model drift

1. Define the local drift contract and safety boundary in the spec and ADR 0010.
2. Move shared model functionality definitions to policy schema version 2 and
   add the Ollama discovery, machine-fit, live-monitoring and safety policy.
3. Implement read-only discovery, metadata parsing, memory estimation,
   configured-variant matching and default plan reporting.
4. Implement the opt-in supervised fit verification, fixed probe allow-list,
   monitor, crash journal, teardown and exit classifications.
5. Add fixture-backed unit tests and a pytest live test excluded from defaults.
6. Document local drift policy, safe supervised invocation, traceability and
   changelog.
7. Run the full repository validation, then push and open a PR against `main`.
