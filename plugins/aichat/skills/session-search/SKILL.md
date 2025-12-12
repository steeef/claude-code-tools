---
name: session-search
description: Use this skill when you need to find out details of specific work that was 
done in previous sessions with a code agent, which could be Claude-Code or Codex-CLI.
---

# session-search

Use the `aichat search` command in bash to search previous code-agent session JSONL 
files. Do `aichat search --help` to see how to use it!
In that help string, pay particular attention to the fields returned in the 
JSONL-formatted results.

IMPORTANT: 

(1) you MUST set the flag `--json` when you use this command, otherwise
it will spawn an interactive UI, which is NOT what you want. When you use this flag, you will get results in JSONL format, And you would typically use `jq` to query these.

(2) This command depends on the `claude-code-tools` and `aichat-search` packages being 
installed on the user's machine. If you get an error indicating that these are not 
available, then you must ask the user to install them using the following instructions 
shown in install.md








