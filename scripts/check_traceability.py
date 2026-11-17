#!/usr/bin/env python3
"""Check spec → code → test traceability.

ADR 0001 makes the ADR set the specification: every module in
``src/sdd4gh/`` mirrors a decision in ``docs/adr/``, and every decision
names the code and tests that implement it. This script enforces that
traceability mechanically, so a module added without a covering decision,
or a decision implemented without a test, fails locally instead of
reaching review.

The rules enforced here are the ones ADR 0001 and ADR 0002 state in
prose; nothing new is decided by this script.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SRC_ROOT = Path("src/sdd4gh")
TESTS_ROOT = Path("tests")
ADR_DIR = Path("docs/adr")

# Test helpers are not verification of a decision.
TEST_HELPERS = ("__init__.py", "http.py")

# ADR citation forms accepted in a module or test docstring:
#   "ADR 0004", "ADR 0004 §3", "docs/adr/0004-worker-task-model.md"
ADR_NUMBER = re.compile(r"ADR (\d{4})")
ADR_PATH = re.compile(r"adr/(\d{4})-")

# Modules that legitimately carry no ADR citation, with the reason.
# ports.py declares the injection port ADR 0002 §"Shared modules" names;
# it is a structural contract, not an implementation of one decision.
UNCITED_MODULE_ALLOWLIST: dict[str, str] = {
    "src/sdd4gh/contracts/ports.py": (
        "structural port named by ADR 0002 'Shared modules'; implements no single decision"
    ),
}

# ADRs that decide process or policy without a module of their own.
# Their verification is the ADR-invariant and contract tests, which cite
# them directly, so they are not required to have a citing module.
NO_MODULE_ADR_ALLOWLIST: set[int] = {
    1,  # the decision to adopt SDD; verified by this checker
    2,  # the layering decision; verified by code review per ADR 0002
    9,  # LangGraph selection; gated by the C9 dependency gate, no module yet
    10,  # OpenCode selection; the coding agent runs outside the framework
    11,  # Kubernetes worker hosting; local-cluster milestone, no module yet
}


def tracked_python(root: Path) -> list[Path]:
    """Python files tracked by git under ``root``."""
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    return [path for name in result.stdout.split() if (path := Path(name)).is_relative_to(root)]


def source_modules() -> list[Path]:
    return [path for path in tracked_python(SRC_ROOT) if path.name != "__init__.py"]


def test_files() -> list[Path]:
    return [path for path in tracked_python(TESTS_ROOT) if path.name not in TEST_HELPERS]


def adr_files() -> dict[int, Path]:
    """ADR number → path, for every ADR file present."""
    found: dict[int, Path] = {}
    for path in sorted((REPO_ROOT / ADR_DIR).glob("*.md")):
        match = re.match(r"(\d{4})-", path.name)
        if match:
            found[int(match.group(1))] = path
    return found


def read(path: Path) -> str:
    """Read a repo-relative path against the current REPO_ROOT."""
    return (REPO_ROOT / path).read_text()


def cited_adrs(text: str) -> set[int]:
    """ADR numbers a file's text cites, in either accepted form."""
    return {int(m.group(1)) for m in ADR_NUMBER.finditer(text)} | {
        int(m.group(1)) for m in ADR_PATH.finditer(text)
    }


def module_name(path: Path) -> str:
    """Dotted module name for a source path, e.g. sdd4gh.domain.pr_checks."""
    parts = list(path.with_suffix("").parts)
    return ".".join(parts[parts.index("sdd4gh") :])


def imported_modules(text: str) -> set[str]:
    """sdd4gh modules a test file imports."""
    return set(re.findall(r"^\s*(?:from|import)\s+(sdd4gh[\w.]*)", text, re.MULTILINE))


def check_numbering(adrs: dict[int, Path]) -> list[str]:
    """ADR numbers are contiguous and never reused (ADR 0001 §1)."""
    if not adrs:
        return ["docs/adr/: no ADR files found"]
    numbers = sorted(adrs)
    expected = list(range(1, numbers[-1] + 1))
    missing = sorted(set(expected) - set(numbers))
    errors = []
    if missing:
        errors.append(
            "docs/adr/: ADR numbering is not contiguous — missing "
            + ", ".join(f"{n:04d}" for n in missing)
            + " (ADR 0001 §1: numbers are contiguous and never reused)"
        )
    return errors


def check_modules_cite_adr(adrs: dict[int, Path]) -> list[str]:
    """Every source module cites the ADR it mirrors (ADR 0001 §2)."""
    errors = []
    for path in source_modules():
        if str(path) in UNCITED_MODULE_ALLOWLIST:
            continue
        cited = cited_adrs(read(path))
        if not cited:
            errors.append(
                f"{path}: cites no ADR — add the decision it mirrors to the module "
                f"docstring, or allowlist it in scripts/check_traceability.py with a reason"
            )
        else:
            unknown = sorted(cited - set(adrs))
            for number in unknown:
                errors.append(f"{path}: cites ADR {number:04d}, which has no file in docs/adr/")
    return errors


def check_tests_cite_adr(adrs: dict[int, Path]) -> list[str]:
    """Every test file cites the ADR it verifies (ADR 0001 §3)."""
    errors = []
    for path in test_files():
        cited = cited_adrs(read(path))
        if not cited:
            errors.append(
                f"{path}: cites no ADR — name the decision it verifies in the module "
                f"docstring, or allowlist it in scripts/check_traceability.py with a reason"
            )
        else:
            unknown = sorted(cited - set(adrs))
            for number in unknown:
                errors.append(f"{path}: cites ADR {number:04d}, which has no file in docs/adr/")
    return errors


def check_adrs_have_code(adrs: dict[int, Path]) -> list[str]:
    """Every implemented ADR names the code that implements it (ADR 0001 §1)."""
    cited_by_code: set[int] = set()
    for path in source_modules():
        cited_by_code |= cited_adrs(read(path))

    errors = []
    for number, path in sorted(adrs.items()):
        if number in NO_MODULE_ADR_ALLOWLIST:
            continue
        if number not in cited_by_code:
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: no module in src/sdd4gh/ cites it — "
                f"add the decision to the implementing module's docstring, or allowlist "
                f"it in scripts/check_traceability.py with a reason"
            )
    return errors


def check_adrs_have_tests(adrs: dict[int, Path]) -> list[str]:
    """Every ADR with implementing code has a test that verifies it.

    A test verifies an ADR either by citing it directly, or by importing a
    module that cites it — the import is the code path the test exercises.
    """
    module_adrs: dict[int, set[str]] = {}
    for path in source_modules():
        for number in cited_adrs(read(path)):
            module_adrs.setdefault(number, set()).add(module_name(path))

    test_adrs: set[int] = set()
    for path in test_files():
        test_adrs |= cited_adrs(read(path))

    errors = []
    for number, modules in sorted(module_adrs.items()):
        if number in test_adrs:
            continue
        covering = [
            path
            for path in test_files()
            if any(
                imported == module or imported.startswith(module + ".")
                for imported in imported_modules(read(path))
                for module in modules
            )
        ]
        if not covering:
            errors.append(
                f"{adrs[number].relative_to(REPO_ROOT)}: implemented by "
                f"{len(modules)} module(s) but no test cites or imports them — "
                f"add a test that names this ADR"
            )
    return errors


def check_dependencies_linked(adrs: dict[int, Path]) -> list[str]:
    """An ADR that depends on another links it in Related (ADR 0001 §4)."""
    errors = []
    for number, path in sorted(adrs.items()):
        text = read(path)
        context = text.split("## Decision")[0]
        related = text.split("## Related")[-1]
        declared = cited_adrs(context) - {number}
        linked = cited_adrs(related) | {
            int(m.group(1)) for m in re.finditer(r"\]\((\d{4})-", related)
        }
        for dependency in sorted(declared - linked):
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: Context depends on ADR "
                f"{dependency:04d} but Related does not link it — "
                f"add the link (ADR 0001 §4)"
            )
    return errors


def main() -> int:
    adrs = adr_files()
    modules = source_modules()
    tests = test_files()
    print(
        f"Checking traceability across {len(adrs)} ADRs, "
        f"{len(modules)} source modules and {len(tests)} test files..."
    )

    errors: list[str] = []
    errors += check_numbering(adrs)
    errors += check_modules_cite_adr(adrs)
    errors += check_tests_cite_adr(adrs)
    errors += check_adrs_have_code(adrs)
    errors += check_adrs_have_tests(adrs)
    errors += check_dependencies_linked(adrs)

    if errors:
        print(f"\n❌ Found {len(errors)} traceability problem(s):")
        for error in errors:
            print(f"  {error}")
        return 1

    print("\n✅ Spec → code → test traceability holds!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
