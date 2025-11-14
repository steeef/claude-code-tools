# Smart Trim: LLM-Powered Intelligent Session Trimming

**Date:** 2025-11-14
**Status:** Implemented with Parallel Agents

## Overview
Use Claude Agent SDK with parallel agents to intelligently identify and trim non-essential parts of session files, replacing them with placeholders.

## Implementation Architecture

### Parallel Agent Approach
The session is automatically chunked and analyzed by multiple Claude agents in parallel:
- Sessions are split into chunks of `max_lines_per_agent` lines (default: 100)
- Each chunk is analyzed independently by a separate agent instance
- Results are merged to produce the final list of trimmable lines
- Protected indices (user messages, recent N messages) are identified upfront and excluded from all chunks

## Components

### 1. Core Module: `smart_trim_core.py`

**Main Function:**
```python
def identify_trimmable_lines(
    session_file: Path,
    exclude_types: Optional[List[str]] = None,  # e.g., ["user"] to skip user messages
    preserve_recent: int = 10,  # Always preserve last N messages
    max_lines_per_agent: int = 100,  # Max lines per agent chunk
) -> List[int]:  # returns line indices to trim
    """
    Use LLM agents in parallel to analyze session and identify safe-to-trim lines.

    Returns list of integer indices (0-based) of JSONL lines that can be
    safely replaced with placeholders.
    """
```

**Implementation Details:**
- `_analyze_session_async()`: Orchestrates parallel agent analysis
  - Identifies protected indices (user messages, recent messages, malformed lines)
  - Splits non-protected lines into chunks
  - Launches parallel agents using `asyncio.gather()`
  - Merges results and filters out protected indices
- `_analyze_chunk()`: Analyzes a single chunk with one agent
  - Receives chunk data with original line indices
  - Returns line numbers relative to original session
  - Uses Claude Agent SDK's `query()` function

**Options:**
- `exclude_types`: Skip certain message types (default: `["user"]`)
- `preserve_recent`: Always preserve last N messages (default: 10)
- `max_lines_per_agent`: Maximum lines per agent chunk (default: 100)

### 2. CLI Script: `smart_trim.py`

**Usage:**
```bash
smart-trim session.jsonl [OPTIONS]

Options:
  --exclude-types TYPE[,TYPE]      Message types to never trim (default: user)
  --preserve-recent N              Always keep last N messages (default: 10)
  --max-lines-per-agent N          Max lines per agent chunk (default: 100)
  --output-dir DIR                 Output directory (default: same as input)
  --dry-run                        Show what would be trimmed without doing it
```

**Implementation:**
1. Auto-detect agent type (Claude/Codex) from session filename
2. Call `identify_trimmable_lines()` to get indices using parallel agents
3. Use `trim_lines()` helper to replace lines with placeholders
4. Generate new session file with UUID, preserving agent type naming convention
5. Display stats: lines trimmed, characters saved, tokens saved (estimate)

**Helper Function:**
```python
def trim_lines(input_file: Path, line_indices: List[int], output_file: Path) -> dict:
    """
    Replace specified lines with placeholders.
    Returns stats dict with num_lines_trimmed, chars_saved, tokens_saved.
    """
```

## System Prompt Template

```
You are analyzing a coding agent session to identify content that can be safely removed
without affecting the ability to continue the work.

Review this conversation and identify:
- Verbose tool results that were only needed for one-time analysis
- Assistant messages with extensive explanations that are no longer relevant
- Intermediate debugging output no longer needed
- Large file reads that served their purpose

DO NOT mark for removal:
- User messages
- Recent messages (last 10)
- Messages containing critical context or decisions
- Error messages or warnings

Return a JSON list of line numbers (0-indexed) that can be trimmed.
```

## Dependencies

- `claude-agent-sdk` - Already in pyproject.toml
- Existing `trim_session` module for placeholder replacement

## Testing Strategy

1. Unit tests for `identify_trimmable_lines()`
2. Integration test with sample session files
3. Verify trimmed sessions are still resumable
4. Compare smart-trim vs naive trim (threshold-based) effectiveness

## Success Criteria

- ✅ Accurately identifies trimmable content without removing critical context
- ✅ Preserves session continuity (trimmed sessions work when resumed)
- ✅ More intelligent than threshold-based trimming
- ✅ CLI tool is easy to use
- ✅ Reasonable performance (< 30s for typical session)
