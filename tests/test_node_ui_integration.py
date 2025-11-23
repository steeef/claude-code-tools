"""Tests for Node-based UI integration triggered by --altui."""

import sys

import pytest

from claude_code_tools import find_session


def _sample_sessions():
    """Return a minimal sample session list used by tests."""
    return [
        {
            "agent": "claude",
            "agent_display": "Claude",
            "session_id": "abc123",
            "mod_time": 0.0,
            "create_time": 0.0,
            "lines": 10,
            "project": "demo",
            "preview": "last msg",
            "cwd": "/tmp/demo",
            "branch": "main",
            "claude_home": None,
            "is_trimmed": False,
            "derivation_type": None,
            "is_sidechain": False,
        }
    ]


def test_altui_prefers_node_ui_runner(monkeypatch):
    """--altui should route to Node UI runner instead of fallback tables."""

    calls = {"invoked": False}

    def fake_run_node_menu_ui(sessions, keywords, action_handler, stderr_mode, **kwargs):
        calls["invoked"] = True
        assert sessions == _sample_sessions()
        assert keywords == ["test"]
        assert callable(action_handler)
        assert stderr_mode is False

    monkeypatch.setattr(
        find_session, "run_node_menu_ui", fake_run_node_menu_ui
    )
    monkeypatch.setattr(
        find_session, "search_all_agents", lambda *a, **k: _sample_sessions()
    )
    monkeypatch.setattr(find_session, "RICH_AVAILABLE", False)
    monkeypatch.setattr(find_session, "TUI_AVAILABLE", False)

    argv = ["find-session", "test", "--altui"]
    monkeypatch.setattr(sys, "argv", argv)

    # Expect the node UI runner to be invoked; current behavior will fail this
    # assertion until integration is implemented.
    find_session.main()

    assert calls["invoked"], "Node UI runner was not called for --altui"


def test_kwargs_passed_to_action_handler(monkeypatch):
    """Node UI results should forward kwargs into action handler."""

    captured = {}

    def fake_run_node_menu_ui(sessions, keywords, action_handler, stderr_mode, **kwargs):
        # Simulate Node writing out kwargs
        action_handler(
            sessions[0], "suppress_resume", {"tools": "bash", "threshold": 250}
        )

    monkeypatch.setattr(find_session, "run_node_menu_ui", fake_run_node_menu_ui)
    monkeypatch.setattr(
        find_session, "search_all_agents", lambda *a, **k: _sample_sessions()
    )
    monkeypatch.setattr(find_session, "RICH_AVAILABLE", False)
    monkeypatch.setattr(find_session, "TUI_AVAILABLE", False)

    def spy_handle_action(session, action, shell_mode=False, action_kwargs=None):
        captured["session"] = session
        captured["action"] = action
        captured["kwargs"] = action_kwargs

    monkeypatch.setattr(find_session, "handle_action", spy_handle_action)

    argv = ["find-session", "test", "--altui"]
    monkeypatch.setattr(sys, "argv", argv)

    find_session.main()

    assert captured["action"] == "suppress_resume"
    assert captured["kwargs"]["tools"] == "bash"
    assert captured["kwargs"]["threshold"] == 250
