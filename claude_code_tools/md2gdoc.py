#!/usr/bin/env python3
"""
md2gdoc: Upload Markdown files to Google Drive as native Google Docs.

This tool uses the Google Drive API to upload markdown files with native
conversion to Google Docs format - the same conversion that happens when
you manually upload a .md file and click "Open in Google Docs".

Prerequisites:
- First run: Will open browser for OAuth authentication (one-time setup)
- Credentials stored in ~/.config/md2gdoc/
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

console = Console()

# Google Drive API scopes
# Using 'drive' scope to access all files (including shortcuts/shared folders)
# 'drive.file' only sees files created by this app
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Config directory for storing credentials (global fallback)
CONFIG_DIR = Path.home() / ".config" / "md2gdoc"

# Local (project-specific) credential files - checked first
LOCAL_TOKEN_FILE = Path(".gdoc-token.json")
LOCAL_CREDENTIALS_FILE = Path(".gdoc-credentials.json")

# Global credential files - fallback
GLOBAL_TOKEN_FILE = CONFIG_DIR / "token.json"
GLOBAL_CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"


def get_token_file() -> Path:
    """Get token file path - local first, then global."""
    if LOCAL_TOKEN_FILE.exists():
        return LOCAL_TOKEN_FILE
    return GLOBAL_TOKEN_FILE


def get_credentials_file() -> Path:
    """Get credentials file path - local first, then global."""
    if LOCAL_CREDENTIALS_FILE.exists():
        return LOCAL_CREDENTIALS_FILE
    if GLOBAL_CREDENTIALS_FILE.exists():
        return GLOBAL_CREDENTIALS_FILE
    # Return local path for error messages (preferred location)
    return LOCAL_CREDENTIALS_FILE

# Default OAuth client credentials (for CLI tools)
# Users can override by placing their own credentials.json in CONFIG_DIR
DEFAULT_CLIENT_CONFIG = {
    "installed": {
        "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
        "project_id": "md2gdoc",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "YOUR_CLIENT_SECRET",
        "redirect_uris": ["http://localhost"],
    }
}


def check_dependencies() -> bool:
    """Check if required Google API packages are installed."""
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401

        return True
    except ImportError:
        console.print(
            Panel(
                "[red]Missing dependencies:[/red] google-api-python-client, "
                "google-auth-oauthlib\n\n"
                "Install with:\n"
                "[cyan]pip install google-api-python-client google-auth-oauthlib[/cyan]",
                title="Dependencies Required",
                border_style="red",
            )
        )
        return False


def get_credentials():
    """
    Get OAuth credentials. Tries in order:
    1. Saved token from previous run (local .gdoc-token.json, then global)
    2. Application Default Credentials (from gcloud)
    3. Manual OAuth flow using credentials.json (local, then global)
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    token_file = get_token_file()
    credentials_file = get_credentials_file()

    # Option 1: Load existing token if available
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
            if creds and creds.valid:
                console.print(f"[dim]Using token: {token_file}[/dim]")
                return creds
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Save refreshed token
                with open(token_file, "w") as f:
                    f.write(creds.to_json())
                console.print(f"[dim]Using token: {token_file}[/dim]")
                return creds
        except Exception:
            pass  # Fall through to other methods

    # Option 2: Try Application Default Credentials (gcloud auth)
    try:
        import google.auth

        creds, _ = google.auth.default(scopes=SCOPES)
        if creds and creds.valid:
            console.print("[dim]Using Application Default Credentials[/dim]")
            return creds
    except Exception:
        pass  # Fall through to OAuth flow

    # Option 3: Manual OAuth flow
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not credentials_file.exists():
        console.print(
            Panel(
                "[red]OAuth credentials not found![/red]\n\n"
                "[bold]Option A - Project-specific (recommended):[/bold]\n"
                f"Save OAuth client JSON as: [cyan].gdoc-credentials.json[/cyan]\n"
                "(in current directory)\n\n"
                "[bold]Option B - Global:[/bold]\n"
                f"Save as: [cyan]{GLOBAL_CREDENTIALS_FILE}[/cyan]\n\n"
                "[bold]To get the OAuth client JSON:[/bold]\n"
                "1. Go to console.cloud.google.com\n"
                "2. APIs & Services → Credentials\n"
                "3. Create Credentials → OAuth client ID → Desktop app\n"
                "4. Download JSON",
                title="Setup Required",
                border_style="yellow",
            )
        )
        return None

    console.print(f"[dim]Using credentials: {credentials_file}[/dim]")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_file), SCOPES
    )
    console.print("[cyan]Opening browser for Google authentication...[/cyan]")
    creds = flow.run_local_server(port=0)

    # Save token locally (in current directory)
    with open(LOCAL_TOKEN_FILE, "w") as token:
        token.write(creds.to_json())
    console.print(f"[green]Token saved to {LOCAL_TOKEN_FILE}[/green]")

    return creds


def get_drive_service():
    """Get authenticated Google Drive service."""
    from googleapiclient.discovery import build

    creds = get_credentials()
    if not creds:
        return None

    return build("drive", "v3", credentials=creds)


def find_folder_id(service, folder_path: str, create_if_missing: bool = True) -> Optional[str]:
    """Find folder by path (following shortcuts), optionally create if missing."""
    if not folder_path:
        return None  # Root folder

    parts = folder_path.strip("/").split("/")
    parent_id = "root"

    for part in parts:
        # Search for folder OR shortcut with this name under parent
        query = (
            f"name = '{part}' and "
            f"'{parent_id}' in parents and "
            f"(mimeType = 'application/vnd.google-apps.folder' or "
            f"mimeType = 'application/vnd.google-apps.shortcut') and "
            f"trashed = false"
        )
        console.print(f"[dim]Looking for '{part}' in parent={parent_id}[/dim]")
        results = (
            service.files()
            .list(q=query, fields="files(id, name, mimeType, shortcutDetails)", pageSize=10)
            .execute()
        )
        files = results.get("files", [])
        console.print(f"[dim]Found {len(files)} matches: {[(f['name'], f['mimeType']) for f in files]}[/dim]")

        if files:
            file = files[0]
            if file.get("mimeType") == "application/vnd.google-apps.shortcut":
                # Follow the shortcut to get target folder ID
                shortcut_details = file.get("shortcutDetails", {})
                target_id = shortcut_details.get("targetId")
                if target_id:
                    console.print(f"[dim]Following shortcut: {part}[/dim]")
                    parent_id = target_id
                else:
                    console.print(f"[yellow]Warning: Shortcut {part} has no target[/yellow]")
                    return None
            else:
                parent_id = file["id"]
        else:
            if not create_if_missing:
                return None
            # Folder doesn't exist - create it
            file_metadata = {
                "name": part,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            folder = (
                service.files().create(body=file_metadata, fields="id").execute()
            )
            parent_id = folder["id"]
            console.print(f"[dim]Created folder: {part}[/dim]")

    return parent_id


def check_file_exists(service, folder_id: Optional[str], filename: str) -> bool:
    """Check if a file with this name exists in the folder."""
    parent = folder_id if folder_id else "root"
    query = (
        f"name = '{filename}' and "
        f"'{parent}' in parents and "
        f"mimeType = 'application/vnd.google-apps.document' and "
        f"trashed = false"
    )
    console.print(f"[dim]Checking for existing file: {filename}[/dim]")
    results = (
        service.files()
        .list(q=query, fields="files(id, name)", pageSize=10)
        .execute()
    )
    files = results.get("files", [])
    if files:
        console.print(f"[dim]Found {len(files)} existing file(s): {[f['name'] for f in files]}[/dim]")
    return len(files) > 0


def list_existing_versions(
    service, folder_id: Optional[str], base_name: str
) -> list[str]:
    """List existing files that match the base name pattern."""
    parent = folder_id if folder_id else "root"
    query = (
        f"name contains '{base_name}' and "
        f"'{parent}' in parents and "
        f"mimeType = 'application/vnd.google-apps.document' and "
        f"trashed = false"
    )
    results = (
        service.files()
        .list(q=query, fields="files(id, name)", pageSize=100)
        .execute()
    )
    return [f["name"] for f in results.get("files", [])]


def get_next_version_name(
    service, folder_id: Optional[str], base_name: str
) -> str:
    """Get the next available version name (e.g., report-1, report-2)."""
    existing = list_existing_versions(service, folder_id, base_name)

    if not existing:
        return f"{base_name}-1"

    # Find the highest version number
    max_version = 0
    for f in existing:
        match = re.match(rf"^{re.escape(base_name)}-(\d+)$", f)
        if match:
            version = int(match.group(1))
            max_version = max(max_version, version)

    return f"{base_name}-{max_version + 1}"


def delete_file(service, folder_id: Optional[str], filename: str) -> bool:
    """Delete a file by name (for overwrite)."""
    parent = folder_id if folder_id else "root"
    query = (
        f"name = '{filename}' and "
        f"'{parent}' in parents and "
        f"mimeType = 'application/vnd.google-apps.document' and "
        f"trashed = false"
    )
    results = (
        service.files()
        .list(q=query, fields="files(id)", pageSize=1)
        .execute()
    )
    files = results.get("files", [])
    if files:
        service.files().delete(fileId=files[0]["id"]).execute()
        return True
    return False


def prompt_for_conflict(existing_name: str, versioned_name: str) -> Optional[str]:
    """
    Prompt user for action when file already exists.

    Returns:
        - "version": use versioned name
        - "overwrite": overwrite existing
        - None: user cancelled
    """
    console.print()
    console.print(
        Panel(
            f"[yellow]File already exists:[/yellow] [bold]{existing_name}[/bold]",
            title="Conflict Detected",
            border_style="yellow",
        )
    )
    console.print()

    # Show options
    options_text = Text()
    options_text.append("  [Enter] ", style="cyan bold")
    options_text.append("Add version suffix → ", style="dim")
    options_text.append(f"{versioned_name}\n", style="green")
    options_text.append("  [YES]   ", style="red bold")
    options_text.append("Overwrite existing file", style="dim")

    console.print(options_text)
    console.print()

    choice = Prompt.ask(
        "Your choice",
        default="",
        show_default=False,
    )

    if choice == "":
        return "version"
    elif choice.upper() == "YES":
        return "overwrite"
    else:
        console.print("[dim]Invalid choice. Cancelling.[/dim]")
        return None


def upload_markdown(
    service,
    md_path: Path,
    folder_id: Optional[str],
    filename: str,
) -> Optional[str]:
    """
    Upload markdown file to Google Drive with native conversion to Google Docs.

    Returns the file ID on success, None on failure.
    """
    from googleapiclient.http import MediaFileUpload

    file_metadata = {
        "name": filename,
        "mimeType": "application/vnd.google-apps.document",
    }
    if folder_id:
        file_metadata["parents"] = [folder_id]

    # Upload with text/markdown MIME type - Google converts natively
    media = MediaFileUpload(
        str(md_path),
        mimetype="text/markdown",
        resumable=True,
    )

    try:
        with console.status("[cyan]Uploading to Google Drive...[/cyan]"):
            file = (
                service.files()
                .create(body=file_metadata, media_body=media, fields="id,webViewLink")
                .execute()
            )
        return file.get("webViewLink")
    except Exception as e:
        console.print(f"[red]Upload error:[/red] {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload Markdown files to Google Drive as native Google Docs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  md2gdoc report.md                           # Upload to root of Drive
  md2gdoc report.md --folder "OTA/Reports"    # Upload to specific folder
  md2gdoc report.md --name "Q4 Summary"       # Upload with custom name
  md2gdoc report.md --on-existing version     # Auto-version if exists (no prompt)

Credentials (in order of precedence):
  1. .gdoc-token.json in current directory (project-specific)
  2. ~/.config/md2gdoc/token.json (global)
  3. Application Default Credentials (gcloud)

First run opens browser for OAuth (one-time per project).
        """,
    )

    parser.add_argument(
        "markdown_file",
        type=Path,
        help="Path to the Markdown file to upload",
    )

    parser.add_argument(
        "--folder",
        "-f",
        type=str,
        default="",
        help="Target folder in Google Drive (e.g., 'OTA/Reports')",
    )

    parser.add_argument(
        "--name",
        "-n",
        type=str,
        default="",
        help="Name for the Google Doc (default: markdown filename without extension)",
    )

    parser.add_argument(
        "--on-existing",
        type=str,
        choices=["ask", "version", "overwrite"],
        default="ask",
        help="Action when file exists: ask (prompt), version (auto-increment), "
        "overwrite (replace). Default: ask",
    )

    args = parser.parse_args()

    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    # Validate input file
    if not args.markdown_file.exists():
        console.print(f"[red]Error:[/red] File not found: {args.markdown_file}")
        sys.exit(1)

    if args.markdown_file.suffix.lower() not in [".md", ".markdown"]:
        console.print(
            "[yellow]Warning:[/yellow] "
            "File doesn't have .md extension, proceeding anyway"
        )

    # Get Drive service
    service = get_drive_service()
    if not service:
        sys.exit(1)

    # Find or create target folder
    folder_id = None
    if args.folder:
        console.print(f"[dim]Finding folder: {args.folder}[/dim]")
        folder_id = find_folder_id(service, args.folder)

    # Determine the target filename
    if args.name:
        target_name = args.name
    else:
        target_name = args.markdown_file.stem

    # Check if file already exists
    file_exists = check_file_exists(service, folder_id, target_name)

    final_name = target_name
    if file_exists:
        versioned_name = get_next_version_name(service, folder_id, target_name)

        # Determine action based on --on-existing flag
        on_existing = getattr(args, "on_existing", "ask")
        if on_existing == "ask":
            action = prompt_for_conflict(target_name, versioned_name)
            if action is None:
                console.print("[dim]Upload cancelled.[/dim]")
                sys.exit(0)
        else:
            action = on_existing

        if action == "version":
            final_name = versioned_name
            console.print(f"[dim]File exists, using versioned name: {final_name}[/dim]")
        elif action == "overwrite":
            console.print(f"[dim]Deleting existing file: {target_name}[/dim]")
            delete_file(service, folder_id, target_name)

    # Upload with native markdown conversion
    console.print(
        f"[cyan]Uploading[/cyan] {args.markdown_file.name} → Google Docs..."
    )
    web_link = upload_markdown(service, args.markdown_file, folder_id, final_name)

    if not web_link:
        sys.exit(1)

    # Success message
    location = f"{args.folder}/{final_name}" if args.folder else final_name

    console.print()
    console.print(
        Panel(
            f"[green]Successfully uploaded![/green]\n\n"
            f"[dim]Name:[/dim] {final_name}\n"
            f"[dim]Location:[/dim] {location}\n"
            f"[dim]Link:[/dim] {web_link}",
            title="Done",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
