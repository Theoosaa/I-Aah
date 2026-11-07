"""I-Aah: read, categorize and analyse German bank statements."""

from typing import Final

# The single source of the version: pyproject.toml reads it from here, so nothing needs the
# installed package metadata at run time – the Windows build bundles none (it would carry the
# path of the developer's checkout).
__version__: Final[str] = "4.0.0"
