"""Intelligent session trimming using LLM analysis."""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import List, Optional, Any, Dict

# Import Claude SDK only when needed (may not be installed for Codex-only users)
try:
    from claude_agent_sdk import query, ClaudeAgentOptions
    from claude_agent_sdk.types import AssistantMessage, ResultMessage
    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False

from claude_code_tools.session_utils import (
    encode_claude_project_path,
    extract_cwd_from_session,
    get_claude_home,
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


ANALYSIS_PROMPT = """You are analyzing a coding agent session to identify content that can be safely removed.

Your task: Identify line numbers that can be trimmed without affecting the ability to continue work.

This is chunk {chunk_index} of {total_chunks} (lines {chunk_start}-{chunk_end} of the session).

WHAT YOU'RE SEEING:
- Each line is labeled: LINE N [len=X]: [TYPE]: where N is the line number, X is content length
- TYPE indicates content source:
  - [ASSISTANT]: Claude's response text (thinking blocks are filtered out)
  - [USER]: User's input text
  - [TOOL_RESULT]: Output from tool calls (file reads, bash commands, etc.)
- System messages (file-history-snapshot, summary, etc.) are filtered out
- Reasoning/thinking tokens are filtered out (they don't count in context)

LENGTH THRESHOLD:
- ONLY consider lines with length >= {trim_threshold} characters for trimming
- Lines shorter than {trim_threshold} chars should NEVER be included in your output

CONSIDER FOR TRIMMING (if length >= {trim_threshold}):
- Verbose tool results that were one-time analysis only
- Lengthy assistant explanations no longer relevant
- Intermediate debugging output
- Large file reads that served their purpose
- Repetitive explanations or acknowledgments

DO NOT TRIM:
- Lines with length < {trim_threshold} characters
- Critical user instructions or context
- Recent messages (already protected)
- Critical context or decisions
- Error messages or warnings
- Information that might be referenced in later parts of the session

Pay special attention to the USER CUSTOM INSTRUCTIONS below.

USER CUSTOM INSTRUCTIONS:
{custom_instructions}

{response_format}

============ SESSION CONTENT START ============

{session_content}

============ SESSION CONTENT END ============
"""

RESPONSE_FORMAT_NORMAL = """Respond with ONLY a JSON array of the line numbers to trim, e.g.: [0, 5, 12, 23]
Use the exact line numbers shown in the "LINE N:" labels."""

RESPONSE_FORMAT_VERBOSE = """Respond with ONLY a JSON array of tuples [line_number, rationale, description], e.g.:
[[0, "verbose tool output", "Reading `/src/config.py`"], [5, "redundant explanation", "Explaining test setup"], [12, "debug output", "Bash output from `npm test`"]]

For each line:
- rationale: Brief phrase (max 5-6 words) explaining why it can be trimmed
- description: 1-2 sentence summary of what the line contains. IMPORTANT: Always include explicit file paths when the content involves reading, writing, or editing files (e.g., "Writing code to `/src/main.py`", "Result of reading `/config/settings.json`")

Use the exact line numbers shown in the "LINE N:" labels."""

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

IMPORTANT CONSTRAINTS:
- ONLY consider entries where len >= 500 for trimming

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

IMPORTANT CONSTRAINTS:
- ONLY consider entries where len >= 500 for trimming

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
            if total_len < 50:  # Skip very short lines
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

    # Extract session_id from filename
    session_id = session_file.stem

    # Write session representation to file instead of embedding in prompt
    if cli_type == "codex":
        exports_dir = Path(".codex/exports")
    else:
        exports_dir = Path(".claude/exports")
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
        is_codex_session = ".codex" in str(session_file)
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
        if cli_type == "codex":
            # Codex outputs JSONL stream - extract text from response_item events
            text = ""
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if event.get("type") == "response_item":
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
        is_codex_session = ".codex" in str(session_file)
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


async def _analyze_chunk(
    chunk_data: List[tuple],
    chunk_index: int,
    total_chunks: int,
    chunk_start: int,
    chunk_end: int,
    verbose: bool = False,
    trim_threshold: int = SMART_TRIM_THRESHOLD,
    cwd: Optional[str] = None,
    custom_instructions: Optional[str] = None,
):
    """
    Analyze a single chunk of session lines.

    Args:
        chunk_data: List of (line_idx, preview, content_len) tuples for this chunk
        chunk_index: Index of this chunk (0-based)
        total_chunks: Total number of chunks
        chunk_start: Starting line number in original session
        chunk_end: Ending line number in original session
        verbose: If True, return list of (line_idx, rationale, description) tuples
        trim_threshold: Minimum content length for trimming consideration
        cwd: Working directory for constructing session file path (for marking
            the helper session)

    Returns:
        If verbose=False: List of line indices to trim
        If verbose=True: List of (line_idx, rationale, description) tuples
    """
    # Format chunk content with explicit line numbers and lengths
    # Use double newlines to clearly separate each LINE entry
    session_content = "\n\n".join(
        f"LINE {idx} [len={content_len}]:\n{preview}"
        for idx, preview, content_len in chunk_data
    )

    # Query Claude agent
    response_format = RESPONSE_FORMAT_VERBOSE if verbose else RESPONSE_FORMAT_NORMAL

    # Use default instructions if none provided
    default_instructions = (
        "trim messages that are not relevant to the last task "
        "being worked on in this session"
    )
    instructions = custom_instructions or default_instructions

    prompt = ANALYSIS_PROMPT.format(
        chunk_index=chunk_index + 1,
        total_chunks=total_chunks,
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        session_content=session_content,
        response_format=response_format,
        trim_threshold=trim_threshold,
        custom_instructions=instructions,
    )

    options = ClaudeAgentOptions(
        system_prompt="You are an expert at analyzing coding sessions and identifying redundant content.",
        permission_mode='bypassPermissions'
    )

    response_text = ""
    session_id = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            # Extract text from TextBlock objects in content
            for block in message.content:
                if hasattr(block, 'text'):
                    response_text += block.text
        elif CLAUDE_SDK_AVAILABLE and isinstance(message, ResultMessage):
            # Capture session_id from ResultMessage
            session_id = getattr(message, 'session_id', None)

    # Delete the helper session since it's no longer needed
    # Note: SDK creates sessions in os.getcwd(), not the cwd of the session being analyzed
    if session_id:
        try:
            claude_home = get_claude_home()
            current_cwd = os.getcwd()
            encoded_path = encode_claude_project_path(current_cwd)
            session_file = (
                claude_home / "projects" / encoded_path / f"{session_id}.jsonl"
            )
            # mark_session_as_helper(session_file)  # Keep for reference
            session_file.unlink(missing_ok=True)
        except Exception:
            pass  # Don't fail analysis if deletion fails

    # Parse response to get line numbers (and rationales/descriptions if verbose)
    try:
        start = response_text.find('[')
        end = response_text.rfind(']') + 1
        if start >= 0 and end > start:
            result = json.loads(response_text[start:end])
            # Validate format
            if verbose:
                # Should be list of [line_num, rationale, description] tuples
                parsed = []
                for item in result:
                    if isinstance(item, list) and len(item) >= 2:
                        line_num = int(item[0])
                        rationale = str(item[1])
                        # Description is optional for backwards compatibility
                        description = str(item[2]) if len(item) >= 3 else ""
                        parsed.append((line_num, rationale, description))
                return parsed
            else:
                # Should be list of integers
                if all(isinstance(item, int) for item in result):
                    return result
        return []
    except (json.JSONDecodeError, ValueError, TypeError):
        return []


def _analyze_chunk_codex(
    chunk_data: List[tuple],
    chunk_index: int,
    total_chunks: int,
    chunk_start: int,
    chunk_end: int,
    verbose: bool = False,
    trim_threshold: int = SMART_TRIM_THRESHOLD,
):
    """
    Analyze a single chunk of session lines using Codex CLI.

    Fallback for when Claude SDK is not available.

    Args:
        chunk_data: List of (line_idx, preview, content_len) tuples for this chunk
        chunk_index: Index of this chunk (0-based)
        total_chunks: Total number of chunks
        chunk_start: Starting line number in original session
        chunk_end: Ending line number in original session
        verbose: If True, return list of (line_idx, rationale, description) tuples
        trim_threshold: Minimum content length for trimming consideration

    Returns:
        If verbose=False: List of line indices to trim
        If verbose=True: List of (line_idx, rationale, description) tuples
    """
    # Format chunk content with explicit line numbers and lengths
    # Use double newlines to clearly separate each LINE entry
    session_content = "\n\n".join(
        f"LINE {idx} [len={content_len}]:\n{preview}"
        for idx, preview, content_len in chunk_data
    )

    # Build prompt (same as Claude but without sub-agent references)
    response_format = RESPONSE_FORMAT_VERBOSE if verbose else RESPONSE_FORMAT_NORMAL
    prompt = ANALYSIS_PROMPT.format(
        chunk_index=chunk_index + 1,
        total_chunks=total_chunks,
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        session_content=session_content,
        response_format=response_format,
        trim_threshold=trim_threshold,
    )

    # Prepend system context to the prompt for Codex
    full_prompt = (
        "You are an expert at analyzing coding sessions and identifying "
        "redundant content.\n\n" + prompt
    )

    try:
        # Run codex exec --json
        cmd = ["codex", "exec", "--json", full_prompt]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=300  # 5 minute timeout per chunk
        )

        # Parse JSON stream to extract assistant's text response
        response_text = ""
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                # Codex outputs response_item events with message payloads
                if event.get("type") == "response_item":
                    payload = event.get("payload", {})
                    if payload.get("type") == "message":
                        content = payload.get("content", [])
                        for block in content:
                            if isinstance(block, dict) and "text" in block:
                                response_text += block.get("text", "")
            except json.JSONDecodeError:
                continue

        # Parse response to get line numbers
        start = response_text.find('[')
        end = response_text.rfind(']') + 1
        if start >= 0 and end > start:
            parsed_result = json.loads(response_text[start:end])
            if verbose:
                # Should be list of [line_num, rationale, description] tuples
                parsed = []
                for item in parsed_result:
                    if isinstance(item, list) and len(item) >= 2:
                        line_num = int(item[0])
                        rationale = str(item[1])
                        description = str(item[2]) if len(item) >= 3 else ""
                        parsed.append((line_num, rationale, description))
                return parsed
            else:
                # Should be list of integers
                if all(isinstance(item, int) for item in parsed_result):
                    return parsed_result
        return []

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError, ValueError, TypeError):
        return []


async def _analyze_chunk_codex_async(
    chunk_data: List[tuple],
    chunk_index: int,
    total_chunks: int,
    chunk_start: int,
    chunk_end: int,
    verbose: bool = False,
    trim_threshold: int = SMART_TRIM_THRESHOLD,
):
    """Async wrapper for _analyze_chunk_codex to allow parallel execution."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _analyze_chunk_codex,
        chunk_data,
        chunk_index,
        total_chunks,
        chunk_start,
        chunk_end,
        verbose,
        trim_threshold,
    )


async def _analyze_session_async(
    session_lines: List[str],
    exclude_types: List[str],
    preserve_recent: int,
    max_lines_per_agent: int = 100,
    verbose: bool = False,
    content_threshold: int = 200,
    preserve_head: int = 0,
    preserve_tail: Optional[int] = None,
    cwd: Optional[str] = None,
    custom_instructions: Optional[str] = None,
):
    """
    Use Claude Agent SDK to identify trimmable lines using parallel agents.

    Args:
        session_lines: List of JSONL lines from session
        exclude_types: Message types to never trim (e.g., ["user"])
        preserve_recent: Number of recent messages to always preserve (deprecated,
            use preserve_tail instead)
        max_lines_per_agent: Maximum lines per agent chunk (default: 100)
        verbose: If True, return (line_idx, rationale) tuples
        content_threshold: Min chars for content extraction (default: 200)
        preserve_head: Number of messages at beginning to always preserve
            (default: 0)
        preserve_tail: Number of messages at end to always preserve (default:
            None, uses preserve_recent)
        cwd: Working directory for constructing helper session file paths

    Returns:
        If verbose=False: List of line indices to trim
        If verbose=True: List of (line_idx, rationale) tuples
    """
    # Use preserve_tail if specified, otherwise fall back to preserve_recent
    if preserve_tail is None:
        preserve_tail = preserve_recent
    # Build session content and identify protected indices
    session_data = []
    protected_indices = set()

    # Claude Code trimmable types
    claude_trimmable_types = {"user", "assistant", "tool_result"}
    # Codex new format
    codex_new_type = "response_item"
    # Codex old format trimmable types
    codex_old_trimmable = {"message", "function_call_output"}
    # Codex old format protected types
    codex_old_protected = {"reasoning", "function_call"}

    for idx, line in enumerate(session_lines):
        try:
            data = json.loads(line)
            msg_type = data.get("type", "unknown")

            # Determine if this is a trimmable message
            is_trimmable = False
            effective_type = msg_type

            if msg_type in claude_trimmable_types:
                # Claude Code format
                is_trimmable = True

            elif msg_type == codex_new_type:
                # Codex new format - check payload type
                payload = data.get("payload", {})
                payload_type = payload.get("type", "")

                if payload_type == "reasoning":
                    # Codex reasoning (like Claude thinking) - protect
                    protected_indices.add(idx)
                    continue
                elif payload_type in ("message", "function_call_output"):
                    # Trimmable Codex types
                    is_trimmable = True
                    effective_type = codex_new_type
                else:
                    # Other Codex types (function_call, etc.) - protect
                    protected_indices.add(idx)
                    continue

            elif msg_type in codex_old_trimmable:
                # Codex old format (Sept 2025 and earlier)
                is_trimmable = True
                effective_type = msg_type

            elif msg_type in codex_old_protected:
                # Codex old format protected types
                protected_indices.add(idx)
                continue

            else:
                # System types (file-history-snapshot, summary, etc.) - protect
                protected_indices.add(idx)
                continue

            if not is_trimmable:
                protected_indices.add(idx)
                continue

            # Protect thinking-only messages (Claude Code only)
            if msg_type == "assistant":
                message = data.get("message", {})
                content = message.get("content", [])
                if isinstance(content, list) and content:
                    # Check if all content items are thinking blocks
                    if all(
                        isinstance(item, dict) and item.get("type") == "thinking"
                        for item in content
                    ):
                        protected_indices.add(idx)
                        continue

            # Mark protected indices based on exclude_types, preserve_head, or
            # preserve_tail
            if (msg_type in exclude_types or
                idx < preserve_head or
                idx >= len(session_lines) - preserve_tail):
                protected_indices.add(idx)
                continue

            # Extract relevant content based on message type
            relevant_content = extract_relevant_content(data, effective_type, content_threshold)

            if relevant_content:
                # Calculate total content length across all fields
                total_content_len = sum(len(content) for _, content in relevant_content)

                # Show extracted content with type labels
                preview_parts = []
                for label, content in relevant_content[:3]:  # Max 3 content fields
                    content_preview = content[:500] if len(content) > 500 else content
                    preview_parts.append(f"{label}({len(content)} chars): {content_preview}")
                preview = " | ".join(preview_parts)

                # Store (idx, preview, content_len) tuple
                session_data.append((idx, preview, total_content_len))
            else:
                # No relevant content - skip this line (nothing to trim)
                continue

        except json.JSONDecodeError:
            protected_indices.add(idx)  # Protect malformed lines

    if not session_data:
        return []

    # Build a mapping of line index to content length for filtering
    content_lengths = {idx: content_len for idx, _, content_len in session_data}

    # Split into chunks for parallel processing
    chunks = []
    for i in range(0, len(session_data), max_lines_per_agent):
        chunk = session_data[i:i + max_lines_per_agent]
        if chunk:
            chunk_start = chunk[0][0]
            chunk_end = chunk[-1][0]
            chunks.append((chunk, i // max_lines_per_agent, chunk_start, chunk_end))

    total_chunks = len(chunks)

    # Launch parallel agents for each chunk
    # Use Claude SDK if available (has parallel sub-agents), otherwise fall back to Codex
    if CLAUDE_SDK_AVAILABLE:
        tasks = [
            _analyze_chunk(
                chunk, chunk_idx, total_chunks, chunk_start, chunk_end,
                verbose, trim_threshold=SMART_TRIM_THRESHOLD, cwd=cwd,
                custom_instructions=custom_instructions
            )
            for chunk, chunk_idx, chunk_start, chunk_end in chunks
        ]
    else:
        # Fall back to Codex CLI
        tasks = [
            _analyze_chunk_codex_async(
                chunk, chunk_idx, total_chunks, chunk_start, chunk_end,
                verbose, trim_threshold=SMART_TRIM_THRESHOLD
            )
            for chunk, chunk_idx, chunk_start, chunk_end in chunks
        ]

    # Gather results from all agents
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge results and filter out protected indices AND lines under threshold
    if verbose:
        # Results are list of (line_idx, rationale, description) tuples
        trimmable_dict = {}
        for result in results:
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, tuple) and len(item) >= 2:
                        line_idx = item[0]
                        rationale = item[1]
                        description = item[2] if len(item) >= 3 else ""
                        # Filter: not protected AND content >= threshold
                        content_len = content_lengths.get(line_idx, 0)
                        if (line_idx not in protected_indices and
                                content_len >= SMART_TRIM_THRESHOLD):
                            trimmable_dict[line_idx] = (rationale, description)
        # Return sorted list of tuples: (line_idx, rationale, description)
        return [(idx, rat_desc[0], rat_desc[1]) for idx, rat_desc in sorted(trimmable_dict.items())]
    else:
        # Results are list of integers
        trimmable = set()
        for result in results:
            if isinstance(result, list):
                trimmable.update(result)
        # Filter out protected indices AND lines under threshold
        return sorted([
            idx for idx in trimmable
            if idx not in protected_indices and
               content_lengths.get(idx, 0) >= SMART_TRIM_THRESHOLD
        ])


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


def identify_trimmable_lines(
    session_file: Path,
    exclude_types: Optional[List[str]] = None,
    preserve_recent: int = 10,
    max_lines_per_agent: int = 100,
    verbose: bool = True,
    content_threshold: int = 200,
    preserve_head: int = 0,
    preserve_tail: Optional[int] = None,
    custom_instructions: Optional[str] = None,
):
    """
    Identify session lines that can be safely trimmed using parallel agents.

    Args:
        session_file: Path to session JSONL file
        exclude_types: Message types to never trim (default: ["user"])
        preserve_recent: Always preserve last N messages (default: 10,
            deprecated - use preserve_tail instead)
        max_lines_per_agent: Max lines per agent chunk (default: 100)
        verbose: If True, return (line_idx, rationale, description) tuples
            (default: True)
        content_threshold: Min chars to extract from JSON (default: 200)
        preserve_head: Always preserve first N messages (default: 0)
        preserve_tail: Always preserve last N messages (default: None, uses
            preserve_recent)
        custom_instructions: Optional custom instructions for the trim agents

    Returns:
        If verbose=False: List of 0-indexed line numbers to trim
        If verbose=True: List of (line_idx, rationale, description) tuples where
            description is a 1-2 sentence summary with explicit file paths
    """
    if exclude_types is None:
        exclude_types = []

    # Read session file
    with open(session_file, 'r') as f:
        session_lines = f.readlines()

    # Extract cwd for marking helper sessions
    cwd = extract_cwd_from_session(session_file)

    # Run async analysis with parallel agents
    return asyncio.run(_analyze_session_async(
        session_lines,
        exclude_types,
        preserve_recent,
        max_lines_per_agent,
        verbose,
        content_threshold,
        preserve_head,
        preserve_tail,
        cwd=cwd,
        custom_instructions=custom_instructions,
    ))
