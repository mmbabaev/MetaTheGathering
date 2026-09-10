"""Smoke test: verify all app.add_handler() calls in main.py are valid.

Catches mistakes like passing two handlers to a single add_handler() call,
which causes TypeError: group is not int at runtime.
"""

import ast
import pathlib

import main


def _parse_add_handler_calls(source: str) -> list[ast.Call]:
    """Return all app.add_handler(...) Call nodes from the source."""
    tree = ast.parse(source)
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_handler":
            calls.append(node)
    return calls


def test_each_add_handler_has_exactly_one_positional_arg():
    """Every app.add_handler() call must pass exactly one positional argument.

    The second positional arg is `group: int`; accidentally passing a second
    handler there raises TypeError at startup.
    """
    source = pathlib.Path("main.py").read_text()
    calls = _parse_add_handler_calls(source)
    assert calls, "No app.add_handler() calls found — check the test"
    for call in calls:
        assert len(call.args) == 1, (
            f"app.add_handler() at line {call.lineno} has {len(call.args)} positional args — expected exactly 1"
        )


def test_retired_slash_commands_are_not_registered():
    source = pathlib.Path("main.py").read_text()
    tree = ast.parse(source)
    registered_commands = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CommandHandler"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }

    assert {"add_players", "tournament_status"}.isdisjoint(registered_commands)


def test_retired_commands_are_hidden_from_every_command_menu():
    retired = {"add_players", "tournament_status"}

    assert retired.isdisjoint(c.command for c in main._USER_COMMANDS)
    assert retired.isdisjoint(c.command for c in main._SCOREKEEPER_COMMANDS)
    assert retired.isdisjoint(c.command for c in main._ADMIN_COMMANDS)
