#!/bin/bash
# Shell function wrapper for find-codex-session that preserves directory changes
#
# To use this, add the following line to your ~/.bashrc or ~/.zshrc:
#   source /path/to/claude-code-tools/scripts/fcs-codex-function.sh
#
# Then use 'fcs-codex' instead of 'find-codex-session' to have directory
# changes persist

fcs-codex() {
    # Check if user is asking for help
    if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
        find-codex-session --help
        return
    fi

    # Run find-codex-session in shell mode and evaluate the output
    # Use sed to remove any leading empty lines that might cause issues
    eval "$(find-codex-session --shell "$@" | sed '/^$/d')"
}
