"""Self-contained HTML report: the Markdown report's tables, with charts above them.

Charts are inline SVG with one shared tooltip (filled with ``textContent``: labels come from run
records). Colours follow a validated categorical palette (first three slots, light and dark),
text uses text tokens only, and every value a chart shows is also in the tables below it.
"""

from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from kbench.report import _load, render, slicer_label

# Categorical slots 1-3 of the reference palette, validated all-pairs in both modes (BD-019).
SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a")
SERIES_DARK = ("#3987e5", "#d95926", "#199e70")
MAX_SERIES = len(SERIES_LIGHT)

WIDTH = 720
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _fmt(value: float, digits: int = 3) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return (
        f"{value:.{digits}g}"
        if abs(value) < 0.001
        else f"{value:.{digits}f}".rstrip("0").rstrip(".")
    )


def _compact(value: float) -> str:
    """Axis labels: in full below 10,000, then 10K, 100K, 1M, 10M."""
    for size, suffix in ((1e9, "G"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= 10_000 and abs(value) >= size:
            return f"{value / size:g}{suffix}"
    return _fmt(value)


def _decades(low: float, high: float) -> list[float]:
    first, last = math.floor(math.log10(low)), math.ceil(math.log10(high))
    return [10.0**exponent for exponent in range(first, last + 1)]


def _nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    span = high - low or 1.0
    step = 10 ** math.floor(math.log10(span / count))
    for factor in (1, 2, 5, 10):
        if span / (step * factor) <= count:
            step *= factor
            break
    first, last = math.floor(low / step), math.ceil(high / step)
    return [round(index * step, 12) for index in range(first, last + 1)]


def _tip(lines: Sequence[str]) -> str:
    return _esc(json.dumps(list(lines)))


class Series:
    """The report's series: one per slicer label, in order of first appearance, at most three."""

    def __init__(self, labels: Sequence[str]) -> None:
        self.labels: list[str] = []
        for label in labels:
            if label not in self.labels:
                self.labels.append(label)
        self.shown = self.labels[:MAX_SERIES]

    def slot(self, label: str) -> int | None:
        return self.shown.index(label) + 1 if label in self.shown else None


def _legend(series: Series, labels: Sequence[str], mark: str) -> str:
    if len(labels) < 2:
        return ""
    items = []
    for label in labels:
        slot = series.slot(label)
        key = (
            f'<span class="key-dot" style="background:var(--series-{slot})"></span>'
            if mark == "dot"
            else f'<span class="key-line" style="background:var(--series-{slot})"></span>'
        )
        items.append(f'<span class="legend-item">{key}{_esc(label)}</span>')
    return f'<div class="legend">{"".join(items)}</div>'


def timing_chart(cases: Sequence[dict[str, Any]], series: Series) -> str | None:
    """Median wall time per case and slicer: dots on a logarithmic axis, joined per case."""
    rows: dict[str, list[tuple[str, float, dict[str, Any]]]] = {}
    for case in cases:
        perf = case.get("performance")
        label = slicer_label(case)
        if not perf or perf["wall_s"]["median"] is None or series.slot(label) is None:
            continue
        rows.setdefault(case["case"], []).append((label, perf["wall_s"]["median"], perf))
    if not rows:
        return None
    values = [value for entries in rows.values() for _, value, _ in entries]
    ticks = _decades(min(values), max(values))
    left, right, top, row_height = 230, 24, 28, 30
    height = top + row_height * len(rows) + 30
    plot = WIDTH - left - right

    def x_of(value: float) -> float:
        span = math.log10(ticks[-1]) - math.log10(ticks[0]) or 1.0
        return left + plot * (math.log10(value) - math.log10(ticks[0])) / span

    parts = [
        f'<svg viewBox="0 0 {WIDTH} {height}" role="img" aria-label="Median wall time per case">'
    ]
    for tick in ticks:
        x = x_of(tick)
        parts.append(
            f'<line class="grid" x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{height - 26}"/>'
        )
        parts.append(
            f'<text class="tick" x="{x:.1f}" y="{height - 10}" text-anchor="middle">{_fmt(tick)} s</text>'
        )
    for index, (name, entries) in enumerate(rows.items()):
        y = top + row_height * index + row_height / 2
        parts.append(
            f'<text class="row-label" x="{left - 12}" y="{y + 4:.1f}" text-anchor="end">{_esc(name)}</text>'
        )
        if len(entries) > 1:
            xs = [x_of(value) for _, value, _ in entries]
            parts.append(
                f'<line class="connector" x1="{min(xs):.1f}" y1="{y:.1f}" x2="{max(xs):.1f}" y2="{y:.1f}"/>'
            )
        for label, value, perf in entries:
            slot = series.slot(label)
            x = x_of(value)
            lines = [
                f"{_fmt(value)} s median wall time",
                f"{label} · {name}",
                f"min {_fmt(perf['wall_s']['min'])} s, max {_fmt(perf['wall_s']['max'])} s",
            ]
            parts.append(
                f'<g class="mark" tabindex="0" data-tip="{_tip(lines)}">'
                f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="12"/>'
                f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="5" style="fill:var(--series-{slot})"/></g>'
            )
    parts.append("</svg>")
    labels = [
        label
        for label in series.shown
        if any(label == e[0] for entries in rows.values() for e in entries)
    ]
    return _card(
        "Median wall time",
        "Seconds per case, logarithmic axis; each dot is one slicer, joined when a case has several.",
        _legend(series, labels, "dot") + "".join(parts),
    )


def line_chart(
    title: str,
    note: str,
    lines_by_label: dict[str, list[tuple[float, float]]],
    series: Series,
    *,
    x_name: str,
    y_name: str,
    log_x: bool = False,
    log_y: bool = False,
    zero_line: bool = False,
    show_markers: bool = True,
) -> str | None:
    """Lines with markers, a crosshair snapping to the nearest X, and every series in one tooltip."""
    data = {
        label: points for label, points in lines_by_label.items() if points and series.slot(label)
    }
    if not data:
        return None
    xs = sorted({x for points in data.values() for x, _ in points})
    ys = [y for points in data.values() for _, y in points]
    left, right, top, bottom = 64, 24, 16, 40
    height = 260
    plot_w, plot_h = WIDTH - left - right, height - top - bottom
    if log_x:
        x_ticks = _decades(min(xs), max(xs))
        x_low, x_high = math.log10(x_ticks[0]), math.log10(x_ticks[-1])
    else:
        x_ticks = _nice_ticks(min(xs), max(xs))
        x_low, x_high = x_ticks[0], x_ticks[-1]
    if log_y:
        y_ticks = _decades(min(ys), max(ys))
        y_low, y_high = math.log10(y_ticks[0]), math.log10(y_ticks[-1])
    else:
        low = min(min(ys), 0.0) if zero_line else min(ys)
        y_ticks = _nice_ticks(low, max(max(ys), 0.0) if zero_line else max(ys))
        y_low, y_high = y_ticks[0], y_ticks[-1]

    def sx(x: float) -> float:
        value = math.log10(x) if log_x else x
        return left + plot_w * (value - x_low) / ((x_high - x_low) or 1.0)

    def sy(y: float) -> float:
        value = math.log10(y) if log_y else y
        return top + plot_h * (1 - (value - y_low) / ((y_high - y_low) or 1.0))

    parts = [f'<svg viewBox="0 0 {WIDTH} {height}" role="img" aria-label="{_esc(title)}">']
    for tick in y_ticks:
        y = sy(tick)
        parts.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{WIDTH - right}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick" x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{_compact(tick)}</text>'
        )
    if zero_line and not log_y:
        parts.append(
            f'<line class="axis" x1="{left}" y1="{sy(0):.1f}" x2="{WIDTH - right}" y2="{sy(0):.1f}"/>'
        )
    for tick in x_ticks:
        parts.append(
            f'<text class="tick" x="{sx(tick):.1f}" y="{height - bottom + 18}" text-anchor="middle">{_compact(tick)}</text>'
        )
    parts.append(
        f'<text class="axis-name" x="{left + plot_w / 2:.1f}" y="{height - 4}" text-anchor="middle">{_esc(x_name)}</text>'
    )
    parts.append(
        f'<text class="axis-name" transform="translate(14 {top + plot_h / 2:.1f}) rotate(-90)" text-anchor="middle">{_esc(y_name)}</text>'
    )
    for label, points in data.items():
        slot = series.slot(label)
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(points)
        )
        parts.append(f'<path class="line" d="{path}" style="stroke:var(--series-{slot})"/>')
        if show_markers:
            for x, y in points:
                parts.append(
                    f'<circle class="marker" cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" style="fill:var(--series-{slot})"/>'
                )

    readouts = []
    for x in xs:
        rows = []
        for label, points in data.items():
            values = [y for px, y in points if px == x]
            if values:
                rows.append([series.slot(label), _fmt(values[0]), label])
        readouts.append({"x": round(sx(x), 1), "title": f"{x_name}: {_fmt(x)}", "rows": rows})
    parts.append(
        f'<line class="crosshair" x1="0" y1="{top}" x2="0" y2="{top + plot_h}" visibility="hidden"/>'
        f'<rect class="overlay" x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" '
        f'data-readouts="{_esc(json.dumps(readouts))}"/>'
    )
    parts.append("</svg>")
    return _card(title, note, _legend(series, list(data), "line") + "".join(parts))


def scaling_charts(cases: Sequence[dict[str, Any]], series: Series) -> list[str]:
    """Wall time against triangle count, and against CPU count, where a run varies them."""
    charts = []
    by_target: dict[str, dict[str, list[tuple[float, float]]]] = {}
    by_cpus: dict[str, dict[str, list[tuple[float, float]]]] = {}
    for case in cases:
        perf = case.get("performance")
        if not perf or perf["wall_s"]["median"] is None:
            continue
        label = slicer_label(case)
        key = f"{case['model']['id']}@{case['target']}"
        if case.get("cpus"):
            by_cpus.setdefault(key, {}).setdefault(label, []).append(
                (len(case["cpus"]), perf["wall_s"]["median"])
            )
        else:
            # A triangle-count series holds one model family (``<family>-s<n>``) on one target:
            # the geometry stays the same while only its tessellation changes.
            family = re.match(r"^(.*)-s\d+$", case["model"]["id"])
            if family is None:
                continue
            key = f"{family.group(1)}@{case['target']}"
            by_target.setdefault(key, {}).setdefault(label, []).append(
                (float(case["model"]["triangle_count"]), perf["wall_s"]["median"])
            )
    for target, lines in by_target.items():
        lines = {
            label: sorted(points)
            for label, points in lines.items()
            if len({x for x, _ in points}) >= 3
        }
        chart = line_chart(
            f"Wall time against triangle count: {target}",
            "Median seconds per model, both axes logarithmic.",
            lines,
            series,
            x_name="triangles",
            y_name="seconds",
            log_x=True,
            log_y=True,
        )
        if chart:
            charts.append(chart)
    for key, lines in by_cpus.items():
        lines = {label: sorted(points) for label, points in lines.items() if len(points) >= 2}
        chart = line_chart(
            f"Wall time against CPU count: {key}",
            "Median seconds with the slicer restricted to that many CPUs.",
            lines,
            series,
            x_name="CPUs",
            y_name="seconds",
            zero_line=True,
        )
        if chart:
            charts.append(chart)
    return charts


def layer_charts(
    analysed: Sequence[tuple[dict[str, Any], dict[str, Any]]], series: Series
) -> list[str]:
    """Per-layer area error for every case, every slicer on the same chart."""
    by_case: dict[str, dict[str, list[tuple[float, float]]]] = {}
    for case, metrics in analysed:
        errors = metrics["layers"]["area_error_mm2"]
        by_case.setdefault(case["case"], {})[slicer_label(case)] = [
            (float(index), float(error)) for index, error in enumerate(errors) if error is not None
        ]
    charts = []
    for name, lines in by_case.items():
        chart = line_chart(
            f"Area error by layer: {name}",
            "Measured minus reference section area, mm², per layer from the plate up.",
            lines,
            series,
            x_name="layer",
            y_name="mm²",
            zero_line=True,
            show_markers=False,
        )
        if chart:
            charts.append(chart)
    return charts


def _card(title: str, note: str, body: str) -> str:
    return f'<section class="card"><h3>{_esc(title)}</h3><p class="note">{_esc(note)}</p>{body}</section>'


def markdown_to_html(text: str) -> str:
    """The subset of Markdown the text report uses: headings, tables, lists, paragraphs, code."""

    def inline(value: str) -> str:
        escaped = _esc(value)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        return re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)

    out: list[str] = []
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("|"):
            block = []
            while index < len(lines) and lines[index].startswith("|"):
                block.append([cell.strip() for cell in lines[index].strip("|").split("|")])
                index += 1
            head, body = block[0], [row for row in block[2:]]
            out.append('<div class="table-wrap"><table><thead><tr>')
            out.extend(f"<th>{inline(cell)}</th>" for cell in head)
            out.append("</tr></thead><tbody>")
            for row in body:
                out.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>")
            out.append("</tbody></table></div>")
            continue
        if line.startswith("- "):
            out.append("<ul>")
            while index < len(lines) and lines[index].startswith("- "):
                out.append(f"<li>{inline(lines[index][2:])}</li>")
                index += 1
            out.append("</ul>")
            continue
        heading = re.match(r"^(#{1,3}) (.*)$", line)
        if heading:
            level = len(heading.group(1)) + 1  # The page title is the only h1.
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
        index += 1
    return "\n".join(out)


def render_html(run_dirs: Sequence[Path] | Path) -> str:
    directories = [run_dirs] if isinstance(run_dirs, Path) else list(run_dirs)
    runs = [_load(directory / "run.json") for directory in directories]
    cases = [
        _load(directory / entry["record"])
        for directory, run in zip(directories, runs, strict=True)
        for entry in run["cases"]
    ]
    analysed = [
        (case, _load(Path(case["directory"]) / "metrics.json"))
        for case in cases
        if case.get("analysis", {}).get("status") == "analysed"
    ]
    series = Series([slicer_label(case) for case in cases])
    charts = [
        chart for chart in [timing_chart(cases, series), *scaling_charts(cases, series)] if chart
    ]
    charts += layer_charts(analysed, series)
    note = ""
    if len(series.labels) > MAX_SERIES:
        note = (
            f'<p class="note">Charts show the first {MAX_SERIES} slicers; '
            f"{len(series.labels) - MAX_SERIES} more are in the tables.</p>"
        )
    title = runs[0]["run_id"] if len(runs) == 1 else f"{len(runs)} runs"
    markdown = render(directories)
    body = markdown_to_html(markdown.split("\n", 1)[1] if markdown.startswith("# ") else markdown)
    return TEMPLATE.format(
        title=_esc(f"kbench report {title}"),
        heading=_esc(f"Benchmark report: {title}"),
        charts="\n".join(charts) or '<p class="note">No chart for this run.</p>',
        note=note,
        body=body,
        series_light="".join(f"--series-{i + 1}:{c};" for i, c in enumerate(SERIES_LIGHT)),
        series_dark="".join(f"--series-{i + 1}:{c};" for i, c in enumerate(SERIES_DARK)),
        font=FONT,
        script=SCRIPT,
    )


def write_html(run_dir: Path, others: Sequence[Path] = ()) -> Path:
    path = run_dir / ("report.html" if not others else "comparison.html")
    path.write_text(render_html([run_dir, *others]), encoding="utf-8")
    return path


SCRIPT = """
(() => {
  const tip = document.getElementById("tip");
  function show(lines, x, y, keys) {
    tip.replaceChildren();
    lines.forEach((line, i) => {
      const row = document.createElement("div");
      row.className = i === 0 ? "tip-value" : "tip-label";
      if (keys && keys[i]) {
        const key = document.createElement("span");
        key.className = "key-line";
        key.style.background = "var(--series-" + keys[i] + ")";
        row.appendChild(key);
      }
      row.appendChild(document.createTextNode(line));
      tip.appendChild(row);
    });
    tip.hidden = false;
    const width = tip.offsetWidth, height = tip.offsetHeight;
    tip.style.left = Math.min(x + 14, window.innerWidth - width - 8) + "px";
    tip.style.top = Math.max(8, y - height - 10) + "px";
  }
  function hide() { tip.hidden = true; }
  document.querySelectorAll(".mark").forEach((mark) => {
    const lines = JSON.parse(mark.dataset.tip);
    const open = (event) => {
      const box = mark.getBoundingClientRect();
      show(lines, event.clientX ?? box.right, event.clientY ?? box.top);
    };
    mark.addEventListener("pointermove", open);
    mark.addEventListener("focus", () => { const b = mark.getBoundingClientRect(); show(lines, b.right, b.top); });
    mark.addEventListener("pointerleave", hide);
    mark.addEventListener("blur", hide);
  });
  document.querySelectorAll(".overlay").forEach((overlay) => {
    const readouts = JSON.parse(overlay.dataset.readouts);
    const svg = overlay.ownerSVGElement;
    const cross = svg.querySelector(".crosshair");
    overlay.addEventListener("pointermove", (event) => {
      const point = svg.createSVGPoint();
      point.x = event.clientX; point.y = event.clientY;
      const local = point.matrixTransform(svg.getScreenCTM().inverse());
      let best = readouts[0];
      readouts.forEach((r) => { if (Math.abs(r.x - local.x) < Math.abs(best.x - local.x)) best = r; });
      cross.setAttribute("x1", best.x); cross.setAttribute("x2", best.x);
      cross.setAttribute("visibility", "visible");
      const lines = [best.title], keys = [null];
      best.rows.forEach((row) => { lines.push(row[1] + "  " + row[2]); keys.push(row[0]); });
      show(lines, event.clientX, event.clientY, keys);
    });
    overlay.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hide(); });
  });
})();
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb; --text-primary: #0b0b0b; --text-secondary: #52514e;
  --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  {series_light}
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    {series_dark}
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  {series_dark}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--page); color: var(--text-primary); font: 14px/1.5 {font}; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 22px; margin: 0 0 16px; }}
h2 {{ font-size: 18px; margin: 32px 0 8px; }}
h3 {{ font-size: 15px; margin: 24px 0 8px; }}
h4 {{ font-size: 14px; margin: 16px 0 6px; }}
p, li {{ color: var(--text-secondary); max-width: 80ch; }}
code {{ font-family: ui-monospace, monospace; font-size: 12px; }}
.charts {{ display: grid; grid-template-columns: minmax(0, 860px); gap: 16px; }}
.card {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; min-width: 0; }}
.card h3 {{ margin: 0 0 2px; font-size: 14px; color: var(--text-primary); }}
.note {{ margin: 0 0 8px; font-size: 12px; color: var(--muted); }}
svg {{ width: 100%; height: auto; display: block; font-family: {font}; }}
.grid {{ stroke: var(--grid); stroke-width: 1; }}
.axis {{ stroke: var(--axis); stroke-width: 1; }}
.tick, .axis-name {{ fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }}
.row-label {{ fill: var(--text-secondary); font-size: 12px; }}
.connector {{ stroke: var(--axis); stroke-width: 2; }}
.dot {{ stroke: var(--surface-1); stroke-width: 2; }}
.hit {{ fill: transparent; }}
.mark {{ cursor: default; outline: none; }}
.mark:hover .dot, .mark:focus .dot {{ stroke: var(--text-primary); }}
.line {{ fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
.marker {{ stroke: var(--surface-1); stroke-width: 2; }}
.crosshair {{ stroke: var(--muted); stroke-width: 1; }}
.overlay {{ fill: transparent; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 0 0 6px; font-size: 12px; color: var(--text-secondary); }}
.legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
.key-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
.key-line {{ width: 14px; height: 2px; border-radius: 1px; display: inline-block; margin-right: 6px; vertical-align: middle; }}
#tip {{ position: fixed; z-index: 10; pointer-events: none; background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 6px; padding: 6px 8px; font-size: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.12); max-width: 360px; }}
.tip-value {{ color: var(--text-primary); font-weight: 600; }}
.tip-label {{ color: var(--text-secondary); }}
.table-wrap {{ overflow-x: auto; margin: 8px 0 16px; }}
table {{ border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }}
th, td {{ border-bottom: 1px solid var(--grid); padding: 4px 8px; text-align: left; vertical-align: top; }}
th {{ color: var(--text-primary); font-weight: 600; }}
td {{ color: var(--text-secondary); }}
</style>
</head>
<body>
<main>
<h1>{heading}</h1>
{note}
<div class="charts">
{charts}
</div>
{body}
</main>
<div id="tip" role="tooltip" hidden></div>
<script>{script}</script>
</body>
</html>
"""
