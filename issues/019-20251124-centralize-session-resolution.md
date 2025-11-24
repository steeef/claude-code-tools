# Centralize Session Path Resolution to Eliminate Code Duplication

## Issue

Massive code duplication for session path resolution across multiple files. This
has already caused bugs (e.g., malformed session check missing in local search
path). Need to consolidate all session resolution logic into a single central
module.

## Duplicated Functions

Currently duplicated across multiple files:

| Function | Locations | Purpose |
|----------|-----------|---------|
| `get_claude_home()` | session_menu_cli.py, session_utils.py, others? | Get Claude home with CLAUDE_CONFIG_DIR support |
| `get_codex_home()` | session_menu_cli.py, find_codex_session.py, others? | Get Codex home directory |
| `extract_cwd_from_session()` | session_menu_cli.py, find_claude_session.py | Extract working directory from session |
| `resolve_session_path()` | session_utils.py, export_codex_session.py | Resolve session ID to file path |
| `detect_agent_from_path()` | session_menu_cli.py, aichat.py (continue/export) | Detect Claude vs Codex from path |
| `find_session_file()` | session_menu_cli.py only | Find session by partial ID in both agents |
| `is_valid_session()` / `is_malformed_session()` | find_claude_session.py only | Validate session file structure |
| `extract_git_branch_*()` | Multiple files | Extract git branch from session metadata |

## Root Cause

No centralized session resolution module. Each tool reimplements the same logic,
leading to:
- Code duplication
- Inconsistent behavior
- Bugs when one copy is updated but others aren't
- Maintenance nightmare

## Solution: Test-Driven Refactoring

### Phase 1: Write Comprehensive Tests (Regression Tests)

**Goal**: Lock in current behavior with tests BEFORE refactoring.

Create `tests/test_session_resolution.py` with fixtures and tests covering:

1. **Home directory resolution**
   - Test `get_claude_home()` with CLI arg, CLAUDE_CONFIG_DIR, default
   - Test `get_codex_home()` with CLI arg, default
   - Test precedence: CLI > ENV > default

2. **Session validation**
   - Test `is_valid_session()` with valid sessions (user, assistant, tool_result)
   - Test rejection of file-history-snapshot-only sessions
   - Test rejection of queue-operation-only sessions
   - Test sub-agent sessions (should be valid)
   - Test empty files, malformed JSON, missing sessionId

3. **Agent detection**
   - Test `detect_agent_from_path()` with various paths
   - Test .claude paths → "claude"
   - Test .codex paths → "codex"
   - Test .claude-rja paths → "claude"
   - Test unknown paths → None

4. **Session metadata extraction**
   - Test `extract_cwd_from_session()` with cwd in various positions
   - Test `extract_git_branch()` for both Claude and Codex formats
   - Test sessions without cwd/branch → None

5. **Session file lookup**
   - Test `find_session_file()` with full UUID
   - Test with partial UUID (unique match)
   - Test with partial UUID (multiple matches)
   - Test with non-existent ID
   - Test across both Claude and Codex homes

6. **Session path resolution**
   - Test `resolve_session_path()` with full path
   - Test with session ID
   - Test with partial ID
   - Test with custom home directories

**Test fixtures**:
- Create `tests/fixtures/sessions/` directory structure
- Mock `.claude/projects/` with valid/invalid session files
- Mock `.codex/sessions/YYYY/MM/DD/` structure
- Include various session types (valid, file-history-snapshot, queue-operation,
  sub-agent)

**Expected outcome**: All tests PASS with current (duplicated) code.

### Phase 2: Centralize Into session_utils.py

Create/expand `claude_code_tools/session_utils.py` with:

```python
# Home directory resolution
def get_claude_home(cli_arg: Optional[str] = None) -> Path
def get_codex_home(cli_arg: Optional[str] = None) -> Path

# Session validation
def is_valid_session(filepath: Path) -> bool
def is_malformed_session(filepath: Path) -> bool  # Deprecated wrapper

# Agent detection
def detect_agent_from_path(file_path: Path) -> Optional[str]

# Metadata extraction
def extract_cwd_from_session(session_file: Path) -> Optional[str]
def extract_git_branch_claude(session_file: Path) -> Optional[str]
def extract_git_branch_codex(session_file: Path) -> Optional[str]

# Session lookup
def find_session_file(
    session_id: str,
    claude_home: Optional[str] = None,
    codex_home: Optional[str] = None,
) -> Optional[Tuple[str, Path, str, Optional[str]]]

# Path resolution
def resolve_session_path(
    session_id_or_path: str,
    claude_home: Optional[str] = None,
    codex_home: Optional[str] = None,
) -> Tuple[str, Path]  # Returns (agent, path)
```

### Phase 3: Update All Consumers

Replace all local implementations with imports from `session_utils.py`:

**Files to update**:
- `claude_code_tools/session_menu_cli.py` - Remove local impls, import central
- `claude_code_tools/find_claude_session.py` - Move validation functions out
- `claude_code_tools/find_codex_session.py` - Remove duplicates
- `claude_code_tools/export_codex_session.py` - Remove resolve_session_path
- `claude_code_tools/aichat.py` - Import detect_agent_from_path
- Any other files found during grep search

### Phase 4: Verify Tests Still Pass

Run `pytest tests/test_session_resolution.py -v`

**Expected outcome**: All tests PASS, proving refactor preserved behavior.

## Implementation Plan

1. **Audit current state** - `rg` to find ALL occurrences of duplicated
   functions
2. **Write comprehensive tests** - Cover all edge cases with fixtures
3. **Run tests** - Verify they pass with current duplicated code
4. **Create canonical session_utils.py** - Implement all functions once
5. **Update imports** - Replace local implementations one file at a time
6. **Run tests after each change** - Ensure no regressions
7. **Clean up** - Remove old duplicated code
8. **Final test run** - All tests green

## Benefits

- **Single source of truth** for session resolution
- **Easier to fix bugs** - one place to update
- **Consistent behavior** across all commands
- **Test coverage** ensures correctness
- **Future-proof** - new commands just import from session_utils

## Testing Strategy

Use pytest with:
- Fixtures for mock session directories
- Parametrized tests for multiple scenarios
- tmpdir for isolated test environments
- Clear assertions and error messages

Example test structure:
```python
@pytest.fixture
def mock_claude_home(tmp_path):
    """Create mock .claude directory structure"""
    # Create projects/foo/valid-session.jsonl
    # Create projects/bar/malformed-session.jsonl
    return tmp_path

def test_get_claude_home_with_env(monkeypatch, tmp_path):
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path))
    assert get_claude_home() == tmp_path

def test_find_session_file_partial_id(mock_claude_home):
    result = find_session_file("abc123", claude_home=str(mock_claude_home))
    assert result is not None
    agent, path, cwd, branch = result
    assert agent == "claude"
    assert "abc123" in path.stem
```

## Success Criteria

- [ ] All duplicated functions identified
- [ ] Comprehensive test suite written (>90% coverage)
- [ ] Tests pass with current code
- [ ] All functions centralized in session_utils.py
- [ ] All consumer files updated to import from central module
- [ ] All duplicated code removed
- [ ] Tests still pass after refactoring
- [ ] No regressions in manual testing

## Timeline

Estimated: 2-3 hours
- 30 min: Audit and document all duplications
- 60 min: Write comprehensive tests
- 60 min: Refactor and update imports
- 30 min: Verify and cleanup
