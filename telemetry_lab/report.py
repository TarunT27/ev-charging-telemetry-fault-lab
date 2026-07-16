"""Self-contained, offline HTML analytics report."""

from __future__ import annotations

from collections import Counter
from html import escape

from telemetry_lab.models import ScenarioResult


def _series_polyline(result: ScenarioResult, width: int = 920, height: int = 260) -> str:
    samples = result.observed_samples
    if not samples:
        return ""
    maximum = max(1.0, max(sample.power_kw for sample in samples))
    grouped: dict[str, list[tuple[int, float]]] = {}
    for sample in samples:
        grouped.setdefault(sample.charger_id, []).append((sample.sequence, max(0.0, sample.power_kw)))
    palette = ("#66e3c4", "#ffb454", "#8aa8ff", "#f4748b", "#b794f6")
    lines: list[str] = []
    denominator = max(1, result.config.samples_per_charger - 1)
    for index, (charger_id, points) in enumerate(grouped.items()):
        coordinates = " ".join(
            f"{40 + sequence / denominator * (width - 70):.1f},{height - 28 - power / maximum * (height - 55):.1f}"
            for sequence, power in points
        )
        lines.append(
            f'<polyline points="{coordinates}" fill="none" stroke="{palette[index % len(palette)]}" '
            f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><title>{escape(charger_id)}</title></polyline>'
        )
    return "".join(lines)


def render_html_report(result: ScenarioResult) -> str:
    """Render a portable dashboard with no remote scripts, fonts, or images."""

    metrics = result.report.metrics
    fault_counts = Counter(event.fault_type.value for event in result.events)
    finding_counts = Counter(finding.rule for finding in result.report.findings)
    fault_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{count}</td><td><span class='bar' style='--w:{min(100, count * 8)}%'></span></td></tr>"
        for name, count in fault_counts.most_common()
    ) or "<tr><td colspan='3' class='muted'>No faults injected</td></tr>"
    finding_rows = "".join(
        f"<li><span>{escape(name)}</span><strong>{count}</strong></li>" for name, count in finding_counts.most_common(6)
    ) or "<li><span>No anomaly findings</span><strong>0</strong></li>"
    event_rows = "".join(
        f"<tr><td>{escape(event.charger_id)}</td><td>{event.sequence}</td><td><code>{escape(event.fault_type.value)}</code></td>"
        f"<td>{escape(event.detail)}</td></tr>"
        for event in result.events[:12]
    ) or "<tr><td colspan='4' class='muted'>Baseline run: no injected events</td></tr>"
    recovery_rows = "".join(
        f"<tr><td>{escape(action.charger_id)}</td><td>{action.sequence}</td><td><code>{escape(action.action)}</code></td>"
        f"<td>{escape(action.outcome)}</td><td>{escape(action.detail)}</td></tr>"
        for action in result.recovery_actions[:16]
    ) or "<tr><td colspan='5' class='muted'>Baseline run: no recovery actions required</td></tr>"
    detection_percent = metrics.detection_rate * 100
    title = escape(result.config.name)
    polyline = _series_polyline(result)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Telemetry Fault Lab</title>
<style>
:root{{--ink:#eaf4ff;--muted:#8fa6bd;--panel:#101d2b;--panel2:#142638;--line:#223a50;--mint:#66e3c4;--amber:#ffb454;--red:#f4748b;--blue:#8aa8ff}}
*{{box-sizing:border-box}}body{{margin:0;background:#07111c;color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}}
body:before{{content:"";position:fixed;inset:0;background:radial-gradient(circle at 80% 0,#153a4f80,transparent 38%),linear-gradient(135deg,#07111c,#0b1724);z-index:-1}}
.shell{{max-width:1180px;margin:auto;padding:42px 24px 64px}}.eyebrow{{color:var(--mint);font-size:12px;letter-spacing:.16em;text-transform:uppercase;font-weight:800}}
h1{{font-size:clamp(32px,5vw,62px);line-height:1.02;margin:10px 0 14px;max-width:820px}}.lede{{color:var(--muted);max-width:680px;font-size:17px}}
.status{{display:inline-flex;gap:9px;align-items:center;margin-top:20px;padding:8px 12px;border:1px solid #2b4a5e;border-radius:999px;background:#0b1b28}}.dot{{width:8px;height:8px;background:var(--mint);border-radius:50%;box-shadow:0 0 18px var(--mint)}}
.grid{{display:grid;gap:16px}}.kpis{{grid-template-columns:repeat(5,1fr);margin:34px 0}}.card{{background:linear-gradient(145deg,#122333e8,#0d1a27e8);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 18px 50px #0004}}
.kpi strong{{display:block;font-size:28px;margin-top:7px}}.kpi span{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}}.accent{{color:var(--mint)}}
.main{{grid-template-columns:minmax(0,2fr) minmax(270px,1fr)}}h2{{font-size:18px;margin:0 0 16px}}.chart{{width:100%;height:auto;background:#091622;border:1px solid #1e3447;border-radius:14px}}
.axis{{stroke:#31475a;stroke-width:1}}.chart-label{{fill:#7790a8;font-size:12px}}.list{{list-style:none;margin:0;padding:0}}.list li{{display:flex;justify-content:space-between;padding:11px 0;border-bottom:1px solid var(--line)}}
.ring{{width:130px;aspect-ratio:1;border-radius:50%;margin:10px auto 20px;background:conic-gradient(var(--mint) 0 {detection_percent:.1f}%,#203345 {detection_percent:.1f}%);display:grid;place-items:center}}.ring:after{{content:"{detection_percent:.0f}%";display:grid;place-items:center;width:92px;aspect-ratio:1;border-radius:50%;background:#10202e;font-weight:800;font-size:24px}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:12px 10px;border-bottom:1px solid var(--line)}}th{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}}code{{color:var(--amber);background:#2b2218;padding:3px 7px;border-radius:6px}}.muted{{color:var(--muted)}}
.bar{{display:block;width:var(--w);height:7px;background:linear-gradient(90deg,var(--mint),var(--blue));border-radius:99px;min-width:4px}}.section{{margin-top:16px}}.foot{{color:var(--muted);font-size:12px;margin-top:26px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}}
@media(max-width:850px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.main{{grid-template-columns:1fr}}}}@media(max-width:520px){{.kpis{{grid-template-columns:1fr}}.shell{{padding:28px 14px}}.table-wrap{{overflow:auto}}}}
</style></head><body><main class="shell">
<div class="eyebrow">EV Reliability Engineering · Deterministic Run</div><h1>{title}</h1>
<p class="lede">A virtual charger/controller replay with injected ground truth, explainable diagnostics, bounded retry and reconnect recovery, and reproducible seed <strong>{result.config.seed}</strong>.</p><div class="status"><span class="dot"></span> recovery verified · {len(result.original_samples)} source samples</div>
<section class="grid kpis">
<article class="card kpi"><span>Detection rate</span><strong class="accent">{detection_percent:.0f}%</strong></article>
<article class="card kpi"><span>Recovery rate</span><strong class="accent">{metrics.recovery_rate * 100:.0f}%</strong></article>
<article class="card kpi"><span>Retries</span><strong>{metrics.retry_count}</strong></article>
<article class="card kpi"><span>Reconnects</span><strong>{metrics.reconnect_count}</strong></article>
<article class="card kpi"><span>Unsafe actions</span><strong>{metrics.unsafe_actions}</strong></article></section>
<section class="grid main"><article class="card"><h2>Fleet power profile</h2><svg class="chart" viewBox="0 0 920 260" role="img" aria-label="Power over scenario sequence"><line class="axis" x1="40" y1="232" x2="890" y2="232"/><line class="axis" x1="40" y1="20" x2="40" y2="232"/><text class="chart-label" x="47" y="42">kW</text><text class="chart-label" x="820" y="250">sequence</text>{polyline}</svg></article>
<aside class="card"><h2>Detector coverage</h2><div class="ring" aria-label="Detection rate {detection_percent:.0f} percent"></div><ul class="list">{finding_rows}</ul></aside></section>
<section class="grid main section"><article class="card"><h2>Injected fault distribution</h2><div class="table-wrap"><table><thead><tr><th>Fault</th><th>Count</th><th>Relative volume</th></tr></thead><tbody>{fault_rows}</tbody></table></div></article>
<article class="card"><h2>Run contract</h2><ul class="list"><li><span>Chargers</span><strong>{result.config.charger_count}</strong></li><li><span>Samples / charger</span><strong>{result.config.samples_per_charger}</strong></li><li><span>Injected faults</span><strong>{metrics.injected_faults}</strong></li><li><span>Energy observed</span><strong>{metrics.energy_kwh:.1f} kWh</strong></li><li><span>P95 injected delay</span><strong>{metrics.p95_delay_ms} ms</strong></li></ul></article></section>
<section class="card section"><h2>Ground-truth event trail</h2><div class="table-wrap"><table><thead><tr><th>Charger</th><th>Sequence</th><th>Fault</th><th>Injection detail</th></tr></thead><tbody>{event_rows}</tbody></table></div></section>
<section class="card section"><h2>Virtual controller recovery log</h2><div class="table-wrap"><table><thead><tr><th>Charger</th><th>Sequence</th><th>Action</th><th>Outcome</th><th>Safety evidence</th></tr></thead><tbody>{recovery_rows}</tbody></table></div></section>
<footer class="foot"><span>Generated offline by EV Charging Telemetry Fault Lab</span><span>Synthetic data only · no charger control commands</span></footer>
</main></body></html>"""
