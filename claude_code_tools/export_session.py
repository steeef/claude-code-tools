"""Export sessions with YAML front matter for indexing."""

import json
import os
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Optional

# Lazy import yaml to allow module to load even if not installed
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    yaml = None  # type: ignore
    YAML_AVAILABLE = False


def _require_yaml():
    """Raise helpful error if pyyaml is not installed."""
    if not YAML_AVAILABLE:
        raise ImportError(
            "pyyaml is required for YAML front matter export.\n"
            "Install with: pip install pyyaml\n"
            "Or reinstall claude-code-tools: uv tool install claude-code-tools"
        )


def extract_session_metadata(session_file: Path, agent: str) -> dict[str, Any]:
    """
    Extract metadata from a session JSONL file.

    Reads the first few lines to extract:
    - session_id
    - cwd (working directory)
    - git branch (if available)
    - lineage info (trim_metadata, continue_metadata)

    Args:
        session_file: Path to session JSONL file
        agent: Agent type ('claude' or 'codex')

    Returns:
        Dict with extracted metadata
    """
    metadata: dict[str, Any] = {
        "session_id": session_file.stem,
        "agent": agent,
        "file_path": str(session_file.absolute()),
        "cwd": None,
        "branch": None,
        "derivation_type": None,
        "parent_session_id": None,
        "parent_session_file": None,
        "original_session_id": None,
        "trim_stats": None,
    }

    try:
        with open(session_file, "r", encoding="utf-8") as f:
            line_count = 0
            for line in f:
                line_count += 1
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Extract cwd
                if metadata["cwd"] is None and data.get("cwd"):
                    metadata["cwd"] = data["cwd"]

                # Extract session ID from sessionId field if available
                if data.get("sessionId"):
                    metadata["session_id"] = data["sessionId"]

                # Extract trim_metadata (for trimmed sessions)
                if "trim_metadata" in data:
                    tm = data["trim_metadata"]
                    metadata["derivation_type"] = "trimmed"
                    metadata["parent_session_file"] = tm.get("parent_file")
                    if tm.get("parent_file"):
                        parent_path = Path(tm["parent_file"])
                        metadata["parent_session_id"] = parent_path.stem
                    if tm.get("stats"):
                        metadata["trim_stats"] = tm["stats"]

                # Extract continue_metadata (for continued sessions)
                if "continue_metadata" in data:
                    cm = data["continue_metadata"]
                    metadata["derivation_type"] = "continued"
                    metadata["parent_session_id"] = cm.get("parent_session_id")
                    metadata["parent_session_file"] = cm.get("parent_session_file")

                # Extract git branch for Claude sessions
                if agent == "claude" and data.get("type") == "file-history-snapshot":
                    git_info = data.get("metadata", {}).get("git", {})
                    if git_info.get("branch"):
                        metadata["branch"] = git_info["branch"]

                # Extract git branch for Codex sessions
                if agent == "codex" and data.get("type") == "session_meta":
                    payload = data.get("payload", {})
                    git_info = payload.get("git", {})
                    if git_info.get("branch"):
                        metadata["branch"] = git_info["branch"]
                    if payload.get("cwd"):
                        metadata["cwd"] = payload["cwd"]

                # Stop after first 20 lines (metadata is always at the top)
                if line_count >= 20:
                    break

    except (OSError, IOError):
        pass

    # Get file stats
    try:
        stat = session_file.stat()
        metadata["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        metadata["created"] = datetime.fromtimestamp(stat.st_ctime).isoformat()
    except OSError:
        pass

    # Count lines
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            metadata["lines"] = sum(1 for _ in f)
    except (OSError, IOError):
        metadata["lines"] = 0

    # Derive project name from cwd
    if metadata["cwd"]:
        metadata["project"] = Path(metadata["cwd"]).name

    return metadata


def find_original_session_id(session_file: Path) -> Optional[str]:
    """
    Trace back through lineage to find the original session ID.

    Args:
        session_file: Path to session file

    Returns:
        Original session ID or None if this is the original
    """
    try:
        from claude_code_tools.session_lineage import get_full_lineage_chain

        chain = get_full_lineage_chain(session_file)
        if chain and len(chain) > 1:
            # Last item in chain is the original
            original_file, _ = chain[-1]
            return original_file.stem
    except Exception:
        pass

    return None


def generate_yaml_frontmatter(metadata: dict[str, Any]) -> str:
    """
    Generate YAML front matter string from metadata.

    Args:
        metadata: Dict with session metadata

    Returns:
        YAML front matter string with --- delimiters

    Raises:
        ImportError: If pyyaml is not installed
    """
    _require_yaml()

    # Build ordered dict for cleaner YAML output
    yaml_data: dict[str, Any] = {}

    # Identity
    yaml_data["session_id"] = metadata.get("session_id")
    yaml_data["agent"] = metadata.get("agent")
    yaml_data["file_path"] = metadata.get("file_path")

    # Project context
    if metadata.get("project"):
        yaml_data["project"] = metadata["project"]
    if metadata.get("branch"):
        yaml_data["branch"] = metadata["branch"]
    if metadata.get("cwd"):
        yaml_data["cwd"] = metadata["cwd"]

    # Stats
    if metadata.get("lines"):
        yaml_data["lines"] = metadata["lines"]
    if metadata.get("created"):
        yaml_data["created"] = metadata["created"]
    if metadata.get("modified"):
        yaml_data["modified"] = metadata["modified"]

    # Lineage
    if metadata.get("derivation_type"):
        yaml_data["derivation_type"] = metadata["derivation_type"]
    if metadata.get("parent_session_id"):
        yaml_data["parent_session_id"] = metadata["parent_session_id"]
    if metadata.get("parent_session_file"):
        yaml_data["parent_session_file"] = metadata["parent_session_file"]
    if metadata.get("original_session_id"):
        yaml_data["original_session_id"] = metadata["original_session_id"]

    # Trim stats (only for trimmed sessions)
    if metadata.get("trim_stats"):
        yaml_data["trim_stats"] = metadata["trim_stats"]

    yaml_str = yaml.dump(yaml_data, default_flow_style=False, sort_keys=False)
    return f"---\n{yaml_str}---\n"


def export_conversation_content(session_file: Path, agent: str) -> str:
    """
    Export conversation content (without YAML front matter).

    Reuses existing export logic from export_claude_session / export_codex_session.

    Args:
        session_file: Path to session file
        agent: Agent type ('claude' or 'codex')

    Returns:
        Formatted conversation content
    """
    output = StringIO()

    if agent == "claude":
        from claude_code_tools.export_claude_session import export_session_to_markdown

        export_session_to_markdown(session_file, output)
    else:
        from claude_code_tools.export_codex_session import export_session_to_markdown

        export_session_to_markdown(session_file, output)

    return output.getvalue()


def export_with_yaml_frontmatter(
    session_file: Path,
    output_path: Path,
    agent: str,
    include_original_lineage: bool = True,
) -> dict[str, Any]:
    """
    Export a session with YAML front matter.

    Creates an export file with:
    1. YAML front matter containing all metadata
    2. Conversation content

    Args:
        session_file: Path to session JSONL file
        output_path: Path for output file
        agent: Agent type ('claude' or 'codex')
        include_original_lineage: If True, trace back to find original session ID

    Returns:
        Metadata dict that was written to YAML
    """
    # Extract metadata
    metadata = extract_session_metadata(session_file, agent)

    # Find original session ID if this is a derived session
    if include_original_lineage and metadata.get("derivation_type"):
        original_id = find_original_session_id(session_file)
        if original_id:
            metadata["original_session_id"] = original_id

    # Generate YAML front matter
    yaml_frontmatter = generate_yaml_frontmatter(metadata)

    # Export conversation content
    content = export_conversation_content(session_file, agent)

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write output file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(yaml_frontmatter)
        f.write("\n")
        f.write(content)

    return metadata


def parse_exported_session(export_path: Path) -> tuple[dict[str, Any], str]:
    """
    Parse an exported session file with YAML front matter.

    Args:
        export_path: Path to exported .txt file

    Returns:
        Tuple of (metadata_dict, conversation_content)

    Raises:
        ValueError: If file doesn't have valid YAML front matter
        ImportError: If pyyaml is not installed
    """
    _require_yaml()

    content = export_path.read_text(encoding="utf-8")

    if not content.startswith("---\n"):
        raise ValueError("Export file does not start with YAML delimiter")

    # Find closing delimiter
    end_idx = content.find("\n---\n", 4)
    if end_idx == -1:
        raise ValueError("No closing YAML delimiter found")

    yaml_str = content[4:end_idx]
    metadata = yaml.safe_load(yaml_str)

    conversation = content[end_idx + 5:]  # Skip "\n---\n"

    return metadata, conversation
