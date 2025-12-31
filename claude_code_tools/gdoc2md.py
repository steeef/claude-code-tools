#!/usr/bin/env python3
"""
gdoc2md: Download Google Docs as Markdown files.

This tool uses the Google Drive API to export Google Docs as Markdown,
using Google's native markdown export (same as File → Download → Markdown).

Prerequisites:
- First run: Will open browser for OAuth authentication (one-time setup)
- Credentials stored in .gdoc-credentials.json (local) or ~/.config/md2gdoc/
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel

console = Console()

# Import shared utilities from md2gdoc
from claude_code_tools.md2gdoc import (
    SCOPES,
    check_dependencies,
    get_credentials,
    get_drive_service,
    find_folder_id,
)


def find_doc_by_name(
    service, folder_id: Optional[str], doc_name: str
) -> Optional[dict]:
    """Find a Google Doc by name in a folder. Returns file metadata or None."""
    parent = folder_id if folder_id else "root"
    query = (
        f"name = '{doc_name}' and "
        f"'{parent}' in parents and "
        f"mimeType = 'application/vnd.google-apps.document' and "
        f"trashed = false"
    )
    results = (
        service.files()
        .list(q=query, fields="files(id, name)", pageSize=1)
        .execute()
    )
    files = results.get("files", [])
    return files[0] if files else None


def list_docs_in_folder(service, folder_id: Optional[str]) -> list[dict]:
    """List all Google Docs in a folder."""
    parent = folder_id if folder_id else "root"
    query = (
        f"'{parent}' in parents and "
        f"mimeType = 'application/vnd.google-apps.document' and "
        f"trashed = false"
    )
    results = (
        service.files()
        .list(q=query, fields="files(id, name)", pageSize=100, orderBy="name")
        .execute()
    )
    return results.get("files", [])


def download_doc_as_markdown(service, file_id: str) -> Optional[str]:
    """Download a Google Doc as Markdown content."""
    try:
        # Export as markdown
        content = (
            service.files()
            .export(fileId=file_id, mimeType="text/markdown")
            .execute()
        )
        # Content is returned as bytes
        if isinstance(content, bytes):
            return content.decode("utf-8")
        return content
    except Exception as e:
        console.print(f"[red]Export error:[/red] {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Google Docs as Markdown files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  gdoc2md "My Document"                        # Download from root
  gdoc2md "My Document" --folder "OTA/Reports" # Download from folder
  gdoc2md "My Document" -o report.md           # Save with custom name
  gdoc2md --list --folder OTA                  # List docs in folder

Credentials (in order of precedence):
  1. .gdoc-token.json in current directory (project-specific)
  2. ~/.config/md2gdoc/token.json (global)
  3. Application Default Credentials (gcloud)
        """,
    )

    parser.add_argument(
        "doc_name",
        type=str,
        nargs="?",
        help="Name of the Google Doc to download",
    )

    parser.add_argument(
        "--folder",
        "-f",
        type=str,
        default="",
        help="Folder in Google Drive (e.g., 'OTA/Reports')",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="",
        help="Output filename (default: <doc_name>.md)",
    )

    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List Google Docs in the folder instead of downloading",
    )

    args = parser.parse_args()

    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    # Need either doc_name or --list
    if not args.doc_name and not args.list:
        parser.print_help()
        sys.exit(1)

    # Get Drive service
    service = get_drive_service()
    if not service:
        sys.exit(1)

    # Find folder if specified
    folder_id = None
    if args.folder:
        console.print(f"[dim]Finding folder: {args.folder}[/dim]")
        folder_id = find_folder_id(service, args.folder, create_if_missing=False)
        if folder_id is None:
            console.print(f"[red]Error:[/red] Folder not found: {args.folder}")
            sys.exit(1)

    # List mode
    if args.list:
        docs = list_docs_in_folder(service, folder_id)
        if not docs:
            console.print("[yellow]No Google Docs found in this folder.[/yellow]")
            sys.exit(0)

        console.print(f"\n[bold]Google Docs in {args.folder or 'My Drive'}:[/bold]\n")
        for doc in docs:
            console.print(f"  • {doc['name']}")
        console.print(f"\n[dim]Total: {len(docs)} document(s)[/dim]")
        sys.exit(0)

    # Download mode
    console.print(f"[dim]Looking for: {args.doc_name}[/dim]")
    doc = find_doc_by_name(service, folder_id, args.doc_name)

    if not doc:
        console.print(f"[red]Error:[/red] Document not found: {args.doc_name}")
        # Suggest listing
        console.print(f"[dim]Use --list to see available documents[/dim]")
        sys.exit(1)

    # Download as markdown
    console.print(f"[cyan]Downloading[/cyan] {doc['name']} → Markdown...")
    content = download_doc_as_markdown(service, doc["id"])

    if content is None:
        sys.exit(1)

    # Determine output filename
    if args.output:
        output_path = Path(args.output)
    else:
        # Use doc name, sanitize for filesystem
        safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in doc["name"])
        output_path = Path(f"{safe_name}.md")

    # Check if file exists
    if output_path.exists():
        console.print(
            f"[yellow]Warning:[/yellow] {output_path} already exists, overwriting"
        )

    # Write file
    output_path.write_text(content, encoding="utf-8")

    console.print()
    console.print(
        Panel(
            f"[green]Successfully downloaded![/green]\n\n"
            f"[dim]Document:[/dim] {doc['name']}\n"
            f"[dim]Saved to:[/dim] {output_path}",
            title="Done",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
