const form = document.querySelector('#scenario-form');
const chart = document.querySelector('#result-chart');
const svgNamespace = 'http://www.w3.org/2000/svg';

function chargerColor(index) {
  return `hsl(${(160 + index * 47) % 360} 72% 67%)`;
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(svgNamespace, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  return element;
}

function renderChart(samples, sampleCount) {
  if (!samples.length) {
    const empty = svgElement('text', {x: 400, y: 130, 'text-anchor': 'middle'});
    empty.textContent = 'No observed samples';
    chart.replaceChildren(empty);
    return;
  }
  const grouped = samples.reduce((groups, sample) => ({
    ...groups,
    [sample.charger_id]: [...(groups[sample.charger_id] || []), sample],
  }), {});
  const maxPower = Math.max(1, ...samples.map((sample) => Math.max(0, sample.power_kw)));
  const nodes = [40, 90, 140, 190, 240].map((y) => svgElement('line', {
    class: 'chart-grid', x1: 35, y1: y, x2: 780, y2: y,
  }));
  const legendItems = [];
  Object.entries(grouped).forEach(([charger, points], index) => {
    const coordinates = points.map((sample) => {
      const x = 35 + (sample.sequence / Math.max(1, sampleCount - 1)) * 745;
      const y = 235 - (Math.max(0, sample.power_kw) / maxPower) * 190;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    const line = svgElement('polyline', {
      points: coordinates,
      fill: 'none',
      stroke: chargerColor(index),
      'stroke-width': 2.5,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
    });
    const title = svgElement('title');
    title.textContent = charger;
    line.appendChild(title);
    nodes.push(line);

    const legend = document.createElement('span');
    legend.style.setProperty('--series-color', chargerColor(index));
    legend.textContent = charger;
    legendItems.push(legend);
  });
  const peak = svgElement('text', {x: 42, y: 28});
  peak.textContent = `${maxPower.toFixed(0)} kW peak`;
  nodes.push(peak);
  chart.replaceChildren(...nodes);
  document.querySelector('#legend').replaceChildren(...legendItems);
}

function textPills(selector, values) {
  const pills = values.map((value) => {
    const pill = document.createElement('span');
    pill.textContent = value;
    return pill;
  });
  document.querySelector(selector).replaceChildren(...pills);
}

function renderResult(data) {
  const metrics = data.metrics;
  document.querySelector('#result-name').textContent = data.config.name;
  document.querySelector('#run-state').textContent = 'recovered';
  document.querySelector('#metric-detection').textContent = `${(metrics.detection_rate * 100).toFixed(0)}%`;
  document.querySelector('#metric-recovery').textContent = `${(metrics.recovery_rate * 100).toFixed(0)}%`;
  document.querySelector('#metric-reconnects').textContent = metrics.reconnect_count;
  document.querySelector('#metric-unsafe').textContent = metrics.unsafe_actions;
  document.querySelector('#event-summary').textContent = `${data.meta.total_events} faults · ${data.meta.total_findings} findings`;
  textPills('#event-pills', data.events.slice(0, 12).map(
    (event) => `${event.charger_id} · #${event.sequence} · ${event.fault_type}`,
  ));
  document.querySelector('#recovery-summary').textContent = `${data.meta.total_recovery_actions} actions · ${metrics.retry_count} retries`;
  textPills('#recovery-pills', data.recovery_actions.slice(0, 12).map(
    (action) => `${action.charger_id} · ${action.action} · ${action.outcome}`,
  ));
  renderChart(data.samples, data.config.samples_per_charger);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  const status = document.querySelector('#form-status');
  button.disabled = true;
  document.querySelector('#run-label').textContent = 'Injecting faults…';
  document.querySelector('#run-state').textContent = 'running';
  status.textContent = 'Running virtual charger telemetry, controller recovery, and diagnostics.';
  const payload = {
    name: document.querySelector('#name').value,
    preset: document.querySelector('#preset').value,
    seed: Number(document.querySelector('#seed').value),
    charger_count: Number(document.querySelector('#chargers').value),
    samples_per_charger: Number(document.querySelector('#samples').value),
  };
  try {
    const response = await fetch('/api/v1/scenarios', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`Scenario rejected (${response.status})`);
    const body = await response.json();
    renderResult(body.data);
    status.textContent = `Seed ${payload.seed} recovered safely. Repeat the run for the same result.`;
  } catch (error) {
    document.querySelector('#run-state').textContent = 'failed';
    status.textContent = error instanceof Error ? error.message : 'Scenario failed.';
  } finally {
    button.disabled = false;
    document.querySelector('#run-label').textContent = 'Run fault injection';
  }
});
