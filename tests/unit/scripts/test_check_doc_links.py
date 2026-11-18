"""Unit tests for repository-wide Markdown reference checks."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def load_checker():
    """Load scripts/check_doc_links.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "check_doc_links", SCRIPTS_DIR / "check_doc_links.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_doc_links"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return load_checker()


@pytest.fixture
def repo(tmp_path):
    """Create an isolated repository with root, template, and prompt Markdown."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / ".github").mkdir()
    (tmp_path / "prompts").mkdir()
    (tmp_path / "README.md").write_text("# README\n")
    (tmp_path / "docs/audit note.md").write_text("# Audit note\n")
    (tmp_path / "docs/adr/0001-sample.md").write_text("# ADR 0001\n\n## 2. Decision\n\nText.\n")
    (tmp_path / ".github/pull_request_template.md").write_text("[Missing](../missing.md)\n")
    (tmp_path / "prompts/sentinel.md").write_text("See `../docs/adr/0001-sample.md#2-decision`.\n")
    subprocess.run(
        ["git", "add", "README.md", "docs/adr/0001-sample.md"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def run_checks(checker, repo):
    """Run the link and ADR-reference rules against the temporary repository."""
    original_root = checker.REPO_ROOT
    checker.REPO_ROOT = repo
    try:
        files = checker.tracked_markdown()
        repo_files = [repo / path for path in files]
        errors = [
            error for path in repo_files for error in checker.check_file(path, repo_root=repo)
        ]
        errors.extend(checker.check_adr_references(repo_files, repo_root=repo))
        return files, errors
    finally:
        checker.REPO_ROOT = original_root


def test_tracked_markdown_includes_all_repository_locations(checker, repo):
    files, _ = run_checks(checker, repo)

    assert Path(".github/pull_request_template.md") in files
    assert Path("docs/audit note.md") in files
    assert Path("prompts/sentinel.md") in files


def test_broken_links_and_backticked_anchors_are_reported(checker, repo):
    (repo / ".github/pull_request_template.md").write_text("[Missing](../missing.md)\n")
    (repo / "prompts/sentinel.md").write_text("See `../docs/adr/0001-sample.md#missing-section`.\n")

    _, errors = run_checks(checker, repo)

    assert any("link target does not exist" in error for error in errors)
    assert any("anchor #missing-section not found" in error for error in errors)


def test_missing_numbered_adr_section_is_reported(checker, repo):
    (repo / "README.md").write_text("See ADR 0001 §3.\n")

    _, errors = run_checks(checker, repo)

    assert any("ADR 0001 has no section 3" in error for error in errors)


def test_valid_numbered_adr_section_passes(checker, repo):
    (repo / "README.md").write_text("See ADR 0001 §2.\n")

    _, errors = run_checks(checker, repo)

    assert not any("ADR 0001" in error for error in errors)


def test_external_markdown_url_with_whitespace_is_reported(checker, repo):
    (repo / "README.md").write_text("[Broken](https://example.com/a b)\n")

    _, errors = run_checks(checker, repo)

    assert any("URL contains whitespace" in error for error in errors)
