"""Unit tests for the documented-defaults checker (ADR 0002 SN1, ADR 0006 §2).

Each test builds a throwaway documentation and source layout in ``tmp_path``
and runs one rule of scripts/check_doc_defaults.py against it, so a rule
that stops firing fails here rather than in CI.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def load_checker():
    """Load scripts/check_doc_defaults.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "check_doc_defaults", SCRIPTS_DIR / "check_doc_defaults.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_doc_defaults"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return load_checker()


@pytest.fixture
def repo(tmp_path):
    """A git repository with one ADR and the constants module it names."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / ".github").mkdir()
    (tmp_path / "prompts").mkdir()
    (tmp_path / "src/sdd4gh/contracts").mkdir(parents=True)
    (tmp_path / "src/sdd4gh/contracts/constants.py").write_text(
        '"""Constants."""\n\nCONFIDENCE_SHOW_BELOW = 0.95\n'
    )
    (tmp_path / "src/sdd4gh/contracts/pr_process.py").write_text(
        '"""PR process."""\n\nMAX_CORRECTION_ATTEMPTS_PER_BATCH = 5\n'
    )
    (tmp_path / "docs/adr/0006-pr-process.md").write_text(
        "# ADR 0006\n\n"
        "The gate is [`CONFIDENCE_SHOW_BELOW`](../../src/sdd4gh/contracts/constants.py).\n\n"
        "Corrections are capped at `MAX_CORRECTION_ATTEMPTS_PER_BATCH` attempts "
        "per batch (defined in `src/sdd4gh/contracts/pr_process.py`).\n"
    )
    (tmp_path / ".github/pull_request_template.md").write_text("# PR template\n")
    (tmp_path / "prompts/sentinel.md").write_text("# Prompt\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def run_rule(checker, repo, rule):
    """Run one rule function against ``repo`` and return its errors."""
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    original_root = checker.REPO_ROOT
    checker.REPO_ROOT = repo
    try:
        return rule(checker.doc_files())
    finally:
        checker.REPO_ROOT = original_root


class TestSymbolLinks:
    def test_symbol_defined_in_target_passes(self, checker, repo):
        assert run_rule(checker, repo, checker.check_symbol_links) == []

    def test_symbol_missing_from_target_fails(self, checker, repo):
        adr = repo / "docs/adr/0006-pr-process.md"
        adr.write_text(
            "# ADR 0006\n\n"
            "The gate is [`MISSING_SYMBOL`](../../src/sdd4gh/contracts/constants.py).\n"
        )
        errors = run_rule(checker, repo, checker.check_symbol_links)
        assert any("MISSING_SYMBOL" in error for error in errors)

    def test_link_to_nonexistent_file_fails(self, checker, repo):
        adr = repo / "docs/adr/0006-pr-process.md"
        adr.write_text("# ADR 0006\n\nSee [`CONFIDENCE_SHOW_BELOW`](../../src/nope.py).\n")
        errors = run_rule(checker, repo, checker.check_symbol_links)
        assert any("does not exist" in error for error in errors)

    def test_document_inventory_includes_templates_and_prompts(self, checker, repo):
        (repo / "prompts/untracked note.md").write_text("# Untracked prompt\n")
        original_root = checker.REPO_ROOT
        checker.REPO_ROOT = repo
        try:
            files = checker.doc_files()
        finally:
            checker.REPO_ROOT = original_root

        assert Path(".github/pull_request_template.md") in files
        assert Path("prompts/sentinel.md") in files
        assert Path("prompts/untracked note.md") in files


class TestSymbolPaths:
    def test_symbol_in_named_file_passes(self, checker, repo):
        assert run_rule(checker, repo, checker.check_symbol_paths) == []

    def test_symbol_in_wrong_file_fails(self, checker, repo):
        adr = repo / "docs/adr/0006-pr-process.md"
        adr.write_text(
            "# ADR 0006\n\n"
            "Corrections are capped at `MAX_CORRECTION_ATTEMPTS_PER_BATCH` attempts "
            "per batch (defined in `src/sdd4gh/contracts/constants.py`).\n"
        )
        errors = run_rule(checker, repo, checker.check_symbol_paths)
        assert any("MAX_CORRECTION_ATTEMPTS_PER_BATCH" in error for error in errors)
        assert any("pr_process.py" in error for error in errors)


class TestSymbolValues:
    def test_matching_value_passes(self, checker, repo):
        adr = repo / "docs/adr/0006-pr-process.md"
        adr.write_text("# ADR 0006\n\nThe cap is `MAX_CORRECTION_ATTEMPTS_PER_BATCH` (5).\n")
        assert run_rule(checker, repo, checker.check_symbol_values) == []

    def test_wrong_value_fails(self, checker, repo):
        adr = repo / "docs/adr/0006-pr-process.md"
        adr.write_text("# ADR 0006\n\nThe cap is `MAX_CORRECTION_ATTEMPTS_PER_BATCH` (3).\n")
        errors = run_rule(checker, repo, checker.check_symbol_values)
        assert any("documented as (3)" in error for error in errors)


class TestLocalDefaults:
    def test_local_endpoint_passes(self, checker, repo):
        adr = repo / "docs/adr/0006-pr-process.md"
        adr.write_text("# ADR 0006\n\nThe base URL is `http://127.0.0.1:11434/v1`.\n")
        assert run_rule(checker, repo, checker.check_local_defaults) == []

    def test_wrong_local_endpoint_fails(self, checker, repo):
        adr = repo / "docs/adr/0006-pr-process.md"
        adr.write_text("# ADR 0006\n\nThe base URL is `http://127.0.0.1:9999/v1`.\n")
        errors = run_rule(checker, repo, checker.check_local_defaults)
        assert any("does not match the code default" in error for error in errors)

    def test_non_local_provider_fails(self, checker, repo):
        adr = repo / "docs/adr/0006-pr-process.md"
        adr.write_text('# ADR 0006\n\nDefaults `provider="openai"`.\n')
        errors = run_rule(checker, repo, checker.check_local_defaults)
        assert any('provider "openai"' in error for error in errors)


class TestDefinesSymbol:
    def test_assignment_is_a_definition(self, checker, repo):
        module = repo / "src/sdd4gh/contracts/constants.py"
        assert checker.defines_symbol(module, "CONFIDENCE_SHOW_BELOW")
        assert not checker.defines_symbol(module, "NOT_THERE")

    def test_def_and_class_are_definitions(self, checker, tmp_path):
        module = tmp_path / "m.py"
        module.write_text("def f():\n    pass\n\n\nclass C:\n    pass\n")
        assert checker.defines_symbol(module, "f")
        assert checker.defines_symbol(module, "C")
