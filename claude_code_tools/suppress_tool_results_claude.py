"""Claude Code specific logic for suppressing tool results."""

import json
from pathlib import Path
from typing import Any, Dict, Set, Tuple


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


def process_claude_session(
    input_file: Path,
    output_file: Path,
    tool_map: Dict[str, str],
    target_tools: Set[str],
    threshold: int,
    create_placeholder: callable,
) -> Tuple[int, int]:
    """
    Process Claude Code session file and suppress tool results.

    Args:
        input_file: Path to input JSONL file.
        output_file: Path to output JSONL file.
        tool_map: Mapping of tool_use_id to tool name.
        target_tools: Set of tool names to suppress (None means all).
        threshold: Minimum length threshold for suppression.
        create_placeholder: Function to create placeholder text.

    Returns:
        Tuple of (num_suppressed, chars_saved).
    """
    num_suppressed = 0
    chars_saved = 0

    with open(input_file, "r") as infile, open(
        output_file, "w"
    ) as outfile:
        for line_num, line in enumerate(infile, start=1):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                outfile.write(line)
                continue

            # Check if this is a user message with tool results
            if data.get("type") == "user":
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

                            # Check if should suppress
                            if content_length >= threshold and (
                                target_tools is None
                                or tool_name.lower() in target_tools
                            ):
                                placeholder = create_placeholder(
                                    tool_name, content_length
                                )
                                item["content"] = placeholder
                                num_suppressed += 1
                                chars_saved += (
                                    content_length - len(placeholder)
                                )

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
                                placeholder = create_placeholder(
                                    tool_name, content_length
                                )
                                tool_result["content"] = placeholder

            # Write the (potentially modified) line
            outfile.write(json.dumps(data) + "\n")

    return num_suppressed, chars_saved
