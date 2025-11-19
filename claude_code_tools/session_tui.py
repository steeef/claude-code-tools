"""
Textual-based Terminal User Interface for session management.

Provides an interactive, arrow-navigable interface for browsing and
managing Claude Code and Codex sessions.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
from datetime import datetime
import textwrap

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, ListView, ListItem, OptionList, Static
from textual.widgets.option_list import Option
from textual.message import Message
from rich.text import Text


class ActionMenuScreen(ModalScreen[Optional[str]]):
    """Minimal modal screen for selecting session actions."""

    BINDINGS = [
        Binding("escape", "dismiss_none", "Back"),
    ]

    def __init__(
        self,
        session_id: str,
        agent: str,
        project_name: str,
        git_branch: Optional[str] = None,
        is_sidechain: bool = False,
    ):
        """
        Initialize action menu screen.

        Args:
            session_id: Session identifier
            agent: Agent type ('claude' or 'codex')
            project_name: Project or working directory name
            git_branch: Optional git branch name
            is_sidechain: If True, this is a sub-agent session
        """
        super().__init__()
        self.session_id = session_id
        self.agent = agent
        self.project_name = project_name
        self.git_branch = git_branch
        self.is_sidechain = is_sidechain

    def compose(self) -> ComposeResult:
        """Compose the action menu UI."""
        with Container(id="action-menu-container"):
            yield Static(
                f"[bold]{self.session_id[:8]}...[/] | "
                f"{self.agent.title()} | {self.project_name}"
                + (f" | {self.git_branch}" if self.git_branch else ""),
                id="session-header",
            )

            # Build options list
            options = []
            if not self.is_sidechain:
                options.append(Option("Resume Session", id="resume"))
                options.append(Option("Continue (Fresh Session)", id="continue"))
            options.extend([
                Option("Show File Path", id="path"),
                Option("Copy Session File", id="copy"),
            ])
            if not self.is_sidechain:
                options.append(Option("Clone & Resume", id="clone"))
            options.extend([
                Option("Export to Text", id="export"),
                Option("← Back", id="back"),
            ])

            yield OptionList(*options, id="action-options")

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Handle option selection."""
        if event.option.id == "back":
            self.dismiss(None)
        else:
            self.dismiss(event.option.id)

    def action_dismiss_none(self) -> None:
        """Dismiss with None (back action)."""
        self.dismiss(None)


class SessionCard(Static):
    """A card widget displaying session information with multi-line preview."""

    DEFAULT_CSS = """
    SessionCard {
        height: auto;
        padding: 1 2;
        border: solid $panel-lighten-1;
        margin: 0 1;
    }

    SessionCard.selected {
        background: $accent;
        border: solid $accent-lighten-2;
    }

    SessionCard:hover {
        background: $panel-lighten-1;
    }
    """

    def __init__(
        self,
        session: Tuple[Any, ...],
        index: int,
        is_selected: bool = False,
    ):
        """
        Initialize session card.

        Args:
            session: Session tuple data
            index: Display index (1-based)
            is_selected: Whether this card is currently selected
        """
        super().__init__()
        self.session = session
        self.index = index
        self.is_selected = is_selected

        # Extract session details
        if isinstance(session, (tuple, list)) and len(session) >= 10:  # Claude tuple format
            (
                session_id,
                mod_time,
                create_time,
                line_count,
                project_name,
                preview,
                project_path,
                git_branch,
                is_trimmed,
                is_sidechain,
            ) = session[:10]
            agent = "Claude"
        else:  # Dict format
            session_id = session.get("session_id", "")
            mod_time = session.get("mod_time", 0)
            line_count = session.get("lines", 0)
            project_name = session.get("project", "")
            preview = session.get("preview", "")
            git_branch = session.get("branch", "")
            is_sidechain = session.get("is_sidechain", False)
            agent = session.get("agent_display", "Unknown")

        # Store extracted values
        self.session_id = session_id
        self.agent = agent
        self.project_name = project_name
        self.git_branch = git_branch
        self.mod_time = mod_time
        self.line_count = line_count
        self.preview = preview
        self.is_sidechain = is_sidechain

    def render(self) -> Text:
        """Render the session card content."""
        date_str = datetime.fromtimestamp(self.mod_time).strftime("%m/%d %H:%M")

        # First line: index, agent, project, branch, date
        branch_display = f"({self.git_branch})" if self.git_branch else ""
        header = Text()
        header.append(f"{self.index}. ", style="bold cyan")
        header.append(f"[{self.agent}] ", style="bold yellow")
        header.append(f"{self.project_name[:30]} ", style="white")
        if branch_display:
            header.append(f"{branch_display[:18]} ", style="dim")
        # Pad to align date to the right
        header.append(" " * (70 - len(header.plain)))
        header.append(f"{date_str}", style="dim")

        # Second line: Session ID and line count
        session_display = f"{self.session_id[:12]}..."
        if self.is_sidechain:
            session_display += " (sub)"

        info = Text()
        info.append(f"   Session: ", style="dim")
        info.append(session_display, style="cyan")
        info.append(f"                  {self.line_count:,} lines", style="dim")

        # Preview lines (wrapped, max 3 lines)
        preview_text = Text()
        if self.preview:
            preview_lines = textwrap.wrap(self.preview, width=70)[:3]
            preview_text.append("   Preview: ", style="dim")
            preview_text.append(preview_lines[0] if preview_lines else "")
            for line in preview_lines[1:]:
                preview_text.append("\n            ")
                preview_text.append(line)

        # Combine all parts
        result = Text()
        result.append_text(header)
        result.append("\n")
        result.append_text(info)
        if self.preview:
            result.append("\n")
            result.append_text(preview_text)

        return result

    def on_mount(self) -> None:
        """Update classes when mounted."""
        if self.is_selected:
            self.add_class("selected")


class SessionTableScreen(Screen):
    """Main screen displaying interactive session table."""

    BINDINGS = [
        Binding("escape", "quit_app", "Quit"),
        Binding("q", "quit_app", "Quit"),
        Binding("g", "goto_mode", "Goto Row"),
        Binding("1", "quick_select(1)", "Select 1"),
        Binding("2", "quick_select(2)", "Select 2"),
        Binding("3", "quick_select(3)", "Select 3"),
        Binding("4", "quick_select(4)", "Select 4"),
        Binding("5", "quick_select(5)", "Select 5"),
        Binding("6", "quick_select(6)", "Select 6"),
        Binding("7", "quick_select(7)", "Select 7"),
        Binding("8", "quick_select(8)", "Select 8"),
        Binding("9", "quick_select(9)", "Select 9"),
    ]

    def __init__(
        self,
        sessions: List[Tuple[Any, ...]],
        keywords: List[str],
        action_handler: Callable[[Tuple[Any, ...], str], None],
    ):
        """
        Initialize session table screen.

        Args:
            sessions: List of session tuples
            keywords: Search keywords used
            action_handler: Function to handle selected actions
        """
        super().__init__()
        self.sessions = sessions
        self.keywords = keywords
        self.action_handler = action_handler
        self.goto_mode = False
        self.goto_input = ""
        self.selected_index = 0

    def compose(self) -> ComposeResult:
        """Compose the session list UI."""
        title = (
            f"Sessions matching: {', '.join(self.keywords)}"
            if self.keywords
            else "All Sessions"
        )
        yield Header(show_clock=True)
        yield Static(f"[bold cyan]{title}[/]", id="table-title")

        # Create scrollable container for session cards
        with VerticalScroll(id="session-list"):
            for idx, session in enumerate(self.sessions, 1):
                yield SessionCard(session, idx, is_selected=(idx == 1))

        yield Static("", id="goto-input-display")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize list when screen is mounted."""
        # Focus the scroll container
        self.query_one("#session-list").focus()

        # Auto-select if only one session
        if len(self.sessions) == 1:
            self.notify("Auto-selecting only session...")
            self.show_action_menu_for_row(0)

    def on_click(self, event) -> None:
        """Handle click on session card."""
        if not self.goto_mode:
            # Find which card was clicked
            card = event.widget
            if isinstance(card, SessionCard):
                # Find the index of this card
                cards = list(self.query(SessionCard))
                if card in cards:
                    self.select_card(cards.index(card))
                    self.show_action_menu_for_row(cards.index(card))

    def on_key(self, event) -> None:
        """Handle key press events."""
        if self.goto_mode:
            # Goto mode key handling
            if event.key == "escape":
                self.goto_mode = False
                self.goto_input = ""
                self.update_goto_display()
                event.prevent_default()
            elif event.key.isdigit():
                self.goto_input += event.key
                self.update_goto_display()
                event.prevent_default()
            elif event.key == "enter":
                if self.goto_input:
                    row_index = int(self.goto_input) - 1
                    if 0 <= row_index < len(self.sessions):
                        self.select_card(row_index)
                        self.show_action_menu_for_row(row_index)
                self.goto_mode = False
                self.goto_input = ""
                self.update_goto_display()
                event.prevent_default()
        else:
            # Normal navigation
            if event.key == "enter":
                self.show_action_menu_for_row(self.selected_index)
                event.prevent_default()
            elif event.key == "down":
                if self.selected_index < len(self.sessions) - 1:
                    self.select_card(self.selected_index + 1)
                event.prevent_default()
            elif event.key == "up":
                if self.selected_index > 0:
                    self.select_card(self.selected_index - 1)
                event.prevent_default()

    def select_card(self, index: int) -> None:
        """Select a card by index."""
        if 0 <= index < len(self.sessions):
            cards = list(self.query(SessionCard))

            # Remove selected class from all cards
            for card in cards:
                card.remove_class("selected")

            # Add selected class to new card
            if index < len(cards):
                cards[index].add_class("selected")
                # Scroll to make it visible
                cards[index].scroll_visible()

            self.selected_index = index

    def show_action_menu_for_row(self, row_index: int) -> None:
        """Show action menu for selected session."""
        if 0 <= row_index < len(self.sessions):
            session = self.sessions[row_index]

            # Extract session details
            if isinstance(session, (tuple, list)) and len(session) >= 10:  # Claude tuple format
                session_id = session[0]
                project_name = session[4]
                git_branch = session[7]
                is_sidechain = session[9]
                agent = "claude"
            else:  # Dict format
                session_id = session.get("session_id", "")
                project_name = session.get("project", "")
                git_branch = session.get("branch")
                is_sidechain = session.get("is_sidechain", False)
                agent = session.get("agent", "unknown")

            # Show action menu and handle result
            self.app.push_screen(
                ActionMenuScreen(
                    session_id=session_id,
                    agent=agent,
                    project_name=project_name,
                    git_branch=git_branch,
                    is_sidechain=is_sidechain,
                ),
                callback=lambda action: self.handle_action_result(session, action),
            )

    def handle_action_result(
        self, session: Tuple[Any, ...], action: Optional[str]
    ) -> None:
        """Handle the result from action menu."""
        if action:
            # Call the action handler
            self.action_handler(session, action)

            # If action is resume, clone, or continue, exit the app
            if action in ("resume", "clone", "continue", "suppress_resume", "smart_trim_resume"):
                self.app.exit()
            else:
                # For other actions, show the action menu again (persistent loop)
                self.show_action_menu_for_row(self.selected_index)

    def action_quit_app(self) -> None:
        """Quit the application."""
        self.app.exit()

    def action_goto_mode(self) -> None:
        """Enter goto row mode."""
        self.goto_mode = True
        self.goto_input = ""
        self.update_goto_display()

    def action_quick_select(self, row_num: str) -> None:
        """Quick select row by number (1-9)."""
        if not self.goto_mode:
            row_index = int(row_num) - 1
            if 0 <= row_index < len(self.sessions):
                self.select_card(row_index)
                self.show_action_menu_for_row(row_index)

    def update_goto_display(self) -> None:
        """Update the goto input display."""
        display = self.query_one("#goto-input-display", Static)
        if self.goto_mode:
            display.update(
                f"[bold yellow]Goto row:[/] {self.goto_input}_"
            )
        else:
            display.update("")


class SessionMenuApp(App):
    """Main TUI application for session management."""

    CSS = """
    #action-menu-container {
        width: 60;
        height: auto;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    #session-header {
        padding: 0 1 1 1;
        text-align: center;
    }

    #action-options {
        height: auto;
        max-height: 15;
    }

    #table-title {
        padding: 1 2;
        background: $panel;
    }

    #goto-input-display {
        padding: 0 2;
        height: 1;
        background: $panel;
    }

    #session-list {
        height: 1fr;
        padding: 1 0;
    }
    """

    def __init__(
        self,
        sessions: List[Tuple[Any, ...]],
        keywords: List[str],
        action_handler: Callable[[Tuple[Any, ...], str], None],
    ):
        """
        Initialize the session menu TUI app.

        Args:
            sessions: List of session tuples
            keywords: Search keywords
            action_handler: Function to handle actions
        """
        super().__init__()
        self.sessions = sessions
        self.keywords = keywords
        self.action_handler = action_handler

    def on_mount(self) -> None:
        """Push the main session table screen on mount."""
        self.push_screen(
            SessionTableScreen(
                self.sessions,
                self.keywords,
                self.action_handler,
            )
        )


def run_session_tui(
    sessions: List[Tuple[Any, ...]],
    keywords: List[str],
    action_handler: Callable[[Tuple[Any, ...], str], None],
) -> None:
    """
    Run the session management TUI.

    Args:
        sessions: List of session tuples
        keywords: Search keywords used to find sessions
        action_handler: Callback function to handle selected actions
    """
    app = SessionMenuApp(sessions, keywords, action_handler)
    app.run()
