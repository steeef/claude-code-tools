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
        self.schema_builder.add_text_field("export_path", stored=True)

        # First and last message fields (for preview in TUI)
        self.schema_builder.add_text_field("first_msg_role", stored=True)
        self.schema_builder.add_text_field("first_msg_content", stored=True)
        self.schema_builder.add_text_field("last_msg_role", stored=True)
        self.schema_builder.add_text_field("last_msg_content", stored=True)

        # Session type fields (for filtering in TUI)
        self.schema_builder.add_text_field("derivation_type", stored=True)
        self.schema_builder.add_text_field("is_sidechain", stored=True)  # "true"/"false"

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
            })

        # Sort by modified timestamp (most recent first)
        results.sort(key=lambda x: x["modified"] or "", reverse=True)

        return results[:limit]
