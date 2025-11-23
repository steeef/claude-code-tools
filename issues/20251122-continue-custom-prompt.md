# Add --prompt flag to aichat continue command

## Feature

Allow users to provide custom summarization instructions when using
`aichat continue`.

## Usage

```bash
aichat continue <session_id> --prompt "focus on bug fixes, ignore refactoring"
```

## Interactive Prompt

When user selects "continue" action from session menu, prompt:
"Enter custom summarization instructions (or press Enter to skip):"
- If user provides text, pass as --prompt to continue command
- If user presses Enter, run continue without custom instructions

## Implementation

Append user prompt to fixed summarization prompt with:
"Below are some special instructions from the user. Prioritize these in
combination with the above instructions: [user prompt]"
