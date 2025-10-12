#!/bin/bash
# Shell wrapper for find-session to enable persistent directory changes
#
# Usage: Add this to your .bashrc or .zshrc:
#   source /path/to/claude-code-tools/scripts/fs-function.sh
#
# Then use:
#   fs "keywords"
#   fs -g
#   fs "bug,fix" --agents claude

fs() {
    # Check if user is asking for help
    if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
        find-session --help
        return
    fi

    # Run find-session in shell mode and evaluate the output
    # Remove empty lines to avoid issues with eval
    eval "$(find-session --shell "$@" | sed '/^$/d')"
}
