"""Enforce the layer rules from AGENTS.md: dependencies only point downward."""

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

PACKAGE_ROOT: Final = Path(__file__).resolve().parent.parent / "src" / "iaah"

GUI_TOOLKITS: Final = ("tkinter", "PIL.ImageTk")
PLOTTING: Final = ("matplotlib",)
UPPER_LAYERS: Final = ("iaah.gui", "iaah.cli")
DISPLAY_FREE_GUI_MODULES: Final = ("session.py", "viewmodel.py")

# layer directory -> module prefixes it must not import
FORBIDDEN_IMPORTS: Final[dict[str, tuple[str, ...]]] = {
    "core": (*GUI_TOOLKITS, *PLOTTING, "PIL", *UPPER_LAYERS, "iaah.charts", "iaah.export"),
    "charts": (*GUI_TOOLKITS, *UPPER_LAYERS, "iaah.export"),
    "export": (*GUI_TOOLKITS, *UPPER_LAYERS),
}


def _imported_modules(path: Path) -> Iterator[str]:
    # utf-8-sig: tolerate a BOM written by Windows editors.
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def _violations(layer: str) -> list[str]:
    forbidden = FORBIDDEN_IMPORTS[layer]
    found: list[str] = []
    for path in sorted((PACKAGE_ROOT / layer).rglob("*.py")):
        for module in _imported_modules(path):
            if module.startswith(forbidden):
                found.append(f"{path.relative_to(PACKAGE_ROOT)}: {module}")
    return found


def _relative_imports() -> list[str]:
    found: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                found.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}")
    return found


@pytest.mark.parametrize("layer", sorted(FORBIDDEN_IMPORTS))
def test_layer_respects_import_boundaries(layer: str) -> None:
    assert _violations(layer) == []


@pytest.mark.parametrize("module", DISPLAY_FREE_GUI_MODULES)
def test_gui_state_needs_no_display(module: str) -> None:
    # The GUI's state and view model are unit-tested without a display.
    path = PACKAGE_ROOT / "gui" / module
    assert [name for name in _imported_modules(path) if name.startswith(GUI_TOOLKITS)] == []


def test_no_relative_imports() -> None:
    # Relative imports would slip past the boundary check above, so they are banned.
    assert _relative_imports() == []
