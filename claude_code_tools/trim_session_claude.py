"""Claude Code specific logic for suppressing tool results."""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple


def build_tool_name_mapping(input_file: Path) -> Dict[str, str]:
    """
    Build a mapping of tool_use_id to tool name for Claude sessions.

    Args:
        input_file: Path to the input JSONL file.

    Returns:
        Dictionary mapping tool_use_id to tool name.
    """
    tool_map = {}

    with open(input_file, "r") as f:
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if data.get("type") != "assistant":
                continue

            content = data.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue

            for item in content:
                if (
                    isinstance(item, dict)
                    and item.get("type") == "tool_use"
                ):
                    tool_id = item.get("id")
                    tool_name = item.get("name")
                    if tool_id and tool_name:
                        tool_map[tool_id] = tool_name

    return tool_map


def get_content_length(content: Any) -> int:
    """
    Calculate the length of tool result content.

    Args:
        content: The content field from a tool_result.

    Returns:
        Length in characters.
    """
    if isinstance(content, str):
        return len(content)
    elif isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, dict) and "text" in item:
                total += len(item["text"])
            else:
                total += len(str(item))
        return total
    else:
        return len(str(content))


def truncate_content(content: Any, threshold: int, tool_name: str) -> str:
    """
    Truncate content to threshold length, preserving first N characters.

    Args:
        content: The content field from a tool_result.
        threshold: Maximum length to preserve.
        tool_name: Name of the tool (for truncation notice).

    Returns:
        Truncated content string.
    """
    # Convert content to string if needed
    if isinstance(content, str):
        content_str = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            else:
                parts.append(str(item))
        content_str = "".join(parts)
    else:
        content_str = str(content)

    # If content is within threshold, return as-is
    if len(content_str) <= threshold:
        return content_str

    # Truncate and add notice
    original_length = len(content_str)
    truncated = content_str[:threshold]
    truncation_notice = (
        f"\n\n[...truncated - original content was "
        f"{original_length:,} characters, showing first {threshold}]"
    )

    return truncated + truncation_notice


def process_claude_session(
    input_file: Path,
    output_file: Path,
    tool_map: Dict[str, str],
    target_tools: Set[str],
    threshold: int,
    create_placeholder: callable,
    new_session_id: Optional[str] = None,
    trim_assistant_messages: Optional[int] = None,
) -> Tuple[int, int, int]:
    """
    Process Claude Code session file and trim tool results and assistant messages.

    Args:
        input_file: Path to input JSONL file.
        output_file: Path to output JSONL file.
        tool_map: Mapping of tool_use_id to tool name.
        target_tools: Set of tool names to suppress (None means all).
        threshold: Minimum length threshold for trimming.
        create_placeholder: Function to create placeholder text.
        new_session_id: Optional new session ID to replace in all events.
        trim_assistant_messages: Optional assistant message trimming (see trim_and_create_session).

    Returns:
        Tuple of (num_tools_trimmed, num_assistant_trimmed, chars_saved).
    """
    num_tools_trimmed = 0
    num_assistant_trimmed = 0
    chars_saved = 0

    # First pass: identify assistant messages to trim
    assistant_indices_to_trim = set()
    if trim_assistant_messages is not None:
        assistant_messages = []  # List of (line_num, length, data)

        with open(input_file, "r") as f:
            for line_num, line in enumerate(f, start=1):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "assistant":
                    content = data.get("message", {}).get("content", [])
                    total_length = sum(
                        len(str(item.get("text", "")))
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                    if total_length >= threshold:
                        assistant_messages.append((line_num, total_length, data))

        # Determine which to trim based on parameter
        if trim_assistant_messages > 0:
            # Trim first N
            count = min(trim_assistant_messages, len(assistant_messages))
            assistant_indices_to_trim = {
                msg[0] for msg in assistant_messages[:count]
            }
        elif trim_assistant_messages < 0:
            # Trim all except last abs(N)
            keep_count = min(abs(trim_assistant_messages), len(assistant_messages))
            trim_count = len(assistant_messages) - keep_count
            assistant_indices_to_trim = {
                msg[0] for msg in assistant_messages[:trim_count]
            }

    # Second pass: process and trim
    with open(input_file, "r") as infile, open(
        output_file, "w"
    ) as outfile:
        for line_num, line in enumerate(infile, start=1):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                outfile.write(line)
                continue

            # Trim assistant messages if needed
            if data.get("type") == "assistant" and line_num in assistant_indices_to_trim:
                content = data.get("message", {}).get("content", [])
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        original_text = item.get("text", "")
                        original_length = len(original_text)
                        if original_length >= threshold:
                            placeholder = (
                                f"[Assistant message trimmed - "
                                f"original content was {original_length:,} characters]"
                            )
                            item["text"] = placeholder
                            chars_saved += original_length - len(placeholder)
                            num_assistant_trimmed += 1

            # Check if this is a user message with tool results
            elif data.get("type") == "user":
                content = data.get("message", {}).get("content")

                # Handle array content with tool_result
                if isinstance(content, list):
                    for item in content:
                        if (
                            isinstance(item, dict)
                            and item.get("type") == "tool_result"
                        ):
                            tool_use_id = item.get("tool_use_id")
                            tool_name = tool_map.get(
                                tool_use_id, "Unknown"
                            )
                            result_content = item.get("content", "")

                            content_length = get_content_length(
                                result_content
                            )

                            # Check if should truncate
                            if content_length >= threshold and (
                                target_tools is None
                                or tool_name.lower() in target_tools
                            ):
                                truncated = truncate_content(
                                    result_content, threshold, tool_name
                                )
                                item["content"] = truncated
                                num_tools_trimmed += 1
                                chars_saved += content_length - len(truncated)

                # Also suppress in toolUseResult.content if present
                if (
                    "toolUseResult" in data
                    and isinstance(data["toolUseResult"], dict)
                ):
                    tool_result = data["toolUseResult"]
                    if "content" in tool_result:
                        # Find the tool_use_id from message content
                        tool_use_id = None
                        if isinstance(content, list):
                            for item in content:
                                if item.get("type") == "tool_result":
                                    tool_use_id = item.get(
                                        "tool_use_id"
                                    )
                                    break

                        if tool_use_id:
                            tool_name = tool_map.get(
                                tool_use_id, "Unknown"
                            )
                            result_content = tool_result["content"]
                            content_length = get_content_length(
                                result_content
                            )

                            if content_length >= threshold and (
                                target_tools is None
                                or tool_name.lower() in target_tools
                            ):
                                truncated = truncate_content(
                                    result_content, threshold, tool_name
                                )
                                tool_result["content"] = truncated

            # Replace sessionId if new_session_id provided
            if new_session_id and "sessionId" in data:
                data["sessionId"] = new_session_id

            # Write the (potentially modified) line
            outfile.write(json.dumps(data) + "\n")

    return num_tools_trimmed, num_assistant_trimmed, chars_saved
