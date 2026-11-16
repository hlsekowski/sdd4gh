"""Unit tests for the traceability checker (ADR 0001 §1–§4).

Each test builds a throwaway repository layout in ``tmp_path`` and runs one
rule of scripts/check_traceability.py against it, so a rule that stops
firing fails here rather than in CI.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def load_checker():
    """Load scripts/check_traceability.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "check_traceability", SCRIPTS_DIR / "check_traceability.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_traceability"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return load_checker()


@pytest.fixture
def repo(tmp_path):
    """A minimal git repository with two ADRs, one module and one test."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / "src/sdd4gh/domain").mkdir(parents=True)
    (tmp_path / "tests/unit/domain").mkdir(parents=True)
    (tmp_path / "docs/adr/0001-spec-driven-development.md").write_text(
        "# ADR 0001\n\n## Status\n\nAccepted\n\n## Context\n\nText.\n\n"
        "## Decision\n\nText.\n\n## Related\n\n"
    )
    (tmp_path / "docs/adr/0002-architecture-dependency-model.md").write_text(
        "# ADR 0002\n\n## Status\n\nAccepted\n\n## Context\n\nText.\n\n"
        "## Decision\n\nText.\n\n## Related\n\n"
    )
    (tmp_path / "docs/adr/0003-local-development-workflow.md").write_text(
        "# ADR 0003\n\n## Status\n\nAccepted\n\n## Context\n\nText.\n\n"
        "## Decision\n\nText.\n\n## Related\n\n"
    )
    (tmp_path / "docs/adr/0004-worker-task-model.md").write_text(
        "# ADR 0004\n\n## Status\n\nAccepted\n\n## Context\n\n"
        "Depends on ADR 0003.\n\n## Decision\n\nText.\n\n## Related\n\n"
        "- [ADR 0003](0003-local-development-workflow.md)\n"
    )
    (tmp_path / "src/sdd4gh/domain/task_queue.py").write_text(
        '"""Task queue.\n\nMirrors ADR 0004 §2.\n"""\n'
    )
    (tmp_path / "tests/unit/domain/test_task_queue.py").write_text(
        '"""Tests for the task queue (ADR 0004)."""\n'
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def run_rule(checker, repo, rule):
    """Run one rule function against ``repo`` and return its errors.

    The rules read git-tracked files, so anything the test just wrote is
    staged first.
    """
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    original_root = checker.REPO_ROOT
    checker.REPO_ROOT = repo
    try:
        return rule(checker.adr_files())
    finally:
        checker.REPO_ROOT = original_root


class TestNumbering:
    def test_contiguous_numbering_passes(self, checker, repo):
        assert run_rule(checker, repo, checker.check_numbering) == []

    def test_gap_in_numbering_fails(self, checker, repo):
        (repo / "docs/adr/0002-architecture-dependency-model.md").unlink()
        errors = run_rule(checker, repo, checker.check_numbering)
        assert any("not contiguous" in error for error in errors)


class TestModuleCitations:
    def test_cited_module_passes(self, checker, repo):
        assert run_rule(checker, repo, checker.check_modules_cite_adr) == []

    def test_uncited_module_fails(self, checker, repo):
        module = repo / "src/sdd4gh/domain/task_queue.py"
        module.write_text('"""Task queue."""\n')
        errors = run_rule(checker, repo, checker.check_modules_cite_adr)
        assert any("cites no ADR" in error for error in errors)

    def test_citation_to_missing_adr_fails(self, checker, repo):
        # Built at runtime so this file does not itself cite a missing ADR.
        missing = "ADR " + "00" + "99"
        module = repo / "src/sdd4gh/domain/task_queue.py"
        module.write_text(f'"""Task queue.\n\nMirrors {missing}.\n"""\n')
        errors = run_rule(checker, repo, checker.check_modules_cite_adr)
        assert any(missing in error for error in errors)

    def test_allowlisted_module_is_skipped(self, checker, repo):
        module = repo / "src/sdd4gh/contracts/ports.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text('"""Ports."""\n')
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        assert run_rule(checker, repo, checker.check_modules_cite_adr) == []


class TestTestCitations:
    def test_cited_test_passes(self, checker, repo):
        assert run_rule(checker, repo, checker.check_tests_cite_adr) == []

    def test_uncited_test_fails(self, checker, repo):
        test = repo / "tests/unit/domain/test_task_queue.py"
        test.write_text('"""Tests for the task queue."""\n')
        errors = run_rule(checker, repo, checker.check_tests_cite_adr)
        assert any("cites no ADR" in error for error in errors)


class TestAdrHasCode:
    def test_adr_with_module_passes(self, checker, repo):
        # ADR 0003 is a process ADR with no module of its own in this fixture.
        original = checker.NO_MODULE_ADR_ALLOWLIST
        checker.NO_MODULE_ADR_ALLOWLIST = original | {3}
        try:
            assert run_rule(checker, repo, checker.check_adrs_have_code) == []
        finally:
            checker.NO_MODULE_ADR_ALLOWLIST = original

    def test_adr_without_module_fails(self, checker, repo):
        module = repo / "src/sdd4gh/domain/task_queue.py"
        module.write_text('"""Task queue."""\n')
        errors = run_rule(checker, repo, checker.check_adrs_have_code)
        assert any("no module in src/sdd4gh/ cites it" in error for error in errors)


class TestAdrHasTests:
    def test_citing_test_satisfies_the_adr(self, checker, repo):
        assert run_rule(checker, repo, checker.check_adrs_have_tests) == []

    def test_importing_test_satisfies_the_adr(self, checker, repo):
        test = repo / "tests/unit/domain/test_task_queue.py"
        test.write_text('"""Tests."""\n\nfrom sdd4gh.domain.task_queue import claim\n')
        assert run_rule(checker, repo, checker.check_adrs_have_tests) == []

    def test_unrelated_test_fails(self, checker, repo):
        test = repo / "tests/unit/domain/test_task_queue.py"
        test.write_text('"""Tests."""\n\nfrom sdd4gh.domain.other import thing\n')
        errors = run_rule(checker, repo, checker.check_adrs_have_tests)
        assert any("no test cites or imports them" in error for error in errors)


class TestDependenciesLinked:
    def test_linked_dependency_passes(self, checker, repo):
        assert run_rule(checker, repo, checker.check_dependencies_linked) == []

    def test_unlinked_dependency_fails(self, checker, repo):
        adr = repo / "docs/adr/0004-worker-task-model.md"
        adr.write_text(
            "# ADR 0004\n\n## Status\n\nAccepted\n\n## Context\n\n"
            "Depends on ADR 0003.\n\n## Decision\n\nText.\n\n## Related\n\n"
        )
        errors = run_rule(checker, repo, checker.check_dependencies_linked)
        assert any("does not link it" in error for error in errors)


class TestCitedAdrs:
    def test_bare_and_path_forms_both_resolve(self, checker):
        assert checker.cited_adrs("Mirrors ADR 0004 §2.") == {4}
        assert checker.cited_adrs("Mirrors docs/adr/0004-worker-task-model.md.") == {4}
        assert checker.cited_adrs("No citation here.") == set()
