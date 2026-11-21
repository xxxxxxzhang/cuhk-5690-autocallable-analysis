"""Render historical, scenario and Monte Carlo charts as standalone SVG files."""
from collections import Counter
from datetime import date
from math import ceil
from statistics import median

from reportlab.graphics import renderSVG
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
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


def plot_simulated_paths(paths, terms, *, filename="monte_carlo_paths.svg", max_paths=40,
                         total_paths=None):
    """Plot a representative subset and the median of simulated normalized paths."""
    if not paths:
        raise ValueError("At least one simulated path is required")
    symbols = list(terms["underlyings"])
    observations = [row[0] for row in terms["schedule"]]
    step = max(1, len(paths) // max_paths)
    selected = paths[::step][:max_paths]
    fig = Drawing(900, 650)
    fig.add(Rect(0, 0, 900, 650, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 615, "Correlated-GBM simulated underlying paths",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 592,
                   f"{(total_paths or len(paths)):,} paths generated; {len(selected)} displayed; pricing date = 100",
                   fontSize=11))

    palette = ["#1856a3", "#007657", "#ad4918"]
    for panel, symbol in enumerate(symbols):
        base = float(terms["underlyings"][symbol]["initial"])
        series = []
        all_values = []
        for path in selected:
            values = [100.0] + [100.0 * float(path[day][symbol]) / base for day in observations]
            all_values.append(values)
            series.append(list(enumerate(values)))
        median_values = [median(values[index] for values in all_values)
                         for index in range(len(observations) + 1)]
        series.append(list(enumerate(median_values)))

        autocall = 100.0 * float(terms["autocall"]["level_as_fraction_of_initial"])
        barrier = 100.0 * float(terms["underlyings"][symbol]["coupon_barrier"]) / base
        series.extend(([(0, autocall), (len(observations), autocall)],
                       [(0, barrier), (len(observations), barrier)]))
        values_flat = [value for values in all_values for value in values]
        y_min = max(0, 25 * int(min([*values_flat, barrier]) / 25))
        y_max = max(125, 25 * ceil(max([*values_flat, autocall]) / 25))

        chart = LinePlot()
        chart.x, chart.y = 60, 415 - panel * 175
        chart.width, chart.height = 790, 120
        chart.xValueAxis.valueMin, chart.xValueAxis.valueMax = 0, len(observations)
        chart.xValueAxis.valueSteps = list(range(0, len(observations) + 1, 2))
        chart.xValueAxis.labelTextFormat = lambda value: "P" if value == 0 else f"O{int(value)}"
        chart.yValueAxis.valueMin, chart.yValueAxis.valueMax = y_min, y_max
        chart.yValueAxis.valueStep = max(25, 25 * ceil((y_max - y_min) / 125))
        chart.yValueAxis.visibleGrid = True
        chart.yValueAxis.gridStrokeColor = colors.HexColor("#e5e7eb")
        chart.data = series
        for index in range(len(selected)):
            chart.lines[index].strokeColor = colors.HexColor("#cbd5e1")
            chart.lines[index].strokeWidth = 0.55
        median_index = len(selected)
        chart.lines[median_index].strokeColor = colors.HexColor(palette[panel])
        chart.lines[median_index].strokeWidth = 2.2
        chart.lines[median_index + 1].strokeColor = colors.HexColor("#555d68")
        chart.lines[median_index + 1].strokeDashArray = [5, 3]
        chart.lines[median_index + 2].strokeColor = colors.HexColor("#b42318")
        chart.lines[median_index + 2].strokeDashArray = [5, 3]
        fig.add(chart)
        fig.add(String(60, chart.y + chart.height + 12, symbol,
                       fontName="Helvetica-Bold", fontSize=12,
                       fillColor=colors.HexColor(palette[panel])))

    fig.add(String(60, 25,
                   "Grey paths  |  Coloured median  |  Dashed autocall and coupon barriers",
                   fontSize=9))
    target = ROOT / "output/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_value_distribution(present_values, estimated_value, principal, *,
                            issuer_estimate=940.80,
                            filename="monte_carlo_value_distribution.svg", bins=30):
    """Render a compact histogram of discounted path values."""
    if len(present_values) == 0:
        raise ValueError("At least one present value is required")
    low, high = min(present_values), max(present_values)
    if high <= low:
        low, high = low - 1.0, high + 1.0
    width = (high - low) / bins
    counts = [0] * bins
    for value in present_values:
        index = min(int((value - low) / width), bins - 1)
        counts[index] += 1

    fig = Drawing(900, 455)
    fig.add(Rect(0, 0, 900, 455, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 418, "Monte Carlo discounted payoff distribution",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 394,
                   f"{len(present_values):,} simulated paths   |   value per USD {principal:,.0f} note",
                   fontSize=11))
    left, bottom, plot_width, plot_height = 65, 85, 780, 255
    maximum = max(counts)
    bar_width = plot_width / bins
    for index, count in enumerate(counts):
        height = 0 if maximum == 0 else plot_height * count / maximum
        fig.add(Rect(left + index * bar_width, bottom, max(1, bar_width - 1), height,
                     fillColor=colors.HexColor("#7aa5d8"), strokeColor=None))
    fig.add(Line(left, bottom, left + plot_width, bottom, strokeColor=colors.black))
    fig.add(Line(left, bottom, left, bottom + plot_height, strokeColor=colors.black))

    def x_position(value):
        return left + plot_width * (value - low) / (high - low)

    for tick in range(5):
        value = low + (high - low) * tick / 4
        x = x_position(value)
        fig.add(Line(x, bottom - 4, x, bottom, strokeColor=colors.black))
        fig.add(String(x - 18, bottom - 20, f"{value:,.0f}", fontSize=8))
    markers = (
        (estimated_value, "Model value", "#0b5cab", -97, -13),
        (issuer_estimate, "Barclays estimate", "#6f42c1", 7, -31),
        (principal, "Issue price", "#b42318", 7, -49),
    )
    for value, label, colour, label_dx, label_dy in markers:
        if low <= value <= high:
            x = x_position(value)
            fig.add(Line(x, bottom, x, bottom + plot_height,
                         strokeColor=colors.HexColor(colour), strokeWidth=1.8,
                         strokeDashArray=[5, 3]))
            fig.add(String(x + label_dx, bottom + plot_height + label_dy,
                           f"{label}: {value:,.2f}",
                           fillColor=colors.HexColor(colour), fontSize=9))
    fig.add(String(60, 38,
                   "Historical-baseline correlated GBM; risk-neutral values are model outputs, not market quotes.",
                   fontSize=9))
    target = ROOT / "output/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_maturity_redemption_map(terms, *, filename="maturity_redemption_map.svg"):
    """Show the maturity principal rule as a worst-of/best-of state map."""
    fig = Drawing(900, 520)
    fig.add(Rect(0, 0, 900, 520, fillColor=colors.white, strokeColor=None))
    fig.add(String(65, 482, "Maturity principal redemption map",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(65, 458,
                   "Worst-of below 50 can still receive full principal when best-of reaches 100",
                   fontSize=11))
    left, bottom, width, height = 90, 90, 720, 330
    x_max, y_max, cells = 120.0, 160.0, 48
    face = float(terms["principal"])
    barrier = sum(
        100 * float(spec["principal_barrier"]) / float(spec["initial"])
        for spec in terms["underlyings"].values()
    ) / len(terms["underlyings"])
    best_level = 100 * float(terms["maturity"]["best_of_principal_protection_level"])
    cell_w, cell_h = width / cells, height / cells

    for ix in range(cells):
        worst = x_max * (ix + 0.5) / cells
        for iy in range(cells):
            best = y_max * (iy + 0.5) / cells
            if best + 1e-9 < worst:
                fill = colors.HexColor("#f3f4f6")
            else:
                redemption = face if worst >= barrier or best >= best_level else face * worst / 100
                fraction = redemption / face
                fill = colors.Color(
                    0.86 - 0.52 * fraction,
                    0.25 + 0.38 * fraction,
                    0.20 + 0.60 * fraction,
                )
            fig.add(Rect(left + ix * cell_w, bottom + iy * cell_h,
                         cell_w + 0.2, cell_h + 0.2,
                         fillColor=fill, strokeColor=None))

    def x_pos(value):
        return left + width * value / x_max

    def y_pos(value):
        return bottom + height * value / y_max

    fig.add(Line(x_pos(barrier), bottom, x_pos(barrier), bottom + height,
                 strokeColor=colors.HexColor("#b42318"), strokeWidth=1.7,
                 strokeDashArray=[5, 3]))
    fig.add(Line(left, y_pos(best_level), left + width, y_pos(best_level),
                 strokeColor=colors.HexColor("#6f42c1"), strokeWidth=1.7,
                 strokeDashArray=[5, 3]))
    fig.add(String(x_pos(barrier) + 5, bottom + 8, f"Barrier {barrier:.0f}",
                   fillColor=colors.HexColor("#b42318"), fontSize=9))
    fig.add(String(left + 8, y_pos(best_level) + 5, f"Best-of protection {best_level:.0f}",
                   fillColor=colors.HexColor("#6f42c1"), fontSize=9))
    fig.add(Line(left, bottom, left + width, bottom, strokeColor=colors.black))
    fig.add(Line(left, bottom, left, bottom + height, strokeColor=colors.black))
    for value in (0, 25, 50, 75, 100, 120):
        x = x_pos(value)
        fig.add(Line(x, bottom - 4, x, bottom, strokeColor=colors.black))
        fig.add(String(x - 8, bottom - 19, f"{value:.0f}", fontSize=8))
    for value in (0, 50, 100, 150):
        y = y_pos(value)
        fig.add(Line(left - 4, y, left, y, strokeColor=colors.black))
        fig.add(String(left - 28, y - 3, f"{value:.0f}", fontSize=8))
    fig.add(String(left + width / 2 - 65, 55, "Worst-of at maturity (% of initial)", fontSize=10))
    fig.add(String(8, bottom + height / 2, "Best-of (% of initial)", fontSize=10))
    fig.add(String(610, 65, "Grey: infeasible (best-of < worst-of)", fontSize=8))
    target = ROOT / "output/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_exit_distribution(exit_rows, *, scenario="historical_baseline",
                           filename="exit_distribution.svg"):
    """Plot unconditional autocall and maturity exit probabilities by period."""
    rows = [row for row in exit_rows if row["scenario"] == scenario]
    rows.sort(key=lambda row: int(row["period"]))
    if not rows:
        raise ValueError(f"No exit distribution for {scenario}")
    fig = Drawing(900, 480)
    fig.add(Rect(0, 0, 900, 480, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 442, "Exit timing under the historical baseline",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 418,
                   "Unconditional share of all risk-neutral paths; O12 is maturity",
                   fontSize=11))
    left, bottom, width, height = 70, 92, 780, 285
    maximum = max(float(row["autocall_Q"]) + float(row["maturity_Q"]) for row in rows)
    y_max = max(0.60, ceil(maximum * 10) / 10)
    slot = width / len(rows)
    cumulative, previous = 0.0, None
    for index, row in enumerate(rows):
        autocall = float(row["autocall_Q"])
        maturity = float(row["maturity_Q"])
        x = left + index * slot + slot * 0.18
        call_height = height * autocall / y_max
        maturity_height = height * maturity / y_max
        fig.add(Rect(x, bottom, slot * 0.64, call_height,
                     fillColor=colors.HexColor("#d97706"), strokeColor=None))
        fig.add(Rect(x, bottom + call_height, slot * 0.64, maturity_height,
                     fillColor=colors.HexColor("#6f42c1"), strokeColor=None))
        total = autocall + maturity
        if total >= 0.01:
            fig.add(String(x - 2, bottom + call_height + maturity_height + 5,
                           f"{total:.1%}", fontSize=7))
        fig.add(String(x + slot * 0.18, bottom - 18, f"O{row['period']}", fontSize=8))
        cumulative += autocall
        point = (x + slot * 0.32, bottom + height * cumulative / y_max)
        if previous is not None:
            fig.add(Line(previous[0], previous[1], point[0], point[1],
                         strokeColor=colors.HexColor("#1856a3"), strokeWidth=1.6))
        fig.add(Circle(point[0], point[1], 2.4,
                       fillColor=colors.HexColor("#1856a3"), strokeColor=None))
        previous = point
    fig.add(Line(left, bottom, left + width, bottom, strokeColor=colors.black))
    fig.add(Line(left, bottom, left, bottom + height, strokeColor=colors.black))
    for value in (0.0, 0.2, 0.4, 0.6):
        y = bottom + height * value / y_max
        fig.add(Line(left - 4, y, left, y, strokeColor=colors.black))
        fig.add(String(left - 38, y - 3, f"{value:.0%}", fontSize=8))
    fig.add(Rect(610, 395, 12, 8, fillColor=colors.HexColor("#d97706"), strokeColor=None))
    fig.add(String(627, 393, "Autocall", fontSize=9))
    fig.add(Rect(690, 395, 12, 8, fillColor=colors.HexColor("#6f42c1"), strokeColor=None))
    fig.add(String(707, 393, "Maturity", fontSize=9))
    fig.add(Line(775, 399, 794, 399, strokeColor=colors.HexColor("#1856a3"), strokeWidth=1.6))
    fig.add(String(800, 393, "Cumulative call", fontSize=9))
    fig.add(String(60, 42,
                   "Risk-neutral model probabilities, not forecasts of real-world frequencies.",
                   fontSize=9))
    target = ROOT / "output/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_scenario_sensitivity(rows, *, filename="scenario_sensitivity.svg"):
    """Plot scenario value changes relative to the historical baseline."""
    values = {row["scenario"]: float(row["pv_usd"]) for row in rows}
    baseline = values["historical_baseline"]
    order = [
        ("half_year_window", "Half-year window"),
        ("lower_correlation", "Lower correlation"),
        ("higher_correlation", "Higher correlation"),
        ("no_memory_counterfactual", "No memory coupon"),
        ("high_vol_and_low_correlation", "High vol + low corr"),
        ("all_vols_plus_25pct", "All vols +25%"),
        ("no_best_protection_counterfactual", "No best-of protection"),
    ]
    deltas = [(key, label, values[key] - baseline) for key, label in order]
    bound = max(abs(delta) for _key, _label, delta in deltas) * 1.15
    fig = Drawing(900, 500)
    fig.add(Rect(0, 0, 900, 500, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 462, "Model-value sensitivity",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 438,
                   f"Change from historical baseline value of USD {baseline:,.2f} per note",
                   fontSize=11))
    left, centre, right = 255, 545, 835
    top, gap = 390, 43
    fig.add(Line(centre, 82, centre, 406, strokeColor=colors.HexColor("#6b7280"),
                 strokeWidth=1.0))
    for index, (_key, label, delta) in enumerate(deltas):
        y = top - index * gap
        x = centre + (right - centre) * delta / bound
        colour = "#1856a3" if delta >= 0 else "#b42318"
        fig.add(String(60, y - 4, label, fontSize=10))
        fig.add(Line(centre, y, x, y, strokeColor=colors.HexColor(colour), strokeWidth=2.0))
        fig.add(Circle(x, y, 4, fillColor=colors.HexColor(colour), strokeColor=None))
        text = f"{delta:+.2f}"
        fig.add(String(x + (7 if delta >= 0 else -45), y - 4, text,
                       fillColor=colors.HexColor(colour), fontSize=9))
    fig.add(String(left - 18, 60, f"−{bound:.0f}", fontSize=8))
    fig.add(String(centre - 4, 60, "0", fontSize=8))
    fig.add(String(right - 10, 60, f"+{bound:.0f}", fontSize=8))
    fig.add(String(60, 27,
                   "Historical-window, market-parameter and contract counterfactuals are distinct tests.",
                   fontSize=9))
    target = ROOT / "output/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_nominal_return_distribution(returns, *,
                                     filename="nominal_return_distribution.svg",
                                     bins=40):
    """Show the left-tailed risk-neutral distribution of nominal total returns."""
    values = [float(value) for value in returns]
    if not values:
        raise ValueError("At least one nominal return is required")
    ordered = sorted(values)
    low, high = ordered[0], ordered[-1]
    width = (high - low) / bins if high > low else 1.0
    counts = [0] * bins
    for value in values:
        index = min(int((value - low) / width), bins - 1)
        counts[index] += 1
    mean = sum(values) / len(values)
    median_value = median(values)
    p05 = ordered[int((len(ordered) - 1) * 0.05)]
    fig = Drawing(900, 455)
    fig.add(Rect(0, 0, 900, 455, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 418, "Risk-neutral nominal return distribution",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 394,
                   "Undiscounted total receipts divided by USD 1,000, less one",
                   fontSize=11))
    left, bottom, plot_width, plot_height = 65, 85, 780, 255
    maximum = max(counts)
    bar_width = plot_width / bins
    for index, count in enumerate(counts):
        midpoint = low + width * (index + 0.5)
        height = plot_height * count / maximum if maximum else 0
        colour = "#c95b52" if midpoint <= p05 else "#7aa5d8"
        fig.add(Rect(left + index * bar_width, bottom, max(1, bar_width - 1), height,
                     fillColor=colors.HexColor(colour), strokeColor=None))
    fig.add(Line(left, bottom, left + plot_width, bottom, strokeColor=colors.black))
    fig.add(Line(left, bottom, left, bottom + plot_height, strokeColor=colors.black))

    def x_position(value):
        return left + plot_width * (value - low) / (high - low)

    markers = (
        (mean, "Mean", "#0b5cab", -55, -13),
        (median_value, "Median", "#007657", 6, -31),
        (p05, "5th percentile", "#b42318", 6, -49),
    )
    for value, label, colour, dx, dy in markers:
        x = x_position(value)
        fig.add(Line(x, bottom, x, bottom + plot_height,
                     strokeColor=colors.HexColor(colour), strokeWidth=1.5,
                     strokeDashArray=[5, 3]))
        fig.add(String(x + dx, bottom + plot_height + dy,
                       f"{label}: {value:.1%}",
                       fillColor=colors.HexColor(colour), fontSize=9))
    for tick in range(5):
        value = low + (high - low) * tick / 4
        x = x_position(value)
        fig.add(String(x - 15, bottom - 20, f"{value:.0%}", fontSize=8))
    fig.add(String(60, 38,
                   "Red bars mark the worst 5% tail; probabilities are risk-neutral, not real-world forecasts.",
                   fontSize=9))
    target = ROOT / "output/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_parameter_window_comparison(calibrations, scenario_rows, *,
                                     filename="parameter_window_comparison.svg"):
    """Compare full-year and half-year volatility estimates and model values."""
    full, half = calibrations
    scenario = {row["scenario"]: float(row["pv_usd"]) for row in scenario_rows}
    symbols = list(full["volatilities"])
    fig = Drawing(900, 470)
    fig.add(Rect(0, 0, 900, 470, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 432, "Historical-window sensitivity",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 408,
                   "Annualized volatility estimates and resulting model value",
                   fontSize=11))
    left, bottom, width, height = 85, 105, 500, 240
    slot = width / len(symbols)
    for index, symbol in enumerate(symbols):
        full_vol = float(full["volatilities"][symbol])
        half_vol = float(half["volatilities"][symbol])
        x = left + index * slot + 30
        fig.add(Rect(x, bottom, 38, height * full_vol / 0.75,
                     fillColor=colors.HexColor("#1856a3"), strokeColor=None))
        fig.add(Rect(x + 48, bottom, 38, height * half_vol / 0.75,
                     fillColor=colors.HexColor("#7aa5d8"), strokeColor=None))
        fig.add(String(x + 18, bottom - 20, symbol, fontSize=9))
        fig.add(String(x - 1, bottom + height * full_vol / 0.75 + 5,
                       f"{full_vol:.1%}", fontSize=8))
        fig.add(String(x + 45, bottom + height * half_vol / 0.75 + 5,
                       f"{half_vol:.1%}", fontSize=8))
    fig.add(Line(left, bottom, left + width, bottom, strokeColor=colors.black))
    fig.add(String(650, 325, "Model value", fontName="Helvetica-Bold", fontSize=12))
    fig.add(String(650, 285, f"Full year   USD {scenario['historical_baseline']:,.2f}", fontSize=11))
    fig.add(String(650, 250, f"Half year   USD {scenario['half_year_window']:,.2f}", fontSize=11))
    delta = scenario["half_year_window"] - scenario["historical_baseline"]
    fig.add(String(650, 210, f"Difference  {delta:+,.2f}",
                   fillColor=colors.HexColor("#b42318"), fontSize=11))
    fig.add(Rect(610, 380, 12, 8, fillColor=colors.HexColor("#1856a3"), strokeColor=None))
    fig.add(String(627, 378, "Full-year window", fontSize=9))
    fig.add(Rect(735, 380, 12, 8, fillColor=colors.HexColor("#7aa5d8"), strokeColor=None))
    fig.add(String(752, 378, "Half-year window", fontSize=9))
    fig.add(String(60, 42,
                   "The window changes volatility and correlation jointly; it is not a one-factor shock.",
                   fontSize=9))
    target = ROOT / "output/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_correlation_heatmap(calibrations, *,
                             filename="correlation_heatmap.svg"):
    """Compare historical Pearson correlations from two calibration windows."""
    if len(calibrations) != 2:
        raise ValueError("Exactly two calibration windows are required")
    symbols = list(calibrations[0]["correlation"])
    if not symbols:
        raise ValueError("Correlation matrix cannot be empty")

    fig = Drawing(900, 470)
    fig.add(Rect(0, 0, 900, 470, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 432, "Historical correlation comparison",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 408,
                   "Pearson correlations of daily log returns through the pricing date",
                   fontSize=11))

    panel_lefts = [105, 535]
    cell = 78
    for panel, (calibration, panel_left) in enumerate(zip(calibrations, panel_lefts, strict=True)):
        matrix = calibration["correlation"]
        label = (f"{calibration['window_start']} to "
                 f"{calibration['window_end']}")
        fig.add(String(panel_left, 365, label,
                       fontName="Helvetica-Bold", fontSize=11))
        fig.add(String(panel_left, 347,
                       f"{calibration['daily_returns']} daily returns",
                       fillColor=colors.HexColor("#555d68"), fontSize=9))
        for index, symbol in enumerate(symbols):
            fig.add(String(panel_left + index * cell + 23, 330, symbol,
                           fontName="Helvetica-Bold", fontSize=9))
            fig.add(String(panel_left - 46, 286 - index * cell, symbol,
                           fontName="Helvetica-Bold", fontSize=9))
        for row, left_symbol in enumerate(symbols):
            for column, right_symbol in enumerate(symbols):
                value = float(matrix[left_symbol][right_symbol])
                intensity = max(0.0, min(1.0, value))
                fill = colors.Color(
                    0.90 - 0.70 * intensity,
                    0.94 - 0.57 * intensity,
                    0.98 - 0.32 * intensity,
                )
                x = panel_left + column * cell
                y = 250 - row * cell
                fig.add(Rect(x, y, cell - 4, cell - 4,
                             fillColor=fill,
                             strokeColor=colors.HexColor("#d9dfe7"),
                             strokeWidth=0.6))
                text_colour = colors.white if value >= 0.75 else colors.HexColor("#17202a")
                fig.add(String(x + 20, y + 31, f"{value:.3f}",
                               fillColor=text_colour,
                               fontName="Helvetica-Bold", fontSize=10))

    legend_left, legend_bottom, legend_width = 330, 55, 240
    for index in range(24):
        intensity = index / 23
        fill = colors.Color(
            0.90 - 0.70 * intensity,
            0.94 - 0.57 * intensity,
            0.98 - 0.32 * intensity,
        )
        fig.add(Rect(legend_left + index * legend_width / 24, legend_bottom,
                     legend_width / 24 + 0.5, 10, fillColor=fill, strokeColor=None))
    fig.add(String(legend_left - 12, legend_bottom - 16, "0", fontSize=8))
    fig.add(String(legend_left + legend_width - 8, legend_bottom - 16, "1", fontSize=8))
    fig.add(String(legend_left + 76, legend_bottom - 16, "Correlation", fontSize=8))
    fig.add(String(60, 22,
                   "Changing the window alters all volatilities and correlations jointly; it is not a one-factor shock.",
                   fontSize=9))
    target = ROOT / "output/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_coupon_distribution(coupon_totals, coupon_amount, *,
                             filename="coupon_distribution.svg"):
    """Plot the risk-neutral distribution of total coupon receipts per note."""
    values = [float(value) for value in coupon_totals]
    if not values:
        raise ValueError("At least one coupon total is required")
    amount = float(coupon_amount)
    if amount <= 0:
        raise ValueError("coupon_amount must be positive")

    coupon_counts = [int(round(value / amount)) for value in values]
    frequencies = Counter(coupon_counts)
    maximum_count = max(frequencies)
    periods = list(range(maximum_count + 1))
    probabilities = [frequencies.get(period, 0) / len(values) for period in periods]
    maximum_probability = max(probabilities)

    fig = Drawing(900, 470)
    fig.add(Rect(0, 0, 900, 470, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 432, "Risk-neutral total coupon distribution",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 408,
                   f"Per USD 1,000 note  |  one contractual coupon = USD {amount:.3f}",
                   fontSize=11))

    left, bottom, plot_width, plot_height = 70, 100, 775, 250
    slot = plot_width / len(periods)
    bar_width = max(6, slot * 0.68)
    for period, probability in zip(periods, probabilities, strict=True):
        height = plot_height * probability / maximum_probability if maximum_probability else 0
        x = left + period * slot + (slot - bar_width) / 2
        colour = "#b42318" if period == 0 else "#3f79bd"
        fig.add(Rect(x, bottom, bar_width, height,
                     fillColor=colors.HexColor(colour), strokeColor=None))
        if probability >= 0.025:
            fig.add(String(x + max(0, bar_width / 2 - 13), bottom + height + 7,
                           f"{probability:.1%}", fontSize=8))
        fig.add(String(x + max(0, bar_width / 2 - 4), bottom - 20,
                       str(period), fontSize=8))

    fig.add(Line(left, bottom, left + plot_width, bottom, strokeColor=colors.black))
    fig.add(Line(left, bottom, left, bottom + plot_height, strokeColor=colors.black))
    for tick in range(5):
        probability = maximum_probability * tick / 4
        y = bottom + plot_height * tick / 4
        fig.add(Line(left - 4, y, left, y, strokeColor=colors.black))
        fig.add(String(left - 42, y - 3, f"{probability:.0%}", fontSize=8))
    fig.add(String(330, 58, "Number of contractual coupon periods ultimately paid", fontSize=9))
    zero_probability = probabilities[0]
    mean_coupon = sum(values) / len(values)
    fig.add(String(60, 30,
                   f"No-coupon paths: {zero_probability:.2%}  |  mean total coupon: USD {mean_coupon:.2f}",
                   fontSize=9))
    fig.add(String(525, 30,
                   "Memory changes timing and recovery, not the USD 39.125 unit.",
                   fillColor=colors.HexColor("#555d68"), fontSize=9))
    target = ROOT / "output/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_event_study_cars(rows, *, filename="spacex_car.svg"):
    """Compare target cumulative abnormal returns across event windows."""
    selected = sorted(rows, key=lambda row: (
        int(row["window_end"]) - int(row["window_start"]), row["target"]
    ))
    if not selected:
        raise ValueError("No event-study rows to plot")
    labels = [
        f"{row['target']} [{row['window_start']:+d},{row['window_end']:+d}]"
        for row in selected
    ]
    values = [100 * float(row["car"]) for row in selected]
    limit = max(1.0, max(abs(value) for value in values) * 1.25)
    fig = Drawing(900, 470)
    fig.add(Rect(0, 0, 900, 470, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 432, "SpaceX IPO cumulative abnormal returns",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 408,
                   "Two-factor market model: QQQ and SOXX; trading-day windows",
                   fontSize=11))
    left, bottom, width, height = 95, 105, 735, 245
    zero = bottom + height * limit / (2 * limit)
    fig.add(Line(left, zero, left + width, zero,
                 strokeColor=colors.HexColor("#374151"), strokeWidth=1))
    slot = width / len(values)
    bar_width = slot * 0.60
    for index, (label, value) in enumerate(zip(labels, values, strict=True)):
        x = left + index * slot + (slot - bar_width) / 2
        y = zero if value >= 0 else zero + height * value / (2 * limit)
        bar_height = abs(height * value / (2 * limit))
        colour = "#1d6f42" if value >= 0 else "#b42318"
        fig.add(Rect(x, y, bar_width, bar_height,
                     fillColor=colors.HexColor(colour), strokeColor=None))
        fig.add(String(x + 2, zero + (bar_height + 7 if value >= 0 else -18),
                       f"{value:.2f}%", fontSize=8,
                       fillColor=colors.HexColor(colour)))
        fig.add(String(x - 6, bottom - 24, label, fontSize=7))
    fig.add(String(60, 35,
                   "Negative CAR indicates underperformance after controlling for broad technology and semiconductor returns.",
                   fontSize=9))
    target = ROOT / "output/stress/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_factorial_stress(rows, *, filename="factorial_stress.svg"):
    """Show current value and key probabilities for the four factorial scenarios."""
    order = ["current_regime", "rate_only", "ipo_only", "joint"]
    by_name = {row["scenario"]: row for row in rows}
    if not set(order).issubset(by_name):
        raise ValueError("Factorial stress plot is missing a required scenario")
    values = [float(by_name[name]["pv_usd"]) for name in order]
    low = min(values) - 20
    high = max(values) + 20
    fig = Drawing(900, 500)
    fig.add(Rect(0, 0, 900, 500, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 462, "Rate-curve and mega-IPO proxy factorial stress test",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 438,
                   "All four factorial scenarios use identical shocks and the same election-regime parameters",
                   fontSize=11))
    left, bottom, width, height = 90, 145, 730, 245
    slot = width / len(order)
    palette = ["#4b78a8", "#d18f28", "#8f6bb3", "#b42318"]
    for index, name in enumerate(order):
        row = by_name[name]
        value = float(row["pv_usd"])
        x = left + index * slot + 38
        bar_width = slot - 76
        bar_height = height * (value - low) / (high - low)
        fig.add(Rect(x, bottom, bar_width, bar_height,
                     fillColor=colors.HexColor(palette[index]), strokeColor=None))
        fig.add(String(x + 5, bottom + bar_height + 9,
                       f"USD {value:.2f}", fontSize=9,
                       fillColor=colors.HexColor(palette[index])))
        fig.add(String(x, bottom - 22, name, fontSize=9))
        fig.add(String(x - 10, bottom - 43,
                       f"Call {float(row['autocall_Q']):.1%}", fontSize=8))
        fig.add(String(x - 10, bottom - 59,
                       f"Loss {float(row['principal_loss_Q']):.1%}", fontSize=8))
    fig.add(Line(left, bottom, left + width, bottom, strokeColor=colors.black))
    fig.add(String(60, 35,
                   "Base = current regime + flat rate; IPO = mega-IPO proxy shock sourced from SpaceX [-5,+5] CAR.",
                   fontSize=9))
    target = ROOT / "output/stress/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_interaction_effect(rows, *, filename="interaction_effect.svg"):
    """Visualize additive and actual joint effects on current note value."""
    by_name = {row["scenario"]: row for row in rows}
    base = float(by_name["current_regime"]["pv_usd"])
    rate_effect = float(by_name["rate_only"]["pv_usd"]) - base
    ipo_effect = float(by_name["ipo_only"]["pv_usd"]) - base
    additive = base + rate_effect + ipo_effect
    joint = float(by_name["joint"]["pv_usd"])
    interaction = joint - additive
    labels = ["Base", "Additive prediction", "Actual joint"]
    values = [base, additive, joint]
    low, high = min(values) - 20, max(values) + 20
    fig = Drawing(900, 455)
    fig.add(Rect(0, 0, 900, 455, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 417, "Nonlinear joint-effect diagnostic",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 393,
                   "Does the combined rate/mega-IPO proxy result equal the two standalone effects?",
                   fontSize=11))
    left, bottom, width, height = 125, 115, 650, 220
    slot = width / len(values)
    colours = ["#4b78a8", "#7c8b9a", "#b42318"]
    for index, (label, value) in enumerate(zip(labels, values, strict=True)):
        x = left + index * slot + 52
        bar_width = slot - 104
        bar_height = height * (value - low) / (high - low)
        fig.add(Rect(x, bottom, bar_width, bar_height,
                     fillColor=colors.HexColor(colours[index]), strokeColor=None))
        fig.add(String(x - 2, bottom + bar_height + 8,
                       f"USD {value:.2f}", fontSize=9))
        fig.add(String(x - 18, bottom - 22, label, fontSize=9))
    fig.add(Line(left, bottom, left + width, bottom, strokeColor=colors.black))
    fig.add(String(60, 50,
                   f"Rate effect {rate_effect:+.2f}  |  mega-IPO proxy effect {ipo_effect:+.2f}  |  interaction {interaction:+.2f} USD",
                   fontSize=10))
    target = ROOT / "output/stress/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target


def plot_election_regime(comparison_rows, scenario_rows, *,
                         filename="election_regime_comparison.svg"):
    """Compare pre/post election volatility and the legacy/current-regime value."""
    if not comparison_rows:
        raise ValueError("No election-regime comparison rows to plot")
    by_scenario = {row["scenario"]: row for row in scenario_rows}
    legacy = float(by_scenario["legacy_current"]["pv_usd"])
    regime = float(by_scenario["current_regime"]["pv_usd"])
    fig = Drawing(900, 510)
    fig.add(Rect(0, 0, 900, 510, fillColor=colors.white, strokeColor=None))
    fig.add(String(60, 472, "Post-midterm-election regime update",
                   fontName="Helvetica-Bold", fontSize=22))
    fig.add(String(60, 448,
                   "Equal-length realized windows for diagnosis; EWMA volatility for forward simulation",
                   fontSize=11))

    left, bottom, width, height = 75, 150, 540, 235
    maximum = 100 * max(
        max(float(row["pre_annualized_volatility"]),
            float(row["post_annualized_volatility"]),
            float(row["ewma_annualized_volatility"]))
        for row in comparison_rows
    ) * 1.20
    group_width = width / len(comparison_rows)
    colours = ["#7c8b9a", "#b42318", "#1d6f42"]
    labels = ["Pre-election", "Post-election", "EWMA current"]
    keys = ["pre_annualized_volatility", "post_annualized_volatility",
            "ewma_annualized_volatility"]
    for group, row in enumerate(comparison_rows):
        for index, key in enumerate(keys):
            value = 100 * float(row[key])
            bar_width = group_width / 5
            x = left + group * group_width + (index + 1) * bar_width
            bar_height = height * value / maximum
            fig.add(Rect(x, bottom, bar_width - 4, bar_height,
                         fillColor=colors.HexColor(colours[index]), strokeColor=None))
            fig.add(String(x - 1, bottom + bar_height + 7,
                           f"{value:.1f}%", fontSize=7))
        fig.add(String(left + group * group_width + group_width / 2 - 15,
                       bottom - 22, row["symbol"], fontSize=9))
    fig.add(Line(left, bottom, left + width, bottom, strokeColor=colors.black))
    for index, label in enumerate(labels):
        x = 80 + index * 135
        fig.add(Rect(x, 414, 12, 8, fillColor=colors.HexColor(colours[index]),
                     strokeColor=None))
        fig.add(String(x + 17, 411, label, fontSize=8))

    box_x = 660
    fig.add(String(box_x, 350, "Current-value comparison",
                   fontName="Helvetica-Bold", fontSize=11))
    fig.add(String(box_x, 318, f"Legacy parameters: USD {legacy:.2f}", fontSize=10))
    fig.add(String(box_x, 291, f"Election regime:  USD {regime:.2f}", fontSize=10))
    difference = regime - legacy
    fig.add(String(box_x, 264, f"Difference:       USD {difference:+.2f}",
                   fontSize=10,
                   fillColor=colors.HexColor("#1d6f42" if difference >= 0 else "#b42318")))
    fig.add(String(60, 55,
                   "The election date is a regime breakpoint, not a second price shock; current spots are not adjusted again.",
                   fontSize=9))
    target = ROOT / "output/stress/figures" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(fig, str(target))
    return target
