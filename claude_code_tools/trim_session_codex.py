"""Codex specific logic for suppressing tool results."""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple


def build_tool_name_mapping(input_file: Path) -> Dict[str, str]:
    """
    Build a mapping of call_id to tool name for Codex sessions.

    Args:
        input_file: Path to the input JSONL file.

    Returns:
        Dictionary mapping call_id to tool name.
    """
    tool_map = {}

    with open(input_file, "r") as f:
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Look for function_call entries
            if data.get("type") != "response_item":
                continue

            payload = data.get("payload", {})
            if payload.get("type") != "function_call":
                continue

            call_id = payload.get("call_id")
            tool_name = payload.get("name")

            if call_id and tool_name:
                tool_map[call_id] = tool_name

    return tool_map


def get_output_length(output_str: str) -> int:
    """
    Calculate the length of Codex tool output.

    Codex outputs are double-JSON-encoded, so we need to parse twice.

    Args:
        output_str: The JSON-encoded output string.

    Returns:
        Length of the actual output content in characters.
    """
    try:
        # First parse: get the output object
        output_obj = json.loads(output_str)
        # Second parse or direct access to output field
        if isinstance(output_obj, dict) and "output" in output_obj:
            return len(str(output_obj["output"]))
        else:
            return len(str(output_obj))
    except (json.JSONDecodeError, TypeError):
        return len(output_str)


def create_suppressed_output(
    tool_name: str, original_length: int, call_id: str, metadata: Dict
) -> str:
    """
    Create a suppressed output in Codex format.

    Args:
        tool_name: Name of the tool.
        original_length: Original output length.
        call_id: The call_id for correlation.
        metadata: Original metadata to preserve.

    Returns:
        JSON-encoded output string with suppression placeholder.
    """
    placeholder_text = (
        f"[Results from {tool_name} tool suppressed - "
        f"original content was {original_length:,} characters]"
    )

    # Preserve metadata, replace output
    suppressed_obj = {
        "output": placeholder_text,
        "metadata": metadata,
    }

    return json.dumps(suppressed_obj)


def process_codex_session(
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
    Process Codex session file and trim tool results and assistant messages.

    Args:
        input_file: Path to input JSONL file.
        output_file: Path to output JSONL file.
        tool_map: Mapping of call_id to tool name.
        target_tools: Set of tool names to suppress (None means all).
        threshold: Minimum length threshold for trimming.
        create_placeholder: Function to create placeholder text (unused
            for Codex, we use create_suppressed_output instead).
        new_session_id: Optional new session ID to replace in session_meta events.
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

                if data.get("type") == "response_item":
                    payload = data.get("payload", {})
                    if (
                        payload.get("type") == "message"
                        and payload.get("role") == "assistant"
                    ):
                        content = payload.get("content", [])
                        total_length = sum(
                            len(str(item.get("text", "")))
                            for item in content
                            if isinstance(item, dict)
                            and item.get("type") == "output_text"
                        )
                        if total_length >= threshold:
                            assistant_messages.append(
                                (line_num, total_length, data)
                            )

        # Determine which to trim based on parameter
        if trim_assistant_messages > 0:
            # Trim first N
            count = min(trim_assistant_messages, len(assistant_messages))
            assistant_indices_to_trim = {
                msg[0] for msg in assistant_messages[:count]
            }
        elif trim_assistant_messages < 0:
            # Trim all except last abs(N)
            keep_count = min(
                abs(trim_assistant_messages), len(assistant_messages)
            )
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

            # Replace session_id in session_meta events if new_session_id provided
            if new_session_id and data.get("type") == "session_meta":
                if "payload" in data and "id" in data["payload"]:
                    data["payload"]["id"] = new_session_id

            # Trim assistant messages if needed
            if (
                data.get("type") == "response_item"
                and line_num in assistant_indices_to_trim
            ):
                payload = data.get("payload", {})
                if (
                    payload.get("type") == "message"
                    and payload.get("role") == "assistant"
                ):
                    content = payload.get("content", [])
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "output_text":
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

            # Look for function_call_output entries
            if data.get("type") != "response_item":
                outfile.write(json.dumps(data) + "\n")
                continue

            payload = data.get("payload", {})
            if payload.get("type") != "function_call_output":
                outfile.write(json.dumps(data) + "\n")
                continue

            # This is a tool result
            call_id = payload.get("call_id")
            tool_name = tool_map.get(call_id, "Unknown")
            output_str = payload.get("output", "")

            # Calculate output length (parse double-JSON)
            output_length = get_output_length(output_str)

            # Check if should suppress
            should_suppress = output_length >= threshold and (
                target_tools is None or tool_name.lower() in target_tools
            )

            if should_suppress:
                # Parse the output to extract metadata
                try:
                    output_obj = json.loads(output_str)
                    metadata = (
                        output_obj.get("metadata", {})
                        if isinstance(output_obj, dict)
                        else {}
                    )
                except (json.JSONDecodeError, TypeError):
                    metadata = {}

                # Create suppressed output
                suppressed_output = create_suppressed_output(
                    tool_name, output_length, call_id, metadata
                )

                # Replace the output
                payload["output"] = suppressed_output
                num_tools_trimmed += 1
                chars_saved += output_length - len(suppressed_output)

            # Write the (potentially modified) line
            outfile.write(json.dumps(data) + "\n")

    return num_tools_trimmed, num_assistant_trimmed, chars_saved
