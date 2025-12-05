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
use std::collections::{HashMap, HashSet};
use tantivy::{
    collector::TopDocs,
    query::{AllQuery, BooleanQuery, BoostQuery, Occur, PhraseQuery, QueryParser, TermQuery},
    schema::{IndexRecordOption, Value},
    snippet::SnippetGenerator,
    Index, ReloadPolicy, Term,
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
    #[serde(rename = "file_path")]
    export_path: String,
    first_msg_role: String,
    first_msg_content: String,
    last_msg_role: String,
    last_msg_content: String,
    derivation_type: String,  // "trimmed", "continued", or ""
    is_sidechain: bool,       // Sub-agent session
    claude_home: String,      // Source Claude home directory
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

    /// Medium date display: "11/27 - 11/29" or "11/29" (no time)
    fn date_medium(&self) -> String {
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
                let (earlier, later) = if created <= modified {
                    (created, modified)
                } else {
                    (modified, created)
                };

                if earlier.format("%m/%d").to_string() == later.format("%m/%d").to_string() {
                    later.format("%m/%d").to_string()
                } else {
                    format!("{} - {}", earlier.format("%m/%d"), later.format("%m/%d"))
                }
            }
            (None, Some(modified)) => modified.format("%m/%d").to_string(),
            _ => self.modified.chars().take(5).collect(),
        }
    }

    /// Compact date display: relative time like "3h", "5d", "2w", "3mo"
    fn date_compact(&self) -> String {
        let parse_date = |s: &str| {
            DateTime::parse_from_rfc3339(s)
                .or_else(|_| {
                    chrono::NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f")
                        .map(|ndt| Utc.from_utc_datetime(&ndt).fixed_offset())
                })
                .ok()
        };

        let modified_dt = match parse_date(&self.modified) {
            Some(dt) => dt,
            None => return "?".to_string(),
        };

        let now = Utc::now();
        let duration = now.signed_duration_since(modified_dt);

        let hours = duration.num_hours();
        let days = duration.num_days();

        if hours < 1 {
            format!("{}m", duration.num_minutes().max(1))
        } else if hours < 24 {
            format!("{}h", hours)
        } else if days < 7 {
            format!("{}d", days)
        } else if days < 30 {
            format!("{}w", days / 7)
        } else if days < 365 {
            format!("{}mo", days / 30)
        } else {
            format!("{}y", days / 365)
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
    index_path: String, // Path to Tantivy index for keyword search
    search_snippets: HashMap<String, String>, // session_id -> matching snippet from content

    // Filter state - inclusion-based (true = include this type)
    include_original: bool,   // true by default - include original sessions
    include_sub: bool,        // false by default - exclude sub-agents
    include_trimmed: bool,    // true by default - include trimmed sessions
    include_continued: bool,  // true by default - include continued sessions
    filter_agent: Option<String>, // None = all, Some("claude"), Some("codex")
    filter_min_lines: Option<i64>,
    filter_after_date: Option<String>,  // YYYYMMDD - modified date must be >= this
    filter_after_date_display: Option<String>, // User-friendly display format
    filter_before_date: Option<String>, // YYYYMMDD - modified date must be <= this
    filter_before_date_display: Option<String>, // User-friendly display format
    filter_claude_home: Option<String>, // Filter to sessions from this Claude home
    filter_codex_home: Option<String>,  // Filter Codex sessions to this Codex home

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

    // Scope modal (/ key)
    scope_modal_open: bool,
    scope_modal_selected: usize,
    filter_dir: Option<String>, // Custom directory filter (overrides scope_global)

    // Result limit
    max_results: Option<usize>, // Limit number of displayed results (--num-results / -n)

    // Sort mode: false = relevance (default), true = time (reverse chronological)
    sort_by_time: bool,

    // Exit confirmation
    confirming_exit: bool,
}

#[derive(Clone, PartialEq)]
enum InputMode {
    MinLines,   // :m - waiting for number
    Agent,      // :a - waiting for 1 or 2
    JumpToLine, // C-g - waiting for line number
    AfterDate,  // :> - waiting for date
    BeforeDate, // :< - waiting for date
    ScopeDir,   // Custom directory for scope filter
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
    fn new(sessions: Vec<Session>, index_path: String, filter_claude_home: Option<String>, filter_codex_home: Option<String>) -> Self {
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
            index_path,
            search_snippets: HashMap::new(),
            // Filter state
            include_original: true,   // Include original by default
            include_sub: false,       // Exclude sub-agents by default
            include_trimmed: true,    // Include trimmed by default
            include_continued: true,  // Include continued by default
            filter_agent: None,
            filter_min_lines: None,
            filter_after_date: None,
            filter_after_date_display: None,
            filter_before_date: None,
            filter_before_date_display: None,
            filter_claude_home,
            filter_codex_home,
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
            // Scope modal
            scope_modal_open: false,
            scope_modal_selected: 0,
            filter_dir: None,
            // Result limit
            max_results: None,
            // Sort mode
            sort_by_time: false,
            // Exit confirmation
            confirming_exit: false,
        };
        app.filter();
        app
    }

    fn new_with_options(sessions: Vec<Session>, index_path: String, cli: &CliOptions) -> Self {
        let total = sessions.len();
        let launch_cwd = std::env::current_dir()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_default();

        // Parse date filters if provided
        let (after_date, after_display) = cli.after_date.as_ref()
            .and_then(|d| parse_flexible_date(d))
            .map(|(cmp, disp)| (Some(cmp), Some(disp)))
            .unwrap_or((None, None));

        let (before_date, before_display) = cli.before_date.as_ref()
            .and_then(|d| parse_flexible_date(d))
            .map(|(cmp, disp)| (Some(cmp), Some(disp)))
            .unwrap_or((None, None));

        let mut app = Self {
            sessions,
            filtered: Vec::new(),
            query: cli.query.clone().unwrap_or_default(),
            selected: 0,
            list_scroll: 0,
            preview_scroll: 0,
            should_quit: false,
            should_select: None,
            total_sessions: total,
            // --dir overrides -g: if filter_dir is set, scope_global is effectively false
            scope_global: if cli.filter_dir.is_some() { false } else { cli.global_search },
            launch_cwd,
            index_path,
            search_snippets: HashMap::new(),
            // Filter state from CLI
            // If ANY type flag is specified, use explicit mode (only include what's specified)
            // If NO type flags are specified, use defaults (original + trimmed + continued, no sub-agents)
            include_original: if cli.any_type_flag_specified() {
                cli.include_original
            } else {
                true  // default: include
            },
            include_sub: cli.include_sub,  // always explicit (default false)
            include_trimmed: if cli.any_type_flag_specified() {
                cli.include_trimmed
            } else {
                true  // default: include
            },
            include_continued: if cli.any_type_flag_specified() {
                cli.include_continued
            } else {
                true  // default: include
            },
            filter_agent: cli.agent_filter.clone(),
            filter_min_lines: cli.min_lines,
            filter_after_date: after_date,
            filter_after_date_display: after_display,
            filter_before_date: before_date,
            filter_before_date_display: before_display,
            filter_claude_home: cli.claude_home.clone(),
            filter_codex_home: cli.codex_home.clone(),
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
            // Scope modal
            scope_modal_open: false,
            scope_modal_selected: 0,
            filter_dir: cli.filter_dir.clone(),
            // Result limit
            max_results: cli.num_results,
            // Sort mode
            sort_by_time: false,
            // Exit confirmation
            confirming_exit: false,
        };
        app.filter();
        app
    }

    fn filter(&mut self) {
        self.filtered = self
            .sessions
            .iter()
            .enumerate()
            .filter(|(_, s)| {
                // Home filter - apply based on session agent type
                if s.agent == "codex" {
                    // Codex session: filter by codex_home
                    if let Some(ref codex_home) = self.filter_codex_home {
                        if !s.claude_home.is_empty() && s.claude_home != *codex_home {
                            return false;
                        }
                    }
                } else {
                    // Claude session: filter by claude_home
                    if let Some(ref home) = self.filter_claude_home {
                        if !s.claude_home.is_empty() && s.claude_home != *home {
                            return false;
                        }
                    }
                }

                // Scope filter: filter_dir overrides scope_global
                if let Some(ref filter_dir) = self.filter_dir {
                    // Custom directory filter - match exact dir or subdirectories
                    // Must be exact match OR start with filter_dir + "/"
                    if !s.cwd.is_empty() {
                        let is_match = s.cwd == *filter_dir
                            || s.cwd.starts_with(&format!("{}/", filter_dir));
                        if !is_match {
                            return false;
                        }
                    }
                } else if !self.scope_global && !s.cwd.is_empty() && s.cwd != self.launch_cwd {
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

                // No query filter at this stage - handled by tantivy_matches below
                true
            })
            .map(|(i, _)| i)
            .collect();

        // If there's a keyword query, use Tantivy full-text search
        if !self.query.trim().is_empty() {
            let (snippets, ranked_ids) = search_tantivy(
                &self.index_path,
                &self.query,
                self.filter_claude_home.as_deref(),
                self.filter_codex_home.as_deref(),
            );
            if !snippets.is_empty() {
                // Store snippets for rendering
                self.search_snippets = snippets.clone();
                // Filter to only sessions that match the Tantivy search
                self.filtered.retain(|&i| {
                    snippets.contains_key(&self.sessions[i].session_id)
                });

                if self.sort_by_time {
                    // Sort by modified time (reverse chronological)
                    self.filtered.sort_by(|&a, &b| {
                        self.sessions[b].modified.cmp(&self.sessions[a].modified)
                    });
                } else {
                    // Reorder filtered by Tantivy ranking (phrase + recency boosted)
                    // Build position map for ranking
                    let rank_pos: HashMap<&str, usize> = ranked_ids
                        .iter()
                        .enumerate()
                        .map(|(pos, id)| (id.as_str(), pos))
                        .collect();

                    // Sort filtered by position in ranked_ids (lower = higher rank)
                    self.filtered.sort_by_key(|&i| {
                        rank_pos
                            .get(self.sessions[i].session_id.as_str())
                            .copied()
                            .unwrap_or(usize::MAX)
                    });
                }
            } else {
                // No Tantivy matches - clear results and snippets
                self.search_snippets.clear();
                self.filtered.clear();
            }
        } else {
            // Clear snippets when no query - sort by time (most recent first)
            self.search_snippets.clear();
            self.filtered.sort_by(|&a, &b| {
                self.sessions[b].modified.cmp(&self.sessions[a].modified)
            });
        }

        // Apply max_results limit if specified
        if let Some(limit) = self.max_results {
            self.filtered.truncate(limit);
        }

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

    fn has_active_filters(&self) -> bool {
        !self.query.is_empty()
            || self.filter_min_lines.is_some()
            || self.filter_after_date.is_some()
            || self.filter_before_date.is_some()
            || self.filter_agent.is_some()
            || !self.include_original
            || self.include_sub
            || !self.include_trimmed
            || !self.include_continued
    }

    fn on_escape(&mut self) {
        if self.query.is_empty() {
            // If there are active filters, show confirmation before exiting
            if self.has_active_filters() {
                self.confirming_exit = true;
            } else {
                self.should_quit = true;
            }
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
        // Determine which directory to display
        let dir_to_show = if let Some(ref dir) = self.filter_dir {
            dir.clone()
        } else if self.scope_global {
            return "everywhere".to_string();
        } else {
            self.launch_cwd.clone()
        };

        // Show ~/path for short paths, ~/.../<dir> for long paths
        let home = std::env::var("HOME").unwrap_or_default();
        let path = if !home.is_empty() && dir_to_show.starts_with(&home) {
            format!("~{}", &dir_to_show[home.len()..])
        } else {
            dir_to_show.clone()
        };
        if path.len() > 35 {
            let last = std::path::Path::new(&dir_to_show)
                .file_name()
                .and_then(|s| s.to_str())
                .unwrap_or("");
            format!("~/.../{}", last)
        } else {
            path
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

    // Status bar height: 2 for nav+actions, +1 if we have annotations OR active filters
    let show_legend = app.has_annotations();
    let has_filters = !app.include_original
        || app.include_sub
        || !app.include_trimmed
        || !app.include_continued
        || app.filter_agent.is_some()
        || app.filter_min_lines.is_some()
        || app.filter_after_date.is_some()
        || app.filter_before_date.is_some();
    let status_height = if show_legend || has_filters { 3 } else { 2 };

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

    // Scope modal overlay
    if app.scope_modal_open {
        render_scope_modal(frame, app, &t, area);
    }

    // View/Actions modal overlay
    if matches!(app.action_mode, Some(ActionMode::ViewOrActions)) {
        render_view_actions_modal(frame, &t, area);
    }

    // Exit confirmation modal overlay
    if app.confirming_exit {
        render_exit_confirmation_modal(frame, &t, area);
    }
}

fn render_exit_confirmation_modal(frame: &mut Frame, t: &Theme, area: Rect) {
    use ratatui::widgets::{Block, Borders, Clear};

    // Center the modal
    let modal_width = 52u16;
    let modal_height = 7u16; // message + 2 options + 2 border + 2 padding
    let x = (area.width.saturating_sub(modal_width)) / 2;
    let y = (area.height.saturating_sub(modal_height)) / 2;
    let modal_area = Rect::new(x, y, modal_width, modal_height);

    // Clear the area behind the modal
    frame.render_widget(Clear, modal_area);

    // Modal border
    let block = Block::default()
        .title(" Exit? ")
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
            Span::styled("You have active filters set.", dim),
        ]),
        Line::from(vec![]),
        Line::from(vec![
            Span::styled(" Enter ", keycap),
            Span::styled(" exit and lose filter settings", label),
        ]),
        Line::from(vec![
            Span::styled("  Esc  ", keycap),
            Span::styled(" cancel and return to search", label),
        ]),
    ];

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
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
            FilterMenuItem::AfterDate => match &app.filter_after_date_display {
                Some(d) => format!(" [>{}]", d),
                None => " [None]".to_string(),
            },
            FilterMenuItem::BeforeDate => match &app.filter_before_date_display {
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

fn render_scope_modal(frame: &mut Frame, app: &App, t: &Theme, area: Rect) {
    use ratatui::widgets::{Block, Borders, Clear};

    // Center the modal (wider to fit full directory paths)
    let modal_width = 80u16;
    let modal_height = 7u16; // 3 items + 2 border + 2 padding
    let x = (area.width.saturating_sub(modal_width)) / 2;
    let y = (area.height.saturating_sub(modal_height)) / 2;
    let modal_area = Rect::new(x, y, modal_width, modal_height);

    // Clear the area behind the modal
    frame.render_widget(Clear, modal_area);

    // Modal border
    let block = Block::default()
        .title(" Scope (/) ")
        .borders(Borders::ALL)
        .style(Style::default().bg(t.search_bg));
    frame.render_widget(block, modal_area);

    // Inner content area
    let inner = Rect::new(x + 2, y + 1, modal_width - 4, modal_height - 2);

    // Build menu items based on current state
    // Show full path if short, ~/.../<dir> if long (same logic as scope_display)
    let home = std::env::var("HOME").unwrap_or_default();
    let cwd_display = {
        let path = if !home.is_empty() && app.launch_cwd.starts_with(&home) {
            format!("~{}", &app.launch_cwd[home.len()..])
        } else {
            app.launch_cwd.clone()
        };
        if path.len() > 50 {
            let last = std::path::Path::new(&app.launch_cwd)
                .file_name()
                .and_then(|s| s.to_str())
                .unwrap_or("");
            format!("~/.../{}", last)
        } else {
            path
        }
    };
    let current_dir_label = format!("Current directory ({})", cwd_display);

    let items: Vec<(String, bool)> = vec![
        ("Global (everywhere)".to_string(), app.scope_global && app.filter_dir.is_none()),
        (current_dir_label, !app.scope_global && app.filter_dir.is_none()),
        ("Custom directory...".to_string(), app.filter_dir.is_some()),
    ];

    let mut lines: Vec<Line> = Vec::new();

    for (i, (label, is_active)) in items.iter().enumerate() {
        let is_selected = i == app.scope_modal_selected;

        let style = if is_selected {
            Style::default().bg(t.selection_bg).fg(t.selection_header_fg)
        } else {
            Style::default()
        };

        let prefix = if is_selected { "▶ " } else { "  " };
        let state = if *is_active { " ●" } else { " ○" };

        // For custom directory, show the path if set
        let suffix = if i == 2 {
            if let Some(ref dir) = app.filter_dir {
                let home = std::env::var("HOME").unwrap_or_default();
                let display = if !home.is_empty() && dir.starts_with(&home) {
                    format!(" [~{}]", &dir[home.len()..])
                } else {
                    format!(" [{}]", dir)
                };
                // Truncate if too long
                if display.len() > 30 {
                    format!(" [{}...]", &display[2..28])
                } else {
                    display
                }
            } else {
                String::new()
            }
        } else {
            String::new()
        };

        lines.push(Line::from(vec![
            Span::styled(prefix, style),
            Span::styled(label.clone(), style),
            Span::styled(state, Style::default().fg(t.match_fg)),
            Span::styled(suffix, Style::default().fg(t.dim_fg)),
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
    // Make search box smaller to give more space to directory path (shift right side left by ~20 chars)
    let search_width = (area.width as usize).saturating_sub(right_side_width + 32);

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
    for &idx in &app.filtered {
        let s = &app.sessions[idx];
        max_session_id_len = max_session_id_len.max(s.session_id_display().len());
        max_project_len = max_project_len.max(s.project_name().len());
        max_branch_len = max_branch_len.max(s.branch_display().len());
        max_lines_len = max_lines_len.max(format!("{}L", s.lines).len());
    }
    // Ensure minimums and reasonable maximums
    max_session_id_len = max_session_id_len.max(10).min(20);
    max_project_len = max_project_len.max(10).min(40);
    max_branch_len = max_branch_len.max(8).min(35);
    max_lines_len = max_lines_len.max(4);

    // Calculate available width and determine date format
    // Fixed overhead: row_num + space + icon/agent (8) + 4 separators (12) + padding (2)
    let fixed_overhead = row_num_width + 1 + 8 + 12 + 2;
    let available_width = area.width as usize;

    // Width needed for non-date fields
    let non_date_width = fixed_overhead + max_session_id_len + max_project_len + max_branch_len + max_lines_len;
    let remaining_for_date = available_width.saturating_sub(non_date_width);

    // Determine date format based on available space
    // Full: ~19 chars ("11/27 - 11/29 15:23"), Medium: ~13 chars ("11/27 - 11/29"), Compact: ~4 chars ("35d")
    let date_format = if remaining_for_date >= 19 {
        "full"
    } else if remaining_for_date >= 13 {
        "medium"
    } else {
        "compact"
    };

    // If even medium date doesn't fit well, also truncate branch more aggressively
    let effective_branch_len = if remaining_for_date < 13 && max_branch_len > 15 {
        15  // Truncate branch to 15 chars to make more room
    } else if remaining_for_date < 19 && max_branch_len > 20 {
        20  // Truncate branch to 20 chars
    } else {
        max_branch_len
    };

    // Calculate max date length based on format
    let max_date_len = match date_format {
        "full" => 19,
        "medium" => 13,
        _ => 4,
    };

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
            let branch_padded = format!("{:<width$}", truncate(s.branch_display(), effective_branch_len), width = effective_branch_len);
            let lines_str = format!("{:>width$}", format!("{}L", s.lines), width = max_lines_len);

            // Choose date format based on available space
            let date_text = match date_format {
                "full" => s.date_display(),
                "medium" => s.date_medium(),
                _ => s.date_compact(),
            };
            let date_str = format!("{:>width$}", date_text, width = max_date_len);

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
                // With query: use Tantivy snippet with HTML tags for highlighting
                if let Some(snippet_html) = app.search_snippets.get(&s.session_id) {
                    // Truncate the plain text version but render with HTML tags
                    let snippet_plain = strip_html_tags(snippet_html);
                    let truncated_plain = truncate(&snippet_plain, snippet_width);
                    // Find how much of the HTML snippet to use based on plain text length
                    let mut spans = vec![Span::styled(indent, snippet_style)];
                    // Truncate HTML snippet approximately (allow extra for tags)
                    let html_truncated: String = snippet_html.chars().take(snippet_width + 50).collect();
                    spans.extend(render_snippet_with_html_tags(&html_truncated, snippet_style, highlight_style));
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

    // Search snippet - show matching content when searching (with keyword highlighting)
    if !app.query.is_empty() {
        if let Some(snippet) = app.search_snippets.get(&s.session_id) {
            if !snippet.is_empty() {
                lines.push(Line::from(vec![
                    Span::styled(" ── MATCH ── ", Style::default().fg(t.accent).add_modifier(Modifier::BOLD)),
                ]));

                // Styles for the match snippet
                let match_bg = Color::Rgb(50, 40, 30); // Warm/highlighted background
                let base_style = Style::default().bg(match_bg).fg(t.accent);
                let highlight_style = Style::default().bg(Color::Yellow).fg(Color::Black).add_modifier(Modifier::BOLD);

                // Strip HTML tags for wrapping calculation, but use original for display
                let snippet_plain = strip_html_tags(snippet);
                // Display 12 lines (50% more than original 8)
                for wrapped in wrap_text(snippet, bubble_width + 7).iter().take(12) {
                    // Account for <b></b> tags in padding calculation
                    let visible_chars = strip_html_tags(wrapped).chars().count();
                    let padding = bubble_width.saturating_sub(visible_chars);

                    // Build line with HTML tag-based highlighting
                    let mut line_spans: Vec<Span> = Vec::new();
                    line_spans.push(Span::styled(" ", Style::default().bg(match_bg)));

                    // Parse <b>...</b> tags for highlighting
                    let highlighted = render_snippet_with_html_tags(wrapped, base_style, highlight_style);
                    line_spans.extend(highlighted);

                    line_spans.push(Span::styled(" ".repeat(padding + 1), Style::default().bg(match_bg)));
                    lines.push(Line::from(line_spans));
                }

                lines.push(Line::from(""));
            }
        }
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
    // Check if we have any active filters (need third row for legend or filters)
    let has_filters = !app.include_original
        || app.include_sub
        || !app.include_trimmed
        || !app.include_continued
        || app.filter_agent.is_some()
        || app.filter_min_lines.is_some()
        || app.filter_after_date.is_some()
        || app.filter_before_date.is_some();

    let needs_third_row = show_legend || has_filters;

    // Split area: line 1 (nav), line 2 (actions), optional line 3 (legend + filters)
    let status_layout = if needs_third_row {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(1), Constraint::Length(1), Constraint::Length(1)])
            .split(area)
    } else {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(1), Constraint::Length(1)])
            .split(area)
    };

    let nav_area = status_layout[0];
    let action_area = status_layout[1];

    let keycap = Style::default().bg(t.keycap_bg);
    let label = Style::default();
    let dim = Style::default().fg(t.dim_fg);
    let filter_active = Style::default().fg(t.match_fg);

    // Line 1: Navigation shortcuts OR input mode indicator
    let mut nav_spans: Vec<Span> = Vec::new();

    if let Some(ref mode) = app.input_mode {
        // Input mode indicator
        let prompt = match mode {
            InputMode::MinLines => format!(" Min lines: {}█ ", app.input_buffer),
            InputMode::Agent => " Agent: 1=Claude 2=Codex 0=All ".to_string(),
            InputMode::JumpToLine => format!(" Go to row: {}█ ", app.input_buffer),
            InputMode::AfterDate => format!(" After date: {}█ (any format) ", app.input_buffer),
            InputMode::BeforeDate => format!(" Before date: {}█ (any format) ", app.input_buffer),
            InputMode::ScopeDir => format!(" Directory: {}█ (Enter=apply, empty=global) ", app.input_buffer),
        };
        nav_spans.push(Span::styled(prompt, Style::default().bg(t.accent).fg(Color::Black)));
    } else if app.command_mode {
        // Command mode indicator
        nav_spans.push(Span::styled(" CMD ", Style::default().bg(t.accent).fg(Color::Black)));
        nav_spans.push(Span::styled(" :x clear :o orig :s sub :t trim :c cont :a agent :m lines :> after :< before ", label));
    } else {
        // Normal mode - Line 1: Navigation keybindings (aligned with line 2)
        let has_selection = !app.filtered.is_empty();

        // Aligned columns - each section padded to match line 2:
        // Col1: 21 chars (" Enter " + " view/actions "), Col2: 11 (" / " + " dir    ")
        // Col3: 14 (" C-f " + " filter "), Col4: 17 (" C-s " + " time-sort  ")
        nav_spans.extend([
            Span::styled(" ↑↓ ", keycap),            // 4 chars
            Span::styled(" nav             ", label), // 17 chars = 21 total
            Span::styled("│ ", dim),
            Span::styled(" PgUp/Dn ", keycap),       // 9 chars
            Span::styled("  ", label),               // 2 chars = 11 total
        ]);

        if has_selection {
            nav_spans.extend([
                Span::styled("│ ", dim),
                Span::styled(" Home/End ", keycap),  // 10 chars
                Span::styled("    ", label),         // 4 chars = 14 total
                Span::styled("│ ", dim),
                Span::styled(" C-g ", keycap),       // 5 chars
                Span::styled(" goto        ", label), // 12 chars = 17 total
            ]);
        }
    }

    let nav_line = Line::from(nav_spans);
    frame.render_widget(Paragraph::new(nav_line), nav_area);

    // Line 2: Action shortcuts (only in normal mode)
    let mut action_spans: Vec<Span> = Vec::new();

    if app.input_mode.is_none() && !app.command_mode {
        let has_selection = !app.filtered.is_empty();

        if has_selection {
            action_spans.extend([
                Span::styled(" Enter ", keycap),      // 7 chars
                Span::styled(" view/actions ", label), // 14 chars = 21 total
                Span::styled("│ ", dim),
            ]);
        }

        action_spans.extend([
            Span::styled(" / ", keycap),             // 3 chars
            Span::styled(" dir    ", label),         // 8 chars = 11 total
            Span::styled("│ ", dim),
            Span::styled(" C-f ", keycap),           // 5 chars
            Span::styled(" filter  ", label),        // 9 chars = 14 total
            Span::styled("│ ", dim),
            Span::styled(" C-s ", keycap),           // 5 chars
            Span::styled(if app.sort_by_time { " match-sort  " } else { " time-sort   " }, label), // 12 chars = 17 total
            Span::styled("│ ", dim),
            Span::styled(" Esc ", keycap),
            Span::styled(" quit", label),
        ]);
    }

    let action_line = Line::from(action_spans);
    frame.render_widget(Paragraph::new(action_line), action_area);

    // Third row: annotation legend (if needed) + active filter indicators
    if needs_third_row {
        let mut row3_spans: Vec<Span> = Vec::new();

        // Annotation legend (if annotations exist in results)
        if show_legend {
            row3_spans.extend([
                Span::styled("  ", dim),
                Span::styled("(c)", Style::default().fg(t.dim_fg)),
                Span::styled(" continued  ", dim),
                Span::styled("(t)", Style::default().fg(t.dim_fg)),
                Span::styled(" trimmed  ", dim),
                Span::styled("(s)", Style::default().fg(t.dim_fg)),
                Span::styled(" sub-agent", dim),
            ]);
        }

        // Active filters
        if !app.include_original {
            row3_spans.push(Span::styled(" [-orig]", filter_active));
        }
        if app.include_sub {
            row3_spans.push(Span::styled(" [+sub]", filter_active));
        }
        if !app.include_trimmed {
            row3_spans.push(Span::styled(" [-trim]", filter_active));
        }
        if !app.include_continued {
            row3_spans.push(Span::styled(" [-cont]", filter_active));
        }
        if let Some(ref agent) = app.filter_agent {
            row3_spans.push(Span::styled(format!(" [{}]", agent), filter_active));
        }
        if let Some(min) = app.filter_min_lines {
            row3_spans.push(Span::styled(format!(" [≥{}L]", min), filter_active));
        }
        if let Some(ref date) = app.filter_after_date_display {
            row3_spans.push(Span::styled(format!(" [>{}]", date), filter_active));
        }
        if let Some(ref date) = app.filter_before_date_display {
            row3_spans.push(Span::styled(format!(" [<{}]", date), filter_active));
        }

        let row3 = Paragraph::new(Line::from(row3_spans));
        frame.render_widget(row3, status_layout[2]);
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

    // Strip quotes from query for keyword extraction (phrase search still works via Tantivy)
    let query_clean = query.trim_matches('"').trim_matches('\'');
    let query_lower = query_clean.to_lowercase();
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

/// Highlight multiple keywords in text (from space-separated query), returning styled spans.
fn highlight_keywords_in_line<'a>(
    text: &str,
    query: &str,
    base_style: Style,
    highlight_style: Style,
) -> Vec<Span<'a>> {
    if query.is_empty() || text.is_empty() {
        return vec![Span::styled(text.to_string(), base_style)];
    }

    // Strip quotes from query for keyword extraction
    let query_clean = query.trim_matches('"').trim_matches('\'');
    let query_lower = query_clean.to_lowercase();
    let keywords: Vec<&str> = query_lower.split_whitespace().collect();
    if keywords.is_empty() {
        return vec![Span::styled(text.to_string(), base_style)];
    }

    let text_lower = text.to_lowercase();
    let text_chars: Vec<char> = text.chars().collect();
    let text_lower_chars: Vec<char> = text_lower.chars().collect();

    // Find all keyword positions
    let mut highlights: Vec<(usize, usize)> = Vec::new();
    for keyword in &keywords {
        let kw_chars: Vec<char> = keyword.chars().collect();
        if kw_chars.is_empty() {
            continue;
        }
        let mut search_pos = 0;
        while search_pos + kw_chars.len() <= text_lower_chars.len() {
            let match_found = (0..kw_chars.len())
                .all(|i| text_lower_chars[search_pos + i] == kw_chars[i]);
            if match_found {
                highlights.push((search_pos, search_pos + kw_chars.len()));
                search_pos += kw_chars.len();
            } else {
                search_pos += 1;
            }
        }
    }

    // No highlights found
    if highlights.is_empty() {
        return vec![Span::styled(text.to_string(), base_style)];
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
    let mut spans: Vec<Span> = Vec::new();
    let mut current_pos = 0;

    for (start, end) in merged {
        if current_pos < start {
            let normal_text: String = text_chars[current_pos..start].iter().collect();
            spans.push(Span::styled(normal_text, base_style));
        }
        let highlight_text: String = text_chars[start..end].iter().collect();
        spans.push(Span::styled(highlight_text, highlight_style));
        current_pos = end;
    }

    if current_pos < text_chars.len() {
        let remaining: String = text_chars[current_pos..].iter().collect();
        spans.push(Span::styled(remaining, base_style));
    }

    spans
}

/// Render snippet with Tantivy's <b> tags as highlighted spans.
/// Parses <b>...</b> tags and applies highlight_style to matched text.
fn render_snippet_with_html_tags<'a>(
    text: &str,
    base_style: Style,
    highlight_style: Style,
) -> Vec<Span<'a>> {
    let mut spans: Vec<Span<'a>> = Vec::new();
    let mut current_pos = 0;
    let bytes = text.as_bytes();

    while current_pos < text.len() {
        // Find next <b> tag
        if let Some(start_tag_pos) = text[current_pos..].find("<b>") {
            let abs_start = current_pos + start_tag_pos;

            // Add text before <b> as normal
            if abs_start > current_pos {
                spans.push(Span::styled(text[current_pos..abs_start].to_string(), base_style));
            }

            // Find closing </b>
            let content_start = abs_start + 3; // skip "<b>"
            if let Some(end_tag_pos) = text[content_start..].find("</b>") {
                let content_end = content_start + end_tag_pos;
                // Add highlighted text
                spans.push(Span::styled(text[content_start..content_end].to_string(), highlight_style));
                current_pos = content_end + 4; // skip "</b>"
            } else {
                // No closing tag, treat rest as normal
                spans.push(Span::styled(text[current_pos..].to_string(), base_style));
                break;
            }
        } else {
            // No more <b> tags, add remaining text as normal
            spans.push(Span::styled(text[current_pos..].to_string(), base_style));
            break;
        }
    }

    if spans.is_empty() {
        spans.push(Span::styled(text.to_string(), base_style));
    }

    spans
}

/// Strip HTML tags from snippet for plain text output (e.g., JSON)
fn strip_html_tags(text: &str) -> String {
    text.replace("<b>", "").replace("</b>", "")
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

/// Parse a flexible date string into (YYYYMMDD, display_format) for comparison and display
/// Accepts: YYYYMMDD, YYYY-MM-DD, MM/DD/YYYY, MM/DD/YY, MM/DD, etc.
/// Returns (comparison_format, display_format) where comparison is YYYYMMDD and display
/// is a user-friendly format like "11/29/25"
fn parse_flexible_date(input: &str) -> Option<(String, String)> {
    use chrono::NaiveDate;

    let input = input.trim();
    if input.is_empty() {
        return None;
    }

    // Try various formats - 2-digit year MUST come before 4-digit for same separator
    // to avoid "11/29/25" being parsed as year 11, month 29, day 25
    let formats = [
        "%Y%m%d",      // 20251129
        "%Y-%m-%d",    // 2025-11-29
        "%m/%d/%y",    // 11/29/25 (2-digit year FIRST for / separator)
        "%m-%d-%y",    // 11-29-25 (2-digit year FIRST for - separator)
        "%m/%d/%Y",    // 11/29/2025
        "%m-%d-%Y",    // 11-29-2025
        "%Y/%m/%d",    // 2025/11/29 (4-digit year LAST for / separator)
    ];

    for fmt in formats {
        if let Ok(date) = NaiveDate::parse_from_str(input, fmt) {
            let comparison = date.format("%Y%m%d").to_string();
            let display = date.format("%m/%d/%y").to_string();
            return Some((comparison, display));
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
            let comparison = date.format("%Y%m%d").to_string();
            let display = date.format("%m/%d/%y").to_string();
            return Some((comparison, display));
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
    // Open index FIRST, then get schema from it (not build our own!)
    let index = Index::open_in_dir(index_path)
        .context("Failed to open index. Run 'aichat build-index' first.")?;

    let schema = index.schema();

    // Look up fields by name from the actual index schema
    let session_id_field = schema.get_field("session_id").context("missing session_id")?;
    let agent_field = schema.get_field("agent").context("missing agent")?;
    let project_field = schema.get_field("project").context("missing project")?;
    let branch_field = schema.get_field("branch").context("missing branch")?;
    let cwd_field = schema.get_field("cwd").context("missing cwd")?;
    let created_field = schema.get_field("created").context("missing created")?;
    let modified_field = schema.get_field("modified").context("missing modified")?;
    let lines_field = schema.get_field("lines").context("missing lines")?;
    let export_path_field = schema.get_field("export_path").context("missing export_path")?;
    let first_msg_role_field = schema.get_field("first_msg_role").context("missing first_msg_role")?;
    let first_msg_content_field = schema.get_field("first_msg_content").context("missing first_msg_content")?;
    let last_msg_role_field = schema.get_field("last_msg_role").context("missing last_msg_role")?;
    let last_msg_content_field = schema.get_field("last_msg_content").context("missing last_msg_content")?;
    let derivation_type_field = schema.get_field("derivation_type").context("missing derivation_type")?;
    let is_sidechain_field = schema.get_field("is_sidechain").context("missing is_sidechain")?;
    // claude_home may not exist in older indexes, so make it optional
    let claude_home_field = schema.get_field("claude_home").ok();

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

        // Get claude_home if field exists, otherwise empty string
        let claude_home = claude_home_field
            .map(|f| get_text(f))
            .unwrap_or_default();

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
            claude_home,
        });
    }

    sessions.sort_by(|a, b| b.modified.cmp(&a.modified));
    sessions.truncate(limit);

    Ok(sessions)
}

/// Search Tantivy index for sessions matching keyword query.
/// Returns (snippets_map, ranked_session_ids) where:
/// - snippets_map: session_id -> snippet for lookup
/// - ranked_session_ids: session_ids in score order (highest first)
fn search_tantivy(
    index_path: &str,
    query_str: &str,
    filter_claude_home: Option<&str>,
    filter_codex_home: Option<&str>,
) -> (HashMap<String, String>, Vec<String>) {
    // Return empty if query is empty
    if query_str.trim().is_empty() {
        return (HashMap::new(), Vec::new());
    }

    let result: Option<(HashMap<String, String>, Vec<String>)> = (|| {
        let index = Index::open_in_dir(index_path).ok()?;
        let schema = index.schema();

        // Get fields for search and ranking
        let content_field = schema.get_field("content").ok()?;
        let session_id_field = schema.get_field("session_id").ok()?;
        let modified_field = schema.get_field("modified").ok()?;
        let claude_home_field = schema.get_field("claude_home").ok();

        let reader = index
            .reader_builder()
            .reload_policy(ReloadPolicy::OnCommitWithDelay)
            .try_into()
            .ok()?;
        let searcher = reader.searcher();

        // Create query parser for content field
        let query_parser = QueryParser::for_index(&index, vec![content_field]);

        // Parse the base query with lenient parsing
        let base_query = query_parser.parse_query_lenient(query_str).0;

        // Phrase boosting: multi-word queries get 5x boost for exact phrase match
        let words: Vec<&str> = query_str.split_whitespace().collect();
        let content_query: Box<dyn tantivy::query::Query> = if words.len() > 1 {
            // Create phrase query for exact match
            let terms: Vec<Term> = words
                .iter()
                .map(|w| Term::from_field_text(content_field, &w.to_lowercase()))
                .collect();
            let phrase_query = PhraseQuery::new(terms);
            let boosted_phrase = BoostQuery::new(Box::new(phrase_query), 5.0);

            // Combine: boosted phrase OR base query
            Box::new(BooleanQuery::new(vec![
                (Occur::Should, Box::new(boosted_phrase) as Box<dyn tantivy::query::Query>),
                (Occur::Should, Box::new(base_query) as Box<dyn tantivy::query::Query>),
            ]))
        } else {
            Box::new(base_query)
        };

        // Build final query with claude_home filter if field exists and filters provided
        let final_query: Box<dyn tantivy::query::Query> = if let Some(home_field) = claude_home_field {
            // Build home filter: match either claude_home OR codex_home
            let mut home_clauses: Vec<(Occur, Box<dyn tantivy::query::Query>)> = Vec::new();

            if let Some(ch) = filter_claude_home {
                let term = Term::from_field_text(home_field, ch);
                home_clauses.push((Occur::Should, Box::new(TermQuery::new(term, IndexRecordOption::Basic))));
            }
            if let Some(cx) = filter_codex_home {
                let term = Term::from_field_text(home_field, cx);
                home_clauses.push((Occur::Should, Box::new(TermQuery::new(term, IndexRecordOption::Basic))));
            }

            if home_clauses.is_empty() {
                // No home filter specified, just use content query
                content_query
            } else {
                // Combine: content query AND (claude_home OR codex_home)
                let home_filter = BooleanQuery::new(home_clauses);
                Box::new(BooleanQuery::new(vec![
                    (Occur::Must, content_query),
                    (Occur::Must, Box::new(home_filter) as Box<dyn tantivy::query::Query>),
                ]))
            }
        } else {
            // No claude_home field in schema, just use content query
            content_query
        };

        // Search with high limit
        let top_docs = searcher.search(&*final_query, &TopDocs::with_limit(2000)).ok()?;

        // Create snippet generator from the query (re-parse since base_query was moved)
        let snippet_query = query_parser.parse_query_lenient(query_str).0;
        let snippet_generator: Option<SnippetGenerator> = SnippetGenerator::create(&searcher, &*snippet_query, content_field)
            .ok()
            .map(|mut g| { g.set_max_num_chars(200); g });

        // Fallback: extract keywords for manual snippet extraction if generator unavailable
        let query_clean = query_str.trim_matches('"').trim_matches('\'');
        let query_lower = query_clean.to_lowercase();
        let keywords: Vec<&str> = query_lower.split_whitespace().collect();

        // Recency ranking: 7-day half-life exponential decay
        let now = Utc::now().timestamp() as f64;
        let half_life_secs = 7.0 * 24.0 * 3600.0; // 7 days

        // Collect results with scores and apply recency boost
        let mut scored_results: Vec<(f32, String, String)> = top_docs
            .iter()
            .filter_map(|(score, doc_address)| {
                let doc: tantivy::TantivyDocument = searcher.doc(*doc_address).ok()?;
                let session_id = doc.get_first(session_id_field)?.as_str()?.to_string();
                let content = doc.get_first(content_field)?.as_str()?;
                let modified = doc.get_first(modified_field)?.as_str().unwrap_or("");

                // Parse modified timestamp and compute recency boost
                let modified_ts = DateTime::parse_from_rfc3339(modified)
                    .map(|dt| dt.timestamp() as f64)
                    .unwrap_or(0.0);
                let age = (now - modified_ts).max(0.0);
                let recency_mult = 1.0 + (-age / half_life_secs).exp();

                let final_score = *score * recency_mult as f32;
                // Use Tantivy's snippet generator if available, else fallback to manual extraction
                // Keep <b> tags for highlighting - they'll be parsed when rendering
                let snippet = if let Some(ref gen) = snippet_generator {
                    let tantivy_snippet = gen.snippet(content);
                    let html = tantivy_snippet.to_html();
                    if html.is_empty() {
                        // Fallback if Tantivy snippet is empty
                        extract_snippet(content, &keywords, 100)
                    } else {
                        html
                    }
                } else {
                    extract_snippet(content, &keywords, 100)
                };
                Some((final_score, session_id, snippet))
            })
            .collect();

        // Re-sort by final score (descending) - recency-adjusted ranking
        scored_results.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));

        // Build both the snippet map and the ranked ID list
        let mut snippets: HashMap<String, String> = HashMap::new();
        let mut ranked_ids: Vec<String> = Vec::new();
        for (_, id, snippet) in scored_results {
            ranked_ids.push(id.clone());
            snippets.insert(id, snippet);
        }

        Some((snippets, ranked_ids))
    })();

    result.unwrap_or_default()
}

/// Extract a snippet from content containing the keywords.
/// For multi-word queries, prioritizes finding the exact phrase over scattered keywords.
/// Returns a window of text around the best match.
fn extract_snippet(content: &str, keywords: &[&str], window_chars: usize) -> String {
    let content_lower = content.to_lowercase();
    let chars: Vec<char> = content.chars().collect();
    let chars_lower: Vec<char> = content_lower.chars().collect();

    // Helper to build snippet around a character position
    let build_snippet = |match_start: usize, match_len: usize| -> String {
        let half_window = window_chars / 2;
        let start_idx = match_start.saturating_sub(half_window);
        let end_idx = (match_start + match_len + half_window).min(chars.len());

        // Find word boundaries (whitespace)
        let snippet_start = (0..start_idx)
            .rev()
            .find(|&idx| chars[idx].is_whitespace())
            .map(|idx| idx + 1)
            .unwrap_or(start_idx);
        let snippet_end = (end_idx..chars.len())
            .find(|&idx| chars[idx].is_whitespace())
            .unwrap_or(end_idx);

        let snippet_text: String = chars[snippet_start..snippet_end].iter().collect();
        let mut snippet = String::new();
        if snippet_start > 0 {
            snippet.push_str("...");
        }
        snippet.push_str(snippet_text.trim());
        if snippet_end < chars.len() {
            snippet.push_str("...");
        }
        snippet
    };

    // For multi-word queries, first try to find the exact phrase
    if keywords.len() > 1 {
        let phrase = keywords.join(" ");
        let phrase_chars: Vec<char> = phrase.chars().collect();
        for i in 0..chars_lower.len().saturating_sub(phrase_chars.len() - 1) {
            let matches = phrase_chars
                .iter()
                .enumerate()
                .all(|(j, &pc)| chars_lower.get(i + j) == Some(&pc));
            if matches {
                return build_snippet(i, phrase_chars.len());
            }
        }
    }

    // Fallback: find the first keyword occurrence (by character index)
    for keyword in keywords {
        let kw_chars: Vec<char> = keyword.chars().collect();
        if kw_chars.is_empty() {
            continue;
        }

        // Search for keyword in lowercased char array
        for i in 0..chars_lower.len().saturating_sub(kw_chars.len() - 1) {
            let matches = kw_chars
                .iter()
                .enumerate()
                .all(|(j, &kc)| chars_lower.get(i + j) == Some(&kc));
            if matches {
                return build_snippet(i, kw_chars.len());
            }
        }
    }

    // Fallback: return start of content
    let end_idx = window_chars.min(chars.len());
    let snippet_end = (0..end_idx)
        .rev()
        .find(|&idx| chars[idx].is_whitespace())
        .unwrap_or(end_idx);
    let snippet_text: String = chars[..snippet_end].iter().collect();
    format!("{}...", snippet_text)
}

// ============================================================================
// JSONL Parsing for Full Conversation View
// ============================================================================

/// Parse JSONL file content into conversational text format.
/// Handles both Claude and Codex JSONL formats.
/// Returns text with "> " prefix for user messages and "⏺ " for assistant messages.
fn parse_jsonl_to_conversation(content: &str) -> String {
    let mut output = String::new();
    let mut last_role: Option<String> = None;

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        // Parse JSON line
        let json: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };

        // Try to extract message based on format
        let (role, text) = extract_message_from_json(&json);

        if let (Some(role), Some(text)) = (role, text) {
            // Skip empty messages
            if text.trim().is_empty() {
                continue;
            }

            // Add blank line between different roles
            if let Some(ref last) = last_role {
                if last != &role && !output.is_empty() {
                    output.push('\n');
                }
            }

            // Format based on role
            let prefix = if role == "user" { "> " } else { "⏺ " };

            // Split text into lines and prefix the first line
            let lines: Vec<&str> = text.lines().collect();
            for (i, line) in lines.iter().enumerate() {
                if i == 0 {
                    output.push_str(prefix);
                    output.push_str(line);
                } else {
                    // Continuation lines - indent to align with content
                    output.push_str("  ");
                    output.push_str(line);
                }
                output.push('\n');
            }

            last_role = Some(role);
        }
    }

    output
}

/// Extract role and text from a JSON entry (handles Claude and Codex formats).
fn extract_message_from_json(json: &serde_json::Value) -> (Option<String>, Option<String>) {
    let entry_type = json.get("type").and_then(|v| v.as_str());

    match entry_type {
        // Claude format: {"type": "user" | "assistant", "message": {...}}
        Some("user") | Some("assistant") => {
            let role = entry_type.map(|s| s.to_string());
            let text = extract_claude_message_text(json);
            (role, text)
        }

        // Codex format: {"type": "response_item", "payload": {"role": "user" | "assistant", ...}}
        Some("response_item") => {
            if let Some(payload) = json.get("payload") {
                let role = payload
                    .get("role")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                let text = extract_codex_message_text(payload);
                (role, text)
            } else {
                (None, None)
            }
        }

        // Codex format: {"type": "event_msg", "payload": {"type": "user_message", "message": "..."}}
        Some("event_msg") => {
            if let Some(payload) = json.get("payload") {
                let msg_type = payload.get("type").and_then(|v| v.as_str());
                match msg_type {
                    Some("user_message") => {
                        let text = payload
                            .get("message")
                            .and_then(|v| v.as_str())
                            .map(|s| s.to_string());
                        (Some("user".to_string()), text)
                    }
                    _ => (None, None),
                }
            } else {
                (None, None)
            }
        }

        _ => (None, None),
    }
}

/// Extract text from Claude message format.
/// User: {"message": {"content": "text"}}
/// Assistant: {"message": {"content": [{"type": "text", "text": "..."}]}}
fn extract_claude_message_text(json: &serde_json::Value) -> Option<String> {
    let message = json.get("message")?;
    let content = message.get("content")?;

    // User messages have string content
    if let Some(text) = content.as_str() {
        return Some(text.to_string());
    }

    // Assistant messages have array of content blocks
    if let Some(blocks) = content.as_array() {
        let mut texts = Vec::new();
        for block in blocks {
            if let Some(block_type) = block.get("type").and_then(|v| v.as_str()) {
                match block_type {
                    "text" => {
                        if let Some(text) = block.get("text").and_then(|v| v.as_str()) {
                            texts.push(text.to_string());
                        }
                    }
                    "tool_use" => {
                        // Optionally show tool calls (condensed)
                        if let Some(name) = block.get("name").and_then(|v| v.as_str()) {
                            texts.push(format!("[Tool: {}]", name));
                        }
                    }
                    _ => {}
                }
            }
        }
        if !texts.is_empty() {
            return Some(texts.join("\n"));
        }
    }

    None
}

/// Extract text from Codex message format.
/// {"content": [{"type": "input_text" | "output_text", "text": "..."}]}
fn extract_codex_message_text(payload: &serde_json::Value) -> Option<String> {
    let content = payload.get("content")?.as_array()?;

    let mut texts = Vec::new();
    for block in content {
        if let Some(block_type) = block.get("type").and_then(|v| v.as_str()) {
            match block_type {
                "input_text" | "output_text" => {
                    if let Some(text) = block.get("text").and_then(|v| v.as_str()) {
                        texts.push(text.to_string());
                    }
                }
                "tool_use" | "function_call" => {
                    if let Some(name) = block.get("name").and_then(|v| v.as_str()) {
                        texts.push(format!("[Tool: {}]", name));
                    }
                }
                _ => {}
            }
        }
    }

    if !texts.is_empty() {
        Some(texts.join("\n"))
    } else {
        None
    }
}

// ============================================================================
// JSON Output
// ============================================================================

fn output_json(app: &App, limit: Option<usize>) -> Result<()> {
    use serde_json::json;

    // Output as JSONL (one JSON object per line) for easy piping and jq processing
    for &idx in app.filtered.iter().take(limit.unwrap_or(usize::MAX)) {
        let s = &app.sessions[idx];
        let obj = json!({
            "session_id": s.session_id,
            "agent": s.agent,
            "project": s.project,
            "branch": s.branch,
            "cwd": s.cwd,
            "lines": s.lines,
            "created": s.created,
            "modified": s.modified,
            "first_msg": s.first_msg_content,
            "last_msg": s.last_msg_content,
            "file_path": s.export_path,
            "derivation_type": s.derivation_type,
            "is_sidechain": s.is_sidechain,
            "snippet": app.search_snippets.get(&s.session_id).map(|s| strip_html_tags(s)),
        });
        println!("{}", serde_json::to_string(&obj)?);
    }
    Ok(())
}

// CLI Options
// ============================================================================

struct CliOptions {
    output_file: Option<std::path::PathBuf>,
    claude_home: Option<String>,
    codex_home: Option<String>,
    global_search: bool,
    filter_dir: Option<String>, // --dir: filter to specific directory (overrides -g)
    num_results: Option<usize>,
    include_original: bool,
    include_sub: bool,
    include_trimmed: bool,
    include_continued: bool,
    min_lines: Option<i64>,
    after_date: Option<String>,
    before_date: Option<String>,
    agent_filter: Option<String>,
    query: Option<String>,
    json_output: bool,
}

impl CliOptions {
    /// Check if any session type filter flag was explicitly specified on CLI.
    /// Used to distinguish between "no flags = use defaults" vs "explicit flags = use only those".
    fn any_type_flag_specified(&self) -> bool {
        self.include_original || self.include_sub || self.include_trimmed || self.include_continued
    }
}

fn parse_cli_args() -> CliOptions {
    let args: Vec<String> = std::env::args().collect();

    // Helper to get value after a flag
    let get_arg_value = |flag: &str| -> Option<String> {
        args.iter()
            .position(|a| a == flag)
            .and_then(|i| args.get(i + 1))
            .map(|s| s.to_string())
    };

    // Helper to check if flag exists
    let has_flag = |flag: &str| -> bool {
        args.iter().any(|a| a == flag)
    };

    // Output file is the LAST positional arg that's a path (contains / or ends with .json)
    // Using rfind to get the last match, avoiding --claude-home/--codex-home values
    let output_file = args.iter()
        .skip(1)  // skip binary name
        .filter(|a| !a.starts_with('-') && (a.contains('/') || a.ends_with(".json")))
        .last()
        .map(std::path::PathBuf::from);

    let claude_home = get_arg_value("--claude-home")
        .or_else(|| std::env::var("CLAUDE_CONFIG_DIR").ok())
        .or_else(|| {
            dirs::home_dir().map(|h| h.join(".claude").to_string_lossy().to_string())
        });

    let codex_home = get_arg_value("--codex-home")
        .or_else(|| std::env::var("CODEX_HOME").ok())
        .or_else(|| {
            dirs::home_dir().map(|h| h.join(".codex").to_string_lossy().to_string())
        });

    let global_search = has_flag("--global") || has_flag("-g");

    // --dir overrides -g: filter to specific directory
    let filter_dir = get_arg_value("--dir").map(|dir| {
        // Expand ~ to home directory
        if dir.starts_with('~') {
            let home = std::env::var("HOME").unwrap_or_default();
            format!("{}{}", home, &dir[1..])
        } else if dir.starts_with('/') {
            dir
        } else {
            // Relative path - make absolute from cwd
            let cwd = std::env::current_dir()
                .map(|p| p.to_string_lossy().to_string())
                .unwrap_or_default();
            format!("{}/{}", cwd, dir)
        }
    });

    let num_results = get_arg_value("--num-results")
        .or_else(|| get_arg_value("-n"))
        .and_then(|s| s.parse().ok());

    // Filter inclusion flags (if specified, include that type)
    let include_original = has_flag("--original");
    let include_sub = has_flag("--sub-agent");
    let include_trimmed = has_flag("--trimmed");
    let include_continued = has_flag("--continued");

    let min_lines = get_arg_value("--min-lines")
        .and_then(|s| s.parse().ok());

    let after_date = get_arg_value("--after");
    let before_date = get_arg_value("--before");

    let agent_filter = get_arg_value("--agent");

    let query = get_arg_value("--query");

    let json_output = has_flag("--json");

    CliOptions {
        output_file,
        claude_home,
        codex_home,
        global_search,
        filter_dir,
        num_results,
        include_original,
        include_sub,
        include_trimmed,
        include_continued,
        min_lines,
        after_date,
        before_date,
        agent_filter,
        query,
        json_output,
    }
}

// Main
// ============================================================================

fn main() -> Result<()> {
    let cli = parse_cli_args();

    let index_path = dirs::home_dir()
        .context("Could not find home directory")?
        .join(".cctools")
        .join("search-index");

    const SESSION_LIMIT: usize = 100_000;
    let sessions = load_sessions(index_path.to_str().unwrap(), SESSION_LIMIT)?;

    // Warn if we hit the limit - sessions may have been truncated
    if sessions.len() >= SESSION_LIMIT && !cli.json_output {
        eprintln!("⚠️  WARNING: Session limit ({}) reached!", SESSION_LIMIT);
        eprintln!("⚠️  Some sessions may have been dropped.");
        eprintln!();
    }

    if sessions.is_empty() {
        if cli.json_output {
            println!("[]");
            return Ok(());
        }
        eprintln!("No sessions found. Run 'aichat search' to auto-index.");
        return Ok(());
    }

    // Show home filters (only for TUI mode)
    if !cli.json_output {
        if let Some(ref home) = cli.claude_home {
            eprintln!("Claude home filter: {}", home);
        }
        if let Some(ref home) = cli.codex_home {
            eprintln!("Codex home filter: {}", home);
        }

        let claude_count = sessions.iter().filter(|s| s.agent != "codex").count();
        let codex_count = sessions.iter().filter(|s| s.agent == "codex").count();
        eprintln!("Sessions in index: {} Claude, {} Codex", claude_count, codex_count);
    }

    // Create app with CLI options pre-configured
    let mut app = App::new_with_options(
        sessions,
        index_path.to_string_lossy().to_string(),
        &cli,
    );

    // JSON output mode - output filtered results and exit
    if cli.json_output {
        return output_json(&app, cli.num_results);
    }

    // Interactive TUI mode
    enable_raw_mode()?;
    let mut stdout = stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    loop {
        terminal.draw(|f| render(f, &mut app))?;

        if app.should_quit {
            break;
        }

        while event::poll(Duration::from_millis(0))? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press {
                    // Handle exit confirmation dialog
                    if app.confirming_exit {
                        match key.code {
                            KeyCode::Enter | KeyCode::Char('y') | KeyCode::Char('Y') => {
                                app.should_quit = true;
                            }
                            KeyCode::Esc | KeyCode::Char('n') | KeyCode::Char('N') => {
                                app.confirming_exit = false;
                            }
                            _ => {}
                        }
                        continue;
                    }

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
                    } else if app.scope_modal_open {
                        // Handle scope modal
                        match key.code {
                            KeyCode::Esc => {
                                app.scope_modal_open = false;
                            }
                            KeyCode::Char('/') => {
                                app.scope_modal_open = false;
                            }
                            KeyCode::Up | KeyCode::Char('k') => {
                                if app.scope_modal_selected > 0 {
                                    app.scope_modal_selected -= 1;
                                }
                            }
                            KeyCode::Down | KeyCode::Char('j') => {
                                if app.scope_modal_selected < 2 {
                                    app.scope_modal_selected += 1;
                                }
                            }
                            KeyCode::Enter | KeyCode::Char(' ') => {
                                match app.scope_modal_selected {
                                    0 => {
                                        // Global
                                        app.scope_global = true;
                                        app.filter_dir = None;
                                        app.filter();
                                        app.scope_modal_open = false;
                                    }
                                    1 => {
                                        // Current directory
                                        app.scope_global = false;
                                        app.filter_dir = None;
                                        app.filter();
                                        app.scope_modal_open = false;
                                    }
                                    2 => {
                                        // Custom directory - enter input mode
                                        app.scope_modal_open = false;
                                        app.input_mode = Some(InputMode::ScopeDir);
                                        // Pre-fill with current filter_dir or launch_cwd
                                        app.input_buffer = app.filter_dir.clone()
                                            .unwrap_or_else(|| app.launch_cwd.clone());
                                    }
                                    _ => {}
                                }
                            }
                            KeyCode::Char('1') => {
                                app.scope_global = true;
                                app.filter_dir = None;
                                app.filter();
                                app.scope_modal_open = false;
                            }
                            KeyCode::Char('2') => {
                                app.scope_global = false;
                                app.filter_dir = None;
                                app.filter();
                                app.scope_modal_open = false;
                            }
                            KeyCode::Char('3') => {
                                // Custom directory - enter input mode
                                app.scope_modal_open = false;
                                app.input_mode = Some(InputMode::ScopeDir);
                                app.input_buffer = app.filter_dir.clone()
                                    .unwrap_or_else(|| app.launch_cwd.clone());
                            }
                            _ => {}
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
                                    let raw_content = std::fs::read_to_string(&session.export_path)
                                        .unwrap_or_else(|_| "Error loading content".to_string());
                                    // Parse JSONL files into conversational format
                                    app.full_content = if session.export_path.ends_with(".jsonl") {
                                        parse_jsonl_to_conversation(&raw_content)
                                    } else {
                                        raw_content
                                    };
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
                                            app.filter_after_date_display = None;
                                        } else if let Some((cmp, disp)) = parse_flexible_date(&app.input_buffer) {
                                            app.filter_after_date = Some(cmp);
                                            app.filter_after_date_display = Some(disp);
                                        }
                                        app.filter();
                                    }
                                    InputMode::BeforeDate => {
                                        if app.input_buffer.is_empty() {
                                            app.filter_before_date = None;
                                            app.filter_before_date_display = None;
                                        } else if let Some((cmp, disp)) = parse_flexible_date(&app.input_buffer) {
                                            app.filter_before_date = Some(cmp);
                                            app.filter_before_date_display = Some(disp);
                                        }
                                        app.filter();
                                    }
                                    InputMode::ScopeDir => {
                                        if app.input_buffer.is_empty() {
                                            // Empty = global
                                            app.scope_global = true;
                                            app.filter_dir = None;
                                        } else {
                                            // Expand ~ to home directory
                                            let path = if app.input_buffer.starts_with('~') {
                                                let home = std::env::var("HOME").unwrap_or_default();
                                                format!("{}{}", home, &app.input_buffer[1..])
                                            } else if app.input_buffer.starts_with('/') {
                                                app.input_buffer.clone()
                                            } else {
                                                // Relative path - make absolute from launch_cwd
                                                format!("{}/{}", app.launch_cwd, app.input_buffer)
                                            };
                                            app.filter_dir = Some(path);
                                            app.scope_global = false;
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
                            KeyCode::Char(c) if mode == InputMode::AfterDate || mode == InputMode::BeforeDate || mode == InputMode::ScopeDir => {
                                // Accept any character for flexible input
                                app.input_buffer.push(c);
                            }
                            KeyCode::Backspace if mode == InputMode::MinLines || mode == InputMode::JumpToLine || mode == InputMode::AfterDate || mode == InputMode::BeforeDate || mode == InputMode::ScopeDir => {
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
                                app.filter_after_date_display = None;
                                app.filter_before_date = None;
                                app.filter_before_date_display = None;
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
                            KeyCode::Char('/') => {
                                // Open scope modal
                                app.scope_modal_open = true;
                                app.scope_modal_selected = 0;
                            }
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
                            KeyCode::Char('s') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                                // Toggle sort mode: relevance <-> time
                                app.sort_by_time = !app.sort_by_time;
                                app.filter(); // Re-sort results
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
        if let Some(ref out_path) = cli.output_file {
            std::fs::write(out_path, &json)?;
        } else {
            println!("{}", json);
        }
    }

    Ok(())
}
