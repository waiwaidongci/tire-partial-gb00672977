import {display,esc} from '../../utils/html.js';
import {table} from './table.js';

function chart(spec) {
  const points = (spec?.points || []).filter(point => Number.isFinite(point.value)).slice(0,12);
  if (!points.length) return '';
  const max = Math.max(...points.map(point => Math.abs(point.value)), 1e-9);
  return `<figure><figcaption>${esc(spec.label)} ${spec.unit ? `· ${esc(spec.unit)}` : ''}</figcaption>${points.map(point => {
    const proportion = Math.abs(point.value) / max * 47;
    const start = point.value < 0 ? 50 - proportion : 50;
    return `<div class="chart-row"><span>${esc(point.label)}</span><div class="chart-track"><i style="inset-inline-start:${start}%;width:${proportion}%"></i></div><strong>${esc(display(point.value))}</strong></div>`;
  }).join('')}</figure>`;
}

export function report(result) {
  const metrics = (result.metric_order || Object.keys(result.metrics)).map(key => [key,result.metrics[key]]);
  const columns = result.columns?.map(key => ({key,label:key}));
  return `<div class="reading"><h2>${esc(result.headline)}</h2><dl class="metrics">${metrics.map(([key,value]) => `<div><dt>${esc(key)}</dt><dd>${esc(display(value))}</dd></div>`).join('')}</dl>${chart(result.chart)}<h3>业务明细</h3>${table(result.rows,columns)}<h3>口径与限制</h3><ul>${result.notes.map(note => `<li>${esc(note)}</li>`).join('')}</ul></div>`;
}
