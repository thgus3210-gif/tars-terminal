'use strict';
(() => {
  let CSRF = null;
  let USER = null;
  let watch = new Set();
  let tierFilter = '';
  let current = null;

  const $ = (s, r = document) => r.querySelector(s);
  const fmtUSD = (n) => n == null ? '—' :
    n >= 1e9 ? '$' + (n / 1e9).toFixed(2) + 'B' :
    n >= 1e6 ? '$' + (n / 1e6).toFixed(1) + 'M' : '$' + Number(n).toLocaleString();
  const pct = (n) => n == null ? '' : (n >= 0 ? '+' : '') + n.toFixed(2) + '%';

  async function api(path, opts = {}) {
    const o = { credentials: 'same-origin', headers: {}, ...opts };
    if (opts.method && opts.method !== 'GET') {
      o.headers['Content-Type'] = 'application/json';
      o.headers['X-CSRF-Token'] = CSRF;
    }
    const r = await fetch(path, o);
    if (r.status === 401) { location.replace('/login?next=/beta'); throw new Error('auth'); }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'error');
    return d;
  }

  // ---- watchlist ----
  async function loadWatchlist() {
    const d = await api('/api/watchlist');
    watch = new Set(d.tickers);
    const box = $('#watchlist');
    if (!d.quotes.length) { box.innerHTML = '<p class="muted">관심종목이 없습니다.</p>'; return; }
    box.innerHTML = '';
    d.quotes.forEach(q => {
      const row = document.createElement('div');
      row.className = 'row' + (current === q.ticker ? ' active' : '');
      const cls = (q.change ?? 0) >= 0 ? 'up' : 'down';
      row.innerHTML =
        `<span class="tk">${q.ticker}</span>` +
        `<span class="px ${cls}">${q.price != null ? '$' + q.price : '—'}</span>` +
        `<span class="px ${cls}">${pct(q.change_pct)}</span>`;
      row.onclick = () => openCompany(q.ticker);
      box.appendChild(row);
    });
  }

  // ---- universe / search ----
  let searchTimer;
  async function loadCompanies(q = '') {
    const d = await api('/api/companies?q=' + encodeURIComponent(q));
    $('#universe-count').textContent = '(' + d.results.length + ')';
    const box = $('#company-list');
    box.innerHTML = '';
    d.results
      .filter(c => !tierFilter || c.tier === tierFilter)
      .forEach(c => {
        const row = document.createElement('div');
        row.className = 'row' + (current === c.ticker ? ' active' : '');
        row.innerHTML =
          `<span class="tk">${c.ticker}</span>` +
          `<span class="nm">${c.name}</span>` +
          `<span class="pill">${c.tier === 'biotech' ? 'BIO' : 'PHARMA'}</span>`;
        row.onclick = () => openCompany(c.ticker);
        box.appendChild(row);
      });
  }

  // ---- detail ----
  async function openCompany(ticker) {
    current = ticker;
    document.querySelectorAll('.row').forEach(r =>
      r.classList.toggle('active', r.querySelector('.tk')?.textContent === ticker));
    const host = $('#detail');
    host.classList.remove('empty');
    host.innerHTML = '<p class="muted">불러오는 중…</p>';
    let d;
    try { d = await api('/api/companies/' + ticker); }
    catch (e) { host.innerHTML = '<p class="muted">오류: ' + e.message + '</p>'; return; }

    const node = $('#tpl-detail').content.cloneNode(true);
    const p = d.profile, q = d.quote, f = d.financials;
    $('.d-name', node).textContent = p.name;
    $('.d-ticker', node).textContent = p.ticker;
    $('.d-tier', node).textContent = p.tier === 'biotech' ? 'Biotech' : 'Big Pharma';
    $('.d-exch', node).textContent = p.exchange || '';
    $('.d-price', node).textContent = q.price != null ? '$' + q.price : '—';
    const chEl = $('.d-change', node);
    chEl.textContent = (q.change != null ? (q.change >= 0 ? '+' : '') + q.change : '') + '  ' + pct(q.change_pct);
    chEl.className = 'd-change mono ' + ((q.change ?? 0) >= 0 ? 'up' : 'down');
    $('.d-stale', node).textContent = q.stale ? '⚠︎ 샘플/지연 데이터' : '실시간 · ' + (q.ts || '');

    // financials
    const fin = $('.d-fin', node);
    const rows = [
      ['시가총액', fmtUSD(q.market_cap)],
      ['매출 (TTM)', fmtUSD(f.revenue_ttm)],
      ['순이익 (TTM)', fmtUSD(f.net_income_ttm)],
      ['R&D 비용 (TTM)', fmtUSD(f.rd_expense_ttm)],
      ['현금성 자산', fmtUSD(f.cash)],
      ['총부채', fmtUSD(f.debt)],
      ['매출총이익률', f.gross_margin != null ? (f.gross_margin * 100).toFixed(1) + '%' : '—'],
    ];
    fin.innerHTML = rows.map(([k, v]) => `<tr><td class="muted">${k}</td><td>${v}</td></tr>`).join('');

    $('.d-desc', node).textContent = p.description || '—';
    if (p.website) $('.d-web', node).innerHTML = `<a href="${p.website}" target="_blank" rel="noopener">${p.website}</a>`;

    // pipeline
    const pipe = $('.d-pipe', node);
    if (!d.pipeline.length) pipe.innerHTML = '<tr><td colspan="6" class="muted">파이프라인 데이터 없음</td></tr>';
    else pipe.innerHTML = d.pipeline.map(x => {
      const cls = /3|Filed|Approved/i.test(x.phase) ? ' ' + x.phase.toLowerCase().replace(/[^a-z0-9]/g, '') : '';
      return `<tr><td class="mono">${x.asset}</td><td>${x.indication}</td>` +
        `<td><span class="phase${cls}">${x.phase}</span></td><td>${x.modality}</td>` +
        `<td>${x.status}</td><td class="muted">${x.updated || ''}</td></tr>`;
    }).join('');

    // news
    const news = $('.d-news', node);
    news.innerHTML = (d.news || []).map(n =>
      `<li><a href="${n.url}" target="_blank" rel="noopener">${n.title}</a>` +
      `<div class="src">${n.source || ''} · ${(n.published || '').slice(0, 10)}</div></li>`).join('')
      || '<li class="muted">뉴스 없음</li>';

    // watch button
    const wbtn = $('.d-watch', node);
    const paint = () => { const on = watch.has(ticker); wbtn.textContent = on ? '★ 관심종목' : '☆ 관심종목 추가'; wbtn.classList.toggle('on', on); };
    paint();
    wbtn.onclick = async () => {
      try {
        if (watch.has(ticker)) { await api('/api/watchlist/' + ticker, { method: 'DELETE' }); watch.delete(ticker); }
        else { await api('/api/watchlist', { method: 'POST', body: JSON.stringify({ ticker }) }); watch.add(ticker); }
        paint(); loadWatchlist();
      } catch (e) { alert(e.message); }
    };

    // note autosave
    const ta = $('.d-note', node);
    const saved = $('.d-note-saved', node);
    ta.value = d.note?.body || '';
    if (d.note?.updated_at) saved.textContent = '· 저장됨 ' + d.note.updated_at.slice(0, 16).replace('T', ' ');
    let t;
    ta.oninput = () => {
      clearTimeout(t); saved.textContent = '· 입력 중…';
      t = setTimeout(async () => {
        try { const r = await api('/api/notes/' + ticker, { method: 'PUT', body: JSON.stringify({ body: ta.value }) });
          saved.textContent = '· 저장됨 ' + (r.note?.updated_at || '').slice(0, 16).replace('T', ' '); }
        catch (e) { saved.textContent = '· 저장 실패'; }
      }, 700);
    };

    host.innerHTML = '';
    host.appendChild(node);
  }

  // ---- boot ----
  async function boot() {
    const s = await fetch('/api/personal/session', { cache: 'no-store' }).then(r => r.json());
    if (!s.authenticated) { location.replace('/login?next=/beta'); return; }
    CSRF = s.csrf; USER = s.username;
    $('#who').textContent = '@' + USER;

    $('#logout').onclick = async () => {
      await fetch('/api/personal/logout', { method: 'POST', credentials: 'same-origin',
        headers: { 'X-CSRF-Token': CSRF } });
      location.replace('/login');
    };
    $('#search').oninput = (e) => { clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadCompanies(e.target.value), 200); };
    document.querySelectorAll('.tier-filter button').forEach(b => b.onclick = () => {
      tierFilter = b.dataset.tier;
      document.querySelectorAll('.tier-filter button').forEach(x =>
        x.setAttribute('aria-pressed', String(x === b)));
      loadCompanies($('#search').value);
    });

    await Promise.all([loadWatchlist(), loadCompanies()]);
  }

  boot().catch(e => { console.error(e); });
})();
