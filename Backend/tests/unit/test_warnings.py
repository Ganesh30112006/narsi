"""Scan warnings that are read back: the unreadable-page warning must round-trip to page numbers."""

from __future__ import annotations

from app.processing.warnings import low_quality_page, low_quality_pages


def test_pages_round_trip_from_their_warnings() -> None:
    other = "Only the first 50 pages were processed."
    warnings = [low_quality_page(3), other, low_quality_page(1), low_quality_page(3)]
    assert low_quality_pages(warnings) == [1, 3]


def test_other_warnings_and_none_give_no_pages() -> None:
    assert low_quality_pages(None) == []
    assert low_quality_pages(["OCR is disabled, so text in this image was not read."]) == []
    assert low_quality_pages(["Page 2: something else entirely."]) == []
