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
) -> Tuple[int, int]:
    """
    Process Codex session file and suppress tool results.

    Args:
        input_file: Path to input JSONL file.
        output_file: Path to output JSONL file.
        tool_map: Mapping of call_id to tool name.
        target_tools: Set of tool names to suppress (None means all).
        threshold: Minimum length threshold for suppression.
        create_placeholder: Function to create placeholder text (unused
            for Codex, we use create_suppressed_output instead).
        new_session_id: Optional new session ID to replace in session_meta events.

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

            # Replace session_id in session_meta events if new_session_id provided
            if new_session_id and data.get("type") == "session_meta":
                if "payload" in data and "id" in data["payload"]:
                    data["payload"]["id"] = new_session_id

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
                num_suppressed += 1
                chars_saved += output_length - len(suppressed_output)

            # Write the (potentially modified) line
            outfile.write(json.dumps(data) + "\n")

    return num_suppressed, chars_saved
