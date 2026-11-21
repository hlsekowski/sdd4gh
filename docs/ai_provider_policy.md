# AI Provider Policy

> **Purpose:** Defines the project's zero-cost provider policy: local inference is one supported option, not the only permitted option; genuinely free hosted tiers are allowed with credential and billing safeguards.
> **Read when:** configuring, changing, or reviewing AI model providers, endpoints, credentials, or billing safeguards.
> **Owns:** the zero-cost provider policy, provider configuration standards, credential and billing safeguards, and the list of allowed provider categories.

## Status

Accepted

## Zero-cost provider policy

Model calls default to zero cost: no paid API usage, subscriptions, or billable usage to the project or developer. Local inference is one supported option, not the only permitted option. Genuinely free hosted tiers are allowed, subject to the credential and billing safeguards below.

### Allowed provider categories

| Category | Allowed | Conditions |
|---|---|---|
| Local inference (Ollama, llama.cpp, vLLM on loopback) | Yes | Endpoint must be a loopback/local address (`127.0.0.1`, `localhost`, `::1`). |
| Genuinely free hosted tier | Yes | Must not depend on a paid subscription. Must not permit accidental metered calls. No billable usage may be enabled by default. |
| Paid API / subscription / billable provider | No | Not authorized by default. Requires a separate decision and tested configuration. |

### Credential and billing safeguards

1. **No paid API keys in defaults.** Configuration files use env-var substitution (`{env:VARIABLE_NAME}`) with no default key value. No real secret is committed.
2. **Free tiers must not depend on a paid subscription.** A provider that requires entering payment details or a paid plan to access its free tier is not a genuinely free tier and is not allowed.
3. **No accidental metered calls.** Provider policies deny all providers by default and allow only explicitly approved zero-cost providers. A failure or unknown model must not fall through to a paid or cloud provider.
4. **Env override only.** Any override to a non-default provider must be set through environment variables, never in tracked files.

## Model drift monitoring

The repository may use an opt-in developer-only check to compare the NVIDIA
catalog and live model availability with `models_policy.json` and
`opencode.json`. It must:

- use only the no-charge NVIDIA account/key and never enable paid usage;
- make no standard CI or local pytest request;
- retry configured models more than newly discovered candidates because
  temporary catalog or rate-limit failures must not be mistaken for drift;
- report candidate additions and removals, with candidate details, but never
  mutate `opencode.json` automatically;
- fail if either candidate list is non-empty.

## Provider configuration

- Single config source: `opencode.json` at the repository root.
- OpenAI-compatible `base_url` + `model` + optional `api_key` boundary (constitution S6). No vendor SDKs.
- Provider policies deny all providers by default, then allow only approved zero-cost providers.
- `baseURL` uses `{env:OPENCODE_BASE_URL}`; `model` uses `{env:OPENCODE_MODEL}`.
- `env` lists credential variables with no default value.

## Related

- [Constitution S5: Zero-cost AI](constitution.md)
- [ADR 0010: OpenCode coding-agent execution](adr/0010-opencode-coding-agent.md)
- [ADR 0008: Workflow runtime and model-routing selection](adr/0008-workflow-runtime-and-model-routing.md)
- [ADR 0010 Implementation Specification](specs/adr-0010-implementation-spec.md)
- [ADR 0012: LiteLLM model routing](adr/0012-litellm-model-routing.md)
- [hlsekowski/sdd4gh#15](https://github.com/hlsekowski/sdd4gh/issues/15): define the zero-cost provider policy with local inference as an option
- [hlsekowski/sdd4gh#1](https://github.com/hlsekowski/sdd4gh/issues/1): configure OpenCode against a local model endpoint (ADR 0010)
