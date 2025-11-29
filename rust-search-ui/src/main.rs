//! Rust TUI for session search - closely modeled after zippoxer/recall
//!
//! Features:
//! - Search bar at top with scope indicator
//! - Session list with project, agent, time ago, snippet
//! - Preview pane with conversation messages
//! - Keyboard shortcuts for navigation and actions

use anyhow::{Context, Result};
use chrono::{DateTime, TimeZone, Utc};
use crossterm::{
    event::{self, Event, KeyCode, KeyEventKind, KeyModifiers},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{List, ListItem, ListState, Paragraph},
    Frame, Terminal,
};
use serde::Serialize;
use std::io::{self, stdout};
use std::time::Duration;
use tantivy::{
    collector::TopDocs,
    query::AllQuery,
    schema::{Schema, Value, STORED, TEXT},
    Index, ReloadPolicy,
};

// ============================================================================
// Theme
// ============================================================================

struct Theme {
    selection_bg: Color,
    selection_header_fg: Color,
    selection_snippet_fg: Color,
    snippet_fg: Color,
    match_fg: Color,
    search_bg: Color,
    placeholder_fg: Color,
    accent: Color,
    dim_fg: Color,
    keycap_bg: Color,
    user_bubble_bg: Color,
    user_label: Color,
    claude_bubble_bg: Color,
    codex_bubble_bg: Color,
    claude_source: Color,
    codex_source: Color,
    separator_fg: Color,
    scope_label_fg: Color,
}

impl Theme {
    fn dark() -> Self {
        Self {
            selection_bg: Color::Rgb(50, 50, 55),
            selection_header_fg: Color::Cyan,
            selection_snippet_fg: Color::Rgb(180, 180, 180),
            snippet_fg: Color::Rgb(120, 120, 120),
            match_fg: Color::Yellow,
            search_bg: Color::Rgb(30, 30, 35),
            placeholder_fg: Color::Rgb(100, 100, 100),
            accent: Color::Cyan,
            dim_fg: Color::Rgb(100, 100, 100),
            keycap_bg: Color::Rgb(60, 60, 65),
            user_bubble_bg: Color::Rgb(30, 45, 55),
            user_label: Color::Rgb(80, 180, 220),
            claude_bubble_bg: Color::Rgb(45, 35, 30),
            codex_bubble_bg: Color::Rgb(30, 45, 35),
            claude_source: Color::Rgb(255, 150, 50),
            codex_source: Color::Rgb(80, 200, 120),
            separator_fg: Color::Rgb(60, 60, 65),
            scope_label_fg: Color::Rgb(140, 140, 140),
        }
    }
}

// ============================================================================
// Session Data
// ============================================================================

#[derive(Debug, Clone, Serialize)]
struct Session {
    session_id: String,
    agent: String,
    project: String,
    branch: String,
    cwd: String,
    created: String,
    modified: String,
    lines: i64,
    export_path: String,
    first_msg_role: String,
    first_msg_content: String,
    last_msg_role: String,
    last_msg_content: String,
    derivation_type: String,  // "trimmed", "continued", or ""
    is_sidechain: bool,       // Sub-agent session
}

impl Session {
    fn project_name(&self) -> &str {
        if self.project.is_empty() {
            std::path::Path::new(&self.cwd)
                .file_name()
                .and_then(|s| s.to_str())
                .unwrap_or("unknown")
        } else {
            &self.project
        }
    }

    fn agent_icon(&self) -> &str {
        if self.agent == "claude" {
            "●"
        } else {
            "■"
        }
    }

    fn agent_display(&self) -> &str {
        if self.agent == "claude" {
            "Claude"
        } else {
            "Codex"
        }
    }

    fn time_ago(&self) -> String {
        format_time_ago(&self.modified)
    }

    /// Session ID display with annotations: abc123.. (t) (c) (sub)
    fn session_id_display(&self) -> String {
        let id_prefix = if self.session_id.len() >= 8 {
            &self.session_id[..8]
        } else {
            &self.session_id
        };
        let mut display = format!("{}..", id_prefix);

        if self.derivation_type == "trimmed" {
            display.push_str(" (t)");
        } else if self.derivation_type == "continued" {
            display.push_str(" (c)");
        }
        if self.is_sidechain {
            display.push_str(" (sub)");
        }
        display
    }

    /// Branch display with fallback
    fn branch_display(&self) -> &str {
        if self.branch.is_empty() {
            "N/A"
        } else {
            &self.branch
        }
    }

    /// Date display as range: "11/27 - 11/29 15:23" or "11/29 15:23" if same day
    fn date_display(&self) -> String {
        let parse_date = |s: &str| {
            DateTime::parse_from_rfc3339(s)
                .or_else(|_| {
                    chrono::NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f")
                        .map(|ndt| Utc.from_utc_datetime(&ndt).fixed_offset())
                })
                .ok()
        };

        let modified_dt = parse_date(&self.modified);
        let created_dt = parse_date(&self.created);

        match (created_dt, modified_dt) {
            (Some(created), Some(modified)) => {
                // Check if same day
                if created.format("%m/%d").to_string() == modified.format("%m/%d").to_string() {
                    // Same day: just show "11/29 15:23"
                    modified.format("%m/%d %H:%M").to_string()
                } else {
                    // Different days: show range "11/27 - 11/29 15:23"
                    format!(
                        "{} - {}",
                        created.format("%m/%d"),
                        modified.format("%m/%d %H:%M")
                    )
                }
            }
            (None, Some(modified)) => modified.format("%m/%d %H:%M").to_string(),
            _ => self.modified.clone(),
        }
    }
}

// ============================================================================
// App State
// ============================================================================

struct App {
    sessions: Vec<Session>,
    filtered: Vec<usize>, // Indices into sessions
    query: String,
    selected: usize,
    list_scroll: usize,
    preview_scroll: usize,
    should_quit: bool,
    should_select: Option<Session>,
    total_sessions: usize,
    scope_global: bool,
    launch_cwd: String,

    // Filter state
    filter_original_only: bool,
    filter_no_sub: bool,
    filter_no_trim: bool,
    filter_no_cont: bool,
    filter_agent: Option<String>, // None = all, Some("claude"), Some("codex")
    filter_min_lines: Option<i64>,

    // Command mode (: prefix)
    command_mode: bool,

    // Full conversation view
    full_view_mode: bool,
    full_content: String,
    full_content_scroll: usize,
}

impl App {
    fn new(sessions: Vec<Session>) -> Self {
        let total = sessions.len();
        let launch_cwd = std::env::current_dir()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_default();

        let mut app = Self {
            sessions,
            filtered: Vec::new(),
            query: String::new(),
            selected: 0,
            list_scroll: 0,
            preview_scroll: 0,
            should_quit: false,
            should_select: None,
            total_sessions: total,
            scope_global: false,
            launch_cwd,
            // Filter state
            filter_original_only: false,
            filter_no_sub: false,
            filter_no_trim: false,
            filter_no_cont: false,
            filter_agent: None,
            filter_min_lines: None,
            // Command mode
            command_mode: false,
            // Full view mode
            full_view_mode: false,
            full_content: String::new(),
            full_content_scroll: 0,
        };
        app.filter();
        app
    }

    fn filter(&mut self) {
        let query_lower = self.query.to_lowercase();
        self.filtered = self
            .sessions
            .iter()
            .enumerate()
            .filter(|(_, s)| {
                // Scope filter
                if !self.scope_global && !s.cwd.is_empty() && s.cwd != self.launch_cwd {
                    return false;
                }

                // Original only: exclude derived and sidechain sessions
                if self.filter_original_only {
                    if !s.derivation_type.is_empty() || s.is_sidechain {
                        return false;
                    }
                }

                // No sub-agent filter
                if self.filter_no_sub && s.is_sidechain {
                    return false;
                }

                // No trimmed filter
                if self.filter_no_trim && s.derivation_type == "trimmed" {
                    return false;
                }

                // No continued filter
                if self.filter_no_cont && s.derivation_type == "continued" {
                    return false;
                }

                // Agent filter
                if let Some(ref agent) = self.filter_agent {
                    if s.agent != *agent {
                        return false;
                    }
                }

                // Min lines filter
                if let Some(min) = self.filter_min_lines {
                    if s.lines < min {
                        return false;
                    }
                }

                // Query filter
                if query_lower.is_empty() {
                    return true;
                }
                s.project.to_lowercase().contains(&query_lower)
                    || s.first_msg_content.to_lowercase().contains(&query_lower)
                    || s.last_msg_content.to_lowercase().contains(&query_lower)
                    || s.session_id.to_lowercase().contains(&query_lower)
            })
            .map(|(i, _)| i)
            .collect();

        self.selected = 0;
        self.list_scroll = 0;
        self.preview_scroll = 0;
    }

    fn selected_session(&self) -> Option<&Session> {
        self.filtered
            .get(self.selected)
            .map(|&i| &self.sessions[i])
    }

    fn on_char(&mut self, c: char) {
        self.query.push(c);
        self.filter();
    }

    fn on_backspace(&mut self) {
        self.query.pop();
        self.filter();
    }

    fn on_escape(&mut self) {
        if self.query.is_empty() {
            self.should_quit = true;
        } else {
            self.query.clear();
            self.filter();
        }
    }

    fn on_up(&mut self) {
        if !self.filtered.is_empty() {
            self.selected = self.selected.saturating_sub(1);
            self.preview_scroll = 0;
        }
    }

    fn on_down(&mut self) {
        if !self.filtered.is_empty() {
            self.selected = (self.selected + 1).min(self.filtered.len() - 1);
            self.preview_scroll = 0;
        }
    }

    fn on_enter(&mut self) {
        if let Some(session) = self.selected_session() {
            self.should_select = Some(session.clone());
            self.should_quit = true;
        }
    }

    fn toggle_scope(&mut self) {
        self.scope_global = !self.scope_global;
        self.filter();
    }

    fn scope_display(&self) -> String {
        if self.scope_global {
            "everywhere".to_string()
        } else {
            // Show ~/.../<dir> format
            let home = std::env::var("HOME").unwrap_or_default();
            let path = if !home.is_empty() && self.launch_cwd.starts_with(&home) {
                format!("~{}", &self.launch_cwd[home.len()..])
            } else {
                self.launch_cwd.clone()
            };
            if path.len() > 25 {
                let last = std::path::Path::new(&self.launch_cwd)
                    .file_name()
                    .and_then(|s| s.to_str())
                    .unwrap_or("");
                format!("~/.../{}", last)
            } else {
                path
            }
        }
    }

    fn scroll_preview_up(&mut self, lines: usize) {
        self.preview_scroll = self.preview_scroll.saturating_sub(lines);
    }

    fn scroll_preview_down(&mut self, lines: usize) {
        self.preview_scroll = self.preview_scroll.saturating_add(lines);
    }
}

// ============================================================================
// UI Rendering
// ============================================================================

fn render(frame: &mut Frame, app: &mut App) {
    let t = Theme::dark();

    // Full view mode - take over entire screen
    if app.full_view_mode {
        render_full_conversation(frame, app, &t);
        return;
    }

    let area = frame.area();

    // Main layout
    let main_layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3), // Search bar
            Constraint::Length(1), // Spacing
            Constraint::Min(0),    // Content
            Constraint::Length(1), // Spacing
            Constraint::Length(1), // Status bar
        ])
        .split(area);

    // Search bar with margins
    let search_area = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Length(1),
            Constraint::Min(0),
            Constraint::Length(1),
        ])
        .split(main_layout[0]);

    render_search_bar(frame, app, &t, search_area[1]);

    // Content area with padding
    let content_area = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Length(1),
            Constraint::Min(0),
            Constraint::Length(1),
        ])
        .split(main_layout[2]);

    // Split content: 40% list, padding, 60% preview
    let content_layout = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(40),
            Constraint::Length(2),
            Constraint::Percentage(60),
        ])
        .split(content_area[1]);

    render_session_list(frame, app, &t, content_layout[0]);
    render_preview(frame, app, &t, content_layout[2]);

    // Status bar with padding
    let status_area = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Length(1),
            Constraint::Min(0),
            Constraint::Length(1),
        ])
        .split(main_layout[4]);

    render_status_bar(frame, app, &t, status_area[1]);
}

fn render_search_bar(frame: &mut Frame, app: &App, t: &Theme, area: Rect) {
    let scope_label = app.scope_display();
    let scope_width = 3 + 3 + 1 + scope_label.len() + 1;
    let search_width = (area.width as usize).saturating_sub(scope_width + 1);

    let middle_line = if app.query.is_empty() {
        let placeholder = " Search...";
        let padding = search_width.saturating_sub(placeholder.len());
        Line::from(vec![
            Span::styled(placeholder, Style::default().fg(t.placeholder_fg)),
            Span::raw(" ".repeat(padding)),
            Span::raw(" "),
            Span::styled(" │ ", Style::default().fg(t.separator_fg)),
            Span::styled(" / ", Style::default().bg(t.keycap_bg)),
            Span::styled(format!(" {} ", scope_label), Style::default().fg(t.scope_label_fg)),
        ])
    } else {
        let query_len = 1 + app.query.chars().count() + 1;
        let padding = search_width.saturating_sub(query_len);
        Line::from(vec![
            Span::raw(" "),
            Span::raw(&app.query),
            Span::styled("█", Style::default().fg(t.accent)),
            Span::raw(" ".repeat(padding)),
            Span::raw(" "),
            Span::styled(" │ ", Style::default().fg(t.separator_fg)),
            Span::styled(" / ", Style::default().bg(t.keycap_bg)),
            Span::styled(format!(" {} ", scope_label), Style::default().fg(t.scope_label_fg)),
        ])
    };

    let separator_pos = search_width + 1;
    let lines = vec![
        Line::from(vec![
            Span::raw(" ".repeat(separator_pos)),
            Span::styled(" │ ", Style::default().fg(t.separator_fg)),
        ]),
        middle_line,
        Line::from(vec![
            Span::raw(" ".repeat(separator_pos)),
            Span::styled(" │ ", Style::default().fg(t.separator_fg)),
        ]),
    ];

    let paragraph = Paragraph::new(lines).style(Style::default().bg(t.search_bg));
    frame.render_widget(paragraph, area);
}

fn render_session_list(frame: &mut Frame, app: &mut App, t: &Theme, area: Rect) {
    let available_width = area.width.saturating_sub(2) as usize;

    if app.filtered.is_empty() {
        let msg = if app.query.is_empty() {
            "No sessions"
        } else {
            "No results"
        };
        let paragraph = Paragraph::new(Span::styled(msg, Style::default().fg(t.dim_fg)));
        frame.render_widget(paragraph, area);
        return;
    }

    let items: Vec<ListItem> = app
        .filtered
        .iter()
        .enumerate()
        .map(|(i, &idx)| {
            let s = &app.sessions[idx];
            let is_selected = i == app.selected;

            let source_color = if s.agent == "claude" {
                t.claude_source
            } else {
                t.codex_source
            };

            let header_style = if is_selected {
                Style::default().fg(t.selection_header_fg)
            } else {
                Style::default()
            };

            // New format: ● Claude  abc123.. (t)  project  main  11/29 10:30  125L
            let header_spans = vec![
                Span::styled(
                    format!("{} {}  ", s.agent_icon(), s.agent_display()),
                    Style::default().fg(source_color),
                ),
                Span::styled(
                    format!("{}  ", s.session_id_display()),
                    Style::default().fg(t.dim_fg),
                ),
                Span::styled(
                    format!("{}  ", truncate(s.project_name(), 12)),
                    header_style,
                ),
                Span::styled(
                    format!("{}  ", truncate(s.branch_display(), 10)),
                    Style::default().fg(t.accent),
                ),
                Span::styled(
                    format!("{}  ", s.date_display()),
                    Style::default().fg(t.dim_fg),
                ),
                Span::styled(
                    format!("{}L", s.lines),
                    header_style,
                ),
            ];

            // Snippet: show last_msg when no query, highlighted match when searching
            let snippet_style = if is_selected {
                Style::default().fg(t.selection_snippet_fg)
            } else {
                Style::default().fg(t.snippet_fg)
            };
            let highlight_style = Style::default().fg(t.match_fg);

            let snippet_line = if app.query.is_empty() {
                // No query: show last message content
                let snippet = truncate(&s.last_msg_content, available_width);
                Line::from(Span::styled(format!("...{}", snippet), snippet_style))
            } else {
                // With query: find matching text and highlight keywords
                // Search in both first and last message content
                let combined_content = format!(
                    "{} {}",
                    s.first_msg_content, s.last_msg_content
                );
                if let Some(spans) = find_matching_snippet(
                    &combined_content,
                    &app.query,
                    available_width,
                    snippet_style,
                    highlight_style,
                ) {
                    Line::from(spans)
                } else {
                    // Fallback to first_msg if no match found
                    let snippet = truncate(&s.first_msg_content, available_width);
                    Line::from(Span::styled(format!("...{}", snippet), snippet_style))
                }
            };

            let lines = vec![
                Line::from(header_spans),
                snippet_line,
                Line::from(""),
            ];

            if is_selected {
                ListItem::new(lines).style(Style::default().bg(t.selection_bg))
            } else {
                ListItem::new(lines)
            }
        })
        .collect();

    let list = List::new(items);

    // Calculate visible items (3 lines per item)
    let lines_per_item = 3;
    let visible_items = (area.height as usize) / lines_per_item;

    if app.selected < app.list_scroll {
        app.list_scroll = app.selected;
    } else if app.selected >= app.list_scroll + visible_items && visible_items > 0 {
        app.list_scroll = app.selected - visible_items + 1;
    }

    let mut list_state = ListState::default();
    list_state.select(Some(app.selected));
    *list_state.offset_mut() = app.list_scroll;

    frame.render_stateful_widget(list, area, &mut list_state);
}

fn render_preview(frame: &mut Frame, app: &mut App, t: &Theme, area: Rect) {
    let Some(s) = app.selected_session() else {
        return;
    };

    let bubble_width = area.width.saturating_sub(4) as usize;
    let mut lines: Vec<Line> = Vec::new();

    // First message
    if !s.first_msg_content.is_empty() {
        let (label, label_color, bubble_bg) = if s.first_msg_role == "user" {
            ("You", t.user_label, t.user_bubble_bg)
        } else if s.agent == "claude" {
            ("Claude", t.claude_source, t.claude_bubble_bg)
        } else {
            ("Codex", t.codex_source, t.codex_bubble_bg)
        };

        lines.push(Line::from(Span::styled(
            format!(" {}", label),
            Style::default().fg(label_color).add_modifier(Modifier::BOLD),
        )));

        for wrapped in wrap_text(&s.first_msg_content, bubble_width).iter().take(8) {
            let padding = bubble_width.saturating_sub(wrapped.chars().count());
            lines.push(Line::from(vec![
                Span::styled(" ", Style::default().bg(bubble_bg)),
                Span::styled(wrapped.clone(), Style::default().bg(bubble_bg)),
                Span::styled(" ".repeat(padding + 1), Style::default().bg(bubble_bg)),
            ]));
        }

        lines.push(Line::from(""));
    }

    // Last message (if different from first)
    if !s.last_msg_content.is_empty() && s.last_msg_content != s.first_msg_content {
        let (label, label_color, bubble_bg) = if s.last_msg_role == "user" {
            ("You", t.user_label, t.user_bubble_bg)
        } else if s.agent == "claude" {
            ("Claude", t.claude_source, t.claude_bubble_bg)
        } else {
            ("Codex", t.codex_source, t.codex_bubble_bg)
        };

        lines.push(Line::from(Span::styled(
            format!(" {}", label),
            Style::default().fg(label_color).add_modifier(Modifier::BOLD),
        )));

        for wrapped in wrap_text(&s.last_msg_content, bubble_width).iter().take(8) {
            let padding = bubble_width.saturating_sub(wrapped.chars().count());
            lines.push(Line::from(vec![
                Span::styled(" ", Style::default().bg(bubble_bg)),
                Span::styled(wrapped.clone(), Style::default().bg(bubble_bg)),
                Span::styled(" ".repeat(padding + 1), Style::default().bg(bubble_bg)),
            ]));
        }
    }

    // Clamp scroll
    let visible_height = area.height as usize;
    let max_scroll = lines.len().saturating_sub(visible_height.min(lines.len()));
    app.preview_scroll = app.preview_scroll.min(max_scroll);

    let visible_lines: Vec<Line> = lines.into_iter().skip(app.preview_scroll).collect();
    let paragraph = Paragraph::new(visible_lines);
    frame.render_widget(paragraph, area);
}

fn render_status_bar(frame: &mut Frame, app: &App, t: &Theme, area: Rect) {
    let keycap = Style::default().bg(t.keycap_bg);
    let label = Style::default();
    let dim = Style::default().fg(t.dim_fg);
    let filter_active = Style::default().fg(t.match_fg);

    let mut spans: Vec<Span> = Vec::new();

    // Command mode indicator
    if app.command_mode {
        spans.push(Span::styled(" CMD ", Style::default().bg(t.accent).fg(Color::Black)));
        spans.push(Span::styled(" :o orig :s sub :t trim :c cont :a agent :m lines ", label));
    } else {
        // Normal keybindings
        let has_selection = !app.filtered.is_empty();
        spans.extend([
            Span::styled(" ↑↓ ", keycap),
            Span::styled(" nav ", label),
        ]);

        if has_selection {
            spans.extend([
                Span::styled(" │ ", dim),
                Span::styled(" Space ", keycap),
                Span::styled(" view ", label),
                Span::styled(" │ ", dim),
                Span::styled(" Enter ", keycap),
                Span::styled(" open ", label),
            ]);
        }

        spans.extend([
            Span::styled(" │ ", dim),
            Span::styled(" : ", keycap),
            Span::styled(" filter ", label),
            Span::styled(" │ ", dim),
            Span::styled(" Esc ", keycap),
            Span::styled(" quit", label),
        ]);

        // Active filters
        if app.filter_original_only {
            spans.push(Span::styled(" [orig]", filter_active));
        }
        if app.filter_no_sub {
            spans.push(Span::styled(" [-sub]", filter_active));
        }
        if app.filter_no_trim {
            spans.push(Span::styled(" [-trim]", filter_active));
        }
        if app.filter_no_cont {
            spans.push(Span::styled(" [-cont]", filter_active));
        }
        if let Some(ref agent) = app.filter_agent {
            spans.push(Span::styled(format!(" [{}]", agent), filter_active));
        }
        if let Some(min) = app.filter_min_lines {
            spans.push(Span::styled(format!(" [≥{}L]", min), filter_active));
        }
    }

    let hints = Line::from(spans);
    let count = Span::styled(format!(" {} sessions", app.filtered.len()), dim);

    let layout = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Min(0), Constraint::Length(count.width() as u16)])
        .split(area);

    frame.render_widget(Paragraph::new(hints), layout[0]);
    frame.render_widget(Paragraph::new(count), layout[1]);
}

fn render_full_conversation(frame: &mut Frame, app: &mut App, t: &Theme) {
    let area = frame.area();

    // Layout: header (2 lines), content, footer (1 line)
    let layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(2), // Header
            Constraint::Min(0),    // Content
            Constraint::Length(1), // Footer
        ])
        .split(area);

    // Header - session info
    if let Some(s) = app.selected_session() {
        let source_color = if s.agent == "claude" {
            t.claude_source
        } else {
            t.codex_source
        };

        let header = Line::from(vec![
            Span::styled(
                format!(" {} {} ", s.agent_icon(), s.agent_display()),
                Style::default().fg(source_color).add_modifier(Modifier::BOLD),
            ),
            Span::styled(
                format!("{}  ", s.session_id_display()),
                Style::default().fg(t.dim_fg),
            ),
            Span::styled(
                format!("{}  ", s.project_name()),
                Style::default().add_modifier(Modifier::BOLD),
            ),
            Span::styled(
                format!("{}  ", s.branch_display()),
                Style::default().fg(t.accent),
            ),
            Span::styled(
                format!("{}L", s.lines),
                Style::default().fg(t.dim_fg),
            ),
        ]);
        frame.render_widget(Paragraph::new(header), layout[0]);
    }

    // Content - full conversation
    let content_lines: Vec<Line> = app
        .full_content
        .lines()
        .skip(app.full_content_scroll)
        .take(layout[1].height as usize)
        .map(|line| Line::from(line.to_string()))
        .collect();

    // Clamp scroll to content bounds
    let total_lines = app.full_content.lines().count();
    let visible = layout[1].height as usize;
    let max_scroll = total_lines.saturating_sub(visible);
    app.full_content_scroll = app.full_content_scroll.min(max_scroll);

    let content = Paragraph::new(content_lines);
    frame.render_widget(content, layout[1]);

    // Footer - navigation hints
    let keycap = Style::default().bg(t.keycap_bg);
    let label = Style::default();
    let dim = Style::default().fg(t.dim_fg);

    let footer = Line::from(vec![
        Span::styled(" ↑↓/jk ", keycap),
        Span::styled(" scroll ", label),
        Span::styled(" │ ", dim),
        Span::styled(" PgUp/Dn ", keycap),
        Span::styled(" page ", label),
        Span::styled(" │ ", dim),
        Span::styled(" Home/End ", keycap),
        Span::styled(" jump ", label),
        Span::styled(" │ ", dim),
        Span::styled(" Space/Esc/q ", keycap),
        Span::styled(" back", label),
        Span::styled(
            format!("  Line {}/{}", app.full_content_scroll + 1, total_lines),
            dim,
        ),
    ]);
    frame.render_widget(Paragraph::new(footer), layout[2]);
}

// ============================================================================
// Helpers
// ============================================================================

fn truncate(s: &str, max: usize) -> String {
    let chars: Vec<char> = s.chars().collect();
    if chars.len() > max {
        format!("{}…", chars[..max - 1].iter().collect::<String>())
    } else {
        s.to_string()
    }
}

/// Find text containing query keywords and return spans with highlighted matches.
/// If query is empty, returns None. Otherwise returns Some(Vec<Span>) with highlighted keywords.
fn find_matching_snippet<'a>(
    content: &str,
    query: &str,
    max_len: usize,
    normal_style: Style,
    highlight_style: Style,
) -> Option<Vec<Span<'a>>> {
    if query.is_empty() {
        return None;
    }

    let query_lower = query.to_lowercase();
    let keywords: Vec<&str> = query_lower.split_whitespace().collect();
    if keywords.is_empty() {
        return None;
    }

    let content_lower = content.to_lowercase();

    // Find first occurrence of any keyword
    let mut best_pos = None;
    for keyword in &keywords {
        if let Some(pos) = content_lower.find(keyword) {
            match best_pos {
                None => best_pos = Some(pos),
                Some(current) if pos < current => best_pos = Some(pos),
                _ => {}
            }
        }
    }

    let start_pos = best_pos.unwrap_or(0);

    // Extract snippet around the match
    let half_len = max_len / 2;
    let snippet_start = start_pos.saturating_sub(half_len);
    let chars: Vec<char> = content.chars().collect();
    let snippet_end = (snippet_start + max_len).min(chars.len());

    let snippet: String = chars[snippet_start..snippet_end].iter().collect();
    let snippet_lower = snippet.to_lowercase();

    // Build spans with highlighted keywords
    let mut spans: Vec<Span> = Vec::new();
    let mut current_pos = 0;
    let snippet_chars: Vec<char> = snippet.chars().collect();
    let snippet_lower_chars: Vec<char> = snippet_lower.chars().collect();

    // Find all keyword positions in the snippet
    let mut highlights: Vec<(usize, usize)> = Vec::new();
    for keyword in &keywords {
        let kw_chars: Vec<char> = keyword.chars().collect();
        let mut search_pos = 0;
        while search_pos + kw_chars.len() <= snippet_lower_chars.len() {
            let match_found = (0..kw_chars.len())
                .all(|i| snippet_lower_chars[search_pos + i] == kw_chars[i]);
            if match_found {
                highlights.push((search_pos, search_pos + kw_chars.len()));
                search_pos += kw_chars.len();
            } else {
                search_pos += 1;
            }
        }
    }

    // Sort and merge overlapping highlights
    highlights.sort_by_key(|h| h.0);
    let mut merged: Vec<(usize, usize)> = Vec::new();
    for (start, end) in highlights {
        if let Some(last) = merged.last_mut() {
            if start <= last.1 {
                last.1 = last.1.max(end);
                continue;
            }
        }
        merged.push((start, end));
    }

    // Build spans
    if snippet_start > 0 {
        spans.push(Span::styled("...", normal_style));
    }

    for (start, end) in merged {
        // Add normal text before highlight
        if current_pos < start {
            let normal_text: String = snippet_chars[current_pos..start].iter().collect();
            spans.push(Span::styled(normal_text, normal_style));
        }
        // Add highlighted text
        let highlight_text: String = snippet_chars[start..end].iter().collect();
        spans.push(Span::styled(highlight_text, highlight_style));
        current_pos = end;
    }

    // Add remaining normal text
    if current_pos < snippet_chars.len() {
        let remaining: String = snippet_chars[current_pos..].iter().collect();
        spans.push(Span::styled(remaining, normal_style));
    }

    if snippet_end < chars.len() {
        spans.push(Span::styled("...", normal_style));
    }

    Some(spans)
}

fn wrap_text(text: &str, max_width: usize) -> Vec<String> {
    let mut result = Vec::new();
    for line in text.lines() {
        if line.trim().is_empty() {
            result.push(String::new());
            continue;
        }
        let mut current = String::new();
        let mut width = 0;
        for word in line.split_whitespace() {
            let word_len = word.chars().count();
            if width == 0 {
                current = word.to_string();
                width = word_len;
            } else if width + 1 + word_len <= max_width {
                current.push(' ');
                current.push_str(word);
                width += 1 + word_len;
            } else {
                result.push(current);
                current = word.to_string();
                width = word_len;
            }
        }
        if !current.is_empty() {
            result.push(current);
        }
    }
    if result.is_empty() {
        result.push(String::new());
    }
    result
}

fn format_time_ago(modified: &str) -> String {
    let Ok(dt) = DateTime::parse_from_rfc3339(modified)
        .or_else(|_| {
            // Try parsing ISO format without timezone
            chrono::NaiveDateTime::parse_from_str(modified, "%Y-%m-%dT%H:%M:%S%.f")
                .map(|ndt| Utc.from_utc_datetime(&ndt).fixed_offset())
        })
    else {
        return modified.to_string();
    };

    let now = Utc::now();
    let duration = now.signed_duration_since(dt);

    if duration.num_minutes() < 1 {
        "just now".to_string()
    } else if duration.num_minutes() < 60 {
        format!("{}m ago", duration.num_minutes())
    } else if duration.num_hours() < 24 {
        format!("{}h ago", duration.num_hours())
    } else if duration.num_days() < 7 {
        format!("{}d ago", duration.num_days())
    } else if duration.num_weeks() < 4 {
        format!("{}w ago", duration.num_weeks())
    } else {
        dt.format("%b %d").to_string()
    }
}

// ============================================================================
// Index Loading
// ============================================================================

fn load_sessions(index_path: &str, limit: usize) -> Result<Vec<Session>> {
    let mut schema_builder = Schema::builder();
    let session_id_field = schema_builder.add_text_field("session_id", TEXT | STORED);
    let agent_field = schema_builder.add_text_field("agent", TEXT | STORED);
    let project_field = schema_builder.add_text_field("project", TEXT | STORED);
    let branch_field = schema_builder.add_text_field("branch", TEXT | STORED);
    let cwd_field = schema_builder.add_text_field("cwd", TEXT | STORED);
    let created_field = schema_builder.add_text_field("created", TEXT | STORED);
    let modified_field = schema_builder.add_text_field("modified", TEXT | STORED);
    let lines_field = schema_builder.add_i64_field("lines", STORED);
    let export_path_field = schema_builder.add_text_field("export_path", TEXT | STORED);
    let first_msg_role_field = schema_builder.add_text_field("first_msg_role", TEXT | STORED);
    let first_msg_content_field = schema_builder.add_text_field("first_msg_content", TEXT | STORED);
    let last_msg_role_field = schema_builder.add_text_field("last_msg_role", TEXT | STORED);
    let last_msg_content_field = schema_builder.add_text_field("last_msg_content", TEXT | STORED);
    let derivation_type_field = schema_builder.add_text_field("derivation_type", TEXT | STORED);
    let is_sidechain_field = schema_builder.add_text_field("is_sidechain", TEXT | STORED);
    let _content_field = schema_builder.add_text_field("content", TEXT | STORED);
    let _schema = schema_builder.build();

    let index = Index::open_in_dir(index_path)
        .context("Failed to open index. Run 'aichat build-index' first.")?;

    let reader = index
        .reader_builder()
        .reload_policy(ReloadPolicy::OnCommitWithDelay)
        .try_into()
        .context("Failed to create reader")?;

    let searcher = reader.searcher();
    let top_docs = searcher
        .search(&AllQuery, &TopDocs::with_limit(limit * 2))
        .context("Search failed")?;

    let mut sessions = Vec::new();
    for (_score, doc_address) in top_docs {
        let doc: tantivy::TantivyDocument = searcher.doc(doc_address)?;

        let get_text = |field| -> String {
            doc.get_first(field)
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string()
        };

        let lines = doc
            .get_first(lines_field)
            .and_then(|v| v.as_i64())
            .unwrap_or(0);

        let is_sidechain_str = get_text(is_sidechain_field);

        sessions.push(Session {
            session_id: get_text(session_id_field),
            agent: get_text(agent_field),
            project: get_text(project_field),
            branch: get_text(branch_field),
            cwd: get_text(cwd_field),
            created: get_text(created_field),
            modified: get_text(modified_field),
            lines,
            export_path: get_text(export_path_field),
            first_msg_role: get_text(first_msg_role_field),
            first_msg_content: get_text(first_msg_content_field),
            last_msg_role: get_text(last_msg_role_field),
            last_msg_content: get_text(last_msg_content_field),
            derivation_type: get_text(derivation_type_field),
            is_sidechain: is_sidechain_str == "true",
        });
    }

    sessions.sort_by(|a, b| b.modified.cmp(&a.modified));
    sessions.truncate(limit);

    Ok(sessions)
}

// ============================================================================
// Main
// ============================================================================

fn main() -> Result<()> {
    let index_path = dirs::home_dir()
        .context("Could not find home directory")?
        .join(".claude")
        .join("search-index");

    let args: Vec<String> = std::env::args().collect();
    let output_file = args.get(1).map(std::path::PathBuf::from);

    let sessions = load_sessions(index_path.to_str().unwrap(), 500)?;

    if sessions.is_empty() {
        eprintln!("No sessions found. Run 'aichat export-all && aichat build-index' first.");
        return Ok(());
    }

    enable_raw_mode()?;
    let mut stdout = stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let mut app = App::new(sessions);

    loop {
        terminal.draw(|f| render(f, &mut app))?;

        if app.should_quit {
            break;
        }

        while event::poll(Duration::from_millis(0))? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press {
                    // Handle full view mode separately
                    if app.full_view_mode {
                        match key.code {
                            KeyCode::Char(' ') | KeyCode::Esc | KeyCode::Char('q') => {
                                app.full_view_mode = false;
                            }
                            KeyCode::Up | KeyCode::Char('k') => {
                                app.full_content_scroll = app.full_content_scroll.saturating_sub(1);
                            }
                            KeyCode::Down | KeyCode::Char('j') => {
                                app.full_content_scroll = app.full_content_scroll.saturating_add(1);
                            }
                            KeyCode::PageUp => {
                                app.full_content_scroll = app.full_content_scroll.saturating_sub(20);
                            }
                            KeyCode::PageDown => {
                                app.full_content_scroll = app.full_content_scroll.saturating_add(20);
                            }
                            KeyCode::Home => {
                                app.full_content_scroll = 0;
                            }
                            KeyCode::End => {
                                let lines = app.full_content.lines().count();
                                app.full_content_scroll = lines.saturating_sub(20);
                            }
                            KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                                app.should_quit = true;
                            }
                            _ => {}
                        }
                    } else if app.command_mode {
                        // Handle command mode (: prefix)
                        app.command_mode = false;
                        match key.code {
                            KeyCode::Char('o') => {
                                app.filter_original_only = !app.filter_original_only;
                                app.filter();
                            }
                            KeyCode::Char('s') => {
                                app.filter_no_sub = !app.filter_no_sub;
                                app.filter();
                            }
                            KeyCode::Char('t') => {
                                app.filter_no_trim = !app.filter_no_trim;
                                app.filter();
                            }
                            KeyCode::Char('c') => {
                                app.filter_no_cont = !app.filter_no_cont;
                                app.filter();
                            }
                            KeyCode::Char('a') => {
                                app.filter_agent = match &app.filter_agent {
                                    None => Some("claude".to_string()),
                                    Some(a) if a == "claude" => Some("codex".to_string()),
                                    Some(_) => None,
                                };
                                app.filter();
                            }
                            KeyCode::Char('m') => {
                                app.filter_min_lines = match app.filter_min_lines {
                                    None => Some(10),
                                    Some(10) => Some(50),
                                    Some(50) => Some(100),
                                    _ => None,
                                };
                                app.filter();
                            }
                            KeyCode::Esc => {} // Just exit command mode
                            _ => {}
                        }
                    } else {
                        // Normal mode
                        match key.code {
                            KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                                app.should_quit = true;
                            }
                            KeyCode::Char(':') => {
                                app.command_mode = true;
                            }
                            KeyCode::Char(' ') => {
                                // Enter full view mode
                                if let Some(session) = app.selected_session() {
                                    app.full_content = std::fs::read_to_string(&session.export_path)
                                        .unwrap_or_else(|_| "Error loading content".to_string());
                                    app.full_content_scroll = 0;
                                    app.full_view_mode = true;
                                }
                            }
                            KeyCode::Esc => app.on_escape(),
                            KeyCode::Enter => app.on_enter(),
                            KeyCode::Up => app.on_up(),
                            KeyCode::Down => app.on_down(),
                            KeyCode::PageUp => app.scroll_preview_up(10),
                            KeyCode::PageDown => app.scroll_preview_down(10),
                            KeyCode::Backspace => app.on_backspace(),
                            KeyCode::Char('/') => app.toggle_scope(),
                            KeyCode::Char(c) => app.on_char(c),
                            _ => {}
                        }
                    }
                }
            }
        }

        std::thread::sleep(Duration::from_millis(16));
    }

    disable_raw_mode()?;
    execute!(io::stdout(), LeaveAlternateScreen)?;

    if let Some(session) = app.should_select {
        let json = serde_json::to_string(&session)?;
        if let Some(out_path) = output_file {
            std::fs::write(&out_path, &json)?;
        } else {
            println!("{}", json);
        }
    }

    Ok(())
}
