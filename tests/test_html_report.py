from __future__ import annotations

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


def test_series_cap() -> None:
    series = Series(["a", "b", "c", "d", "a"])
    assert series.labels == ["a", "b", "c", "d"]
    assert series.shown == ["a", "b", "c"]
    assert series.slot("d") is None
