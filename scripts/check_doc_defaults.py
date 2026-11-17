#!/usr/bin/env python3
"""Check documented defaults match the code defaults they name.

A document that names a constant, a default value or a local-provider
endpoint is making a claim about code. When the code moves or the value
changes, the document silently becomes wrong and a reader trusts it. This
script resolves each such claim against the source tree and fails on the
ones that no longer hold.

The rules enforced here are the ones the ADRs already state: ADR 0002
§"No-Cost AI Rules" (SN1) records the local provider and base URL
defaults, and ADR 0006 §2 records the correction-attempt cap. Nothing new
is decided by this script.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SRC_ROOT = Path("src/sdd4gh")

# Documentation roots whose claims are checked.
DOC_ROOTS = (Path("README.md"), Path("AGENTS.md"), Path("docs"))

# A markdown link whose label is a backticked symbol and whose target is a
# Python file: [`SYMBOL`](../src/sdd4gh/contracts/constants.py)
SYMBOL_LINK = re.compile(r"\[`([A-Za-z_][A-Za-z0-9_]*)`\]\(([^)]+\.py)\)")

# A backticked symbol followed, within one sentence, by a backticked
# source path: `MAX_CORRECTION_ATTEMPTS_PER_BATCH` ... `src/.../constants.py`
SYMBOL_NEAR_PATH = re.compile(r"`([A-Z][A-Z0-9_]{2,})`")
SOURCE_PATH = re.compile(r"`((?:\.\./)?(?:src|scripts|tests)/[^`]+\.py)`")
SENTENCE_WINDOW = 140

# A numeric claim about a constant: `MAX_CORRECTION_ATTEMPTS_PER_BATCH` (5)
SYMBOL_VALUE = re.compile(r"`([A-Z][A-Z0-9_]{2,})`\s*\((\d+)\)")

# The local-provider defaults ADR 0002 SN1 records. A document that states
# one of these must state the value the code actually uses.
LOCAL_BASE_URL = "http://127.0.0.1:11434/v1"
LOCAL_PROVIDER = "ollama"

# Claims that are intentionally not checked, with the reason.
ALLOWLIST: dict[tuple[str, str], str] = {}


def doc_files() -> list[Path]:
    """Markdown files tracked by git under the documentation roots."""
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    return [
        path
        for name in result.stdout.split()
        if (path := Path(name)) and any(path == root or root in path.parents for root in DOC_ROOTS)
    ]


def source_files() -> list[Path]:
    return sorted((REPO_ROOT / SRC_ROOT).rglob("*.py"))


def read(path: Path) -> str:
    """Read a repo-relative path against the current REPO_ROOT."""
    return (REPO_ROOT / path).read_text()


def defines_symbol(path: Path, symbol: str) -> bool:
    """True when ``path`` defines ``symbol`` as a module-level name."""
    text = read(path)
    patterns = (
        rf"^{re.escape(symbol)}\s*[:=]",
        rf"^def {re.escape(symbol)}\b",
        rf"^class {re.escape(symbol)}\b",
        rf"^{re.escape(symbol)}\s*=",
    )
    return any(re.search(pattern, text, re.MULTILINE) for pattern in patterns)


def symbol_value(path: Path, symbol: str) -> str | None:
    """The literal value assigned to ``symbol`` in ``path``, if any."""
    match = re.search(rf"^{re.escape(symbol)}\s*=\s*(.+)$", read(path), re.MULTILINE)
    return match.group(1).strip() if match else None


def find_symbol(symbol: str) -> list[Path]:
    """Source files that define ``symbol`` at module level."""
    return [path for path in source_files() if defines_symbol(path, symbol)]


def check_symbol_links(files: list[Path]) -> list[str]:
    """A linked symbol must be defined in the file the link points at."""
    errors = []
    for path in files:
        text = read(path)
        for match in SYMBOL_LINK.finditer(text):
            symbol, target = match.group(1), match.group(2)
            line = text[: match.start()].count("\n") + 1
            if (path, symbol) in ALLOWLIST:
                continue
            resolved = (REPO_ROOT / path.parent / target).resolve()
            if not resolved.exists():
                errors.append(f"{path}:{line}: `{symbol}` links to {target}, which does not exist")
                continue
            if not defines_symbol(resolved, symbol):
                where = find_symbol(symbol)
                hint = (
                    f" — it is defined in {where[0]}"
                    if len(where) == 1
                    else " — it is not defined anywhere in src/sdd4gh/"
                    if not where
                    else ""
                )
                errors.append(f"{path}:{line}: `{symbol}` is not defined in {target}{hint}")
    return errors


def check_symbol_paths(files: list[Path]) -> list[str]:
    """A symbol named next to a source path must be defined in that path."""
    errors = []
    for path in files:
        text = read(path)
        for match in SYMBOL_NEAR_PATH.finditer(text):
            symbol = match.group(1)
            if (path, symbol) in ALLOWLIST:
                continue
            window = text[match.end() : match.end() + SENTENCE_WINDOW]
            path_match = SOURCE_PATH.search(window)
            if not path_match:
                continue
            target = path_match.group(1)
            line = text[: match.start()].count("\n") + 1
            resolved = (REPO_ROOT / target.removeprefix("../")).resolve()
            if not resolved.exists():
                continue
            if not defines_symbol(resolved, symbol):
                where = find_symbol(symbol)
                hint = (
                    f" — it is defined in {where[0]}"
                    if len(where) == 1
                    else " — it is not defined anywhere in src/sdd4gh/"
                    if not where
                    else ""
                )
                errors.append(
                    f"{path}:{line}: `{symbol}` is documented as living in {target}{hint}"
                )
    return errors


def check_symbol_values(files: list[Path]) -> list[str]:
    """A numeric claim about a constant must match the constant's value."""
    errors = []
    for path in files:
        text = read(path)
        for match in SYMBOL_VALUE.finditer(text):
            symbol, claimed = match.group(1), match.group(2)
            if (path, symbol) in ALLOWLIST:
                continue
            definitions = find_symbol(symbol)
            if not definitions:
                continue
            line = text[: match.start()].count("\n") + 1
            actual = symbol_value(definitions[0], symbol)
            if actual is None:
                continue
            if claimed not in actual:
                errors.append(
                    f"{path}:{line}: `{symbol}` is documented as ({claimed}) "
                    f"but {definitions[0]} sets it to {actual}"
                )
    return errors


def check_local_defaults(files: list[Path]) -> list[str]:
    """A stated local endpoint or provider must match the code default."""
    errors = []
    for path in files:
        text = read(path)
        for i, line in enumerate(text.split("\n"), 1):
            if (path, line.strip()) in ALLOWLIST:
                continue
            for stated in re.findall(r"https?://127\.0\.0\.1:\d+(?:/v\d+)?", line):
                if stated != LOCAL_BASE_URL:
                    errors.append(
                        f"{path}:{i}: local endpoint {stated} does not match the "
                        f"code default {LOCAL_BASE_URL} (ADR 0002 SN1)"
                    )
            if re.search(r'provider\s*=\s*"([^"]+)"', line):
                for provider in re.findall(r'provider\s*=\s*"([^"]+)"', line):
                    if provider != LOCAL_PROVIDER:
                        errors.append(
                            f'{path}:{i}: provider "{provider}" is not the local '
                            f'default "{LOCAL_PROVIDER}" (ADR 0002 SN1)'
                        )
    return errors


def main() -> int:
    files = doc_files()
    print(f"Checking documented defaults across {len(files)} files...")

    errors: list[str] = []
    errors += check_symbol_links(files)
    errors += check_symbol_paths(files)
    errors += check_symbol_values(files)
    errors += check_local_defaults(files)

    if errors:
        print(f"\n❌ Found {len(errors)} documented-default mismatch(es):")
        for error in errors:
            print(f"  {error}")
        return 1

    print("\n✅ Documented defaults match the code!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
