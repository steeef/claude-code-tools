"""Intelligent session trimming using LLM analysis via CLI."""

import json
import subprocess
from pathlib import Path
from typing import List, Optional, Any, Dict

from claude_code_tools.session_utils import (
    get_codex_home,
    get_claude_home,
    get_session_uuid,
    encode_claude_project_path,
    mark_session_as_helper,
)

# Minimum content length (in chars) for a line to be considered for trimming
SMART_TRIM_THRESHOLD = 500


def is_claude_cli_available() -> bool:
    """Check if Claude CLI is available."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


# CLI-based prompt for Claude headless mode
CLI_SMART_TRIM_PROMPT_CLAUDE = """I need help identifying which lines can be trimmed from a coding agent session.

The session representation is in: {session_file}

IMPORTANT - FILE FORMAT:
Each entry in that file is on a single line with format: LINE N [len=X]: [TYPE]: <preview>
- N is a LABEL (the original line number in the session file, 0-indexed)
- X is the content length in characters
- TYPE is one of: [ASSISTANT], [USER], or [TOOL_RESULT]
- The entries are NOT consecutive - there are gaps in the N values (e.g., LINE 4, LINE 22, LINE 53...)

CRITICAL: When returning results, use the EXACT value of N from the "LINE N" label.
Do NOT use the position of the entry in this file. For example, if you see:
  LINE 4 [len=6394]: ...
  LINE 22 [len=1120]: ...
And you want to trim the second entry, return "line": 22 (not "line": 2).

I am trying to truncate selected messages to clear out context, but still be able
to continue the work in this session.

================================================================================
TRIMMING INSTRUCTIONS (PAY SPECIAL ATTENTION):
{custom_instructions}
================================================================================

Session files can be huge, so you MUST strategically deploy PARALLEL SUB-AGENTS
to analyze different portions of the session. Give each sub-agent the proper
context including the TRIMMING INSTRUCTIONS above so they can accurately identify
which messages can be safely trimmed.

Return your results as a JSON array of objects, where each object has:
- "line": the EXACT N value from the "LINE N" label (NOT the position in the file)
- "rationale": brief reason why it can be trimmed (max 5-6 words)
- "summary": 1-2 sentence summary of what the content contains

Example: If the file contains "LINE 42 [len=5000]: ..." and you want to trim it:
[
  {{"line": 42, "rationale": "verbose tool output", "summary": "Reading config.py"}}
]
"""

# CLI-based prompt for Codex (no parallel sub-agents)
CLI_SMART_TRIM_PROMPT_CODEX = """I need help identifying which lines can be trimmed from a coding agent session.

The session representation is in: {session_file}

IMPORTANT - FILE FORMAT:
Each entry in that file is on a single line with format: LINE N [len=X]: [TYPE]: <preview>
- N is a LABEL (the original line number in the session file, 0-indexed)
- X is the content length in characters
- TYPE is one of: [ASSISTANT], [USER], or [TOOL_RESULT]
- The entries are NOT consecutive - there are gaps in the N values (e.g., LINE 4, LINE 22, LINE 53...)

CRITICAL: When returning results, use the EXACT value of N from the "LINE N" label.
Do NOT use the position of the entry in this file. For example, if you see:
  LINE 4 [len=6394]: ...
  LINE 22 [len=1120]: ...
And you want to trim the second entry, return "line": 22 (not "line": 2).

I am trying to truncate selected messages to clear out context, but still be able
to continue the work in this session.

================================================================================
TRIMMING INSTRUCTIONS (PAY SPECIAL ATTENTION):
{custom_instructions}
================================================================================

Session files can be huge, so you MUST strategically explore it
to analyze different portions of the session.

Read the session file and identify entries that can be safely trimmed. Focus on:
- Verbose tool results that were one-time analysis only
- Lengthy explanations no longer relevant to current work
- Intermediate debugging output
- Large file reads that served their purpose

Return your results as a JSON array of objects, where each object has:
- "line": the EXACT N value from the "LINE N" label (NOT the position in the file)
- "rationale": brief reason why it can be trimmed (max 5-6 words)
- "summary": 1-2 sentence summary of what the content contains

Example: If the file contains "LINE 42 [len=5000]: ..." and you want to trim it:
[
  {{"line": 42, "rationale": "verbose tool output", "summary": "Reading config.py"}}
]
"""


def analyze_session_with_cli(
    session_file: Path,
    custom_instructions: Optional[str] = None,
    content_threshold: int = 200,
    cli_type: str = "claude",
) -> List[tuple]:
    """
    Analyze session using CLI headless mode (Claude or Codex).

    Args:
        session_file: Path to session JSONL file
        custom_instructions: Custom trimming instructions
        content_threshold: Min chars to extract from JSON (default: 200)
        cli_type: Which CLI to use - "claude" or "codex" (default: "claude")

    Returns:
        List of (line_idx, rationale, summary) tuples
    """
    # Default instructions if none provided
    default_instructions = (
        "Trim messages that are not relevant to the last task "
        "being worked on in this session."
    )
    instructions = custom_instructions or default_instructions

    # Read and prepare session content
    with open(session_file, 'r') as f:
        session_lines = f.readlines()

    # Build simplified representation
    content_parts = []
    for idx, line in enumerate(session_lines):
        try:
            data = json.loads(line)
            msg_type = data.get("type", "")

            # Extract relevant content based on message type
            relevant = extract_relevant_content(data, msg_type, content_threshold)
            if not relevant:
                continue

            # Calculate total content length
            total_len = sum(len(content) for _, content in relevant)
            # Skip lines too short for trimming to save space
            # (truncation to 500 chars + ~270 char placeholder = ~770 min output)
            if total_len < 800:
                continue

            # Build preview (truncated)
            preview_parts = []
            for label, content in relevant[:2]:  # Max 2 fields
                preview = content[:300] if len(content) > 300 else content
                preview = preview.replace('\n', ' ').strip()
                preview_parts.append(f"{label}: {preview}")
            preview = " | ".join(preview_parts)

            content_parts.append(f"LINE {idx} [len={total_len}]: {preview}")
        except (json.JSONDecodeError, KeyError):
            continue

    session_content = "\n".join(content_parts)

    # Extract session_id (UUID) from filename - works for both Claude and Codex formats
    session_id = get_session_uuid(session_file.name)

    # Determine if this is a Codex session (for output directory placement)
    # Resolve paths to handle ~ and relative paths correctly
    codex_home = str(get_codex_home().resolve())
    session_path = str(Path(session_file).resolve())
    is_codex_session = session_path.startswith(codex_home)

    # Write session representation to file instead of embedding in prompt
    exports_dir = Path(".codex/exports" if is_codex_session else ".claude/exports")
    exports_dir.mkdir(parents=True, exist_ok=True)
    session_repr_file = exports_dir / f"{session_id}.txt"
    with open(session_repr_file, 'w') as f:
        f.write(session_content)

    # Select prompt template based on CLI type
    if cli_type == "codex":
        prompt_template = CLI_SMART_TRIM_PROMPT_CODEX
    else:
        prompt_template = CLI_SMART_TRIM_PROMPT_CLAUDE

    # Build the prompt with file path reference
    prompt = prompt_template.format(
        custom_instructions=instructions,
        session_file=session_repr_file,
    )

    # Call CLI in headless mode
    try:
        if cli_type == "codex":
            # Codex CLI
            result = subprocess.run(
                ["codex", "exec", "--json", prompt],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )
        else:
            # Claude CLI
            result = subprocess.run(
                [
                    "claude", "-p",
                    "--no-session-persistence",
                    "--output-format", "json",
                    "--permission-mode", "bypassPermissions",
                    prompt,
                ],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )

        if result.returncode != 0:
            print(f"   CLI error: {result.stderr[:200]}")
            return []

        # Save raw CLI output for debugging
        raw_debug_dir = Path(".codex" if is_codex_session else ".claude")
        raw_debug_dir.mkdir(exist_ok=True)
        raw_debug_file = raw_debug_dir / f"trim-raw-{session_id}.txt"
        with open(raw_debug_file, 'w') as f:
            f.write(f"=== STDOUT ({len(result.stdout)} chars) ===\n")
            f.write(result.stdout)
            f.write(f"\n\n=== STDERR ({len(result.stderr)} chars) ===\n")
            f.write(result.stderr)
        print(f"   Raw CLI output saved to: {raw_debug_file}")

        # Parse response based on CLI type
        helper_session_id = None  # Track helper session for cleanup
        if cli_type == "codex":
            # Codex outputs JSONL stream - extract text from response_item events
            text = ""
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    # Capture thread_id for cleanup
                    if event.get("type") == "thread.started":
                        helper_session_id = event.get("thread_id")
                    elif event.get("type") == "response_item":
                        payload = event.get("payload", {})
                        if payload.get("type") == "message":
                            content = payload.get("content", [])
                            for block in content:
                                if isinstance(block, dict) and "text" in block:
                                    text += block.get("text", "")
                except json.JSONDecodeError:
                    continue
        else:
            # Claude outputs wrapped JSON
            response = json.loads(result.stdout)
            if isinstance(response, dict):
                text = response.get("result", "")
                # Capture session_id for cleanup
                helper_session_id = response.get("session_id")
            else:
                text = str(response)

        # Find the JSON array in the response
        # Look for the outermost [ and matching ]
        start = text.find('[')
        if start == -1:
            print("   No JSON array found in response")
            return []

        # Find the matching closing bracket by counting brackets
        depth = 0
        end = start
        for i, char in enumerate(text[start:], start):
            if char == '[':
                depth += 1
            elif char == ']':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        if end <= start:
            print("   No matching ] found in response")
            return []

        json_str = text[start:end]
        try:
            items = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"   JSON parse error: {e}")
            # Save raw response for debugging
            debug_file = Path(".claude/trim-debug-response.txt")
            debug_file.parent.mkdir(exist_ok=True)
            with open(debug_file, 'w') as f:
                f.write(f"Full text:\n{text}\n\n")
                f.write(f"Extracted JSON ({start}:{end}):\n{json_str}\n")
            print(f"   Debug saved to: {debug_file}")
            return []

        # Save diagnostic output to .claude/ or .codex/ based on session being trimmed
        diag_dir = Path(".codex" if is_codex_session else ".claude")
        diag_dir.mkdir(exist_ok=True)
        diag_file = diag_dir / f"trim-result-{session_id}.jsonl"
        with open(diag_file, 'w') as f:
            # Write prompt summary
            f.write(json.dumps({
                "type": "prompt_info",
                "session_file": str(session_file),
                "instructions": instructions,
                "num_content_lines": len(content_parts),
                "prompt_length": len(prompt),
            }) + "\n")
            # Write session content sent to CLI
            f.write(json.dumps({
                "type": "session_content",
                "lines": content_parts,
            }) + "\n")
            # Write raw response
            f.write(json.dumps({
                "type": "cli_response",
                "raw": text,
            }) + "\n")
            # Write parsed items
            f.write(json.dumps({
                "type": "parsed_results",
                "items": items,
            }) + "\n")
        print(f"   Diagnostics saved to: {diag_file}")

        # Convert to tuples
        results = []
        for item in items:
            if isinstance(item, dict):
                line = item.get("line", -1)
                rationale = item.get("rationale", "")
                summary = item.get("summary", "")
                if line >= 0:
                    results.append((line, rationale, summary))

        # Clean up helper session
        _delete_helper_session(helper_session_id, cli_type)

        return results

    except subprocess.TimeoutExpired:
        print("   CLI timeout after 10 minutes")
        return []
    except json.JSONDecodeError as e:
        print(f"   JSON parse error: {e}")
        return []
    except Exception as e:
        print(f"   CLI error: {e}")
        return []


def _delete_helper_session(session_id: Optional[str], cli_type: str) -> None:
    """
    Delete a helper session created during smart-trim analysis.

    Marks the session as a helper first (in case deletion fails or indexing
    happens before deletion), then deletes the file.

    Args:
        session_id: The session ID (Claude) or thread_id (Codex) to delete
        cli_type: "claude" or "codex"
    """
    if not session_id:
        return

    try:
        if cli_type == "codex":
            # Codex session files are in ~/.codex/sessions/YYYY/MM/DD/
            # with format rollout-timestamp-thread_id.jsonl
            codex_home = get_codex_home()
            sessions_dir = codex_home / "sessions"
            if sessions_dir.exists():
                # Search for session file containing thread_id
                for session_file in sessions_dir.rglob(f"*{session_id}*.jsonl"):
                    # Mark as helper first (belt and suspenders)
                    mark_session_as_helper(session_file)
                    session_file.unlink(missing_ok=True)
                    break  # Only delete the first match
        else:
            # Claude session files are in ~/.claude/projects/<encoded-cwd>/
            # The session was created in the current working directory context
            cwd = str(Path.cwd())
            claude_home = get_claude_home()
            encoded_path = encode_claude_project_path(cwd)
            session_file = claude_home / "projects" / encoded_path / f"{session_id}.jsonl"
            # Mark as helper first (belt and suspenders)
            mark_session_as_helper(session_file)
            session_file.unlink(missing_ok=True)
    except Exception:
        pass  # Don't fail smart-trim if cleanup fails


def extract_large_content(
    data: Any, min_length: int = 200, path: str = ""
) -> List[tuple]:
    """
    Recursively extract large text content from JSON structure.

    Args:
        data: JSON data (dict, list, or primitive)
        min_length: Minimum string length to extract (default: 200)
        path: Current JSON path (for debugging)

    Returns:
        List of (path, content) tuples for strings >= min_length
    """
    results = []

    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            results.extend(extract_large_content(value, min_length, new_path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_path = f"{path}[{i}]"
            results.extend(extract_large_content(item, min_length, new_path))
    elif isinstance(data, str):
        if len(data) >= min_length:
            results.append((path, data))

    return results


def extract_relevant_content(
    data: Dict[str, Any], msg_type: str, min_length: int = 200
) -> List[tuple]:
    """
    Extract relevant content for trimming from Claude Code or Codex sessions.

    Handles formats:
    - Claude Code: type="assistant"/"user"/"tool_result"
    - Codex (new): type="response_item" with payload.type
    - Codex (old): type="message"/"function_call_output" directly

    Args:
        data: Parsed JSON line data
        msg_type: Message type
        min_length: Minimum string length to extract (default: 200)

    Returns:
        List of (label, content) tuples for relevant strings >= min_length.
        Labels are human-readable: [ASSISTANT], [USER], [TOOL_RESULT]
    """
    results = []

    # Codex new format: response_item with payload
    if msg_type == "response_item":
        payload = data.get("payload", {})
        payload_type = payload.get("type", "")

        if payload_type == "message":
            content = payload.get("content", [])
            if isinstance(content, list):
                for i, block in enumerate(content):
                    if isinstance(block, dict):
                        text = block.get("text", "")
                        if isinstance(text, str) and len(text) >= min_length:
                            results.append(("[ASSISTANT]", text))

        elif payload_type == "function_call_output":
            output = payload.get("output", "")
            if isinstance(output, str) and len(output) >= min_length:
                results.append(("[TOOL_RESULT]", output))

    # Codex old format: message directly at top level
    elif msg_type == "message":
        content = data.get("content", [])
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict):
                    # Old Codex uses input_text/output_text
                    text = block.get("text", "")
                    if isinstance(text, str) and len(text) >= min_length:
                        results.append(("[ASSISTANT]", text))

    # Codex old format: function_call_output directly at top level
    elif msg_type == "function_call_output":
        output = data.get("output", "")
        if isinstance(output, str) and len(output) >= min_length:
            results.append(("[TOOL_RESULT]", output))

    # Claude Code format
    elif msg_type == "assistant":
        # Extract only text-type blocks from content array (skip thinking)
        message = data.get("message", {})
        content = message.get("content", [])
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if isinstance(text, str) and len(text) >= min_length:
                        results.append(("[ASSISTANT]", text))

    elif msg_type == "tool_result":
        # Claude Code tool result
        result = data.get("result", "")
        if isinstance(result, str) and len(result) >= min_length:
            results.append(("[TOOL_RESULT]", result))

    elif msg_type == "user":
        # Claude Code user message - can contain text AND tool_result blocks
        message = data.get("message", {})
        content = message.get("content", [])
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    # Extract text content (actual user input)
                    if block_type == "text" or (not block_type and "text" in block):
                        text = block.get("text", "")
                        if isinstance(text, str) and len(text) >= min_length:
                            results.append(("[USER]", text))
                    # Extract tool_result content (embedded in user messages)
                    elif block_type == "tool_result":
                        tool_content = block.get("content", "")
                        if isinstance(tool_content, str) and len(tool_content) >= min_length:
                            results.append(("[TOOL_RESULT]", tool_content))

    return results


def identify_trimmable_lines_cli(
    session_file: Path,
    exclude_types: Optional[List[str]] = None,
    preserve_recent: int = 10,
    content_threshold: int = 200,
    custom_instructions: Optional[str] = None,
    cli_type: str = "claude",
) -> List[tuple]:
    """
    Identify session lines that can be safely trimmed using CLI.

    Uses the headless CLI mode. For Claude, it deploys parallel sub-agents
    for large sessions.

    Args:
        session_file: Path to session JSONL file
        exclude_types: Message types to never trim (default: [])
        preserve_recent: Always preserve last N messages (default: 10)
        content_threshold: Min chars to extract from JSON (default: 200)
        custom_instructions: Custom trimming instructions
        cli_type: Which CLI to use - "claude" or "codex" (default: "claude")

    Returns:
        List of (line_idx, rationale, summary) tuples
    """
    if exclude_types is None:
        exclude_types = []

    # Read session to determine protected indices
    with open(session_file, 'r') as f:
        session_lines = f.readlines()

    total_lines = len(session_lines)

    # Build protected indices set
    protected_indices = set()

    # Protect by message type
    for idx, line in enumerate(session_lines):
        try:
            data = json.loads(line)
            msg_type = data.get("type", "")
            if msg_type in exclude_types:
                protected_indices.add(idx)
        except json.JSONDecodeError:
            pass

    # Protect recent messages
    if preserve_recent > 0:
        for idx in range(max(0, total_lines - preserve_recent), total_lines):
            protected_indices.add(idx)

    # Call CLI-based analysis
    results = analyze_session_with_cli(
        session_file,
        custom_instructions=custom_instructions,
        content_threshold=content_threshold,
        cli_type=cli_type,
    )

    # Filter out protected indices
    filtered = [
        (idx, rationale, summary)
        for idx, rationale, summary in results
        if idx not in protected_indices
    ]

    return filtered

