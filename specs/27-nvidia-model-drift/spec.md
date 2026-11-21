# Spec: NVIDIA model drift

## Goal

Provide an explicitly invoked, developer-only check that identifies NVIDIA
models which should be considered for addition to or removal from
`opencode.json`.

## Functional requirements

1. Load the functionality policy from repository-root `models_policy.json`.
2. Discover NVIDIA models from `integrate.api.nvidia.com/v1/models`.
3. If catalog discovery fails or is incomplete, use the configured NVIDIA build
   catalog URL as a fallback.
4. Filter discovered models against the policy functionality name patterns.
5. Smoke-test matched models through the NVIDIA OpenAI-compatible chat endpoint.
6. Retry configured models five times and newly discovered candidates three
   times by default, with a configurable delay.
7. Compare smoke-verified candidates with NVIDIA model IDs configured in
   `opencode.json`.
8. Report model names and, for additions, catalog/build details and available
   context/output limits. Never modify `opencode.json`.
9. Fail with a structured report if either candidate list is non-empty.

## Out of scope

- Automatic changes to `opencode.json`.
- Standard local or CI pytest execution.
- Paid-provider usage or mutation of provider billing settings.
- Vendor opinion aggregation beyond details available from NVIDIA catalogs.
