import {api, download} from '../api/client.js';
import {empty, errorSlot} from '../components/common/layout.js';
import {table} from '../components/common/table.js';
import {actions} from '../constants/enums.js';
import {bindForm} from '../hooks/forms.js';
import {state} from '../stores/session.js';
import {esc,time} from '../utils/html.js';

export async function overview() {
  const profile = state.profile;
  const history = await api('/audit');
  return `<section class="summary"><h2>${esc(profile.organization)}</h2><p>${esc(profile.context)}</p><ol>${profile.scenario.map(step => `<li>${esc(step)}</li>`).join('')}</ol><a class="button" href="#1">核对数据</a></section><section><h2>最近操作</h2>${table(history.map(row => ({时间:time(row.at),账号:row.actor,操作:actions[row.action] ?? row.action,记录:row.subject})))}</section>`;
}

export async function source() {
  const profile = state.profile;
  const revisions = await api('/datasets');
  const active = revisions.find(row => row.id === state.datasetId) || revisions[0];
  const detail = active ? await api(`/datasets/${active.id}`) : null;
  const importer = state.account.role === 'analyst' ? `<form id="upload" class="inline-form"><label>导入数据文件<input name="file" type="file" accept=".csv,text/csv" required></label><button type="submit">保存数据版本</button>${errorSlot}</form>` : '';
  return `<section><p>${esc(profile.input)}</p><p class="hint">CSV 表头顺序可调整，列名需匹配样例。</p>${importer}<button type="button" id="example" class="secondary">下载样例 CSV</button><p id="download-error" role="alert" class="error"></p></section>${detail ? `<section><label>数据版本<select id="revision">${revisions.map(row => `<option value="${row.id}" ${row.id === active.id ? 'selected' : ''}>${esc(row.name)} · #${row.id}</option>`).join('')}</select></label><p class="hint">${detail.count} 行 · 页面预览前 ${detail.records.length} 行 · SHA-256 ${esc(detail.checksum.slice(0,12))}</p>${table(detail.records,profile.columns)}</section>` : empty('请导入项目样例或业务 CSV。')}`;
}

export function bindSource(root, refresh) {
  bindForm(root, '#upload', async form => {
    const file = form.elements.file.files[0];
    const imported = await api('/datasets', {name:file.name,csv:await file.text()});
    state.datasetId = imported.id;
    state.status = imported.created ? `已保存 ${imported.rows} 行。` : '数据与已有版本一致，已选中该版本。';
  }, refresh);
  root.querySelector('#revision')?.addEventListener('change', event => {
    state.datasetId = Number(event.target.value);
    refresh();
  });
  root.querySelector('#example')?.addEventListener('click', async () => {
    try {await download('/example.csv', state.profile.filename);}
    catch (error) {root.querySelector('#download-error').textContent = error.message;}
  });
}
