"""Smoke test: verify all app.add_handler() calls in main.py are valid.

Catches mistakes like passing two handlers to a single add_handler() call,
which causes TypeError: group is not int at runtime.
"""

import ast
import pathlib


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
