#!/usr/bin/env python3
"""
Skill Auto-Activation Hook for Claude Code

This UserPromptSubmit hook analyzes user prompts and injects skill activation
reminders based on keyword matches, pattern matching, and context clues.

Input (stdin): JSON from Claude Code with prompt, cwd, session_id
Output (stdout): JSON with hookSpecificOutput.additionalContext for skill suggestions
"""

import json
import sys
import re
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

# Configuration file path - look relative to this script
HOOK_DIR = Path(__file__).parent
RULES_FILE = HOOK_DIR / "skill-rules.json"


def load_rules() -> Dict:
    """Load skill rules configuration"""
    try:
        with open(RULES_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        # Fail gracefully - don't block prompts if config is missing
        return {}


def load_state(state_file: str) -> Dict:
    """Load activation state for cooldown tracking"""
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_state(state_file: str, state: Dict):
    """Save activation state"""
    try:
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass  # Don't block on state save failures


def check_cooldown(skill_name: str, session_id: str, state: Dict, cooldown_minutes: int) -> bool:
    """Check if skill is in cooldown period for this session"""
    key = f"{session_id}:{skill_name}"
    if key in state:
        last_activation = datetime.fromisoformat(state[key])
        if datetime.now() - last_activation < timedelta(minutes=cooldown_minutes):
            return True  # Still in cooldown
    return False


def record_activation(skill_name: str, session_id: str, state: Dict, state_file: str):
    """Record skill activation timestamp"""
    key = f"{session_id}:{skill_name}"
    state[key] = datetime.now().isoformat()
    save_state(state_file, state)


def score_skill(skill_name: str, skill_config: Dict, prompt: str, cwd: str, scoring: Dict) -> int:
    """Calculate activation score for a skill based on matches"""
    score = 0
    prompt_lower = prompt.lower()

    # Keyword matching
    keywords = skill_config['activation'].get('promptKeywords', [])
    for keyword in keywords:
        if keyword.lower() in prompt_lower:
            score += scoring.get('keyword_match', 10)

    # Pattern matching (regex)
    patterns = skill_config['activation'].get('promptPatterns', [])
    for pattern in patterns:
        try:
            if re.search(pattern, prompt, re.IGNORECASE):
                score += scoring.get('pattern_match', 15)
        except re.error:
            continue  # Skip invalid patterns

    # CWD pattern matching
    cwd_patterns = skill_config['activation'].get('cwdPatterns', [])
    for pattern in cwd_patterns:
        # Simple glob-style matching
        pattern_regex = pattern.replace('**/', '.*').replace('*', '[^/]*')
        try:
            if re.search(pattern_regex, cwd):
                score += scoring.get('cwd_match', 8)
        except re.error:
            continue

    return score


def format_suggestions(activated_skills: List[Tuple[str, Dict]]) -> str:
    """Format skill suggestions for injection into context"""
    if not activated_skills:
        return ""

    lines = [
        "",
        "=" * 80,
        "🎯 SKILL ACTIVATION CHECK",
        "=" * 80,
        ""
    ]

    for skill_name, skill_config in activated_skills:
        lines.append(f"➤ {skill_config['message']}")
        lines.append("")

    lines.extend([
        "Use the Skill tool to activate any relevant skills above.",
        "=" * 80,
        ""
    ])

    return "\n".join(lines)


def main():
    """Main hook execution"""
    try:
        # Load input from stdin
        input_data = json.load(sys.stdin)

        # Extract relevant fields
        prompt = input_data.get('prompt', '')
        cwd = input_data.get('cwd', '')
        session_id = input_data.get('session_id', 'unknown')

        # Load configuration
        rules = load_rules()
        if not rules:
            # No rules configured, pass through
            print(json.dumps({}))
            sys.exit(0)

        skills = rules.get('skills', {})
        scoring = rules.get('scoring', {})
        global_config = rules.get('global', {})

        state_file = global_config.get('state_file', '/tmp/.claude_skill_activation_state.json')
        max_suggestions = global_config.get('max_suggestions_per_prompt', 2)

        # Load cooldown state
        state = load_state(state_file)

        # Score all skills
        skill_scores = []
        for skill_name, skill_config in skills.items():
            # Check cooldown first
            cooldown_minutes = skill_config.get('cooldown_minutes', 30)
            if check_cooldown(skill_name, session_id, state, cooldown_minutes):
                continue  # Skip skills in cooldown

            # Calculate score
            score = score_skill(skill_name, skill_config, prompt, cwd, scoring)
            min_score = skill_config['activation'].get('minScore', 10)

            if score >= min_score:
                priority = skill_config.get('priority', 5)
                skill_scores.append((score, priority, skill_name, skill_config))

        # Sort by score (desc), then priority (desc)
        skill_scores.sort(key=lambda x: (x[0], x[1]), reverse=True)

        # Take top N skills
        activated_skills = [(name, config) for _, _, name, config in skill_scores[:max_suggestions]]

        # Record activations
        for skill_name, _ in activated_skills:
            record_activation(skill_name, session_id, state, state_file)

        # Format output
        if activated_skills:
            context_message = format_suggestions(activated_skills)
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context_message
                }
            }
        else:
            # No skills activated - pass through
            output = {}

        print(json.dumps(output))
        sys.exit(0)

    except Exception:
        # Fail gracefully - never block prompts due to hook errors
        print(json.dumps({}), file=sys.stdout)
        sys.exit(0)


if __name__ == "__main__":
    main()
