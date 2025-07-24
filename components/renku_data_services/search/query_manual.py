"""Generate the complete manual for the user query."""

from pathlib import Path

import markdown_code_runner as mcr
from markdown_code_runner import process_markdown

from renku_data_services.app_config import logging

## Remove the warning with fancy unicode that is inserted into every
## occurence of a injected code result, because it breaks the
## conversion to html in the swagger page…
mcr.MARKERS.update({"warning": ""})
mcr.PATTERNS = mcr.markers_to_patterns()


logger = logging.getLogger(__file__)


def __convert_file(input: Path | str) -> str:
    inp = input if isinstance(input, Path) else Path(input)
    with inp.open() as f:
        lines = [line.rstrip("\n") for line in f.readlines()]

    new_lines = process_markdown(lines, verbose=False)
    return "\n".join(new_lines).rstrip() + "\n"


def manual_to_file(out: str | Path) -> None:
    """Print the query manual to the given file."""
    text = manual_to_str()
    outp = out if isinstance(out, Path) else Path(out)
    with outp.open("w") as f:
        f.write(text)


def manual_to_str() -> str:
    """Return the query manual as a markdown string."""
    manual = Path(__file__).parent / "query_manual.md"
    return __convert_file(manual)


def safe_manual_to_str() -> str:
    """Return the query manual or a placeholder if it fails."""
    try:
        return manual_to_str()
    except Exception as e:
        logger.error("Error generating the search query documentation!", exc_info=e)
        return "Generating the documentation failed."
