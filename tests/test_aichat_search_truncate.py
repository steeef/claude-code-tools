"""Tests for aichat-search truncate function (Rust).

This module provides pytest wrappers for the Rust unit tests in aichat-search.
It runs `cargo test` in the rust-search-ui directory to verify the truncate
function handles edge cases correctly.

Related: https://github.com/pchalasani/claude-code-tools/issues/25
"""

import subprocess
from pathlib import Path

import pytest


RUST_PROJECT_DIR = Path(__file__).parent.parent / "rust-search-ui"


@pytest.fixture(scope="module")
def cargo_available() -> bool:
    """Check if cargo is available."""
    try:
        result = subprocess.run(
            ["cargo", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class TestAichatSearchTruncate:
    """Tests for the truncate() function in aichat-search."""

    def test_rust_truncate_tests_pass(self, cargo_available: bool):
        """Run Rust unit tests for truncate function.

        This runs `cargo test` which includes tests for:
        - truncate with max=0 (Issue #25: usize underflow)
        - truncate with max=1 (edge case)
        - truncate normal cases
        - truncate empty strings
        """
        if not cargo_available:
            pytest.skip("cargo not available")

        result = subprocess.run(
            ["cargo", "test", "--", "--test-threads=1"],
            cwd=RUST_PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Combine stdout and stderr for checking results (cargo outputs to both)
        combined = result.stdout + result.stderr

        # Print output for debugging if test fails
        if result.returncode != 0:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)

        assert result.returncode == 0, f"Rust tests failed:\n{combined}"
        assert "test result: ok" in combined, f"Expected all tests to pass:\n{combined}"

    def test_truncate_max_zero_specific(self, cargo_available: bool):
        """Verify the specific test for max=0 passes.

        Issue #25: When max=0, the expression max-1 would underflow to
        usize::MAX, causing a panic.
        """
        if not cargo_available:
            pytest.skip("cargo not available")

        # Use partial match (without --exact) to find the test
        result = subprocess.run(
            ["cargo", "test", "test_truncate_with_max_zero"],
            cwd=RUST_PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )

        combined = result.stdout + result.stderr
        assert result.returncode == 0, f"test_truncate_with_max_zero failed:\n{combined}"
        assert "test tests::test_truncate_with_max_zero ... ok" in combined
