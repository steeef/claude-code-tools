---
name: session-search
description: Search previous code agent sessions (Claude-Code or Codex-CLI) for specific work, decisions, or code patterns. Use when user asks about previous sessions or needs context from earlier conversations. Delegates to subagent to preserve main context.
---

<objective>
Search previous Claude Code sessions for specific work, decisions, or code patterns. Uses a subagent to keep context clean.
</objective>

<quick_start>
Use the session-searcher subagent via the Task tool to search previous sessions:

```
Task(subagent_type="session-searcher", prompt="Find sessions where we discussed [topic]")
```

The subagent handles all searching and returns only a concise summary.

See `plugins/aichat/agents/session-searcher.md` for subagent implementation details.
</quick_start>

<workflow>
1. Invoke the `session-searcher` subagent using the Task tool
2. Provide a clear search query describing what you're looking for
3. The subagent searches, parses results, and returns a summary
4. Use session IDs from the summary if you need to read specific sessions directly
</workflow>

<success_criteria>
- Subagent returns a focused summary (not raw JSON)
- User receives relevant session references with IDs and dates
- Search executed without spawning interactive UI
- Main conversation context remains clean
</success_criteria>

<example>
User asks: "What design direction did we decide on for the terminal UI?"

You invoke:
```
Task(
  subagent_type="session-searcher",
  prompt="Find sessions discussing terminal UI design direction, especially any decisions about styling, colors, or aesthetic approach"
)
```

You receive: A 300-word summary with key findings and session references (not 260 lines of JSON)
</example>

<fallback>
If the subagent is not available, you can search directly:

```bash
aichat search --json "query terms"
```

Requirements:
- MUST use `--json` flag (never spawn interactive UI)
- Parse JSON output with `jq` or similar
- Summarize results before presenting to user

Installation (if aichat command not found):
```bash
uv tool install claude-code-tools   # Python package
cargo install aichat-search         # Rust search TUI
```
</fallback>

<constraints>
- ALWAYS prefer the subagent approach for context efficiency
- NEVER dump raw JSON into the main conversation
- MUST summarize findings concisely
</constraints>
