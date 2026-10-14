"""Static analysis and pattern regression tests for Dashboard Frontend (app.js and index.html).

Asserts that:
1. Video metadata numeric fields (fps_nominal, duration_s, frame_count) do not use
   the buggy `!== undefined ?` guard pattern which allowed null to render as literal "null".
2. Review status counters (rev-approved, rev-total, etc.) do not default to "0" when missing.
3. Every `|| 0` fallback in bin aggregation, counts, and chart rendering is eliminated.
4. Chart bars for unavailable bins are not drawn as zero-height bars without a label.
5. Index.html initial placeholders for review counters are set to 'Unavailable'.
"""

from __future__ import annotations

from pathlib import Path
import re
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPOSITORY_ROOT / "frontend" / "app.js"
INDEX_HTML_PATH = REPOSITORY_ROOT / "frontend" / "index.html"


@pytest.fixture
def app_js_content() -> str:
    assert APP_JS_PATH.is_file(), f"frontend/app.js not found at {APP_JS_PATH}"
    return APP_JS_PATH.read_text(encoding="utf-8")


@pytest.fixture
def index_html_content() -> str:
    assert INDEX_HTML_PATH.is_file(), f"frontend/index.html not found at {INDEX_HTML_PATH}"
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


def test_video_metadata_no_undefined_only_guard_pattern(app_js_content: str) -> None:
    """Video metadata fields must not use `!== undefined ?` pattern which lets null slip through."""
    assert "fps_nominal !== undefined ?" not in app_js_content
    assert "duration_s !== undefined ?" not in app_js_content
    assert "frame_count !== undefined ?" not in app_js_content

    # Regex guard against variations with arbitrary whitespace
    assert not re.search(r"fps_nominal\s*!==\s*undefined\s*\?", app_js_content), (
        "Found `fps_nominal !== undefined ?` guard in app.js"
    )
    assert not re.search(r"duration_s\s*!==\s*undefined\s*\?", app_js_content), (
        "Found `duration_s !== undefined ?` guard in app.js"
    )
    assert not re.search(r"frame_count\s*!==\s*undefined\s*\?", app_js_content), (
        "Found `frame_count !== undefined ?` guard in app.js"
    )


def test_review_status_no_zero_string_default(app_js_content: str) -> None:
    """Review status counters must not default to '0' when missing; missing must show Unavailable."""
    rev_counter_ids = [
        "rev-total",
        "rev-approved",
        "rev-pending",
        "rev-rejected",
        "rev-class-corr",
        "rev-bbox-corr",
        "rev-snippets",
    ]
    for cid in rev_counter_ids:
        assert cid in app_js_content, f"Expected {cid} element update in app.js"

    # Assert that no rev-* assignment has a `: "0"` or `: '0'` default
    assert not re.search(r'rev\.[a-zA-Z_]+\s*!==\s*undefined\s*\?\s*rev\.[a-zA-Z_]+\s*:\s*["\']0["\']', app_js_content)
    assert ': "0"' not in app_js_content
    assert ": '0'" not in app_js_content


def test_no_count_or_bin_or_total_zero_fallbacks(app_js_content: str) -> None:
    """Audit every || 0 and ?? 0 fallback in volume bins, counts, and chart."""
    # Must not silently turn null/undefined count into 0
    assert "b.count || 0" not in app_js_content
    assert "b.count ?? 0" not in app_js_content
    assert "b.bin_start_s || 0" not in app_js_content
    assert "b.bin_start_s ?? 0" not in app_js_content
    assert not re.search(r"reduce\(\s*\(acc,\s*b\)\s*=>\s*acc\s*\+\s*\(b\.count\s*\|\|\s*0\)", app_js_content)


def test_format_text_helper_defined(app_js_content: str) -> None:
    """app.js must define formatText that safely treats null and undefined as 'Unavailable'."""
    assert "function formatText" in app_js_content
    # Checks that null and undefined are both checked
    assert re.search(r"val\s*===\s*null\s*\|\|\s*val\s*===\s*undefined", app_js_content)
    assert '"Unavailable"' in app_js_content


def test_volume_chart_handles_unavailable_bins(app_js_content: str) -> None:
    """Volume chart must explicitly label unavailable bins as Unavailable and not draw them as zero-height without labels."""
    assert "renderVolumeChart" in app_js_content
    # Must contain explicit Unavailable label in chart elements
    assert "Count: Unavailable" in app_js_content
    assert ">Unavailable</text>" in app_js_content


def test_index_html_initial_placeholders_not_zero(index_html_content: str) -> None:
    """Initial placeholder values in index.html for review status counters must be Unavailable, not 0."""
    rev_elements = [
        '<span class="metric-value" id="rev-total">Unavailable</span>',
        '<span class="metric-value" id="rev-approved">Unavailable</span>',
        '<span class="metric-value" id="rev-pending">Unavailable</span>',
        '<span class="val" id="rev-rejected">Unavailable</span>',
        '<span class="val" id="rev-class-corr">Unavailable</span>',
        '<span class="val" id="rev-bbox-corr">Unavailable</span>',
        '<span class="val" id="rev-snippets">Unavailable</span>',
    ]
    for elem in rev_elements:
        assert elem in index_html_content, f"Missing expected placeholder in index.html: {elem}"

    # Ensure no review element has initial text "0"
    assert not re.search(r'id="rev-[a-zA-Z0-9-]+">\s*0\s*<', index_html_content)


def test_ground_truth_table_uses_api_field_names(app_js_content: str) -> None:
    for stale in ("counted_count", "observed_count", "percentage_error", "segment_label"):
        assert stale not in app_js_content
    for field in ("r.counted", "r.observed", "r.percent_error", "r.video_segment_id"):
        assert field in app_js_content


def test_badges_updated_in_place_and_options_escaped(app_js_content: str) -> None:
    assert "outerHTML" not in app_js_content
    assert "out_of_tolerance" in app_js_content
    assert "escapeHtml(r.run_id)" in app_js_content
    assert "escapeHtml(label)" in app_js_content
