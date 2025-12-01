"""Tantivy-based search index for session exports."""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Lazy imports to allow module to load even if deps not installed
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    yaml = None  # type: ignore
    YAML_AVAILABLE = False

try:
    import tantivy
    TANTIVY_AVAILABLE = True
except ImportError:
    tantivy = None  # type: ignore
    TANTIVY_AVAILABLE = False


def _require_deps():
    """Raise helpful error if required dependencies are not installed."""
    missing = []
    if not YAML_AVAILABLE:
        missing.append("pyyaml")
    if not TANTIVY_AVAILABLE:
        missing.append("tantivy")

    if missing:
        raise ImportError(
            f"Missing dependencies for search indexing: {', '.join(missing)}\n"
            f"Install with: pip install {' '.join(missing)}\n"
            "Or reinstall claude-code-tools: uv tool install claude-code-tools"
        )


@dataclass
class SearchResult:
    """A search result with metadata and snippet."""

    session_id: str
    agent: str
    project: str
    branch: Optional[str]
    cwd: Optional[str]
    modified: str
    lines: int
    snippet: str
    score: float
    export_path: str


class IndexState:
    """Track which files have been indexed to enable incremental updates."""

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.indexed_files: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self):
        """Load state from disk."""
        if self.state_path.exists():
            try:
                with open(self.state_path, "r") as f:
                    self.indexed_files = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.indexed_files = {}

    def save(self):
        """Save state to disk."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self.indexed_files, f)

    def needs_reindex(self, file_path: Path) -> bool:
        """Check if file needs to be (re-)indexed."""
        key = str(file_path)
        if key not in self.indexed_files:
            return True

        stat = file_path.stat()
        stored = self.indexed_files[key]

        # Reindex if mtime or size changed
        return (
            stat.st_mtime != stored.get("mtime")
            or stat.st_size != stored.get("size")
        )

    def mark_indexed(self, file_path: Path):
        """Mark file as indexed with current metadata."""
        stat = file_path.stat()
        self.indexed_files[str(file_path)] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
        }


class SessionIndex:
    """Tantivy-based full-text search index for sessions."""

    def __init__(self, index_path: Path):
        """
        Initialize or open a session index.

        Args:
            index_path: Directory for the Tantivy index

        Raises:
            ImportError: If tantivy or pyyaml is not installed
        """
        _require_deps()

        self.index_path = Path(index_path)
        self.state = IndexState(self.index_path / "index_state.json")

        # Define schema
        self.schema_builder = tantivy.SchemaBuilder()

        # Stored fields (retrieved but not searched)
        self.schema_builder.add_text_field("session_id", stored=True)
        self.schema_builder.add_text_field("agent", stored=True)
        self.schema_builder.add_text_field("project", stored=True)
        self.schema_builder.add_text_field("branch", stored=True)
        self.schema_builder.add_text_field("cwd", stored=True)
        self.schema_builder.add_text_field("created", stored=True)
        self.schema_builder.add_text_field("modified", stored=True)
        self.schema_builder.add_integer_field("lines", stored=True)
        # export_path needs "raw" tokenizer for exact match deletion
        self.schema_builder.add_text_field("export_path", stored=True, tokenizer_name="raw")

        # First and last message fields (for preview in TUI)
        self.schema_builder.add_text_field("first_msg_role", stored=True)
        self.schema_builder.add_text_field("first_msg_content", stored=True)
        self.schema_builder.add_text_field("last_msg_role", stored=True)
        self.schema_builder.add_text_field("last_msg_content", stored=True)

        # Session type fields (for filtering in TUI)
        self.schema_builder.add_text_field("derivation_type", stored=True)
        self.schema_builder.add_text_field("is_sidechain", stored=True)  # "true"/"false"

        # Claude home field (for filtering by source Claude home directory)
        self.schema_builder.add_text_field("claude_home", stored=True)

        # Searchable content field
        self.schema_builder.add_text_field("content", stored=True)

        self.schema = self.schema_builder.build()

        # Create or open index
        self.index_path.mkdir(parents=True, exist_ok=True)

        if (self.index_path / "meta.json").exists():
            self.index = tantivy.Index(self.schema, path=str(self.index_path))
        else:
            self.index = tantivy.Index(self.schema, path=str(self.index_path))

    def _parse_export_file(self, export_path: Path) -> Optional[dict[str, Any]]:
        """
        Parse an exported session file with YAML front matter.

        Returns:
            Dict with metadata and content, or None if parsing fails
        """
        try:
            content = export_path.read_text(encoding="utf-8")

            if not content.startswith("---\n"):
                return None

            end_idx = content.find("\n---\n", 4)
            if end_idx == -1:
                return None

            yaml_str = content[4:end_idx]
            metadata = yaml.safe_load(yaml_str)

            conversation = content[end_idx + 5:]

            return {
                "metadata": metadata,
                "content": conversation,
                "export_path": str(export_path),
            }
        except Exception:
            return None

    def build_from_exports(
        self, exports_dir: Path, incremental: bool = True
    ) -> dict[str, int]:
        """
        Build or update index from exported session files.

        Args:
            exports_dir: Directory containing exported .txt files
                (expects subdirs: claude/, codex/)
            incremental: If True, only index new/modified files

        Returns:
            Stats dict: {indexed, skipped, failed}
        """
        stats = {"indexed": 0, "skipped": 0, "failed": 0}

        writer = self.index.writer()

        # Find all export files
        export_files = []
        for subdir in ["claude", "codex"]:
            subdir_path = exports_dir / subdir
            if subdir_path.exists():
                export_files.extend(subdir_path.glob("*.txt"))

        for export_path in export_files:
            # Check if needs indexing
            if incremental and not self.state.needs_reindex(export_path):
                stats["skipped"] += 1
                continue

            # Parse export file
            parsed = self._parse_export_file(export_path)
            if parsed is None:
                stats["failed"] += 1
                continue

            metadata = parsed["metadata"]

            # Create document
            doc = tantivy.Document()
            doc.add_text("session_id", metadata.get("session_id", ""))
            doc.add_text("agent", metadata.get("agent", ""))
            doc.add_text("project", metadata.get("project", ""))
            doc.add_text("branch", metadata.get("branch", "") or "")
            doc.add_text("cwd", metadata.get("cwd", "") or "")
            doc.add_text("created", metadata.get("created", "") or "")
            doc.add_text("modified", metadata.get("modified", ""))
            doc.add_integer("lines", metadata.get("lines", 0))
            doc.add_text("export_path", parsed["export_path"])

            # First and last message fields
            first_msg = metadata.get("first_msg", {}) or {}
            last_msg = metadata.get("last_msg", {}) or {}
            doc.add_text("first_msg_role", first_msg.get("role", ""))
            doc.add_text("first_msg_content", first_msg.get("content", ""))
            doc.add_text("last_msg_role", last_msg.get("role", ""))
            doc.add_text("last_msg_content", last_msg.get("content", ""))

            # Session type fields
            doc.add_text("derivation_type", metadata.get("derivation_type", "") or "")
            doc.add_text(
                "is_sidechain",
                "true" if metadata.get("is_sidechain") else "false"
            )

            doc.add_text("content", parsed["content"])

            writer.add_document(doc)
            self.state.mark_indexed(export_path)
            stats["indexed"] += 1

        writer.commit()
        self.state.save()
        self.index.reload()

        return stats

    def index_single_file(
        self, export_path: Path, writer, incremental: bool = True
    ) -> dict:
        """
        Index a single export file.

        Args:
            export_path: Path to exported .txt file
            writer: Tantivy index writer
            incremental: If True, skip if already indexed

        Returns:
            Dict with result: {status, error}
            status: 'indexed', 'skipped', 'failed'
        """
        result: dict = {"status": "failed", "error": None}

        if not export_path.exists():
            result["error"] = "file not found"
            return result

        # Check if needs indexing
        if incremental and not self.state.needs_reindex(export_path):
            result["status"] = "skipped"
            return result

        # Parse export file
        try:
            parsed = self._parse_export_file(export_path)
        except Exception as e:
            result["error"] = f"parse error: {e}"
            return result

        if parsed is None:
            result["error"] = "failed to parse YAML frontmatter"
            return result

        metadata = parsed["metadata"]

        try:
            # Create document
            doc = tantivy.Document()
            doc.add_text("session_id", metadata.get("session_id", ""))
            doc.add_text("agent", metadata.get("agent", ""))
            doc.add_text("project", metadata.get("project", ""))
            doc.add_text("branch", metadata.get("branch", "") or "")
            doc.add_text("cwd", metadata.get("cwd", "") or "")
            doc.add_text("created", metadata.get("created", "") or "")
            doc.add_text("modified", metadata.get("modified", ""))
            doc.add_integer("lines", metadata.get("lines", 0))
            doc.add_text("export_path", parsed["export_path"])

            # First and last message fields
            first_msg = metadata.get("first_msg", {}) or {}
            last_msg = metadata.get("last_msg", {}) or {}
            doc.add_text("first_msg_role", first_msg.get("role", ""))
            doc.add_text("first_msg_content", first_msg.get("content", ""))
            doc.add_text("last_msg_role", last_msg.get("role", ""))
            doc.add_text("last_msg_content", last_msg.get("content", ""))

            # Session type fields
            doc.add_text(
                "derivation_type", metadata.get("derivation_type", "") or ""
            )
            doc.add_text(
                "is_sidechain",
                "true" if metadata.get("is_sidechain") else "false"
            )

            doc.add_text("content", parsed["content"])

            writer.add_document(doc)
            self.state.mark_indexed(export_path)
            result["status"] = "indexed"
        except Exception as e:
            result["error"] = f"index error: {e}"

        return result

    def get_writer(self):
        """Get a writer for batch indexing."""
        return self.index.writer()

    def commit_and_reload(self, writer):
        """Commit writer changes and reload index."""
        writer.commit()
        self.state.save()
        self.index.reload()

    def build_from_files(
        self, export_files: list[Path], incremental: bool = True
    ) -> dict[str, int]:
        """
        Build or update index from a list of exported session files.

        This is the per-project alternative to build_from_exports().
        Instead of expecting a single directory, it accepts a list of
        export file paths from multiple project directories.

        Args:
            export_files: List of paths to exported .txt files
            incremental: If True, only index new/modified files

        Returns:
            Stats dict: {indexed, skipped, failed}
        """
        stats = {"indexed": 0, "skipped": 0, "failed": 0}

        writer = self.get_writer()

        for export_path in export_files:
            result = self.index_single_file(export_path, writer, incremental)
            if result["status"] == "indexed":
                stats["indexed"] += 1
            elif result["status"] == "skipped":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1

        self.commit_and_reload(writer)

        return stats

    def _extract_session_content(
        self, jsonl_path: Path, agent: str
    ) -> tuple[str, int]:
        """
        Extract searchable content from a session file.

        Handles both Claude and Codex JSONL formats.

        Args:
            jsonl_path: Path to session JSONL file
            agent: Agent type ('claude' or 'codex')

        Returns:
            Tuple of (content_string, message_count)
        """
        messages = []

        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    role: Optional[str] = None
                    text: str = ""

                    if agent == "claude":
                        # Claude format: type is "user" or "assistant"
                        msg_type = data.get("type")
                        if msg_type not in ("user", "assistant"):
                            continue

                        role = msg_type
                        message = data.get("message", {})
                        content = message.get("content")

                        if not content:
                            continue

                        # Extract text content
                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, str):
                                    text += block + "\n"
                                elif isinstance(block, dict):
                                    if block.get("type") == "text":
                                        text += block.get("text", "") + "\n"
                                    elif block.get("type") == "tool_use":
                                        tool_name = block.get("name", "")
                                        text += f"[Tool: {tool_name}]\n"
                                    elif block.get("type") == "tool_result":
                                        result = block.get("content", "")
                                        if isinstance(result, str):
                                            text += result[:500] + "\n"

                    elif agent == "codex":
                        # Codex format: type is "response_item" with payload
                        if data.get("type") != "response_item":
                            continue

                        payload = data.get("payload", {})
                        if payload.get("type") != "message":
                            continue

                        role = payload.get("role")
                        content = payload.get("content", [])

                        if not isinstance(content, list):
                            continue

                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            block_type = block.get("type")
                            # input_text (user) and output_text (assistant)
                            if block_type in ("input_text", "output_text"):
                                text += block.get("text", "") + "\n"

                    if role and text.strip():
                        messages.append(f"[{role}] {text.strip()}")

        except (OSError, IOError):
            pass

        return "\n\n".join(messages), len(messages)

    def _parse_jsonl_session(self, jsonl_path: Path) -> Optional[dict[str, Any]]:
        """
        Parse a JSONL session file directly (no export step).

        Uses extract_session_metadata() from export_session.py for metadata,
        and handles both Claude and Codex JSONL formats for content.

        Args:
            jsonl_path: Path to the session JSONL file

        Returns:
            Dict with metadata and content suitable for indexing, or None on failure
        """
        try:
            # Detect agent from path
            path_str = str(jsonl_path)
            agent = "codex" if ".codex" in path_str else "claude"

            # Use existing helper for metadata extraction
            from claude_code_tools.export_session import extract_session_metadata
            metadata = extract_session_metadata(jsonl_path, agent)

            # Extract content for full-text search
            content, msg_count = self._extract_session_content(jsonl_path, agent)

            if msg_count == 0:
                return None

            # Map metadata fields to expected format
            first_msg = metadata.get("first_msg") or {"role": "", "content": ""}
            last_msg = metadata.get("last_msg") or {"role": "", "content": ""}

            return {
                "metadata": {
                    "session_id": metadata.get("session_id", ""),
                    "agent": agent,
                    "project": metadata.get("project", ""),
                    "branch": metadata.get("branch", "") or "",
                    "cwd": metadata.get("cwd", "") or "",
                    "created": metadata.get("created", "") or "",
                    "modified": metadata.get("modified", "") or "",
                    "is_sidechain": metadata.get("is_sidechain", False),
                    "derivation_type": metadata.get("derivation_type", "") or "",
                },
                "content": content,
                "first_msg": first_msg,
                "last_msg": last_msg,
                "lines": msg_count,
                "file_path": str(jsonl_path),
            }
        except Exception:
            return None

    def index_from_jsonl(
        self,
        jsonl_files: list[Path],
        incremental: bool = True,
        claude_home: Optional[Path] = None,
    ) -> dict[str, int]:
        """
        Build or update index directly from JSONL session files.

        This is the "zero-config" approach - no export step needed.
        Parses JSONL directly and indexes to Tantivy.

        Args:
            jsonl_files: List of paths to session JSONL files
            incremental: If True, only index new/modified files
            claude_home: Claude home directory (stored for filtering)

        Returns:
            Stats dict: {indexed, skipped, failed}
        """
        claude_home_str = str(claude_home) if claude_home else ""
        codex_home_str = str(Path.home() / ".codex")  # Default codex home
        stats = {"indexed": 0, "skipped": 0, "failed": 0}

        writer = self.get_writer()

        for jsonl_path in jsonl_files:
            # Check if needs indexing
            if incremental and not self.state.needs_reindex(jsonl_path):
                stats["skipped"] += 1
                continue

            # Parse JSONL file
            parsed = self._parse_jsonl_session(jsonl_path)
            if parsed is None:
                stats["failed"] += 1
                continue

            metadata = parsed["metadata"]
            first_msg = parsed["first_msg"]
            last_msg = parsed["last_msg"]

            try:
                session_id = metadata.get("session_id", "")
                file_path_str = str(jsonl_path)

                # Delete by file path (unique), not sessionId (shared by sub-agents)
                writer.delete_documents("export_path", file_path_str)

                # Create document
                doc = tantivy.Document()
                doc.add_text("session_id", session_id)
                doc.add_text("agent", metadata.get("agent", ""))
                doc.add_text("project", metadata.get("project", ""))
                doc.add_text("branch", metadata.get("branch", "") or "")
                doc.add_text("cwd", metadata.get("cwd", "") or "")
                doc.add_text("created", metadata.get("created", "") or "")
                doc.add_text("modified", metadata.get("modified", ""))
                doc.add_integer("lines", parsed.get("lines", 0))
                doc.add_text("export_path", parsed["file_path"])  # Store JSONL path

                # First and last message fields
                doc.add_text("first_msg_role", first_msg.get("role", ""))
                doc.add_text("first_msg_content", first_msg.get("content", ""))
                doc.add_text("last_msg_role", last_msg.get("role", ""))
                doc.add_text("last_msg_content", last_msg.get("content", ""))

                # Session type fields
                doc.add_text(
                    "derivation_type", metadata.get("derivation_type", "") or ""
                )
                doc.add_text(
                    "is_sidechain",
                    "true" if metadata.get("is_sidechain") else "false"
                )

                # Source home (for filtering by source directory)
                # Detect from path whether this is a Claude or Codex session
                agent = metadata.get("agent", "")
                if agent == "codex" or ".codex" in file_path_str:
                    # Codex session - store codex home
                    doc.add_text("claude_home", codex_home_str)
                else:
                    # Claude session - store claude home
                    doc.add_text("claude_home", claude_home_str)

                doc.add_text("content", parsed["content"])

                writer.add_document(doc)
                self.state.mark_indexed(jsonl_path)
                stats["indexed"] += 1
            except Exception:
                stats["failed"] += 1

        self.commit_and_reload(writer)

        return stats

    def _generate_snippet(
        self, content: str, query: str, max_len: int = 200
    ) -> str:
        """
        Generate a snippet centered around the first match.

        Args:
            content: Full content text
            query: Search query
            max_len: Maximum snippet length

        Returns:
            Snippet with match context
        """
        if not query:
            # For empty query, return start of content
            return content[:max_len].strip() + "..." if len(content) > max_len else content.strip()

        lower_content = content.lower()
        lower_query = query.lower()

        # Find first occurrence
        pos = lower_content.find(lower_query)
        if pos == -1:
            # Try individual words
            for word in query.split():
                pos = lower_content.find(word.lower())
                if pos != -1:
                    break

        if pos == -1:
            return content[:max_len].strip() + "..."

        # Center snippet around match
        half_len = max_len // 2
        start = max(0, pos - half_len)
        end = min(len(content), pos + len(query) + half_len)

        snippet = content[start:end].strip()

        # Add ellipses
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        # Clean up newlines
        snippet = " ".join(snippet.split())

        return snippet

    def _calculate_recency_score(
        self, modified: str, base_score: float, half_life_days: float = 7.0
    ) -> float:
        """
        Apply recency boost using exponential decay.

        Args:
            modified: ISO format timestamp
            base_score: Original Tantivy score
            half_life_days: Days for score to decay by half

        Returns:
            Score with recency boost (up to 2x for very recent)
        """
        try:
            # Parse modified timestamp
            if "T" in modified:
                mod_time = datetime.fromisoformat(modified.replace("Z", "+00:00"))
            else:
                mod_time = datetime.fromisoformat(modified)

            now = datetime.now(mod_time.tzinfo) if mod_time.tzinfo else datetime.now()
            age_seconds = (now - mod_time).total_seconds()

            half_life_secs = half_life_days * 24 * 3600
            recency_boost = 1.0 + math.exp(-age_seconds / half_life_secs)

            return base_score * recency_boost
        except Exception:
            return base_score

    def search(
        self,
        query: str,
        limit: int = 50,
        project: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Search the index.

        Args:
            query: Search query (empty returns recent sessions)
            limit: Maximum results
            project: Filter to specific project

        Returns:
            List of result dicts with metadata and snippets
        """
        if not query and not project:
            return self.get_recent(limit=limit)

        searcher = self.index.searcher()

        # Build query
        if query:
            # Use Index.parse_query with default fields
            parsed_query = self.index.parse_query(query, ["content"])
        else:
            # Match all for project filter
            parsed_query = self.index.parse_query("*", ["content"])

        # Execute search
        results = []
        top_docs = searcher.search(parsed_query, limit * 2)  # Fetch extra for filtering

        for score, doc_address in top_docs.hits:
            doc = searcher.doc(doc_address)

            # Extract fields
            session_id = doc.get_first("session_id")
            agent = doc.get_first("agent")
            doc_project = doc.get_first("project")
            branch = doc.get_first("branch")
            cwd = doc.get_first("cwd")
            created = doc.get_first("created")
            modified = doc.get_first("modified")
            lines = doc.get_first("lines")
            export_path = doc.get_first("export_path")
            content = doc.get_first("content")

            # Apply project filter
            if project and doc_project != project:
                continue

            # Generate snippet
            snippet = self._generate_snippet(content, query)

            # Apply recency scoring
            final_score = self._calculate_recency_score(modified, score)

            # Extract first/last message fields
            first_msg_role = doc.get_first("first_msg_role") or ""
            first_msg_content = doc.get_first("first_msg_content") or ""
            last_msg_role = doc.get_first("last_msg_role") or ""
            last_msg_content = doc.get_first("last_msg_content") or ""

            results.append({
                "session_id": session_id,
                "agent": agent,
                "project": doc_project,
                "branch": branch,
                "cwd": cwd,
                "created": created,
                "modified": modified,
                "lines": lines,
                "export_path": export_path,
                "snippet": snippet,
                "score": final_score,
                "first_msg_role": first_msg_role,
                "first_msg_content": first_msg_content,
                "last_msg_role": last_msg_role,
                "last_msg_content": last_msg_content,
            })

            if len(results) >= limit:
                break

        # Sort by score (recency-adjusted)
        results.sort(key=lambda x: x["score"], reverse=True)

        return results

    def get_recent(
        self, limit: int = 20, project: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """
        Get recent sessions sorted by modification time.

        Args:
            limit: Maximum results
            project: Filter to specific project

        Returns:
            List of result dicts sorted by recency
        """
        searcher = self.index.searcher()

        # Match all documents
        all_query = tantivy.Query.all_query()
        top_docs = searcher.search(all_query, limit * 3)  # Fetch extra for filtering

        results = []
        for _, doc_address in top_docs.hits:
            doc = searcher.doc(doc_address)

            doc_project = doc.get_first("project")

            # Apply project filter
            if project and doc_project != project:
                continue

            modified = doc.get_first("modified")
            content = doc.get_first("content")

            results.append({
                "session_id": doc.get_first("session_id"),
                "agent": doc.get_first("agent"),
                "project": doc_project,
                "branch": doc.get_first("branch"),
                "cwd": doc.get_first("cwd"),
                "created": doc.get_first("created"),
                "modified": modified,
                "lines": doc.get_first("lines"),
                "export_path": doc.get_first("export_path"),
                "snippet": self._generate_snippet(content, ""),
                "score": 0.0,
                "first_msg_role": doc.get_first("first_msg_role") or "",
                "first_msg_content": doc.get_first("first_msg_content") or "",
                "last_msg_role": doc.get_first("last_msg_role") or "",
                "last_msg_content": doc.get_first("last_msg_content") or "",
                "claude_home": doc.get_first("claude_home") or "",
            })

        # Sort by modified timestamp (most recent first)
        results.sort(key=lambda x: x["modified"] or "", reverse=True)

        return results[:limit]


def auto_index(
    index_path: Optional[Path] = None,
    claude_home: Optional[Path] = None,
    codex_home: Optional[Path] = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Automatically index new/changed session files on launch.

    This implements the "zero-config" Recall model approach:
    - Scans session directories for JSONL files
    - Indexes new/modified files incrementally
    - Returns quickly if nothing changed

    Args:
        index_path: Path to Tantivy index (default: ~/.cctools/search-index)
        claude_home: Claude home directory (default: ~/.claude)
        codex_home: Codex home directory (default: ~/.codex)
        verbose: If True, print progress messages

    Returns:
        Dict with stats: {indexed, skipped, failed, total_files}
    """
    _require_deps()

    # Default paths
    if index_path is None:
        index_path = Path.home() / ".cctools" / "search-index"
    if claude_home is None:
        claude_home = Path.home() / ".claude"
    if codex_home is None:
        codex_home = Path.home() / ".codex"

    # Find all JSONL session files
    jsonl_files: list[Path] = []

    # Claude sessions: ~/.claude/projects/**/*.jsonl
    claude_projects = claude_home / "projects"
    if claude_projects.exists():
        jsonl_files.extend(claude_projects.glob("**/*.jsonl"))

    # Codex sessions: ~/.codex/**/*.jsonl (various subdirs)
    if codex_home.exists():
        jsonl_files.extend(codex_home.glob("**/*.jsonl"))

    if verbose:
        print(f"Found {len(jsonl_files)} session files to check")

    if not jsonl_files:
        return {"indexed": 0, "skipped": 0, "failed": 0, "total_files": 0}

    # Create/open index and run incremental indexing
    index = SessionIndex(index_path)
    stats = index.index_from_jsonl(
        jsonl_files, incremental=True, claude_home=claude_home
    )
    stats["total_files"] = len(jsonl_files)

    if verbose:
        if stats["indexed"] > 0:
            print(f"Indexed {stats['indexed']} new/modified sessions")
        else:
            print("Index up to date")

    return stats
