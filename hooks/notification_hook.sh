#!/bin/bash

input=$(cat)
hook_event_name=$(echo "$input" | jq -r '.hook_event_name // ""')
message=$(echo "$input" | jq -r '.message // "Claude notification"')

title="🤖 Claude Code"

# Detect hook type from hook_event_name
if [[ "$hook_event_name" == "Stop" ]]; then
    subtitle="Task Done"
elif [[ "$hook_event_name" == "Notification" ]]; then
    subtitle="Input Requested"
else
    subtitle=""
fi

if command -v terminal-notifier >/dev/null 2>&1; then
    if [[ "$hook_event_name" == "Stop" ]]; then
        terminal-notifier -title "$title" -subtitle "$subtitle" -message "$message" -timeout 10 -sound Hero
    elif [[ "$hook_event_name" == "Notification" ]]; then
        terminal-notifier -title "$title" -subtitle "$subtitle" -message "$message" -timeout 10 -sound Submarine
    else
        terminal-notifier -title "$title" -message "$message" -timeout 10
    fi
else
    if [[ -n "$subtitle" ]]; then
        curl -H "Title: $title - $subtitle" -d "$message" ntfy.sh/cc-alerts
    else
        curl -H "Title: $title" -d "$message" ntfy.sh/cc-alerts
    fi
fi
