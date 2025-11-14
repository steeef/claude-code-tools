"""Intelligent session trimming using LLM analysis."""

import asyncio
import json
from pathlib import Path
from typing import List, Optional

from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk.types import AssistantMessage
from typing import Any, Dict


ANALYSIS_PROMPT = """You are analyzing a coding agent session to identify content that can be safely removed.

Your task: Identify line numbers that can be trimmed without affecting the ability to continue work.

This is chunk {chunk_index} of {total_chunks} (lines {chunk_start}-{chunk_end} of the session).

IMPORTANT - What you're seeing:
- For assistant messages: ONLY the text content (thinking blocks are filtered out)
- For tool results: The output/result content
- System messages (file-history-snapshot, summary, etc.) are filtered out
- Reasoning/thinking tokens are filtered out (they don't count in context)

Consider for trimming:
- Verbose tool results that were one-time analysis only
- Lengthy assistant explanations no longer relevant
- Intermediate debugging output
- Large file reads that served their purpose
- Repetitive explanations or acknowledgments

DO NOT trim:
- User messages (already protected)
- Recent messages (already protected)
- Critical context or decisions
- Error messages or warnings
- Information that might be referenced in later parts of the session

Session content chunk:
{session_content}

Each line is labeled "LINE N:" where N is the line number in the original session file.

{response_format}
"""

RESPONSE_FORMAT_NORMAL = """Respond with ONLY a JSON array of the line numbers to trim, e.g.: [0, 5, 12, 23]
Use the exact line numbers shown in the "LINE N:" labels."""

RESPONSE_FORMAT_VERBOSE = """Respond with ONLY a JSON array of tuples [line_number, rationale], e.g.:
[[0, "verbose tool output"], [5, "redundant explanation"], [12, "debug output"]]

Each rationale should be a brief phrase (max 5-6 words) explaining why that line can be trimmed.
Use the exact line numbers shown in the "LINE N:" labels."""


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
        List of (path, content) tuples for relevant strings >= min_length
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
                            results.append((f"payload.content[{i}].text", text))

        elif payload_type == "function_call_output":
            output = payload.get("output", "")
            if isinstance(output, str) and len(output) >= min_length:
                results.append(("payload.output", output))

    # Codex old format: message directly at top level
    elif msg_type == "message":
        content = data.get("content", [])
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict):
                    # Old Codex uses input_text/output_text
                    text = block.get("text", "")
                    if isinstance(text, str) and len(text) >= min_length:
                        results.append((f"content[{i}].text", text))

    # Codex old format: function_call_output directly at top level
    elif msg_type == "function_call_output":
        output = data.get("output", "")
        if isinstance(output, str) and len(output) >= min_length:
            results.append(("output", output))

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
                        results.append((f"message.content[{i}].text", text))

    elif msg_type == "tool_result":
        # Claude Code tool result
        result = data.get("result", "")
        if isinstance(result, str) and len(result) >= min_length:
            results.append(("result", result))

    elif msg_type == "user":
        # Claude Code user message
        message = data.get("message", {})
        content = message.get("content", [])
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict):
                    text = block.get("text", "")
                    if isinstance(text, str) and len(text) >= min_length:
                        results.append((f"message.content[{i}].text", text))

    return results


async def _analyze_chunk(
    chunk_data: List[tuple],
    chunk_index: int,
    total_chunks: int,
    chunk_start: int,
    chunk_end: int,
    verbose: bool = False,
):
    """
    Analyze a single chunk of session lines.

    Args:
        chunk_data: List of (line_idx, preview) tuples for this chunk
        chunk_index: Index of this chunk (0-based)
        total_chunks: Total number of chunks
        chunk_start: Starting line number in original session
        chunk_end: Ending line number in original session
        verbose: If True, return list of (line_idx, rationale) tuples

    Returns:
        If verbose=False: List of line indices to trim
        If verbose=True: List of (line_idx, rationale) tuples
    """
    # Format chunk content with explicit line numbers
    session_content = "\n".join(
        f"LINE {idx}: {preview}" for idx, preview in chunk_data
    )

    # Query Claude agent
    response_format = RESPONSE_FORMAT_VERBOSE if verbose else RESPONSE_FORMAT_NORMAL
    prompt = ANALYSIS_PROMPT.format(
        chunk_index=chunk_index + 1,
        total_chunks=total_chunks,
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        session_content=session_content,
        response_format=response_format,
    )

    options = ClaudeAgentOptions(
        system_prompt="You are an expert at analyzing coding sessions and identifying redundant content.",
        permission_mode='bypassPermissions'
    )

    response_text = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            # Extract text from TextBlock objects in content
            for block in message.content:
                if hasattr(block, 'text'):
                    response_text += block.text

    # Parse response to get line numbers (and rationales if verbose)
    try:
        start = response_text.find('[')
        end = response_text.rfind(']') + 1
        if start >= 0 and end > start:
            result = json.loads(response_text[start:end])
            # Validate format
            if verbose:
                # Should be list of [line_num, rationale] tuples
                if all(isinstance(item, list) and len(item) == 2 for item in result):
                    return [(int(item[0]), str(item[1])) for item in result]
            else:
                # Should be list of integers
                if all(isinstance(item, int) for item in result):
                    return result
        return []
    except (json.JSONDecodeError, ValueError, TypeError):
        return []


async def _analyze_session_async(
    session_lines: List[str],
    exclude_types: List[str],
    preserve_recent: int,
    max_lines_per_agent: int = 100,
    verbose: bool = False,
    content_threshold: int = 200,
):
    """
    Use Claude Agent SDK to identify trimmable lines using parallel agents.

    Args:
        session_lines: List of JSONL lines from session
        exclude_types: Message types to never trim (e.g., ["user"])
        preserve_recent: Number of recent messages to always preserve
        max_lines_per_agent: Maximum lines per agent chunk (default: 100)
        verbose: If True, return (line_idx, rationale) tuples
        content_threshold: Min chars for content extraction (default: 200)

    Returns:
        If verbose=False: List of line indices to trim
        If verbose=True: List of (line_idx, rationale) tuples
    """
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

            # Mark protected indices based on exclude_types or preserve_recent
            if msg_type in exclude_types or idx >= len(session_lines) - preserve_recent:
                protected_indices.add(idx)
                continue

            # Extract relevant content based on message type
            relevant_content = extract_relevant_content(data, effective_type, content_threshold)

            if relevant_content:
                # Show extracted content with field paths
                preview_parts = []
                for path, content in relevant_content[:3]:  # Max 3 content fields
                    content_preview = content[:500] if len(content) > 500 else content
                    preview_parts.append(f"{path}({len(content)} chars): {content_preview}")
                preview = " | ".join(preview_parts)
            else:
                # No relevant content, show type and keys
                keys = list(data.keys())[:5]
                preview = f"type={msg_type}, keys={keys} (no relevant content >= {content_threshold} chars)"

            session_data.append((idx, preview))

        except json.JSONDecodeError:
            protected_indices.add(idx)  # Protect malformed lines

    if not session_data:
        return []

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
    tasks = [
        _analyze_chunk(chunk, chunk_idx, total_chunks, chunk_start, chunk_end, verbose)
        for chunk, chunk_idx, chunk_start, chunk_end in chunks
    ]

    # Gather results from all agents
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge results and filter out protected indices
    if verbose:
        # Results are list of (line_idx, rationale) tuples
        trimmable_dict = {}
        for result in results:
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, tuple) and len(item) == 2:
                        line_idx, rationale = item
                        if line_idx not in protected_indices:
                            trimmable_dict[line_idx] = rationale
        # Return sorted list of tuples
        return sorted(trimmable_dict.items())
    else:
        # Results are list of integers
        trimmable = set()
        for result in results:
            if isinstance(result, list):
                trimmable.update(result)
        # Filter out protected indices
        return sorted([idx for idx in trimmable if idx not in protected_indices])


def identify_trimmable_lines(
    session_file: Path,
    exclude_types: Optional[List[str]] = None,
    preserve_recent: int = 10,
    max_lines_per_agent: int = 100,
    verbose: bool = False,
    content_threshold: int = 200,
):
    """
    Identify session lines that can be safely trimmed using parallel agents.

    Args:
        session_file: Path to session JSONL file
        exclude_types: Message types to never trim (default: ["user"])
        preserve_recent: Always preserve last N messages (default: 10)
        max_lines_per_agent: Max lines per agent chunk (default: 100)
        verbose: If True, return (line_idx, rationale) tuples (default: False)
        content_threshold: Min chars to extract from JSON (default: 200)

    Returns:
        If verbose=False: List of 0-indexed line numbers to trim
        If verbose=True: List of (line_idx, rationale) tuples
    """
    if exclude_types is None:
        exclude_types = ["user"]

    # Read session file
    with open(session_file, 'r') as f:
        session_lines = f.readlines()

    # Run async analysis with parallel agents
    return asyncio.run(_analyze_session_async(
        session_lines,
        exclude_types,
        preserve_recent,
        max_lines_per_agent,
        verbose,
        content_threshold
    ))
