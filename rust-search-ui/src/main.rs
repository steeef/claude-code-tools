//! Minimal POC: Rust TUI for session search with Node handoff.
//!
//! This displays recent sessions from the Tantivy index and hands off
//! the selected session to the Node UI via stdout JSON.

use anyhow::{Context, Result};
use crossterm::{
    event::{self, Event, KeyCode, KeyEventKind},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Layout},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph},
    Frame, Terminal,
};
use serde::Serialize;
use std::io::{self, stdout};
use tantivy::{
    collector::TopDocs,
    query::AllQuery,
    schema::{Schema, Value, STORED, TEXT},
    Index, ReloadPolicy,
};

/// Session info extracted from the index.
#[derive(Debug, Clone, Serialize)]
struct Session {
    session_id: String,
    agent: String,
    project: String,
    branch: String,
    modified: String,
    lines: i64,
    export_path: String,
    first_msg_role: String,
    first_msg_content: String,
    last_msg_role: String,
    last_msg_content: String,
}

/// App state.
struct App {
    sessions: Vec<Session>,
    list_state: ListState,
    selected: Option<Session>,
    should_quit: bool,
}

impl App {
    fn new(sessions: Vec<Session>) -> Self {
        let mut list_state = ListState::default();
        if !sessions.is_empty() {
            list_state.select(Some(0));
        }
        Self {
            sessions,
            list_state,
            selected: None,
            should_quit: false,
        }
    }

    fn next(&mut self) {
        if self.sessions.is_empty() {
            return;
        }
        let i = match self.list_state.selected() {
            Some(i) => (i + 1) % self.sessions.len(),
            None => 0,
        };
        self.list_state.select(Some(i));
    }

    fn previous(&mut self) {
        if self.sessions.is_empty() {
            return;
        }
        let i = match self.list_state.selected() {
            Some(i) => {
                if i == 0 {
                    self.sessions.len() - 1
                } else {
                    i - 1
                }
            }
            None => 0,
        };
        self.list_state.select(Some(i));
    }

    fn select(&mut self) {
        if let Some(i) = self.list_state.selected() {
            self.selected = Some(self.sessions[i].clone());
            self.should_quit = true;
        }
    }
}

/// Load sessions from the Tantivy index.
fn load_sessions(index_path: &str, limit: usize) -> Result<Vec<Session>> {
    // Build schema matching Python's search_index.py
    let mut schema_builder = Schema::builder();
    let session_id_field = schema_builder.add_text_field("session_id", TEXT | STORED);
    let agent_field = schema_builder.add_text_field("agent", TEXT | STORED);
    let project_field = schema_builder.add_text_field("project", TEXT | STORED);
    let branch_field = schema_builder.add_text_field("branch", TEXT | STORED);
    let _cwd_field = schema_builder.add_text_field("cwd", TEXT | STORED);
    let modified_field = schema_builder.add_text_field("modified", TEXT | STORED);
    let lines_field = schema_builder.add_i64_field("lines", STORED);
    let export_path_field = schema_builder.add_text_field("export_path", TEXT | STORED);
    // First and last message fields
    let first_msg_role_field = schema_builder.add_text_field("first_msg_role", TEXT | STORED);
    let first_msg_content_field = schema_builder.add_text_field("first_msg_content", TEXT | STORED);
    let last_msg_role_field = schema_builder.add_text_field("last_msg_role", TEXT | STORED);
    let last_msg_content_field = schema_builder.add_text_field("last_msg_content", TEXT | STORED);
    let _content_field = schema_builder.add_text_field("content", TEXT | STORED);
    let _schema = schema_builder.build();

    // Open existing index
    let index = Index::open_in_dir(index_path)
        .context("Failed to open index. Run 'aichat build-index' first.")?;

    let reader = index
        .reader_builder()
        .reload_policy(ReloadPolicy::OnCommitWithDelay)
        .try_into()
        .context("Failed to create reader")?;

    let searcher = reader.searcher();

    // Get all documents (we'll sort by modified in Rust)
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

        sessions.push(Session {
            session_id: get_text(session_id_field),
            agent: get_text(agent_field),
            project: get_text(project_field),
            branch: get_text(branch_field),
            modified: get_text(modified_field),
            lines,
            export_path: get_text(export_path_field),
            first_msg_role: get_text(first_msg_role_field),
            first_msg_content: get_text(first_msg_content_field),
            last_msg_role: get_text(last_msg_role_field),
            last_msg_content: get_text(last_msg_content_field),
        });
    }

    // Sort by modified (most recent first)
    sessions.sort_by(|a, b| b.modified.cmp(&a.modified));
    sessions.truncate(limit);

    Ok(sessions)
}

/// Render the UI.
fn render(frame: &mut Frame, app: &mut App) {
    use ratatui::layout::Direction;
    use ratatui::text::Text;
    use ratatui::widgets::Wrap;

    // Main horizontal split: left (session list) and right (preview)
    let main_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(frame.area());

    // Left side: session list + status bar
    let left_chunks =
        Layout::vertical([Constraint::Min(3), Constraint::Length(3)]).split(main_chunks[0]);

    // Session list
    let items: Vec<ListItem> = app
        .sessions
        .iter()
        .map(|s| {
            let agent_icon = if s.agent == "claude" { "●" } else { "■" };
            let line = Line::from(vec![
                Span::styled(
                    format!("{} ", agent_icon),
                    Style::default().fg(if s.agent == "claude" {
                        Color::Cyan
                    } else {
                        Color::Green
                    }),
                ),
                Span::raw(format!("{:<18} ", truncate(&s.project, 18))),
                Span::styled(
                    format!("{:<12} ", truncate(&s.session_id, 12)),
                    Style::default().fg(Color::DarkGray),
                ),
                Span::raw(format!("{}L", s.lines)),
            ]);
            ListItem::new(line)
        })
        .collect();

    let list = List::new(items)
        .block(
            Block::default()
                .title(" Sessions (↑↓ navigate, Enter select, q quit) ")
                .borders(Borders::ALL),
        )
        .highlight_style(
            Style::default()
                .add_modifier(Modifier::BOLD)
                .bg(Color::DarkGray),
        )
        .highlight_symbol("> ");

    frame.render_stateful_widget(list, left_chunks[0], &mut app.list_state);

    // Status bar
    let status = if let Some(i) = app.list_state.selected() {
        let s = &app.sessions[i];
        format!("{} | {} | {}", s.project, s.branch, s.modified)
    } else {
        "No sessions".to_string()
    };

    let status_widget =
        Paragraph::new(status).block(Block::default().borders(Borders::ALL).title(" Details "));

    frame.render_widget(status_widget, left_chunks[1]);

    // Right side: preview pane with first/last messages
    let preview_content = if let Some(i) = app.list_state.selected() {
        let s = &app.sessions[i];

        let first_role_style = if s.first_msg_role == "user" {
            Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)
        };

        let last_role_style = if s.last_msg_role == "user" {
            Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)
        };

        let first_label = if s.first_msg_role == "user" {
            "USER"
        } else {
            "ASSISTANT"
        };
        let last_label = if s.last_msg_role == "user" {
            "USER"
        } else {
            "ASSISTANT"
        };

        Text::from(vec![
            Line::from(Span::styled("─── First Message ───", Style::default().fg(Color::Blue))),
            Line::from(Span::styled(format!("[{}]", first_label), first_role_style)),
            Line::from(s.first_msg_content.clone()),
            Line::from(""),
            Line::from(Span::styled("─── Last Message ───", Style::default().fg(Color::Blue))),
            Line::from(Span::styled(format!("[{}]", last_label), last_role_style)),
            Line::from(s.last_msg_content.clone()),
        ])
    } else {
        Text::from("No session selected")
    };

    let preview = Paragraph::new(preview_content)
        .block(Block::default().title(" Preview ").borders(Borders::ALL))
        .wrap(Wrap { trim: true });

    frame.render_widget(preview, main_chunks[1]);
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() > max {
        format!("{}…", &s[..max - 1])
    } else {
        s.to_string()
    }
}

fn main() -> Result<()> {
    // Get index path
    let index_path = dirs::home_dir()
        .context("Could not find home directory")?
        .join(".claude")
        .join("search-index");

    // Get output file path from args (for IPC with Python)
    let args: Vec<String> = std::env::args().collect();
    let output_file = args.get(1).map(|s| std::path::PathBuf::from(s));

    // Load sessions
    let sessions = load_sessions(index_path.to_str().unwrap(), 50)?;

    if sessions.is_empty() {
        eprintln!("No sessions found. Run 'aichat export-all && aichat build-index' first.");
        return Ok(());
    }

    // Setup terminal
    enable_raw_mode()?;
    let mut stdout = stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    // Create app
    let mut app = App::new(sessions);

    // Event loop
    loop {
        terminal.draw(|f| render(f, &mut app))?;

        if app.should_quit {
            break;
        }

        if event::poll(std::time::Duration::from_millis(100))? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press {
                    match key.code {
                        KeyCode::Char('q') | KeyCode::Esc => {
                            app.should_quit = true;
                        }
                        KeyCode::Down | KeyCode::Char('j') => app.next(),
                        KeyCode::Up | KeyCode::Char('k') => app.previous(),
                        KeyCode::Enter => app.select(),
                        _ => {}
                    }
                }
            }
        }
    }

    // Restore terminal
    disable_raw_mode()?;
    execute!(io::stdout(), LeaveAlternateScreen)?;

    // Output selected session as JSON for Node handoff
    if let Some(session) = app.selected {
        let json = serde_json::to_string(&session)?;
        if let Some(out_path) = output_file {
            // Write to file for IPC
            std::fs::write(&out_path, &json)?;
        } else {
            // Write to stdout (for direct CLI use)
            println!("{}", json);
        }
    }

    Ok(())
}
