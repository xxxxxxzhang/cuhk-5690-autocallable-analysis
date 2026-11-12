"""Render comparable historical and scenario price charts as standalone SVG files."""
from datetime import date
from math import ceil

from reportlab.graphics import renderSVG
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors

from .payoff import ROOT


def _level_text(value):
    return f"{value:.0f}" if abs(value - round(value)) < 0.05 else f"{value:.1f}"


def _barrier_references(terms):
    """Return normalized barrier lines, merging near-identical published levels."""
    coupon = {
        symbol: 100 * float(spec["coupon_barrier"]) / float(spec["initial"])
        for symbol, spec in terms["underlyings"].items()
    }
    principal = {
        symbol: 100 * float(spec["principal_barrier"]) / float(spec["initial"])
        for symbol, spec in terms["underlyings"].items()
    }

    coupon_values = list(coupon.values())
    principal_values = list(principal.values())
    same_coupon = max(coupon_values) - min(coupon_values) <= 0.25
    same_principal = max(principal_values) - min(principal_values) <= 0.25
    coupon_level = sum(coupon_values) / len(coupon_values)
    principal_level = sum(principal_values) / len(principal_values)

    if same_coupon and same_principal and abs(coupon_level - principal_level) <= 0.25:
        return [(0.5 * (coupon_level + principal_level),
                 "Coupon / principal barrier", "#b42318")]

    references = []
    if same_coupon:
        references.append((coupon_level, "Coupon barrier", "#b42318"))
    else:
        references.extend((level, f"{symbol} coupon barrier", "#b42318")
                          for symbol, level in coupon.items())
    if same_principal:
        references.append((principal_level, "Principal barrier", "#d97706"))
    else:
        references.extend((level, f"{symbol} principal barrier", "#d97706")
                          for symbol, level in principal.items())
    return references


def plot_prices(close, terms, *, filename="normalized_prices.svg",
                title="Historical underlying performance", result=None,
                data_cutoff=None, source_note="Yahoo Finance daily close"):
    """Plot normalized prices over the full contractual observation horizon.

    Historical series stop at the last available date while the x-axis continues
    to the final observation. A complete simulated path may continue after an
    autocall; only the note cash flows, not the underlying process, terminate.
    """
    start = terms["pricing_date"]
    end = terms["schedule"][-1][0]
    start_x = date.fromisoformat(start).toordinal()
    end_x = date.fromisoformat(end).toordinal()

    plotting_data = {
        day: dict(values) for day, values in close.items() if start <= day <= end
    }
    plotting_data.setdefault(start, {
        symbol: spec["initial"] for symbol, spec in terms["underlyings"].items()
    })
    dates = sorted(plotting_data)
    if not dates:
        raise ValueError("No prices fall within the contractual chart horizon")

    fig = Drawing(900, 455)
    fig.add(Rect(0, 0, 900, 455, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 418, title, fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(
        60, 394,
        f"Index, {start} = 100   |   final observation {end}   |   {terms['isin']}",
        fontSize=11,
    ))

    chart = LinePlot()
    chart.x, chart.y, chart.width, chart.height = 60, 92, 790, 255
    chart.xValueAxis.valueMin, chart.xValueAxis.valueMax = start_x, end_x
    tick_dates = [start, *[row[0] for row in terms["schedule"][1::2]]]
    if end not in tick_dates:
        tick_dates.append(end)
    chart.xValueAxis.valueSteps = [date.fromisoformat(day).toordinal() for day in tick_dates]
    chart.xValueAxis.labelTextFormat = lambda value: date.fromordinal(int(value)).strftime("%b %y")
    chart.yValueAxis.visibleGrid = True
    chart.yValueAxis.gridStrokeColor = colors.HexColor("#e1e5ea")
    chart.yValueAxis.valueMin = 0
    chart.yValueAxis.valueStep = 25

    series, styles, labels = [], [], []

    def add_series(points, colour, width=1.0, dash=None):
        series.append(points)
        styles.append((colour, width, dash))

    palette = ["#1856a3", "#007657", "#ad4918"]
    normalized_values = []
    x_values = [date.fromisoformat(day).toordinal() for day in dates]
    for index, (symbol, spec) in enumerate(terms["underlyings"].items()):
        base = float(spec["initial"])
        values = [100 * float(plotting_data[day][symbol]) / base for day in dates]
        normalized_values.extend(values)
        add_series(list(zip(x_values, values)), palette[index], width=1.5)
        left = 60 + index * 118
        fig.add(Line(left, 374, left + 23, 374,
                     strokeColor=colors.HexColor(palette[index]), strokeWidth=2))
        fig.add(String(left + 28, 370, symbol, fontSize=10))

    autocall_level = 100 * float(terms["autocall"]["level_as_fraction_of_initial"])
    references = [(autocall_level, "Autocall level", "#555d68"),
                  *_barrier_references(terms)]
    reference_values = [value for value, _, _ in references]
    y_max = max(125, ceil(max([*normalized_values, *reference_values]) / 25) * 25)
    chart.yValueAxis.valueMax = y_max

    for level, label, colour in references:
        add_series([(start_x, level), (end_x, level)], colour, width=1.1, dash=[5, 3])
        labels.append((level, label, colour))

    processed_observations = {
        row["observation_date"] for row in (result or {}).get("rows", [])
    }
    for observation, _ in terms["schedule"]:
        observation_x = date.fromisoformat(observation).toordinal()
        colour = "#9aa2ad" if observation in processed_observations else "#d9dee5"
        add_series([(observation_x, 0), (observation_x, y_max)],
                   colour, width=0.55, dash=[2, 3])

    add_series([(start_x, 0), (start_x, y_max)],
               "#6f42c1", width=1.2, dash=[3, 3])

    if data_cutoff is not None and start <= data_cutoff < end:
        cutoff_x = date.fromisoformat(data_cutoff).toordinal()
        add_series([(cutoff_x, 0), (cutoff_x, y_max)],
                   "#111827", width=1.0, dash=[4, 3])
    else:
        cutoff_x = None

    autocall_date = (result or {}).get("autocall_date")
    if autocall_date is not None:
        call_x = date.fromisoformat(autocall_date).toordinal()
        add_series([(call_x, 0), (call_x, y_max)],
                   "#c2410c", width=1.8, dash=[6, 2])
    else:
        call_x = None

    chart.data = series
    for index, (colour, width, dash) in enumerate(styles):
        chart.lines[index].strokeColor = colors.HexColor(colour)
        chart.lines[index].strokeWidth = width
        if dash is not None:
            chart.lines[index].strokeDashArray = dash
    fig.add(chart)

    def x_position(value):
        return chart.x + chart.width * (value - start_x) / (end_x - start_x)

    def y_position(value):
        return chart.y + chart.height * value / y_max

    for level, label, colour in labels:
        fig.add(String(chart.x + 7, y_position(level) + 4,
                       f"{_level_text(level)}  {label}",
                       fillColor=colors.HexColor(colour), fontSize=9))

    for period, (observation, _) in enumerate(terms["schedule"], start=1):
        observation_x = date.fromisoformat(observation).toordinal()
        colour = "#555d68" if observation in processed_observations else "#aab2bd"
        fig.add(String(x_position(observation_x) - 6, chart.y + chart.height - 11,
                       f"O{period}", fillColor=colors.HexColor(colour), fontSize=7))

    fig.add(String(chart.x + 5, chart.y + 8, "Pricing date",
                   fillColor=colors.HexColor("#6f42c1"), fontSize=8))
    if cutoff_x is not None:
        fig.add(String(x_position(cutoff_x) + 4, chart.y + chart.height - 26,
                       f"Data cutoff  {data_cutoff}", fontSize=8))
    if call_x is not None:
        fig.add(String(x_position(call_x) + 4, chart.y + chart.height - 39,
                       f"Autocalled  {autocall_date}",
                       fillColor=colors.HexColor("#c2410c"), fontSize=8))

    footer = f"Source: {source_note}  |  chart horizon {start} through {end}"
    if autocall_date is not None and max(dates) > autocall_date:
        footer += "  |  post-autocall prices do not affect note cash flows"
    fig.add(String(60, 40, footer, fontSize=9))

    target = ROOT / "output/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target
