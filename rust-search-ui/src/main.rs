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

    /// Session ID display with annotations: abc123.. (t) (c) (s)
    /// For Codex, extracts UUID (last 36 chars) from session_id
    fn session_id_display(&self) -> String {
        // UUIDs are always 36 characters (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
        // For Codex, extract last 36 chars which is the UUID
        let clean_id = if self.agent == "codex" && self.session_id.len() >= 36 {
            &self.session_id[self.session_id.len() - 36..]
        } else {
            &self.session_id
        };

        let id_prefix = if clean_id.len() >= 8 {
            &clean_id[..8]
        } else {
            clean_id
        };
        let mut display = format!("{}..", id_prefix);

        if self.derivation_type == "trimmed" {
            display.push_str(" (t)");
        } else if self.derivation_type == "continued" {
            display.push_str(" (c)");
        }
        if self.is_sidechain {
            display.push_str(" (s)");
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
                // Ensure earlier date comes first (handle data inconsistencies)
                let (earlier, later) = if created <= modified {
                    (created, modified)
                } else {
                    (modified, created)
                };

                // Check if same day
                if earlier.format("%m/%d").to_string() == later.format("%m/%d").to_string() {
                    // Same day: just show "11/29 15:23" (use the later/modified timestamp)
                    later.format("%m/%d %H:%M").to_string()
                } else {
                    // Different days: show range "11/27 - 11/29 15:23"
                    // Earlier date without time, later date with time
                    format!(
                        "{} - {}",
                        earlier.format("%m/%d"),
                        later.format("%m/%d %H:%M")
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

    // Filter state - inclusion-based (true = include this type)
    include_original: bool,   // true by default - include original sessions
    include_sub: bool,        // false by default - exclude sub-agents
    include_trimmed: bool,    // true by default - include trimmed sessions
    include_continued: bool,  // true by default - include continued sessions
    filter_agent: Option<String>, // None = all, Some("claude"), Some("codex")
    filter_min_lines: Option<i64>,
    filter_after_date: Option<String>,  // YYYYMMDD - modified date must be >= this
    filter_before_date: Option<String>, // YYYYMMDD - modified date must be <= this

    // Command mode (: prefix)
    command_mode: bool,

    // Full conversation view
    full_view_mode: bool,
    full_content: String,
    full_content_scroll: usize,

    // View mode search (/pattern like less)
    view_search_mode: bool,      // Entering search pattern
    view_search_pattern: String, // Current search pattern
    view_search_matches: Vec<usize>, // Line numbers with matches
    view_search_current: usize,  // Current match index

    // Jump mode (num+Enter)
    jump_input: String,

    // Input mode for :m and :a
    input_mode: Option<InputMode>,
    input_buffer: String,

    // Action mode for Enter (view/actions)
    action_mode: Option<ActionMode>,

    // Filter modal
    filter_modal_open: bool,
    filter_modal_selected: usize,
}

#[derive(Clone, PartialEq)]
enum InputMode {
    MinLines,   // :m - waiting for number
    Agent,      // :a - waiting for 1 or 2
    JumpToLine, // C-g - waiting for line number
    AfterDate,  // :> - waiting for date
    BeforeDate, // :< - waiting for date
}

#[derive(Clone, PartialEq)]
enum ActionMode {
    ViewOrActions,  // User pressed Enter, choosing between view (1) or actions (2)
}

#[derive(Clone, PartialEq)]
enum FilterMenuItem {
    ClearAll,
    IncludeOriginal,
    IncludeSub,
    IncludeTrimmed,
    IncludeContinued,
    AgentAll,
    AgentClaude,
    AgentCodex,
    MinLines,
    AfterDate,
    BeforeDate,
}

impl FilterMenuItem {
    fn all() -> Vec<FilterMenuItem> {
        vec![
            FilterMenuItem::ClearAll,
            FilterMenuItem::IncludeOriginal,
            FilterMenuItem::IncludeSub,
            FilterMenuItem::IncludeTrimmed,
            FilterMenuItem::IncludeContinued,
            FilterMenuItem::AgentAll,
            FilterMenuItem::AgentClaude,
            FilterMenuItem::AgentCodex,
            FilterMenuItem::MinLines,
            FilterMenuItem::AfterDate,
            FilterMenuItem::BeforeDate,
        ]
    }

    fn label(&self) -> &str {
        match self {
            FilterMenuItem::ClearAll => "(x) Reset to defaults",
            FilterMenuItem::IncludeOriginal => "(o) Include original sessions",
            FilterMenuItem::IncludeSub => "(s) Include sub-agent sessions",
            FilterMenuItem::IncludeTrimmed => "(t) Include trimmed sessions",
            FilterMenuItem::IncludeContinued => "(c) Include continued sessions",
            FilterMenuItem::AgentAll => "(a) All agents",
            FilterMenuItem::AgentClaude => "(d) Claude only",
            FilterMenuItem::AgentCodex => "(e) Codex only",
            FilterMenuItem::MinLines => "(l) Minimum lines",
            FilterMenuItem::AfterDate => "(>) After date",
            FilterMenuItem::BeforeDate => "(<) Before date",
        }
    }

    fn shortcut(&self) -> char {
        match self {
            FilterMenuItem::ClearAll => 'x',
            FilterMenuItem::IncludeOriginal => 'o',
            FilterMenuItem::IncludeSub => 's',
            FilterMenuItem::IncludeTrimmed => 't',
            FilterMenuItem::IncludeContinued => 'c',
            FilterMenuItem::AgentAll => 'a',
            FilterMenuItem::AgentClaude => 'd',
            FilterMenuItem::AgentCodex => 'e',
            FilterMenuItem::MinLines => 'l',
            FilterMenuItem::AfterDate => '>',
            FilterMenuItem::BeforeDate => '<',
        }
    }
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
            include_original: true,   // Include original by default
            include_sub: false,       // Exclude sub-agents by default
            include_trimmed: true,    // Include trimmed by default
            include_continued: true,  // Include continued by default
            filter_agent: None,
            filter_min_lines: None,
            filter_after_date: None,
            filter_before_date: None,
            // Command mode
            command_mode: false,
            // Full view mode
            full_view_mode: false,
            full_content: String::new(),
            full_content_scroll: 0,
            // View mode search
            view_search_mode: false,
            view_search_pattern: String::new(),
            view_search_matches: Vec::new(),
            view_search_current: 0,
            // Jump mode
            jump_input: String::new(),
            // Input mode
            input_mode: None,
            input_buffer: String::new(),
            // Action mode
            action_mode: None,
            // Filter modal
            filter_modal_open: false,
            filter_modal_selected: 0,
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

                // Inclusion-based filtering: check if session type is included

                // Sub-agent sessions are handled separately from derivation type
                if s.is_sidechain {
                    // Sub-agent: include only if include_sub is true
                    // (derivation type filter does NOT apply to sub-agents)
                    if !self.include_sub {
                        return false;
                    }
                } else {
                    // Non-sub-agent: apply derivation type filter
                    let derivation_included = match s.derivation_type.as_str() {
                        "" => self.include_original,           // Original session
                        "trimmed" => self.include_trimmed,     // Trimmed session
                        "continued" => self.include_continued, // Continued session
                        _ => true, // Unknown type, include by default
                    };
                    if !derivation_included {
                        return false;
                    }
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

                // Date filters (applied to modified date)
                if let Some(ref after_date) = self.filter_after_date {
                    if let Some(session_date) = extract_date_for_comparison(&s.modified) {
                        if session_date < *after_date {
                            return false;
                        }
                    }
                }
                if let Some(ref before_date) = self.filter_before_date {
                    if let Some(session_date) = extract_date_for_comparison(&s.modified) {
                        if session_date > *before_date {
                            return false;
                        }
                    }
                }

                // Query filter - split into keywords, ALL must match (across any field)
                if query_lower.is_empty() {
                    return true;
                }

                // Split query into keywords
                let keywords: Vec<&str> = query_lower.split_whitespace().collect();
                if keywords.is_empty() {
                    return true;
                }

                // Build combined searchable text
                let searchable = format!(
                    "{} {} {} {}",
                    s.project.to_lowercase(),
                    s.first_msg_content.to_lowercase(),
                    s.last_msg_content.to_lowercase(),
                    s.session_id.to_lowercase()
                );

                // ALL keywords must be found somewhere in the searchable text
                keywords.iter().all(|kw| searchable.contains(kw))
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

    fn page_up(&mut self, lines: usize) {
        if !self.filtered.is_empty() {
            self.selected = self.selected.saturating_sub(lines);
            self.preview_scroll = 0;
        }
    }

    fn page_down(&mut self, lines: usize) {
        if !self.filtered.is_empty() {
            self.selected = (self.selected + lines).min(self.filtered.len() - 1);
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

    fn jump_to_row(&mut self, row: usize) {
        if row > 0 && row <= self.filtered.len() {
            self.selected = row - 1; // Convert 1-indexed to 0-indexed
            self.preview_scroll = 0;
        }
        self.jump_input.clear();
    }

    fn process_jump_enter(&mut self) {
        if let Ok(row) = self.jump_input.parse::<usize>() {
            self.jump_to_row(row);
        }
        self.jump_input.clear();
    }

    /// Check if any filtered session has annotations (c/t/sub)
    fn has_annotations(&self) -> bool {
        self.filtered.iter().any(|&idx| {
            let s = &self.sessions[idx];
            !s.derivation_type.is_empty() || s.is_sidechain
        })
    }

    /// Update search matches for view mode search
    fn update_view_search_matches(&mut self) {
        self.view_search_matches.clear();
        self.view_search_current = 0;

        if self.view_search_pattern.is_empty() {
            return;
        }

        let pattern_lower = self.view_search_pattern.to_lowercase();
        for (i, line) in self.full_content.lines().enumerate() {
            if line.to_lowercase().contains(&pattern_lower) {
                self.view_search_matches.push(i);
            }
        }
    }

    /// Jump to next search match in view mode
    fn view_search_next(&mut self) {
        if self.view_search_matches.is_empty() {
            return;
        }

        // Move to next match index (wrap around if at end)
        self.view_search_current = (self.view_search_current + 1) % self.view_search_matches.len();
        self.full_content_scroll = self.view_search_matches[self.view_search_current];
    }

    /// Jump to previous search match in view mode
    fn view_search_prev(&mut self) {
        if self.view_search_matches.is_empty() {
            return;
        }

        // Move to previous match index (wrap around if at beginning)
        if self.view_search_current == 0 {
            self.view_search_current = self.view_search_matches.len() - 1;
        } else {
            self.view_search_current -= 1;
        }
        self.full_content_scroll = self.view_search_matches[self.view_search_current];
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

    // Status bar height: 1 for main, +1 for annotation legend if annotations exist
    let show_legend = app.has_annotations();
    let status_height = if show_legend { 2 } else { 1 };

    // Main layout
    let main_layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),            // Search bar
            Constraint::Length(1),            // Spacing
            Constraint::Min(0),               // Content
            Constraint::Length(1),            // Spacing
            Constraint::Length(status_height), // Status bar (+ legend if annotations)
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

    // Split content: 70% list, padding, 30% preview
    let content_layout = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(70),
            Constraint::Length(2),
            Constraint::Percentage(30),
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

    render_status_bar(frame, app, &t, status_area[1], show_legend);

    // Filter modal overlay
    if app.filter_modal_open {
        render_filter_modal(frame, app, &t, area);
    }

    // View/Actions modal overlay
    if matches!(app.action_mode, Some(ActionMode::ViewOrActions)) {
        render_view_actions_modal(frame, &t, area);
    }
}

fn render_view_actions_modal(frame: &mut Frame, t: &Theme, area: Rect) {
    use ratatui::widgets::{Block, Borders, Clear};

    // Center the modal
    let modal_width = 60u16;
    let modal_height = 7u16; // 3 options + 2 border + 2 padding
    let x = (area.width.saturating_sub(modal_width)) / 2;
    let y = (area.height.saturating_sub(modal_height)) / 2;
    let modal_area = Rect::new(x, y, modal_width, modal_height);

    // Clear the area behind the modal
    frame.render_widget(Clear, modal_area);

    // Modal border
    let block = Block::default()
        .title(" Session ")
        .borders(Borders::ALL)
        .style(Style::default().bg(t.search_bg));
    frame.render_widget(block, modal_area);

    // Inner content area
    let inner = Rect::new(x + 2, y + 1, modal_width - 4, modal_height - 2);

    let keycap = Style::default().bg(t.keycap_bg);
    let label = Style::default();
    let dim = Style::default().fg(t.dim_fg);

    let lines = vec![
        Line::from(vec![
            Span::styled(" (v) ", keycap),
            Span::styled(" view full session", label),
        ]),
        Line::from(vec![
            Span::styled(" (a) ", keycap),
            Span::styled(" actions ", label),
            Span::styled("(session operations/info, trim, resume, transfer context...)", dim),
        ]),
        Line::from(vec![
            Span::styled(" Esc ", keycap),
            Span::styled(" cancel and return", label),
        ]),
    ];

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}

fn render_filter_modal(frame: &mut Frame, app: &App, t: &Theme, area: Rect) {
    use ratatui::widgets::{Block, Borders, Clear};

    // Center the modal
    let modal_width = 42u16;
    let modal_height = 13u16; // 9 items + 2 border + 2 padding
    let x = (area.width.saturating_sub(modal_width)) / 2;
    let y = (area.height.saturating_sub(modal_height)) / 2;
    let modal_area = Rect::new(x, y, modal_width, modal_height);

    // Clear the area behind the modal
    frame.render_widget(Clear, modal_area);

    // Modal border
    let block = Block::default()
        .title(" Filters (|) ")
        .borders(Borders::ALL)
        .style(Style::default().bg(t.search_bg));
    frame.render_widget(block, modal_area);

    // Inner content area
    let inner = Rect::new(x + 2, y + 1, modal_width - 4, modal_height - 2);

    let items = FilterMenuItem::all();
    let mut lines: Vec<Line> = Vec::new();

    for (i, item) in items.iter().enumerate() {
        let is_selected = i == app.filter_modal_selected;

        // Show current state for toggleable filters
        let state_indicator = match item {
            FilterMenuItem::ClearAll => "".to_string(),
            FilterMenuItem::IncludeOriginal => if app.include_original { " [ON]" } else { " [off]" }.to_string(),
            FilterMenuItem::IncludeSub => if app.include_sub { " [ON]" } else { " [off]" }.to_string(),
            FilterMenuItem::IncludeTrimmed => if app.include_trimmed { " [ON]" } else { " [off]" }.to_string(),
            FilterMenuItem::IncludeContinued => if app.include_continued { " [ON]" } else { " [off]" }.to_string(),
            FilterMenuItem::AgentAll => if app.filter_agent.is_none() { " ●" } else { " ○" }.to_string(),
            FilterMenuItem::AgentClaude => if app.filter_agent.as_deref() == Some("claude") { " ●" } else { " ○" }.to_string(),
            FilterMenuItem::AgentCodex => if app.filter_agent.as_deref() == Some("codex") { " ●" } else { " ○" }.to_string(),
            FilterMenuItem::MinLines => match app.filter_min_lines {
                Some(n) => format!(" [≥{}]", n),
                None => " [Any]".to_string(),
            },
            FilterMenuItem::AfterDate => match &app.filter_after_date {
                Some(d) => format!(" [>{}]", d),
                None => " [None]".to_string(),
            },
            FilterMenuItem::BeforeDate => match &app.filter_before_date {
                Some(d) => format!(" [<{}]", d),
                None => " [None]".to_string(),
            },
        };

        let style = if is_selected {
            Style::default().bg(t.selection_bg).fg(t.selection_header_fg)
        } else {
            Style::default()
        };

        let prefix = if is_selected { "▶ " } else { "  " };
        lines.push(Line::from(vec![
            Span::styled(prefix, style),
            Span::styled(item.label(), style),
            Span::styled(state_indicator, Style::default().fg(t.match_fg)),
        ]));
    }

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}

fn render_search_bar(frame: &mut Frame, app: &App, t: &Theme, area: Rect) {
    // Layout: [search...] [N sessions] / ~/path/to/dir
    // Give more space to directory path by making search box smaller
    let scope_label = app.scope_display();
    let session_count = format!("{} sessions", app.filtered.len());

    // Right side: " | N | / path "
    // Calculate widths: separator(3) + count + separator(3) + keycap(3) + scope + padding(2)
    let right_side_width = 3 + session_count.len() + 3 + 3 + scope_label.len() + 2;
    // Make search box smaller to give more space to directory path
    let search_width = (area.width as usize).saturating_sub(right_side_width + 12);

    let middle_line = if app.query.is_empty() {
        let placeholder = " Search...";
        let padding = search_width.saturating_sub(placeholder.len());
        Line::from(vec![
            Span::styled(placeholder, Style::default().fg(t.placeholder_fg)),
            Span::raw(" ".repeat(padding)),
            Span::styled(" │ ", Style::default().fg(t.separator_fg)),
            Span::styled(&session_count, Style::default().fg(t.dim_fg)),
            Span::styled(" │ ", Style::default().fg(t.separator_fg)),
            Span::styled(" / ", Style::default().bg(t.keycap_bg)),
            Span::styled(format!(" {}", scope_label), Style::default().fg(t.scope_label_fg)),
        ])
    } else {
        let query_len = 1 + app.query.chars().count() + 1;
        let padding = search_width.saturating_sub(query_len);
        Line::from(vec![
            Span::raw(" "),
            Span::raw(&app.query),
            Span::styled("█", Style::default().fg(t.accent)),
            Span::raw(" ".repeat(padding)),
            Span::styled(" │ ", Style::default().fg(t.separator_fg)),
            Span::styled(&session_count, Style::default().fg(t.dim_fg)),
            Span::styled(" │ ", Style::default().fg(t.separator_fg)),
            Span::styled(" / ", Style::default().bg(t.keycap_bg)),
            Span::styled(format!(" {}", scope_label), Style::default().fg(t.scope_label_fg)),
        ])
    };

    let separator_pos = search_width;
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

    // Calculate field widths based on max values
    let row_num_width = app.filtered.len().to_string().len().max(2);
    let sep = " | ";

    // Calculate max widths for each field - no artificial caps, show full names
    let mut max_session_id_len = 0usize;
    let mut max_project_len = 0usize;
    let mut max_branch_len = 0usize;
    let mut max_lines_len = 0usize;
    let mut max_date_len = 0usize;
    for &idx in &app.filtered {
        let s = &app.sessions[idx];
        max_session_id_len = max_session_id_len.max(s.session_id_display().len());
        max_project_len = max_project_len.max(s.project_name().len());
        max_branch_len = max_branch_len.max(s.branch_display().len());
        max_lines_len = max_lines_len.max(format!("{}L", s.lines).len());
        max_date_len = max_date_len.max(s.date_display().len());
    }
    // Ensure minimums and reasonable maximums for very long names
    // Session ID: "abcd1234.." (10) + " (c)" (4) or " (t)" (4) or " (s)" (4) = max ~14
    max_session_id_len = max_session_id_len.max(10).min(20);
    max_project_len = max_project_len.max(10).min(40);  // Increased from 30 to 40
    max_branch_len = max_branch_len.max(8).min(35);     // Increased from 25 to 35
    max_lines_len = max_lines_len.max(4);
    max_date_len = max_date_len.max(11); // "MM/DD HH:MM" is 11 chars

    let items: Vec<ListItem> = app
        .filtered
        .iter()
        .enumerate()
        .map(|(i, &idx)| {
            let s = &app.sessions[idx];
            let is_selected = i == app.selected;
            let row_num = i + 1; // 1-indexed

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

            let sep_style = Style::default().fg(t.separator_fg);

            // Agent icon + abbreviation
            let (agent_icon, agent_abbrev) = if s.agent == "claude" {
                ("●", "CLD")
            } else {
                ("■", "CDX")
            };

            // Format: row# [icon Agent] session_id | project | branch | lines | date
            let row_num_str = format!("{:>width$}", row_num, width = row_num_width);
            let session_display = format!("{:<width$}", s.session_id_display(), width = max_session_id_len);
            let project_padded = format!("{:<width$}", truncate(s.project_name(), max_project_len), width = max_project_len);
            let branch_padded = format!("{:<width$}", truncate(s.branch_display(), max_branch_len), width = max_branch_len);
            let lines_str = format!("{:>width$}", format!("{}L", s.lines), width = max_lines_len);

            // Right-align date so single dates appear on the right, ranges extend left
            let date_str = format!("{:>width$}", s.date_display(), width = max_date_len);

            let header_spans = vec![
                Span::styled(format!("{} ", row_num_str), Style::default().fg(t.dim_fg)),
                Span::styled(format!("{} {} ", agent_icon, agent_abbrev), Style::default().fg(source_color)),
                Span::styled(session_display, Style::default().fg(t.dim_fg)),
                Span::styled(sep, sep_style),
                Span::styled(project_padded, header_style),
                Span::styled(sep, sep_style),
                Span::styled(branch_padded, Style::default().fg(t.accent)),
                Span::styled(sep, sep_style),
                Span::styled(lines_str, header_style),
                Span::styled(sep, sep_style),
                Span::styled(date_str, Style::default().fg(t.dim_fg)),
            ];

            // Snippet: show last_msg when no query, highlighted match when searching
            let snippet_style = if is_selected {
                Style::default().fg(t.selection_snippet_fg)
            } else {
                Style::default().fg(t.snippet_fg)
            };
            let highlight_style = Style::default().fg(t.match_fg);

            // Indent snippet to align with content (after row number)
            let indent = " ".repeat(row_num_width + 1);
            let snippet_width = available_width.saturating_sub(row_num_width + 1);

            let snippet_line = if app.query.is_empty() {
                // No query: show last message content
                let snippet = truncate(&s.last_msg_content, snippet_width);
                Line::from(Span::styled(format!("{}...{}", indent, snippet), snippet_style))
            } else {
                // With query: find matching text and highlight keywords
                let combined_content = format!("{} {}", s.first_msg_content, s.last_msg_content);
                if let Some(mut spans) = find_matching_snippet(
                    &combined_content,
                    &app.query,
                    snippet_width,
                    snippet_style,
                    highlight_style,
                ) {
                    // Prepend indent
                    spans.insert(0, Span::styled(indent, snippet_style));
                    Line::from(spans)
                } else {
                    let snippet = truncate(&s.first_msg_content, snippet_width);
                    Line::from(Span::styled(format!("{}...{}", indent, snippet), snippet_style))
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

    // First message - labeled as "FIRST MESSAGE"
    if !s.first_msg_content.is_empty() {
        let (role_label, label_color, bubble_bg) = if s.first_msg_role == "user" {
            ("User", t.user_label, t.user_bubble_bg)
        } else if s.agent == "claude" {
            ("Claude", t.claude_source, t.claude_bubble_bg)
        } else {
            ("Codex", t.codex_source, t.codex_bubble_bg)
        };

        lines.push(Line::from(vec![
            Span::styled(" ── FIRST ── ", Style::default().fg(t.dim_fg)),
            Span::styled(role_label, Style::default().fg(label_color).add_modifier(Modifier::BOLD)),
        ]));

        for wrapped in wrap_text(&s.first_msg_content, bubble_width).iter().take(6) {
            let padding = bubble_width.saturating_sub(wrapped.chars().count());
            lines.push(Line::from(vec![
                Span::styled(" ", Style::default().bg(bubble_bg)),
                Span::styled(wrapped.clone(), Style::default().bg(bubble_bg)),
                Span::styled(" ".repeat(padding + 1), Style::default().bg(bubble_bg)),
            ]));
        }

        lines.push(Line::from(""));
    }

    // Last message - labeled as "LAST MESSAGE" (if different from first)
    if !s.last_msg_content.is_empty() && s.last_msg_content != s.first_msg_content {
        let (role_label, label_color, bubble_bg) = if s.last_msg_role == "user" {
            ("User", t.user_label, t.user_bubble_bg)
        } else if s.agent == "claude" {
            ("Claude", t.claude_source, t.claude_bubble_bg)
        } else {
            ("Codex", t.codex_source, t.codex_bubble_bg)
        };

        lines.push(Line::from(vec![
            Span::styled(" ── LAST ── ", Style::default().fg(t.dim_fg)),
            Span::styled(role_label, Style::default().fg(label_color).add_modifier(Modifier::BOLD)),
        ]));

        for wrapped in wrap_text(&s.last_msg_content, bubble_width).iter().take(6) {
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

fn render_status_bar(frame: &mut Frame, app: &App, t: &Theme, area: Rect, show_legend: bool) {
    // Check if we have any active filters (need second row for legend or filters)
    let has_filters = !app.include_original
        || app.include_sub
        || !app.include_trimmed
        || !app.include_continued
        || app.filter_agent.is_some()
        || app.filter_min_lines.is_some()
        || app.filter_after_date.is_some()
        || app.filter_before_date.is_some();

    let needs_second_row = show_legend || has_filters;

    // Split area into main status bar and optional second line (legend + filters)
    let status_layout = if needs_second_row {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(1), Constraint::Length(1)])
            .split(area)
    } else {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(1)])
            .split(area)
    };

    let main_area = status_layout[0];

    let keycap = Style::default().bg(t.keycap_bg);
    let label = Style::default();
    let dim = Style::default().fg(t.dim_fg);
    let filter_active = Style::default().fg(t.match_fg);

    let mut spans: Vec<Span> = Vec::new();

    // Note: action_mode (ViewOrActions) renders its own modal overlay, no status bar indicator needed

    if let Some(ref mode) = app.input_mode {
        // Input mode indicator
        let prompt = match mode {
            InputMode::MinLines => format!(" Min lines: {}█ ", app.input_buffer),
            InputMode::Agent => " Agent: 1=Claude 2=Codex 0=All ".to_string(),
            InputMode::JumpToLine => format!(" Go to row: {}█ ", app.input_buffer),
            InputMode::AfterDate => format!(" After date: {}█ (any format) ", app.input_buffer),
            InputMode::BeforeDate => format!(" Before date: {}█ (any format) ", app.input_buffer),
        };
        spans.push(Span::styled(prompt, Style::default().bg(t.accent).fg(Color::Black)));
    } else if app.command_mode {
        // Command mode indicator
        spans.push(Span::styled(" CMD ", Style::default().bg(t.accent).fg(Color::Black)));
        spans.push(Span::styled(" :x clear :o orig :s sub :t trim :c cont :a agent :m lines :> after :< before ", label));
    } else {
        // Normal keybindings - ordered: nav, page, home/end, C-g goto, Enter, /, C-f, Esc
        let has_selection = !app.filtered.is_empty();

        // nav, page
        spans.extend([
            Span::styled(" ↑↓ ", keycap),
            Span::styled(" nav ", label),
            Span::styled(" │ ", dim),
            Span::styled(" PgUp/Dn ", keycap),
            Span::styled(" page ", label),
        ]);

        if has_selection {
            // home/end jump, C-g goto, Enter view/actions
            spans.extend([
                Span::styled(" │ ", dim),
                Span::styled(" Home/End ", keycap),
                Span::styled(" jump ", label),
                Span::styled(" │ ", dim),
                Span::styled(" C-g ", keycap),
                Span::styled(" goto ", label),
                Span::styled(" │ ", dim),
                Span::styled(" Enter ", keycap),
                Span::styled(" view/actions ", label),
            ]);
        }

        // / scope toggle
        let scope_indicator = if app.scope_global { "global" } else { "local" };
        spans.extend([
            Span::styled(" │ ", dim),
            Span::styled(" / ", keycap),
            Span::styled(format!(" {} ", scope_indicator), label),
        ]);

        // C-f filter, Esc quit
        spans.extend([
            Span::styled(" │ ", dim),
            Span::styled(" C-f ", keycap),
            Span::styled(" filter ", label),
            Span::styled(" │ ", dim),
            Span::styled(" Esc ", keycap),
            Span::styled(" quit", label),
        ]);
    }

    let hints = Line::from(spans);
    frame.render_widget(Paragraph::new(hints), main_area);

    // Second row: annotation legend (if needed) + active filter indicators (always)
    let mut row2_spans: Vec<Span> = Vec::new();

    // Annotation legend (if annotations exist in results)
    if show_legend {
        row2_spans.extend([
            Span::styled("  ", dim),
            Span::styled("(c)", Style::default().fg(t.dim_fg)),
            Span::styled(" continued  ", dim),
            Span::styled("(t)", Style::default().fg(t.dim_fg)),
            Span::styled(" trimmed  ", dim),
            Span::styled("(s)", Style::default().fg(t.dim_fg)),
            Span::styled(" sub-agent", dim),
        ]);
    }

    // Active filters (always show on second row when non-default)
    if !app.include_original {
        row2_spans.push(Span::styled(" [-orig]", filter_active));
    }
    if app.include_sub {
        row2_spans.push(Span::styled(" [+sub]", filter_active));
    }
    if !app.include_trimmed {
        row2_spans.push(Span::styled(" [-trim]", filter_active));
    }
    if !app.include_continued {
        row2_spans.push(Span::styled(" [-cont]", filter_active));
    }
    if let Some(ref agent) = app.filter_agent {
        row2_spans.push(Span::styled(format!(" [{}]", agent), filter_active));
    }
    if let Some(min) = app.filter_min_lines {
        row2_spans.push(Span::styled(format!(" [≥{}L]", min), filter_active));
    }
    if let Some(ref date) = app.filter_after_date {
        row2_spans.push(Span::styled(format!(" [>{}]", date), filter_active));
    }
    if let Some(ref date) = app.filter_before_date {
        row2_spans.push(Span::styled(format!(" [<{}]", date), filter_active));
    }

    // Render second row if we have legend or filters
    if needs_second_row {
        let row2 = Paragraph::new(Line::from(row2_spans));
        frame.render_widget(row2, status_layout[1]);
    }
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

    // Determine agent label (with icon) and colors for assistant messages
    let (agent_label, assistant_bg, assistant_fg) = if let Some(s) = app.selected_session() {
        if s.agent == "claude" {
            ("● Claude", t.claude_bubble_bg, t.claude_source)
        } else {
            ("■ Codex", t.codex_bubble_bg, t.codex_source)
        }
    } else {
        ("● Assistant", t.claude_bubble_bg, t.claude_source)
    };

    let content_width = layout[1].width.saturating_sub(2) as usize;

    // Search highlighting style - yellow background
    let search_pattern = &app.view_search_pattern;
    let search_highlight = Style::default().bg(Color::Yellow).fg(Color::Black);

    // Content - full conversation with styled messages
    // Track current message context for continuation lines
    #[derive(Clone, Copy, PartialEq)]
    enum MsgContext { None, User, Assistant }
    let mut context = MsgContext::None;

    let content_lines: Vec<Line> = app
        .full_content
        .lines()
        .map(|line| {
            if line.starts_with("> ") {
                // User message - skip "> " (2 chars)
                context = MsgContext::User;
                let msg_content: String = line.chars().skip(2).collect();
                let used = 6 + 1 + msg_content.chars().count(); // " User " + " " + content
                let padding = content_width.saturating_sub(used);
                let base_style = Style::default().bg(t.user_bubble_bg);
                let mut spans = vec![
                    Span::styled(" User ", Style::default().fg(t.user_label).add_modifier(Modifier::BOLD)),
                    Span::styled(" ", base_style),
                ];
                spans.extend(highlight_search_in_text(&msg_content, search_pattern, base_style, search_highlight));
                spans.push(Span::styled(" ".repeat(padding), base_style));
                Line::from(spans)
            } else if line.starts_with("⏺ ") {
                // Assistant message - ⏺ is 3 bytes + space = 4 bytes
                context = MsgContext::Assistant;
                let msg_content: String = line.chars().skip(2).collect(); // Skip icon + space
                let label_with_space = format!(" {} ", agent_label);
                let used = label_with_space.chars().count() + 1 + msg_content.chars().count();
                let padding = content_width.saturating_sub(used);
                let base_style = Style::default().bg(assistant_bg);
                let mut spans = vec![
                    Span::styled(label_with_space, Style::default().fg(assistant_fg).add_modifier(Modifier::BOLD)),
                    Span::styled(" ", base_style),
                ];
                spans.extend(highlight_search_in_text(&msg_content, search_pattern, base_style, search_highlight));
                spans.push(Span::styled(" ".repeat(padding), base_style));
                Line::from(spans)
            } else if line.starts_with("  ⎿") {
                // Tool result - style as dimmed (2 spaces + ⎿ character)
                context = MsgContext::None;
                let content: String = line.chars().skip(3).collect(); // Skip "  ⎿"
                let base_style = Style::default().fg(t.dim_fg);
                let mut spans = vec![Span::styled("      ", base_style)];
                spans.extend(highlight_search_in_text(&content, search_pattern, base_style, search_highlight));
                Line::from(spans)
            } else if line.is_empty() {
                // Empty line - keep context for multi-paragraph messages
                Line::from("")
            } else if context != MsgContext::None {
                // Continuation line within a message block (indented or not)
                match context {
                    MsgContext::User => {
                        let used = 6 + 1 + line.chars().count(); // prefix + " " + content
                        let padding = content_width.saturating_sub(used);
                        let base_style = Style::default().bg(t.user_bubble_bg);
                        let mut spans = vec![
                            Span::styled("      ", Style::default()),
                            Span::styled(" ", base_style),
                        ];
                        spans.extend(highlight_search_in_text(line, search_pattern, base_style, search_highlight));
                        spans.push(Span::styled(" ".repeat(padding), base_style));
                        Line::from(spans)
                    }
                    MsgContext::Assistant => {
                        let label_width = agent_label.chars().count() + 2; // " ● Claude " chars
                        let used = label_width + 1 + line.chars().count();
                        let padding = content_width.saturating_sub(used);
                        let base_style = Style::default().bg(assistant_bg);
                        let mut spans = vec![
                            Span::styled(" ".repeat(label_width), Style::default()),
                            Span::styled(" ", base_style),
                        ];
                        spans.extend(highlight_search_in_text(line, search_pattern, base_style, search_highlight));
                        spans.push(Span::styled(" ".repeat(padding), base_style));
                        Line::from(spans)
                    }
                    MsgContext::None => {
                        let base_style = Style::default();
                        Line::from(highlight_search_in_text(line, search_pattern, base_style, search_highlight))
                    }
                }
            } else {
                // Plain line outside message context (metadata, etc.)
                let base_style = Style::default();
                Line::from(highlight_search_in_text(line, search_pattern, base_style, search_highlight))
            }
        })
        .collect();

    // Track total lines for footer display
    let total_lines = app.full_content.lines().count();

    // Clamp scroll to valid range
    let max_scroll = content_lines.len().saturating_sub(1);
    if app.full_content_scroll > max_scroll {
        app.full_content_scroll = max_scroll;
    }

    // Manually skip lines to scroll (so scroll works on content lines, not visual lines)
    // This ensures search navigation jumps to the correct content line
    let visible_lines: Vec<Line> = content_lines
        .into_iter()
        .skip(app.full_content_scroll)
        .collect();

    let content = Paragraph::new(visible_lines)
        .wrap(ratatui::widgets::Wrap { trim: false });
    frame.render_widget(content, layout[1]);

    // Footer - navigation hints or search input
    let keycap = Style::default().bg(t.keycap_bg);
    let label = Style::default();
    let dim = Style::default().fg(t.dim_fg);
    let highlight = Style::default().fg(t.match_fg);

    let footer = if app.view_search_mode {
        // Search input mode
        Line::from(vec![
            Span::styled(" /", Style::default().fg(t.accent)),
            Span::styled(&app.view_search_pattern, label),
            Span::styled("█", Style::default().fg(t.accent)),
            Span::styled("  (Enter to search, Esc to cancel)", dim),
        ])
    } else if !app.view_search_pattern.is_empty() {
        // Active search - show match count and navigation
        let match_info = if app.view_search_matches.is_empty() {
            "No matches".to_string()
        } else {
            format!(
                "Match {}/{}",
                app.view_search_current + 1,
                app.view_search_matches.len()
            )
        };
        Line::from(vec![
            Span::styled(" /", Style::default().fg(t.accent)),
            Span::styled(&app.view_search_pattern, highlight),
            Span::styled(format!("  {} ", match_info), dim),
            Span::styled(" │ ", dim),
            Span::styled(" n ", keycap),
            Span::styled(" next ", label),
            Span::styled(" N ", keycap),
            Span::styled(" prev ", label),
            Span::styled(" │ ", dim),
            Span::styled(" Esc ", keycap),
            Span::styled(" clear ", label),
            Span::styled(
                format!("  Line {}/{}", app.full_content_scroll + 1, total_lines),
                dim,
            ),
        ])
    } else {
        // Normal mode - show navigation hints
        Line::from(vec![
            Span::styled(" ↑↓/jk ", keycap),
            Span::styled(" scroll ", label),
            Span::styled(" │ ", dim),
            Span::styled(" PgUp/Dn ", keycap),
            Span::styled(" page ", label),
            Span::styled(" │ ", dim),
            Span::styled(" / ", keycap),
            Span::styled(" search ", label),
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
        ])
    };
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

/// Highlight search pattern matches in text, returning spans with base and highlight styles
fn highlight_search_in_text<'a>(
    text: &str,
    pattern: &str,
    base_style: Style,
    highlight_style: Style,
) -> Vec<Span<'a>> {
    if pattern.is_empty() {
        return vec![Span::styled(text.to_string(), base_style)];
    }

    let pattern_lower = pattern.to_lowercase();
    let text_lower = text.to_lowercase();
    let mut spans: Vec<Span> = Vec::new();
    let mut last_end = 0;

    // Find all occurrences of pattern (case-insensitive)
    let text_chars: Vec<char> = text.chars().collect();
    let pattern_chars: Vec<char> = pattern_lower.chars().collect();
    let text_lower_chars: Vec<char> = text_lower.chars().collect();

    let mut i = 0;
    while i + pattern_chars.len() <= text_lower_chars.len() {
        let match_found = (0..pattern_chars.len())
            .all(|j| text_lower_chars[i + j] == pattern_chars[j]);

        if match_found {
            // Add text before match
            if i > last_end {
                let before: String = text_chars[last_end..i].iter().collect();
                spans.push(Span::styled(before, base_style));
            }
            // Add highlighted match
            let matched: String = text_chars[i..i + pattern_chars.len()].iter().collect();
            spans.push(Span::styled(matched, highlight_style));
            last_end = i + pattern_chars.len();
            i = last_end;
        } else {
            i += 1;
        }
    }

    // Add remaining text
    if last_end < text_chars.len() {
        let remaining: String = text_chars[last_end..].iter().collect();
        spans.push(Span::styled(remaining, base_style));
    }

    if spans.is_empty() {
        spans.push(Span::styled(text.to_string(), base_style));
    }

    spans
}

/// Parse a flexible date string into YYYYMMDD format for comparison
/// Accepts: YYYYMMDD, YYYY-MM-DD, MM/DD/YYYY, MM/DD, etc.
fn parse_flexible_date(input: &str) -> Option<String> {
    use chrono::NaiveDate;

    let input = input.trim();
    if input.is_empty() {
        return None;
    }

    // Try various formats
    let formats = [
        "%Y%m%d",      // 20251129
        "%Y-%m-%d",    // 2025-11-29
        "%Y/%m/%d",    // 2025/11/29
        "%m/%d/%Y",    // 11/29/2025
        "%m-%d-%Y",    // 11-29-2025
        "%m/%d/%y",    // 11/29/25
        "%m-%d-%y",    // 11-29-25
    ];

    for fmt in formats {
        if let Ok(date) = NaiveDate::parse_from_str(input, fmt) {
            return Some(date.format("%Y%m%d").to_string());
        }
    }

    // Try MM/DD or MM-DD with current year
    let short_formats = ["%m/%d", "%m-%d"];
    let current_year = chrono::Utc::now().format("%Y").to_string();
    for fmt in short_formats {
        if let Ok(date) = NaiveDate::parse_from_str(
            &format!("{}/{}", input, current_year),
            &format!("{}/{}", fmt, "%Y"),
        ) {
            return Some(date.format("%Y%m%d").to_string());
        }
    }

    None
}

/// Extract YYYYMMDD from an ISO timestamp for comparison
fn extract_date_for_comparison(timestamp: &str) -> Option<String> {
    // Try to parse as RFC3339 or similar
    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(timestamp) {
        return Some(dt.format("%Y%m%d").to_string());
    }
    // Try naive datetime
    if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(timestamp, "%Y-%m-%dT%H:%M:%S%.f") {
        return Some(dt.format("%Y%m%d").to_string());
    }
    // Just try to extract YYYY-MM-DD
    if timestamp.len() >= 10 {
        let date_part = &timestamp[..10];
        if let Ok(date) = chrono::NaiveDate::parse_from_str(date_part, "%Y-%m-%d") {
            return Some(date.format("%Y%m%d").to_string());
        }
    }
    None
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

    let sessions = load_sessions(index_path.to_str().unwrap(), 5000)?;

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
                        if app.view_search_mode {
                            // Search input mode
                            match key.code {
                                KeyCode::Esc => {
                                    // Cancel search input, keep existing pattern if any
                                    app.view_search_mode = false;
                                }
                                KeyCode::Enter => {
                                    // Confirm search and jump to first match
                                    app.view_search_mode = false;
                                    app.update_view_search_matches();
                                    if !app.view_search_matches.is_empty() {
                                        app.view_search_current = 0;
                                        app.full_content_scroll = app.view_search_matches[0];
                                    }
                                }
                                KeyCode::Backspace => {
                                    app.view_search_pattern.pop();
                                }
                                KeyCode::Char(c) => {
                                    app.view_search_pattern.push(c);
                                }
                                _ => {}
                            }
                        } else if !app.view_search_pattern.is_empty() {
                            // Active search - handle search navigation
                            match key.code {
                                KeyCode::Char('n') => {
                                    app.view_search_next();
                                }
                                KeyCode::Char('N') => {
                                    app.view_search_prev();
                                }
                                KeyCode::Enter => {
                                    // Enter also goes to next match
                                    app.view_search_next();
                                }
                                KeyCode::Esc => {
                                    // Clear search pattern
                                    app.view_search_pattern.clear();
                                    app.view_search_matches.clear();
                                    app.view_search_current = 0;
                                }
                                KeyCode::Char('/') => {
                                    // Start new search
                                    app.view_search_pattern.clear();
                                    app.view_search_mode = true;
                                }
                                KeyCode::Char(' ') | KeyCode::Char('q') => {
                                    // Exit view mode, clear search
                                    app.view_search_pattern.clear();
                                    app.view_search_matches.clear();
                                    app.view_search_mode = false;
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
                        } else {
                            // Normal view mode (no active search)
                            match key.code {
                                KeyCode::Char('/') => {
                                    app.view_search_mode = true;
                                    app.view_search_pattern.clear();
                                }
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
                        }
                    } else if app.filter_modal_open {
                        // Handle filter modal
                        let items = FilterMenuItem::all();

                        // Helper to apply filter by item
                        let apply_filter = |app: &mut App, item: &FilterMenuItem| {
                            match item {
                                FilterMenuItem::ClearAll => {
                                    // Reset to defaults
                                    app.include_original = true;
                                    app.include_sub = false;
                                    app.include_trimmed = true;
                                    app.include_continued = true;
                                    app.filter_agent = None;
                                    app.filter_min_lines = None;
                                    app.filter();
                                }
                                FilterMenuItem::IncludeOriginal => {
                                    app.include_original = !app.include_original;
                                    app.filter();
                                }
                                FilterMenuItem::IncludeSub => {
                                    app.include_sub = !app.include_sub;
                                    app.filter();
                                }
                                FilterMenuItem::IncludeTrimmed => {
                                    app.include_trimmed = !app.include_trimmed;
                                    app.filter();
                                }
                                FilterMenuItem::IncludeContinued => {
                                    app.include_continued = !app.include_continued;
                                    app.filter();
                                }
                                FilterMenuItem::AgentAll => {
                                    app.filter_agent = None;
                                    app.filter();
                                }
                                FilterMenuItem::AgentClaude => {
                                    app.filter_agent = Some("claude".to_string());
                                    app.filter();
                                }
                                FilterMenuItem::AgentCodex => {
                                    app.filter_agent = Some("codex".to_string());
                                    app.filter();
                                }
                                FilterMenuItem::MinLines => {
                                    app.filter_modal_open = false;
                                    app.input_mode = Some(InputMode::MinLines);
                                    app.input_buffer.clear();
                                }
                                FilterMenuItem::AfterDate => {
                                    app.filter_modal_open = false;
                                    app.input_mode = Some(InputMode::AfterDate);
                                    app.input_buffer.clear();
                                }
                                FilterMenuItem::BeforeDate => {
                                    app.filter_modal_open = false;
                                    app.input_mode = Some(InputMode::BeforeDate);
                                    app.input_buffer.clear();
                                }
                            }
                        };

                        match key.code {
                            KeyCode::Esc => {
                                app.filter_modal_open = false;
                            }
                            KeyCode::Char('f') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                                app.filter_modal_open = false;
                            }
                            KeyCode::Up | KeyCode::Char('k') => {
                                if app.filter_modal_selected > 0 {
                                    app.filter_modal_selected -= 1;
                                }
                            }
                            KeyCode::Down | KeyCode::Char('j') => {
                                if app.filter_modal_selected < items.len() - 1 {
                                    app.filter_modal_selected += 1;
                                }
                            }
                            KeyCode::Enter | KeyCode::Char(' ') => {
                                let item = items[app.filter_modal_selected].clone();
                                apply_filter(&mut app, &item);
                            }
                            // Shortcut keys
                            KeyCode::Char(c) => {
                                if let Some(item) = items.iter().find(|i| i.shortcut() == c) {
                                    apply_filter(&mut app, item);
                                }
                            }
                            _ => {}
                        }
                    } else if app.action_mode.is_some() {
                        // Handle action mode (view/actions)
                        let mode = app.action_mode.clone().unwrap();
                        match key.code {
                            KeyCode::Esc => {
                                app.action_mode = None;
                            }
                            KeyCode::Char('v') if mode == ActionMode::ViewOrActions => {
                                // View: enter full view mode
                                if let Some(session) = app.selected_session() {
                                    app.full_content = std::fs::read_to_string(&session.export_path)
                                        .unwrap_or_else(|_| "Error loading content".to_string());
                                    app.full_content_scroll = 0;
                                    app.full_view_mode = true;
                                    // Clear any previous search state
                                    app.view_search_mode = false;
                                    app.view_search_pattern.clear();
                                    app.view_search_matches.clear();
                                    app.view_search_current = 0;
                                }
                                app.action_mode = None;
                            }
                            KeyCode::Char('a') if mode == ActionMode::ViewOrActions => {
                                // Actions: select session and quit to show actions menu
                                app.on_enter();
                                app.action_mode = None;
                            }
                            _ => {}
                        }
                    } else if app.input_mode.is_some() {
                        // Handle input mode for :m and :a
                        let mode = app.input_mode.clone().unwrap();
                        match key.code {
                            KeyCode::Esc => {
                                app.input_mode = None;
                                app.input_buffer.clear();
                            }
                            KeyCode::Enter => {
                                match mode {
                                    InputMode::MinLines => {
                                        if let Ok(num) = app.input_buffer.parse::<i64>() {
                                            app.filter_min_lines = if num > 0 { Some(num) } else { None };
                                            app.filter();
                                        }
                                    }
                                    InputMode::Agent => {}
                                    InputMode::JumpToLine => {
                                        if let Ok(row) = app.input_buffer.parse::<usize>() {
                                            app.jump_to_row(row);
                                        }
                                    }
                                    InputMode::AfterDate => {
                                        if app.input_buffer.is_empty() {
                                            app.filter_after_date = None;
                                        } else if let Some(date) = parse_flexible_date(&app.input_buffer) {
                                            app.filter_after_date = Some(date);
                                        }
                                        app.filter();
                                    }
                                    InputMode::BeforeDate => {
                                        if app.input_buffer.is_empty() {
                                            app.filter_before_date = None;
                                        } else if let Some(date) = parse_flexible_date(&app.input_buffer) {
                                            app.filter_before_date = Some(date);
                                        }
                                        app.filter();
                                    }
                                }
                                app.input_mode = None;
                                app.input_buffer.clear();
                            }
                            KeyCode::Char('1') if mode == InputMode::Agent => {
                                app.filter_agent = Some("claude".to_string());
                                app.filter();
                                app.input_mode = None;
                                app.input_buffer.clear();
                            }
                            KeyCode::Char('2') if mode == InputMode::Agent => {
                                app.filter_agent = Some("codex".to_string());
                                app.filter();
                                app.input_mode = None;
                                app.input_buffer.clear();
                            }
                            KeyCode::Char('0') if mode == InputMode::Agent => {
                                app.filter_agent = None;
                                app.filter();
                                app.input_mode = None;
                                app.input_buffer.clear();
                            }
                            KeyCode::Char(c) if c.is_ascii_digit() && (mode == InputMode::MinLines || mode == InputMode::JumpToLine) => {
                                app.input_buffer.push(c);
                            }
                            KeyCode::Char(c) if mode == InputMode::AfterDate || mode == InputMode::BeforeDate => {
                                // Accept any character for flexible date input
                                app.input_buffer.push(c);
                            }
                            KeyCode::Backspace if mode == InputMode::MinLines || mode == InputMode::JumpToLine || mode == InputMode::AfterDate || mode == InputMode::BeforeDate => {
                                app.input_buffer.pop();
                            }
                            _ => {}
                        }
                    } else if app.command_mode {
                        // Handle command mode (: prefix)
                        app.command_mode = false;
                        match key.code {
                            KeyCode::Char('x') | KeyCode::Char('0') => {
                                // Reset to defaults
                                app.include_original = true;
                                app.include_sub = false;
                                app.include_trimmed = true;
                                app.include_continued = true;
                                app.filter_agent = None;
                                app.filter_min_lines = None;
                                app.filter_after_date = None;
                                app.filter_before_date = None;
                                app.filter();
                            }
                            KeyCode::Char('o') => {
                                app.include_original = !app.include_original;
                                app.filter();
                            }
                            KeyCode::Char('s') => {
                                app.include_sub = !app.include_sub;
                                app.filter();
                            }
                            KeyCode::Char('t') => {
                                app.include_trimmed = !app.include_trimmed;
                                app.filter();
                            }
                            KeyCode::Char('c') => {
                                app.include_continued = !app.include_continued;
                                app.filter();
                            }
                            KeyCode::Char('a') => {
                                // Enter agent input mode
                                app.input_mode = Some(InputMode::Agent);
                                app.input_buffer.clear();
                            }
                            KeyCode::Char('m') => {
                                // Enter min-lines input mode
                                app.input_mode = Some(InputMode::MinLines);
                                app.input_buffer.clear();
                            }
                            KeyCode::Char('>') => {
                                // Enter after-date input mode
                                app.input_mode = Some(InputMode::AfterDate);
                                app.input_buffer.clear();
                            }
                            KeyCode::Char('<') => {
                                // Enter before-date input mode
                                app.input_mode = Some(InputMode::BeforeDate);
                                app.input_buffer.clear();
                            }
                            KeyCode::Esc => {} // Just exit command mode
                            _ => {}
                        }
                    } else if !app.jump_input.is_empty() {
                        // Handle jump input mode
                        match key.code {
                            KeyCode::Enter => {
                                app.process_jump_enter();
                            }
                            KeyCode::Esc => {
                                app.jump_input.clear();
                            }
                            KeyCode::Char(c) if c.is_ascii_digit() => {
                                app.jump_input.push(c);
                            }
                            KeyCode::Backspace => {
                                app.jump_input.pop();
                            }
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
                                // Space: add to query (for multi-word search)
                                app.on_char(' ');
                            }
                            KeyCode::Esc => app.on_escape(),
                            KeyCode::Enter => {
                                // If there's pending jump input, use it
                                if !app.jump_input.is_empty() {
                                    app.process_jump_enter();
                                } else if app.selected_session().is_some() {
                                    // Enter action mode to choose view or actions
                                    app.action_mode = Some(ActionMode::ViewOrActions);
                                }
                            }
                            KeyCode::Up => app.on_up(),
                            KeyCode::Down => app.on_down(),
                            KeyCode::PageUp => app.page_up(10),
                            KeyCode::PageDown => app.page_down(10),
                            KeyCode::Home => {
                                // Jump to first result
                                app.selected = 0;
                                app.preview_scroll = 0;
                            }
                            KeyCode::End => {
                                // Jump to last result
                                if !app.filtered.is_empty() {
                                    app.selected = app.filtered.len() - 1;
                                    app.preview_scroll = 0;
                                }
                            }
                            KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => app.page_up(10),
                            KeyCode::Char('d') if key.modifiers.contains(KeyModifiers::CONTROL) => app.page_down(10),
                            KeyCode::Backspace => app.on_backspace(),
                            KeyCode::Char('/') => app.toggle_scope(),
                            KeyCode::Char('f') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                                // Open filter modal
                                app.filter_modal_open = true;
                                app.filter_modal_selected = 0;
                            }
                            KeyCode::Char('g') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                                // Enter jump mode (go to line)
                                app.input_mode = Some(InputMode::JumpToLine);
                                app.input_buffer.clear();
                            }
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
