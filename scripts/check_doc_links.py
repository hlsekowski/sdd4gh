#!/usr/bin/env python3
"""Check documentation links and paths resolve.

Verifies that local Markdown references resolve across the repository.
"""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent


def _this_repo_blob_prefix() -> str:
    """Blob-URL prefix for this repository, derived from its git remote."""
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    slug = re.sub(r"\.git$", "", url)
    slug = re.sub(r"^git@github\.com:", "https://github.com/", slug)
    slug = re.sub(r"^https://github\.com/", "https://github.com/", slug)
    return f"{slug}/blob/"


# File suffixes that identify a backticked repository-file reference.
REPO_FILE_SUFFIXES = {".md", ".py", ".json", ".toml", ".yaml", ".yml", ".txt", ".sh"}
REPO_ROOTS = {"src", "tests", "scripts", "docs", "data", "example", ".github", "prompts"}

# Absolute blob/<branch> URLs to this repository are branch-dependent; use
# relative links. URLs to other repositories have no relative equivalent
# and are allowed.
REPO_BLOB_PREFIX = _this_repo_blob_prefix()

# Paths intentionally excluded from checking.
ALLOWLIST: set[str] = set()

MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
BACKTICK_PATH = re.compile(r"`([^`]+)`")
HEADING = re.compile(r"^#+\s+(.*)$", re.MULTILINE)
ADR_REFERENCE = re.compile(r"\bADR (\d{4})")
ADR_SECTION_REFERENCE = re.compile(
    r"\bADR (\d{4})\s+§{1,2}\s*(\d+)"
    r"(?:\s*[–-]\s*§{1,2}\s*(\d+))?"
)
NUMBERED_HEADING = re.compile(r"^#{2,6}\s+(\d+)[a-z]?(?:[.:)]|\s)", re.MULTILINE)


def tracked_markdown() -> list[Path]:
    """Tracked and unignored untracked Markdown files anywhere in the repository."""
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "*.md",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    return sorted(Path(name) for name in result.stdout.split("\0") if name)


def is_allowlisted(path: Path) -> bool:
    return any(path == Path(entry) or Path(entry) in path.parents for entry in ALLOWLIST)


def slugify(heading: str) -> str:
    """GitHub anchor slug: strip backticks, lowercase, drop punctuation."""
    text = re.sub(r"`([^`]*)`", r"\1", heading.strip()).lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text.strip())


def heading_slugs(path: Path) -> set[str]:
    return {slugify(m.group(1)) for m in HEADING.finditer(path.read_text())}


def looks_like_repo_path(text: str) -> bool:
    """A backticked string that names a repository path."""
    if text.startswith(("http://", "https://", "mailto:", "~", "$", "<", "/")):
        return False
    if "*" in text or " " in text or "\n" in text:
        return False
    file_path = text.partition("#")[0]
    if Path(file_path).suffix.lower() not in REPO_FILE_SUFFIXES:
        return False
    if file_path.startswith(("./", "../")):
        return True
    return Path(file_path).parent == Path(".") or Path(file_path).parts[0] in REPO_ROOTS


def edges(text: str, base: Path, root: Path) -> set[Path]:
    """Paths a document links to: markdown links, plus backticked repo paths.

    A link to a directory counts as an edge to every markdown file inside it,
    because a rendered directory listing reaches them all in one hop.
    """
    found: set[Path] = set()
    for match in MARKDOWN_LINK.finditer(text):
        target = match.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        file_part = target.partition("#")[0]
        if not file_part:
            continue
        resolved = (base / file_part).resolve()
        found.add(resolved)
        if resolved.is_dir():
            found |= {child.resolve() for child in resolved.rglob("*.md")}
    for match in BACKTICK_PATH.finditer(text):
        candidate = match.group(1)
        if candidate.endswith(".md"):
            found.add((root / candidate).resolve())
    return found


def check_file(path: Path, repo_root: Path | None = None) -> list[str]:
    """Return one message per unresolved reference in ``path``."""
    root = (repo_root or REPO_ROOT).resolve()
    errors: list[str] = []
    text = path.read_text()

    for match in MARKDOWN_LINK.finditer(text):
        target = match.group(2)
        line = text[: match.start()].count("\n") + 1

        if target.startswith(("http://", "https://", "mailto:", "#")):
            if target.startswith(("http://", "https://")):
                try:
                    parsed = urlsplit(target)
                except ValueError:
                    errors.append(f"{path}:{line}: malformed URL: {target}")
                    continue
                if any(character.isspace() for character in target) or not parsed.netloc:
                    errors.append(
                        f"{path}:{line}: URL contains whitespace or has no host: {target}"
                    )
                    continue
            if target.startswith(REPO_BLOB_PREFIX):
                errors.append(
                    f"{path}:{line}: absolute repository URL {target} "
                    "- use a relative link (branch-independent)"
                )
            continue

        file_part, _, anchor = target.partition("#")
        if not file_part:
            continue

        resolved = (path.parent / file_part).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"{path}:{line}: link {target} resolves outside the repository")
            continue
        if not resolved.exists():
            errors.append(f"{path}:{line}: link target does not exist: {target}")
            continue

        if anchor and anchor not in heading_slugs(resolved):
            errors.append(f"{path}:{line}: anchor #{anchor} not found in {file_part}")

    # Backticks that form a markdown link label are validated as links above;
    # only bare backticked strings name a repository path.
    link_label_spans = [m.span(1) for m in MARKDOWN_LINK.finditer(text)]

    def inside_link_label(pos: int) -> bool:
        return any(start <= pos < end for start, end in link_label_spans)

    for match in BACKTICK_PATH.finditer(text):
        if inside_link_label(match.start(1)):
            continue
        candidate = match.group(1)
        if not looks_like_repo_path(candidate):
            continue
        line = text[: match.start()].count("\n") + 1
        file_part, _, anchor = candidate.partition("#")
        if file_part.startswith(("./", "../")):
            resolved = (path.parent / file_part).resolve()
        else:
            resolved = (root / file_part).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"{path}:{line}: path {candidate} resolves outside the repository")
            continue
        if not resolved.exists():
            errors.append(f"{path}:{line}: path does not exist: {candidate}")
            continue
        if anchor and anchor not in heading_slugs(resolved):
            errors.append(f"{path}:{line}: anchor #{anchor} not found in {file_part}")

    return errors


def check_adr_references(files: list[Path], repo_root: Path | None = None) -> list[str]:
    """Textual ADR and numbered section references must resolve to an ADR."""
    root = (repo_root or REPO_ROOT).resolve()
    errors: list[str] = []
    existing: dict[int, Path] = {}
    for path in (root / "docs" / "adr").glob("*.md"):
        match = re.match(r"(\d{4})-", path.name)
        if match:
            existing[int(match.group(1))] = path

    for path in files:
        text = path.read_text()
        for match in ADR_REFERENCE.finditer(text):
            number = int(match.group(1))
            if number not in existing:
                line = text[: match.start()].count("\n") + 1
                errors.append(f"{path}:{line}: ADR {number:04d} has no file in docs/adr/")

        for match in ADR_SECTION_REFERENCE.finditer(text):
            number = int(match.group(1))
            adr_path = existing.get(number)
            if adr_path is None:
                continue
            sections = {int(section) for section in NUMBERED_HEADING.findall(adr_path.read_text())}
            start = int(match.group(2))
            end = int(match.group(3) or start)
            referenced_sections = range(start, end + 1) if end >= start else (start, end)
            line = text[: match.start()].count("\n") + 1
            for section in referenced_sections:
                if section not in sections:
                    errors.append(f"{path}:{line}: ADR {number:04d} has no section {section}")
    return errors


def main() -> int:
    files = [path for path in tracked_markdown() if not is_allowlisted(path)]
    print(f"Checking {len(files)} Markdown files repository-wide for unresolved references...")

    errors: list[str] = []
    for path in files:
        errors.extend(check_file(path))
    errors.extend(check_adr_references(files))

    if errors:
        print(f"\n❌ Found {len(errors)} unresolved reference(s):")
        for error in errors:
            print(f"  {error}")
        return 1

    print("\n✅ All documentation links and paths resolve!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
