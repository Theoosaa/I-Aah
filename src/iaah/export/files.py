"""Writing export files: one place that turns OS errors into ``ExportError``.

Exports go wherever the user chose – a file may be open in a viewer (Windows locks it), the
folder may not exist or be read-only. The GUI and CLI catch ``ExportError`` and explain it.
"""

from io import BytesIO
from pathlib import Path
from typing import Final

from matplotlib.figure import Figure

from iaah.core.errors import IaahError

PNG: Final = "png"


class ExportError(IaahError):
    """An export file (or its folder) could not be written; ``path`` names it."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"cannot write {path}")
        self.path = path


def write_export(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path``; ``ExportError`` if the OS refuses."""
    try:
        path.write_bytes(data)
    except OSError as error:
        raise ExportError(path) from error


def ensure_folder(folder: Path) -> Path:
    """Create ``folder`` if needed; ``ExportError`` if it cannot be (e.g. it is a file)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ExportError(folder) from error
    return folder


def figure_png(figure: Figure) -> bytes:
    """A figure as PNG bytes."""
    buffer = BytesIO()
    figure.savefig(buffer, format=PNG)
    return buffer.getvalue()
