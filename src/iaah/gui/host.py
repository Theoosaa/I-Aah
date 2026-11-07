"""What a tab may ask of the main window – so tabs never import the app."""

from collections.abc import Callable
from typing import Protocol

from iaah.gui.session import Session
from iaah.gui.theme import Palette


class Host(Protocol):
    """The main window as the tabs see it."""

    @property
    def session(self) -> Session:
        """The running session."""
        ...

    @property
    def palette(self) -> Palette:
        """The current theme."""
        ...

    def run(self, action: Callable[[], object]) -> bool:
        """Run a user action: German message on error, refresh of the views after success."""
        ...

    def new_category(self) -> str | None:
        """Ask for a new category, create it and return its name (``None`` if cancelled)."""
        ...

    def show_in_review(self, index: int) -> None:
        """Open the booking ``transactions[index]`` in the PDF review."""
        ...

    def status(self, text: str) -> None:
        """A short note in the status bar."""
        ...
