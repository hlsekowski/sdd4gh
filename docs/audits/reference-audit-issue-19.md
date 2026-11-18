> **Purpose:** Records the repository-wide Markdown reference audit for issue #19.
> **Read when:** auditing reference integrity or reviewing the findings from issue #19.
> **Owns:** the evidence and exact repairs from this dated audit; it is a historical snapshot.

# Markdown reference audit - issue #19

**Audit date:** 2026-11-18
**Branch:** `docs/fix-markdown-reference-audit-issue-19`
**Issue:** [hlsekowski/sdd4gh#19](https://github.com/hlsekowski/sdd4gh/issues/19)

## Scope and method

Reviewed every tracked or unignored untracked Markdown file, including the
repository root, `docs/`, `.github/`, and `prompts/`. Checked local links,
heading fragments, backticked repository paths, ADR and numbered-section
citations, code-symbol references, GitHub issue/PR references, and external
URLs. For each existing target, compared the surrounding claim with the
target's content. GitHub records were checked with `gh`; external documentation
pages were fetched and their relevant content inspected.

The initial inventory contained the following 26 files:

| Area | Reviewed Markdown files |
|---|---|
| Root and project instructions | `AGENTS.md`, `CHANGELOG.md`, `README.md` |
| GitHub template | `.github/pull_request_template.md` |
| Prompts | `prompts/sentinel.md` |
| ADRs | `docs/adr/0001-spec-driven-development.md`, `docs/adr/0002-architecture-dependency-model.md`, `docs/adr/0003-local-development-workflow.md`, `docs/adr/0004-worker-task-model.md`, `docs/adr/0005-issue-process.md`, `docs/adr/0006-pr-process.md`, `docs/adr/0007-sdd-process.md`, `docs/adr/0008-workflow-runtime-and-model-routing.md`, `docs/adr/0009-langgraph-workflow-orchestration.md`, `docs/adr/0010-opencode-coding-agent.md`, `docs/adr/0011-kubernetes-worker-hosting.md`, `docs/adr/0012-litellm-model-routing.md` |
| Other documentation | `docs/ai_provider_policy.md`, `docs/constitution.md`, `docs/development.md`, `docs/documentation.md`, `docs/procedures/implement-issue.md`, `docs/specs/adr-0004-implementation-spec.md`, `docs/specs/adr-0010-implementation-spec.md`, `docs/testing.md`, `docs/workflow.md` |

This report is the 27th Markdown file. Its own repository references are also
covered by the repository-wide check.

## Findings and exact repairs

| Location and reference | Existence and contextual result | Evidence and exact repair | Confidence |
|---|---|---|---|
| `docs/adr/0008-workflow-runtime-and-model-routing.md:15`; `docs/procedures/implement-issue.md:11`; related provenance in ADRs 0009-0012 | `sdd4gh#55` does not exist. The source record [`qnagym#55`](https://github.com/hlsekowski/qnagym/issues/55) is closed and its [owner audit comment](https://github.com/hlsekowski/qnagym/issues/55#issuecomment-6801415189) records `APPLICABLE` for predecessor [`qnagym#57`](https://github.com/hlsekowski/qnagym/issues/57); that narrower audit did not replace issue #19's broader requirements. | Verified the owner verdict and predecessor scope; qualified historical references with `qnagym` and clarified that the source audit did not select the complete stack. The procedure now requires an issue-specific applicability gate only when the issue or accepted parent states one; it does not infer a gate from source-repository history. | High |
| `docs/adr/0008-workflow-runtime-and-model-routing.md:15,78,110-113`; `docs/adr/0009-langgraph-workflow-orchestration.md:15,53-54`; `docs/adr/0011-kubernetes-worker-hosting.md:13,15,23,48-49`; `docs/adr/0004-worker-task-model.md:331` | Bare issue numbers were ambiguous across repositories. `qnagym#9` is a closed local-only Kubernetes experiment; `sdd4gh#9` is open and concerns dropped-code documentation. `qnagym#98` is closed and proposed LangGraph without selecting a runtime. | Replaced shorthand with repository-qualified links, explicitly distinguished the unrelated `sdd4gh#9`, and described `qnagym#9` and `qnagym#98` as historical evidence rather than current sdd4gh work or a final runtime decision. | High |
| `docs/adr/0005-issue-process.md:5`; `docs/adr/0006-pr-process.md:211`; `docs/specs/adr-0004-implementation-spec.md:204`; `docs/adr/0008-workflow-runtime-and-model-routing.md:113`; `docs/adr/0012-litellm-model-routing.md:15,64` | `sdd4gh#39`, `sdd4gh#157`, and the unqualified `#13`/`#101` did not support the claims. `qnagym#13` is the closed PR Process source issue; `qnagym#101` is a merged PR introducing LiteLLM into ADR 0008. `sdd4gh#13` is unrelated. The unqualified `#157` was not a valid sdd4gh issue reference; [`qnagym#157`](https://github.com/hlsekowski/qnagym/issues/157) is a closed, separate-project implementation of push-and-PR creation. | Replaced the nonexistent `#39` with links to the two implementation files; removed the unsupported `#157` issue claim; qualified `qnagym#13` and `qnagym#101` and labeled the latter as a merged source-project PR. No equivalent sdd4gh issue was inferred. | High |
| `docs/adr/0003-local-development-workflow.md:9,186`; `docs/adr/0005-issue-process.md:71,76,130`; `docs/adr/0006-pr-process.md:13,15,23,74,120`; `docs/adr/0007-sdd-process.md:55,86`; `docs/specs/adr-0004-implementation-spec.md:230` | References to ADR 0003 sections 7-10 were invalid: the file has sections 1-6, with section 6 pointing to the PR Process. ADR 0006 is the current normative PR specification and has sections 1-5. | Removed the claim that ADR 0003 sections 6-10 were elevated, corrected citations to the corresponding ADR 0006 sections, and removed ADR 0006 headings that falsely identified themselves as ADR 0003 sections. Removed the stale follow-up note after confirming ADR 0003's Related list already points to ADR 0005 and §6 now points to ADR 0006. | High |
| `docs/constitution.md:20-21`; package-relative paths in `docs/adr/0002-architecture-dependency-model.md` | The constitution's `services/...` and `contracts/...` paths did not resolve from the repository root. ADR 0002 used package-relative paths without identifying their base. | Changed constitution paths to `src/sdd4gh/...` and stated that package-relative paths in ADR 0002 are relative to `src/sdd4gh/`. | High |
| `docs/testing.md:163,168-190`; `README.md:42` | The testing example named a nonexistent questions module/function and a nonexistent ADR 0005 heading. README's fixed “491 tests” count was stale. | Replaced the example with the existing `evaluate_issue` API and ADR 0005 section 3; replaced the stale count with the mocked-HTTP/no-live-model test description. | High |
| `.github/pull_request_template.md:17`; `docs/development.md:17-21` | The template required `CHANGELOG.md`, which did not exist. The owner was asked and answered “add” on issue #19. | Added root `CHANGELOG.md` with an Unreleased entry and documented its update convention in `docs/development.md`; retained the template requirement. | High |
| `docs/adr/0012-litellm-model-routing.md:39` | The cited LiteLLM image-security URL returned 404. | Replaced it with `https://docs.litellm.ai/docs/proxy/docker_image_security`, which returned 200 and documents LiteLLM image signatures and verification. | High |
| `docs/adr/0004-worker-task-model.md:53-56,331`; `README.md:33-36` | `#42` looked like a real issue number in an illustrative flow; shared symbols were named without their defining modules. | Replaced `#42` with a neutral `issue N` placeholder, qualified the historical Kubernetes issue, and linked each README symbol to its source module. | High |

## GitHub reference inventory

| GitHub reference | Verified result and contextual relevance |
|---|---|
| [hlsekowski/sdd4gh#1](https://github.com/hlsekowski/sdd4gh/issues/1) | Closed; OpenCode local endpoint provenance. |
| [hlsekowski/sdd4gh#9](https://github.com/hlsekowski/sdd4gh/issues/9) | Open; unrelated dropped-code documentation, not the Kubernetes experiment. |
| [hlsekowski/sdd4gh#12](https://github.com/hlsekowski/sdd4gh/issues/12) | Open; native OpenCode V2 configuration. |
| [hlsekowski/sdd4gh#13](https://github.com/hlsekowski/sdd4gh/issues/13) | Open; unrelated implementer task-report issue, not the PR Process source. |
| [hlsekowski/sdd4gh#15](https://github.com/hlsekowski/sdd4gh/issues/15) | Closed; zero-cost provider policy. |
| [hlsekowski/sdd4gh#19](https://github.com/hlsekowski/sdd4gh/issues/19) | Open; audit requirements baseline, with no linked parent. |
| [hlsekowski/sdd4gh#6](https://github.com/hlsekowski/sdd4gh/pull/6) | Merged; source PR named by issue #19. |
| [hlsekowski/qnagym#9](https://github.com/hlsekowski/qnagym/issues/9) | Closed; local-only Kubernetes experiment. |
| [hlsekowski/qnagym#13](https://github.com/hlsekowski/qnagym/issues/13) | Closed; source-project PR Process issue. |
| [hlsekowski/qnagym#55](https://github.com/hlsekowski/qnagym/issues/55) | Closed; owner audit containing the `APPLICABLE` verdict for #57 and initial technology plan. |
| [hlsekowski/qnagym#57](https://github.com/hlsekowski/qnagym/issues/57) | Closed; predecessor link/path audit, narrower than #19. |
| [hlsekowski/qnagym#98](https://github.com/hlsekowski/qnagym/issues/98) | Closed; LangGraph candidate, no runtime selected. |
| [hlsekowski/qnagym#101](https://github.com/hlsekowski/qnagym/pull/101) | Merged; introduced LiteLLM Proxy with Auto Routing into ADR 0008. |
| [hlsekowski/qnagym#157](https://github.com/hlsekowski/qnagym/issues/157) | Closed; separate-project push-and-PR safe effect, not evidence for the sdd4gh implementation spec. |

These are historical source-project records, not current sdd4gh backlog items.

The initial findings also included nonexistent or misleading local-repository
references: `sdd4gh#55`, `#39`, `#98`, and `#157`. They were removed or
qualified as detailed above. No direct commit-hash or branch-target URL was
found in the Markdown inventory.

## External URL inventory

The 17 non-GitHub HTTPS targets all returned HTTP 200 after the LiteLLM URL
correction. The target content was relevant to the label or claim:

- Workflow candidates: `https://docs.temporal.io/`,
  `https://docs.restate.dev/`, `https://docs.dbos.dev/`,
  `https://www.inngest.com/docs`, and `https://docs.hatchet.run/`.
- Selected technology documentation: `https://docs.langchain.com/oss/python/langgraph/overview`,
  `https://opencode.ai/docs/`, `https://kubernetes.io/docs/concepts/overview/`,
  `https://opencode.ai/config.json`, and
  `https://models.dev/model-schema.json`.
- LiteLLM routing and operation: `https://docs.litellm.ai/docs/proxy/auto_routing`,
  `https://docs.litellm.ai/docs/proxy/docker_quick_start#running-without-a-database`,
  and `https://docs.litellm.ai/docs/proxy/virtual_keys`. The pages confirm
  Auto Routing is beta, budget enforcement requires a database, and virtual
  keys require PostgreSQL.
- LiteLLM security evidence: `https://docs.litellm.ai/blog/security-townhall-updates`,
  `https://docs.litellm.ai/blog/security-incident-oct-21-2026`,
  `https://docs.litellm.ai/blog/security-incident-oct-21-2026-attack-chain`,
  and `https://docs.litellm.ai/docs/proxy/docker_image_security`. The incident
  pages support the cited compromised-release history; the image-security
  page documents signature verification.

The two `localhost` URLs and `http://127.0.0.1:11434/v1` are configuration
examples, not external references. They were checked against the documented
local-provider defaults instead.

## Automated coverage

`scripts/check_doc_links.py` checks repository-wide local Markdown links and
anchors, backticked repository-file paths, repository-owned branch-specific
`blob/` URLs, and ADR file/section references. The symbol/default checker now
uses the same repository-wide Markdown inventory, including prompts and GitHub
templates. External reachability and semantic relevance remain a manual review;
the checker intentionally does not claim to validate remote content.

## Final validation

| Command | Result |
|---|---|
| `pytest` | Passed: 549 tests |
| `ruff check . && ruff format --check .` | Passed: no lint issues; 115 files already formatted |
| `python3 -m mypy src/sdd4gh` | Passed: no issues in 43 source files |
| `python3 scripts/check_doc_links.py` | Passed: 27 Markdown files |
| `python3 scripts/check_doc_structure.py` | Passed: 22 documentation files |
| `python3 scripts/check_traceability.py` | Passed: 12 ADRs, 39 source modules, 38 test files |
| `python3 scripts/check_doc_defaults.py` | Passed: 27 Markdown files |
| `pre-commit run --all-files` | Passed: all hooks |
| `git diff --check` | Passed |
