# Plan: NVIDIA model drift

1. Add the machine-readable model policy and update the ADR 0010 contract.
2. Implement a standard-library-only drift checker under `scripts/`.
3. Add mocked unit tests for discovery, filtering, retry, comparison, and reporting.
4. Add a pytest live test marked `live`; the test uses the drift checker and is
   excluded from default pytest runs.
5. Document the explicit invocation command.
6. Run the full repository validation set, commit, push, and open a PR.
