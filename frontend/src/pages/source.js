import {api, download} from '../api/client.js';
import {empty, errorSlot} from '../components/common/layout.js';
import {table} from '../components/common/table.js';
import {actions} from '../constants/enums.js';
import {bindForm} from '../hooks/forms.js';
import {state} from '../stores/session.js';
import {esc,formData,time} from '../utils/html.js';

const SOURCE_KEYS = ['history', 'pressure', 'brake_load'];
const SOURCE_COPY = {
  history: {title: '轮胎履历', hint: '线路、窗口里程、胎龄、胎纹磨耗；也可传期初/期末胎纹深度。', file: 'tire-history-2026-10.csv'},
  pressure: {title: '胎压巡检', hint: '同一窗口、同一轮胎的冷态胎压/低胎压检测占比。', file: 'pressure-inspection-2026-10.csv'},
  brake_load: {title: '制动载荷', hint: '车载急制动频次与线路平均载荷率。', file: 'brake-load-2026-10.csv'},
};

export async function overview() {
  const profile = state.profile;
  const history = await api('/audit');
  return `<section class="summary"><h2>${esc(profile.organization)}</h2><p>${esc(profile.context)}</p><ol>${profile.scenario.map(step => `<li>${esc(step)}</li>`).join('')}</ol><a class="button" href="#1">核对三源台账</a></section><section><h2>最近操作</h2>${table(history.map(row => ({时间:time(row.at),账号:row.actor,操作:actions[row.action] ?? row.action,记录:row.subject})))}</section>`;
}

function metricCards(stats) {
  if (!stats) return '';
  const items = [
    ['同窗轮胎', stats.total_tires ?? '—'],
    ['有效样本', stats.sample_count ?? '—'],
    ['隔离轮胎', stats.quarantine_count ?? '—'],
    ['缺来源', stats.missing_source_tires ?? '—'],
    ['同版冲突', stats.conflict_tires ?? '—'],
  ];
  return `<dl class="metrics intake-metrics">${items.map(([label,value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`;
}

function quarantineList(entries) {
  if (!entries?.length) return '<p class="notice">本批没有隔离轮胎，三源字段已齐备且同版数值一致。</p>';
  return `<div class="quarantine-list" aria-label="隔离名单">${entries.map(item => `
    <article class="quarantine-card" data-tire-id="${esc(item.tire_id)}" data-testid="quarantine-tire">
      <header><strong data-testid="quarantine-tire-id">${esc(item.tire_id)}</strong><span class="badge danger">隔离</span><span class="hint">${esc(item.window_end)}</span></header>
      <p class="quarantine-reason" data-testid="quarantine-reason">${esc(item.reason || (item.reasons || []).join('；'))}</p>
      <div class="quarantine-tags">${(item.reasons || []).map(reason => `<span class="tag ${reason.includes('冲突') ? 'conflict' : reason.includes('缺来源') ? 'missing' : 'invalid'}">${esc(reason)}</span>`).join('')}</div>
    </article>`).join('')}</div>`;
}

function sourceCards(detail, canEdit) {
  if (!canEdit) return '<p class="hint">当前账号可查看台账和隔离原因；导入补件请使用分析员账号。</p>';
  const windowEnd = detail?.window_end || state.intakeWindow || '2026-10-31';
  const expectedTotal = detail?.declaration?.expected_total ?? '';
  return `<div class="source-grid">${SOURCE_KEYS.map(key => {
    const copy = SOURCE_COPY[key];
    const progress = detail?.sources?.find(item => item.key === key);
    return `<form id="upload-${key}" class="source-card" data-source="${key}" data-testid="source-upload-${key}">
      <div class="source-card-head"><h3>${esc(copy.title)}</h3>${progress ? `<span class="badge ${progress.complete ? 'ok' : 'pending'}">${esc(progress.received ?? 0)}/${esc(progress.expected ?? '未申报')}</span>` : ''}</div>
      <p class="hint">${esc(copy.hint)}</p>
      <label for="file-${key}">选择${esc(copy.title)} CSV<input id="file-${key}" data-testid="source-file-${key}" name="file" type="file" accept=".csv,text/csv" aria-label="${esc(copy.title)} CSV 文件" required></label>
      <label>来源版本（可选，如 2 或 2026-10-31-v2）<input name="version" maxlength="80" placeholder="留空则同版不同值按冲突隔离"></label>
      <input type="hidden" name="window_end" value="${esc(windowEnd)}">
      <input type="hidden" name="batch_uid" value="run-${key}-${Date.now()}-${Math.random().toString(16).slice(2,10)}">
      <input type="hidden" name="expected_total" value="${expectedTotal === null || expectedTotal === undefined ? '' : esc(expectedTotal)}">
      <button type="submit">上传${esc(copy.title)}补件</button>
      <button type="button" class="secondary example-source" data-source="${key}">下载${esc(copy.title)}样例</button>
      <p class="hint">中断后直接再次提交同一表单即续跑；相同批次号或 SHA-256 内容不会新增版本。</p>
      ${errorSlot}
    </form>`;
  }).join('')}</div>`;
}

function activePanel(detail, profile) {
  const active = detail?.active_snapshot;
  if (!active) {
    const candidate = detail?.candidate;
    return `<section><h2>全窗样本与隔离名单</h2>${empty('尚未按申报条数收齐，当前不切换全窗样本和隔离名单；下列预拼原因仅用于补件，不会成为当前正式名单。')}
      ${candidate ? `<div class="candidate-preview"><h3>预拼检查（尚未切换）：样本 ${candidate.stats.sample_count}，隔离 ${candidate.stats.quarantine_count}</h3>${metricCards(candidate.stats)}<h4>预拼隔离原因</h4>${quarantineList(candidate.quarantine)}</div>` : ''}
    </section>`;
  }
  return `<section data-testid="active-window-snapshot"><h2>当前整批：全窗样本与隔离名单</h2>
    <p class="notice">快照 #${active.id} · 数据版本 #${active.dataset_id} · 切换时间 ${time(active.switched_at)}。分析绑定数据版本，因此并发分析只会取切换前或切换后的整批。</p>
    ${metricCards(active.stats)}
    <h3>隔离名单（${active.quarantine?.length || 0}）</h3>
    ${quarantineList(active.quarantine)}
    <h3>有效样本预览</h3>
    ${table(active.samples || [], profile.columns)}
  </section>`;
}

export async function source() {
  const profile = state.profile;
  const canEdit = state.account.role === 'analyst';
  const [windows,revisions] = await Promise.all([api('/intake/windows'),api('/datasets')]);
  const requested = state.intakeWindow || windows[0]?.window_end || '2026-10-31';
  const detail = await api(`/intake/windows/${encodeURIComponent(requested)}`).catch(() => null);
  if (detail) state.intakeWindow = detail.window_end;
  const activeRevision = revisions.find(row => row.id === state.datasetId) || revisions[0];
  const legacyDetail = activeRevision ? await api(`/datasets/${activeRevision.id}`) : null;
  const declaration = detail?.declaration;
  const windowOptions = Array.from(new Set([...(windows || []).map(item => item.window_end), requested]))
    .filter(Boolean).sort().reverse();

  const declarationForm = canEdit ? `<form id="declaration" class="inline-form">
    <label>盘点窗口<input name="window_end" type="date" required value="${esc(detail?.window_end || requested)}"></label>
    <label>每源申报条数<input name="expected_total" type="number" min="0" max="5000" value="${esc(declaration?.expected_total ?? 60)}"></label>
    <label class="check"><input name="reopen" type="checkbox"> 作为新补件轮次重新收齐</label>
    <button type="submit">保存申报并${declaration?.status === 'switched' ? '重开' : '确认'}窗口</button>
    ${errorSlot}
  </form>` : '';

  const progressTable = detail ? table((detail.sources || []).map(item => ({
    来源: item.label,
    当前条数: item.record_count ?? item.received,
    轮胎数: item.tire_count ?? '—',
    申报条数: item.expected ?? '未申报',
    差值: item.difference ?? '—',
    状态: declaration?.status === 'switched' && item.complete ? '已随整批切换' : item.complete ? '已收齐' : '待收齐',
  }))) : empty('请先建立窗口申报。');

  const batchTable = detail?.batches?.length ? table(detail.batches.map(row => ({
    批次: `#${row.id}`,
    来源: row.source_label,
    续跑编号: row.batch_uid,
    版本: row.version_label || '未标注',
    CSV行数: row.row_count,
    新增事实: row.accepted_count,
    迟到旧条: row.stale_count,
    时间: time(row.created),
  }))) : '<p class="empty">还没有分批上传记录。</p>';

  const snapshotTable = detail?.snapshots?.length ? table(detail.snapshots.map(row => ({
    快照: `#${row.id}`,
    轮次: row.revision,
    数据版本: `#${row.dataset_id || '—'}`,
    样本: row.sample_count,
    隔离: row.quarantine_count,
    当前: row.is_active ? '是' : '否',
    切换时间: time(row.switched_at),
  }))) : '';

  const importer = canEdit ? `<form id="upload" class="inline-form"><label>兼容：导入已拼好的整表 CSV<input name="file" type="file" accept=".csv,text/csv" required></label><button type="submit">保存数据版本</button>${errorSlot}</form>` : '';

  return `<section class="intake-hero">
      <h2>三源分批合窗</h2>
      <p>月底盘点时，<strong>轮胎履历、胎压巡检和制动载荷各传一份</strong>。系统按<strong>同窗同胎</strong>拼样本；<strong>缺来源</strong>或<strong>同版数值冲突</strong>的轮胎进入隔离名单并在页面标出原因。</p>
      <p class="hint">迟到的旧版本记录不得覆盖同来源新件；补件可分批到，按申报条数收齐后一次性切换全窗样本和隔离名单。上传中断后续跑不新增版本；旧分析仍绑定当时那批样本复算。</p>
      <label>选择窗口<select id="intake-window">${windowOptions.map(w => `<option value="${esc(w)}" ${w === detail?.window_end ? 'selected' : ''}>${esc(w)}</option>`).join('')}</select></label>
      ${declarationForm}
      <h3>各来源收齐进度</h3>${progressTable}
    </section>
    <section><h2>上传三份台账与分批补件</h2>${sourceCards(detail, canEdit)}</section>
    <section><h2>分批接收记录</h2>${batchTable}${snapshotTable}</section>
    ${activePanel(detail, profile)}
    <section><h2>兼容整表导入与历史版本</h2><p>${esc(profile.input)}</p><p class="hint">原有九列宽表 CSV 仍可直接导入；CSV 表头顺序可调整，列名需匹配样例。新流程会在收齐后自动生成同样结构的不可变数据版本。</p>${importer}<button type="button" id="example" class="secondary">下载整表样例 CSV</button><p id="download-error" role="alert" class="error"></p>
      ${revisions.length ? `<label>历史数据版本<select id="revision">${revisions.map(row => `<option value="${row.id}" ${row.id === activeRevision?.id ? 'selected' : ''}>${esc(row.name)} · #${row.id}</option>`).join('')}</select></label><p class="hint">${legacyDetail?.count ?? 0} 行 · 预览前 ${legacyDetail?.records.length ?? 0} 行 · SHA-256 ${esc(activeRevision?.checksum.slice(0,12) || '')}</p>${legacyDetail ? table(legacyDetail.records,profile.columns) : ''}` : empty('请导入项目样例或业务 CSV。')}
    </section>`;
}

async function resumableUpload(payload, csv) {
  const chunkSize = 24000;
  const chunks = [];
  for (let start = 0; start < csv.length; start += chunkSize) chunks.push(csv.slice(start, start + chunkSize));
  const {csv: _csv, ...metadata} = payload;
  const session = await api('/intake/resumable', {...metadata, chunk_total: chunks.length});
  const received = new Set(session.received_chunks || []);
  for (let index = 0; index < chunks.length; index += 1) {
    if (received.has(index)) continue;
    await api(`/intake/resumable/${encodeURIComponent(session.upload_id)}/chunks/${index}`, {chunk: chunks[index]}, 'PUT');
  }
  return api(`/intake/resumable/${encodeURIComponent(session.upload_id)}/complete`, {});
}

export function bindSource(root, refresh) {
  bindForm(root, '#declaration', async form => {
    const values = formData(form);
    const payload = {
      window_end: values.window_end,
      expected_total: values.expected_total === '' ? null : Number(values.expected_total),
      reopen: Boolean(values.reopen),
    };
    const saved = await api('/intake/declarations', payload);
    state.intakeWindow = saved.window_end;
    state.status = `窗口 ${saved.window_end} 的申报条数已保存。`;
  }, refresh);

  root.querySelector('#intake-window')?.addEventListener('change', event => {
    state.intakeWindow = event.target.value;
    refresh();
  });

  for (const source of SOURCE_KEYS) {
    bindForm(root, `#upload-${source}`, async form => {
      const file = form.elements.file.files[0];
      const payload = {
        source,
        window_end: form.elements.window_end.value,
        batch_uid: form.elements.batch_uid.value,
        filename: file.name,
      };
      const csv = await file.text();
      if (form.elements.version.value.trim()) payload.version = form.elements.version.value.trim();
      if (form.elements.expected_total.value !== '') {
        payload.expected_total = Number(form.elements.expected_total.value);
      } else {
        // No upfront total: each file/batch declares its own row count and the
        // server sums batch declarations, so missing-source rows still join.
        payload.declare_received_rows = true;
      }
      const result = await resumableUpload(payload, csv);
      state.intakeWindow = result.window?.window_end || payload.window_end;
      if (result.snapshot?.dataset_id) state.datasetId = result.snapshot.dataset_id;
      state.status = result.duplicate
        ? '检测到同一续跑批次或相同内容，未新增版本。'
        : result.switched
          ? `申报条数已收齐，已一次性切换：有效样本 ${result.snapshot.sample_count} 条，隔离 ${result.snapshot.quarantine_count} 条。`
          : `本批已接收，当前 ${JSON.stringify(result.window?.received_counts || {})}；收齐后才会切换。`;
    }, refresh);

    root.querySelectorAll(`.example-source[data-source="${source}"]`).forEach(button => {
      button.addEventListener('click', async () => {
        try { await download(`/intake/examples/${source}.csv`, SOURCE_COPY[source].file); }
        catch (error) { root.querySelector('#download-error').textContent = error.message; }
      });
    });
  }

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
