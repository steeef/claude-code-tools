# JSONL Session Log File Structure

This document explains how Claude Code session logs are organized in JSONL
format.

## File Format

Each line in the JSONL file is a separate JSON object representing one event
in the conversation. The file contains **496 total entries** in the example
session.

## Entry Types

There are 5 main types of entries (based on the `type` field):

| Type | Count | Purpose |
|------|-------|---------|
| `assistant` | 296 | Claude's responses, tool calls, and thinking |
| `user` | 161 | User messages and tool results |
| `file-history-snapshot` | 30 | File state snapshots |
| `summary` | 8 | Conversation summaries |
| `system` | 1 | System messages |

## Entry Structures

### 1. Assistant Messages (`type: "assistant"`)

**Top-level fields:**
- `type`: "assistant"
- `message`: Contains the actual message content
- `uuid`, `parentUuid`: For threading/history
- `sessionId`: Session identifier
- `timestamp`: ISO 8601 timestamp
- `cwd`: Current working directory
- `gitBranch`: Current git branch
- `version`: Format version
- `isSidechain`: Boolean
- `requestId`: Request identifier

**Message content array can contain:**

| Content Type | Count | Fields | Purpose |
|--------------|-------|--------|---------|
| `text` | 84 | `type`, `text` | Claude's text responses |
| `thinking` | 92 | `type`, `text` | Claude's reasoning |
| `tool_use` | 120 | `type`, `id`, `name`, `input` | Tool invocations |

**Tool Usage Example:**
```json
{
  "type": "tool_use",
  "id": "toolu_0161RuW6V4pkmipTpNnkaNfh",
  "name": "Task",
  "input": {
    "description": "Analyze session log file",
    "prompt": "...",
    "subagent_type": "Explore"
  }
}
```

### 2. User Messages (`type: "user"`)

**Two formats:**

**A) Simple text messages:**
```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": "Help me understand..."
  },
  "uuid": "...",
  ...
}
```

**B) Tool results (with enhanced metadata):**
```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_0161RuW6V4pkmipTpNnkaNfh",
        "content": "..." or [{"type": "text", "text": "..."}]
      }
    ]
  },
  "toolUseResult": { /* enhanced metadata */ },
  "uuid": "...",
  ...
}
```

**Message content can be:**
- `string`: Simple text messages (21 occurrences)
- `array` with `text` type: Formatted text (20 occurrences)
- `array` with `tool_result` type: Tool results (120 occurrences)

### 3. Tool Results Structure

Tool results are stored in user messages and contain:

**Standard fields:**
- `type`: "tool_result"
- `tool_use_id`: Links back to the tool_use entry (enables correlation)
- `content`: The actual result (string or array)

**Enhanced metadata in `toolUseResult` field:**

The `toolUseResult` field provides rich metadata about tool execution:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | "completed", "error", etc. |
| `content` | various | The actual tool output |
| `totalDurationMs` | number | Total execution time |
| `totalTokens` | number | Tokens used (for Task tool) |
| `totalToolUseCount` | number | Sub-tools used (for Task tool) |
| `usage` | object | Detailed token usage breakdown |
| `prompt` | string | Original prompt (for Task tool) |
| `commandName` | string | Command executed (for Bash tool) |
| `stdout` | string | Standard output (for Bash tool) |
| `stderr` | string | Standard error (for Bash tool) |
| `success` | boolean | Success status (for Bash tool) |
| `durationMs` | number | Execution time (for Bash tool) |
| `filePath` | string | File path (for Read/Write tools) |
| `truncated` | boolean | Whether content was truncated |
| `isImage` | boolean | Whether file is an image |
| `oldString`, `newString` | string | For Edit tool |
| `replaceAll` | boolean | For Edit tool |
| `structuredPatch` | object | Detailed edit information |
| `filenames` | array | Matched files (for Glob tool) |
| `numFiles` | number | Number of files (for Glob tool) |
| `oldTodos`, `newTodos` | array | For TodoWrite tool |
| `interrupted` | boolean | Whether execution was interrupted |
| `userModified` | boolean | Whether user modified the result |

**Note:** Some toolUseResult entries are strings (error messages) rather than
objects.

## Tools Used in the Session

| Tool | Count | Purpose |
|------|-------|---------|
| `Bash` | 39 | Execute shell commands |
| `Edit` | 31 | Edit existing files |
| `Read` | 18 | Read file contents |
| `TodoWrite` | 16 | Manage todo lists |
| `Glob` | 11 | Find files by pattern |
| `Task` | 2 | Launch sub-agents |
| `Skill` | 2 | Execute skills |
| `Grep` | 1 | Search file contents |

## Correlating Tool Calls with Results

Each tool invocation can be traced through its unique ID:

1. **Assistant message** contains `tool_use` with `id` field
2. **User message** contains `tool_result` with `tool_use_id` linking back
3. **Enhanced metadata** in `toolUseResult` provides execution details

**Example correlation:**
```
tool_use: {
  "id": "toolu_0161RuW6V4pkmipTpNnkaNfh",
  "name": "Task",
  ...
}

tool_result: {
  "tool_use_id": "toolu_0161RuW6V4pkmipTpNnkaNfh",
  "content": "..."
}
```

## Other Entry Types

### File History Snapshots (`type: "file-history-snapshot"`)
```json
{
  "type": "file-history-snapshot",
  "messageId": "...",
  "snapshot": { /* file state */ },
  "isSnapshotUpdate": true
}
```

### Summaries (`type: "summary"`)
```json
{
  "type": "summary",
  "leafUuid": "...",
  "summary": "..."
}
```

## Key Insights

1. **Complete traceability**: Every tool call and result can be traced via IDs
2. **Rich metadata**: Tool results include execution metrics, timing, tokens
3. **Hierarchical structure**: Task tool results include sub-agent metrics
4. **Error handling**: Failed tools captured as string errors in toolUseResult
5. **Conversation threading**: UUID/parentUUID enable history reconstruction
6. **Context preservation**: Each entry includes cwd, git branch, timestamp

## Common Queries

**Find all tool uses:**
```bash
jq 'select(.type == "assistant") | .message.content[] |
    select(.type == "tool_use") | {name, id}' session.jsonl
```

**Find tool results by ID:**
```bash
jq 'select(has("toolUseResult")) |
    select(.message.content[].tool_use_id == "toolu_XXX")' session.jsonl
```

**List all tools used:**
```bash
jq -r 'select(.type == "assistant") | .message.content[] |
       select(.type == "tool_use") | .name' session.jsonl |
sort | uniq -c
```

**Find large tool results (>500 chars):**
```bash
jq 'select(has("toolUseResult")) |
    select((.toolUseResult | type) == "object") |
    select((.toolUseResult.content | tostring | length) > 500)' session.jsonl
```
