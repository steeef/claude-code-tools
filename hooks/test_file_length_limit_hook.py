#!/usr/bin/env python3
"""
Test script for file_length_limit_hook.py

Tests the hook's behavior with various scenarios.
"""
import json
import subprocess
import sys
from pathlib import Path


def run_hook(tool_name: str, tool_input: dict) -> dict:
    """Run the hook and return the result."""
    data = {
        "tool_name": tool_name,
        "tool_input": tool_input
    }

    hook_path = Path(__file__).parent / "file_length_limit_hook.py"

    result = subprocess.run(
        [str(hook_path)],
        input=json.dumps(data),
        capture_output=True,
        text=True
    )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Failed to parse hook output: {result.stdout}")
        print(f"Stderr: {result.stderr}")
        return {"decision": "error"}


def test_write_small_file():
    """Test writing a small file (should be approved)."""
    print("Test 1: Write small file (< 1000 lines)")

    content = "\n".join([f"line {i}" for i in range(100)])

    result = run_hook("Write", {
        "file_path": "/tmp/test.py",
        "content": content
    })

    assert result["decision"] == "approve", \
        f"Expected approve, got {result['decision']}"
    print("✓ PASSED: Small file approved")


def test_write_large_file_first_attempt():
    """Test writing a large file (should block on first attempt)."""
    print("\nTest 2: Write large file - first attempt (should block)")

    # Clean up any existing flag file
    flag_file = Path('.claude_file_length_warning.flag')
    if flag_file.exists():
        flag_file.unlink()

    content = "\n".join([f"line {i}" for i in range(1500)])

    result = run_hook("Write", {
        "file_path": "/tmp/test.py",
        "content": content
    })

    assert result["decision"] == "block", \
        f"Expected block, got {result['decision']}"
    assert flag_file.exists(), "Flag file should be created"
    print("✓ PASSED: Large file blocked on first attempt")


def test_write_large_file_second_attempt():
    """Test writing a large file (should approve on second attempt)."""
    print("\nTest 3: Write large file - second attempt (should approve)")

    # Flag file should already exist from previous test
    flag_file = Path('.claude_file_length_warning.flag')
    assert flag_file.exists(), "Flag file should exist from previous test"

    content = "\n".join([f"line {i}" for i in range(1500)])

    result = run_hook("Write", {
        "file_path": "/tmp/test.py",
        "content": content
    })

    assert result["decision"] == "approve", \
        f"Expected approve, got {result['decision']}"
    assert not flag_file.exists(), "Flag file should be deleted"
    print("✓ PASSED: Large file approved on second attempt")


def test_non_source_file():
    """Test writing a large non-source file (should be approved)."""
    print("\nTest 4: Write large non-source file (should approve)")

    content = "\n".join([f"line {i}" for i in range(1500)])

    result = run_hook("Write", {
        "file_path": "/tmp/test.txt",  # Not a source file
        "content": content
    })

    assert result["decision"] == "approve", \
        f"Expected approve for non-source file, got {result['decision']}"
    print("✓ PASSED: Large non-source file approved")


def test_edit_small_file():
    """Test editing a file to keep it small (should be approved)."""
    print("\nTest 5: Edit to create small file (should approve)")

    # Create a temporary test file
    test_file = Path("/tmp/test_edit.py")
    test_file.write_text("\n".join([f"line {i}" for i in range(50)]))

    result = run_hook("Edit", {
        "file_path": str(test_file),
        "old_string": "line 10",
        "new_string": "modified line 10"
    })

    assert result["decision"] == "approve", \
        f"Expected approve, got {result['decision']}"
    print("✓ PASSED: Small edit approved")

    # Cleanup
    test_file.unlink()


def test_non_edit_write_tool():
    """Test that other tools are not affected (should be approved)."""
    print("\nTest 6: Non-Edit/Write tool (should approve)")

    result = run_hook("Read", {
        "file_path": "/tmp/test.py"
    })

    assert result["decision"] == "approve", \
        f"Expected approve for Read tool, got {result['decision']}"
    print("✓ PASSED: Other tools not affected")


def cleanup():
    """Clean up test files and flag file."""
    flag_file = Path('.claude_file_length_warning.flag')
    if flag_file.exists():
        flag_file.unlink()


if __name__ == "__main__":
    print("Running file_length_limit_hook.py tests...\n")
    print("=" * 60)

    try:
        test_write_small_file()
        test_write_large_file_first_attempt()
        test_write_large_file_second_attempt()
        test_non_source_file()
        test_edit_small_file()
        test_non_edit_write_tool()

        print("\n" + "=" * 60)
        print("\n✓ ALL TESTS PASSED!")

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cleanup()
