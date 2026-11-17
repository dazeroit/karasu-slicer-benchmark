from __future__ import annotations

import itertools

from kbench.html_report import Series, _compact, _nice_ticks, line_chart, markdown_to_html


def test_ticks_cover_the_data() -> None:
    ticks = _nice_ticks(0.0, 1.174)
    assert ticks[0] <= 0.0
    assert ticks[-1] >= 1.174
    assert _nice_ticks(-0.3, 0.2)[0] <= -0.3


def test_compact_labels() -> None:
    assert _compact(1000) == "1,000"
    assert _compact(10_000) == "10K"
    assert _compact(1_000_000) == "1M"
    assert _compact(0.5) == "0.5"


def test_markdown_tables_and_escaping() -> None:
    text = (
        "## Title\n\nSome `code` and *note* <b>.\n\n| A | B |\n| --- | --- |\n| 1 | <x> |\n\n- item"
    )
    html = markdown_to_html(text)
    assert "<h3>Title</h3>" in html
    assert "<code>code</code>" in html
    assert "<em>note</em>" in html
    assert "&lt;b&gt;" in html
    assert "<th>A</th>" in html
    assert "<td>&lt;x&gt;</td>" in html
    assert "<li>item</li>" in html


def test_line_chart_escapes_labels_and_lists_every_series() -> None:
    series = Series(["a <script>", "b"])
    chart = line_chart(
        "T",
        "n",
        {"a <script>": [(1.0, 2.0), (2.0, 3.0)], "b": [(1.0, 1.0), (2.0, 4.0)]},
        series,
        x_name="x",
        y_name="y",
    )
    assert chart is not None
    assert "<script>" not in chart
    assert "a &lt;script&gt;" in chart
    assert chart.count('class="line"') == 2
    assert 'class="legend"' in chart  # Two series: a legend.


def test_series_slots_and_short_names() -> None:
    series = Series(["a (x)", "b", "c", "d", "e", "a (x)"])
    assert series.labels == ["a (x)", "b", "c", "d", "e"]
    assert series.shown == ["a (x)", "b", "c", "d"]  # Four on line charts.
    assert series.slot("d") == 4
    assert series.slot("e") is None
    assert series.dot_slot("c") == 3
    assert series.dot_slot("d") is None  # Three on the dot plot.
    assert series.short("a (x)") == "a"
    twins = Series(["karasu (0.2.0-beta.2, abae64b)", "karasu (0.2.0-dev, 45bc195)"])
    assert twins.short("karasu (0.2.0-beta.2, abae64b)") == "karasu abae64b"
    assert Series(["x" * 40]).short("x" * 40) == "x" * 17 + "…"


def test_label_positions_never_overlap() -> None:
    from kbench.html_report import LABEL_GAP_PX, label_positions

    positions = label_positions([100.0, 100.0, 101.0, 102.0], 10.0, 240.0)
    assert all(b - a >= LABEL_GAP_PX - 1e-9 for a, b in itertools.pairwise(positions))
    crowded_bottom = label_positions([238.0, 239.0, 240.0, 240.0], 10.0, 240.0)
    assert max(crowded_bottom) <= 240.0
    assert all(b - a >= LABEL_GAP_PX - 1e-9 for a, b in itertools.pairwise(crowded_bottom))


def test_four_lines_get_four_direct_labels() -> None:
    labels = ["karasu", "dragonfruit", "chitubox", "lychee"]
    series = Series(labels)
    chart = line_chart(
        "T",
        "n",
        {label: [(0.0, 0.0), (1.0, 0.0)] for label in labels},
        series,
        x_name="x",
        y_name="y",
    )
    assert chart is not None
    assert chart.count('class="line"') == 4
    assert chart.count('class="direct-label"') == 4
    assert "var(--series-4)" in chart
    single = line_chart(
        "T", "n", {"karasu": [(0.0, 1.0), (1.0, 2.0)]}, series, x_name="x", y_name="y"
    )
    assert 'class="direct-label"' not in single  # One series: the title names it.
