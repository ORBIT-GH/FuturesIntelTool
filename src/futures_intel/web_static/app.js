const state = { date: new Date().toLocaleDateString('sv-SE') };
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '')
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;').replaceAll('"', '&quot;');

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || payload.message || `HTTP ${response.status}`);
  return payload;
}
function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits });
}
function pct(value) {
  if (value === null || value === undefined) return '-';
  const number = Number(value);
  return `${number >= 0 ? '+' : ''}${number.toFixed(2)}%`;
}
function pill(text, status) {
  const node = $('run-status');
  node.textContent = text;
  node.className = 'pill' + (status === 'failed' ? ' error' : status === 'partial' ? ' warn' : '');
}
function toast(message) {
  const node = $('toast');
  node.textContent = message;
  node.classList.add('show');
  setTimeout(() => node.classList.remove('show'), 2600);
}
function renderMetrics(context, latestRun) {
  const products = context.products || [];
  const missing = products.filter((item) => item.missing).length;
  $('status').innerHTML = `
    <div class="metric"><small>交易日</small><strong>${escapeHtml(context.trading_date)}</strong></div>
    <div class="metric"><small>行情数据截至</small><strong>${escapeHtml(context.effective_market_date || '-')}</strong></div>
    <div class="metric"><small>品种</small><strong>${products.length - missing}/${products.length}</strong></div>
    <div class="metric"><small>上次采集</small><strong>${escapeHtml(latestRun?.status || '-')}</strong></div>`;
}
function renderProducts(context) {
  $('products').innerHTML = (context.products || []).map((item) => {
    if (item.missing) return `<article class="product-card"><h3>${escapeHtml(item.name)}</h3><div class="detail">数据暂缺</div></article>`;
    const change = Number(item.change_pct ?? 0);
    const cls = change > 0 ? 'up' : change < 0 ? 'down' : '';
    const bar = item.bar;
    return `<article class="product-card">
      <h3>${escapeHtml(item.name)}</h3>
      <div class="contract">${escapeHtml(item.contract)} · ${escapeHtml(bar.trading_date)}</div>
      <div class="price ${cls}">${fmt(bar.close)}</div>
      <div class="detail ${cls}">${pct(item.change_pct)}</div>
      <div class="detail">成交 ${fmt(bar.volume, 0)} · 持仓 ${fmt(bar.open_interest, 0)}</div>
      <div class="detail">MA20 ${fmt(item.ma20)} · 持仓变化 ${fmt(item.oi_change, 0)}</div>
    </article>`;
  }).join('');
}
function renderHealth(rows) {
  $('health').innerHTML = rows.map((row) => `<tr>
    <td>${escapeHtml(row.source)}</td><td>${escapeHtml(row.status)}</td>
    <td>${fmt(row.item_count, 0)}</td><td>${escapeHtml(row.message || '')}</td>
    <td>${escapeHtml(row.finished_at || '')}</td></tr>`).join('') || '<tr><td colspan="5">暂无记录</td></tr>';
}
function renderAnomalies(context) {
  const items = context.anomalies || [];
  $('anomaly-count').textContent = `${items.length} 项`;
  $('anomalies').innerHTML = items.map((item) => `<li class="${escapeHtml(item.severity)}"><b>${escapeHtml(item.severity)}</b> ${escapeHtml(item.message)}</li>`).join('') || '<li>未发现异常</li>';
}
async function load() {
  const date = $('date').value || state.date;
  state.date = date;
  try {
    const summary = await api(`/api/summary?date=${encodeURIComponent(date)}`);
    const runId = summary.latest_run?.id;
    const health = runId ? await api(`/api/health?run_id=${runId}`) : [];
    const context = summary.context;
    renderMetrics(context, summary.latest_run);
    renderProducts(context);
    renderAnomalies(context);
    renderHealth(health);
    pill(context.status, context.status);
    const report = await api(`/api/report?date=${encodeURIComponent(date)}`);
    $('brief').textContent = report.available ? report.brief : '还没有生成该日期的日报。';
    $('report-path').textContent = report.report_dir || '';
  } catch (error) {
    toast(error.message);
  }
}
async function runNow() {
  const button = $('run');
  button.disabled = true;
  button.textContent = '运行中...';
  try {
    const result = await api('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: $('date').value || state.date })
    });
    toast(`采集 ${result.collect.status}，日报 ${result.report.status}`);
    await load();
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = '采集并生成日报';
  }
}
$('date').value = state.date;
$('date').addEventListener('change', load);
$('refresh').addEventListener('click', load);
$('run').addEventListener('click', runNow);
load();
