"""Shared utilities for bash command parsing."""
import re


def extract_subcommands(command: str) -> list[str]:
    """
    Split compound bash command into individual subcommands.

    Splits on &&, ||, and ; operators.

    Args:
        command: A bash command string, possibly compound.

    Returns:
        List of individual subcommands.

    Example:
        >>> extract_subcommands("cd /tmp && git add . && git commit -m 'msg'")
        ['cd /tmp', 'git add .', "git commit -m 'msg'"]
    """
    if not command:
        return []
    subcommands = re.split(r'\s*(?:&&|\|\||;)\s*', command)
    return [cmd.strip() for cmd in subcommands if cmd.strip()]
