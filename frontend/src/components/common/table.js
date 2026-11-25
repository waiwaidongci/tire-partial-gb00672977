import {display,esc} from '../../utils/html.js';

function cell(value) {
  if (value && typeof value === 'object' && typeof value.link === 'string') return `<a href="${esc(value.link)}">${esc(value.text)}</a>`;
  if (Array.isArray(value) || (value !== null && typeof value === 'object')) return esc(JSON.stringify(value));
  return esc(display(value) ?? '—');
}

export function table(rows, columns = Object.keys(rows[0] || {}).map(key => ({key, label:key}))) {
  if (!rows.length) return '<p class="empty">这里还没有记录。请先完成上一步。</p>';
  return `<div class="table-wrap" tabindex="0"><table><thead><tr>${columns.map(field => `<th scope="col">${esc(field.label)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${columns.map(field => `<td>${cell(row[field.key])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
