"""Warnings a scan carries to the person reading its results, built in one place so they can also be read back.

A page whose text could not be read reliably is the one that matters most: "nothing found" on such a page means
"could not tell", not "clean", and the results page has to say so. The extractors add the warning with
`low_quality_page`; `low_quality_pages` recovers the page numbers from a stored scan's warnings.
"""

from __future__ import annotations

import re

_LOW_QUALITY = "Page {page}: text recognition quality is low; findings may be missed."
_LOW_QUALITY_PATTERN = re.compile(r"^Page (\d+): text recognition quality is low; findings may be missed\.$")


def low_quality_page(page: int) -> str:
    return _LOW_QUALITY.format(page=page)


def low_quality_pages(warnings: list[str] | None) -> list[int]:
    """Numbers of the pages whose text could not be read reliably, in order."""
    pages = {int(match.group(1)) for warning in warnings or [] if (match := _LOW_QUALITY_PATTERN.match(warning))}
    return sorted(pages)
