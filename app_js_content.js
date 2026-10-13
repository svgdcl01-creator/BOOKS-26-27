// ==================== STATE ====================
let selectedRow = null;
let currentBook = null;
let currentLibs = [];
let searchTimeout = null;
let currentYear = null;   // 🔄 ஆண்டு — assign/send/search/reports/renumber/reclaim எல்லாமே இதையே பயன்படுத்தும்.
                          // Admin மட்டும் மாற்ற முடியும் (selector Admin-க்கு மட்டுமே); dclstaff Admin வைத்த ஆண்டையே தானாக பின்பற்றும்.
let workWageCenters = [];   // 🏷️ பிரிக்க/அனுப்ப-ல் உண்மையில் பயன்படுத்தப்படும் filter — [] = அனைத்தும்.
                             // admin-க்கு எப்போதும் [] (admin எப்போதும் அனைத்தும் பார்ப்பார்); dclstaff-க்கு Admin configure செய்ததே இதில் வரும்.
let adminConfigWageCenters = [];   // Admin-ன் selector panel-ல் தற்போது தேர்ந்தெடுக்கப்பட்டிருப்பவை (dclstaff-க்கான configuration — Admin-ன் சொந்த பார்வையை பாதிக்காது).
const WAGE_CENTER_MAX = 3;

// query string-க்குள் அனுப்ப — pipe/பிரிக்கப்பட்ட wage_center பட்டியல் (actual filter)
function wageCenterQueryParam() {
  return workWageCenters.join(',');
}
// UI-ல் காட்ட — Admin தேர்ந்தெடுத்திருப்பவை
function wageCenterDisplayLabel() {
  return adminConfigWageCenters.join(', ');
}

// Google Books API key — "ISBN → தலைப்பு தேடு" (Books API-க்கு மட்டும் restrict செய்யப்பட்டது) — 429 rate-limit தவிர்க்க
const GOOGLE_BOOKS_API_KEY = 'AIzaSyBKAAXZJCC7JB8WBUszv9s2o8-fhC4qj90';

// ==================== YEAR SELECTOR ====================
// Admin-க்கு மட்டுமே selector காட்டப்படும் (dclstaff-க்கு இல்லை). Admin மாற்றும் ஆண்டையே
// dclstaff தானாக (server-side setting வழியாக) பின்பற்றுவார்.
async function initYearSelector() {
  if (window.CURRENT_ROLE === 'admin') {
    try {
      const data = await fetch('/api/years/available').then(r => r.json());
      const years = data.years || ['2024-2025'];
      let active = data.default || years[0];
      try {
        const sv = await fetch('/api/years/staff_view').then(r => r.json());
        if (sv && sv.active_year && years.includes(sv.active_year)) active = sv.active_year;
      } catch (e) { /* setting இல்லாவிட்டாலும் தொடரலாம் */ }
      currentYear = active;
      const sel = document.getElementById('yearSelect');
      if (sel) {
        sel.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join('');
        sel.value = currentYear;
      }
    } catch (e) { currentYear = currentYear || '2024-2025'; }
  } else {
    try {
      const sv = await fetch('/api/years/staff_view').then(r => r.json());
      currentYear = (sv && sv.active_year) || '2024-2025';
    } catch (e) { currentYear = currentYear || '2024-2025'; }
  }
}

function onYearChange(val) {
  currentYear = val;
  toast('📅 ஆண்டு: ' + currentYear + ' — dcl staff-க்கும் இதே ஆண்டு அமையும்', 'success');
  updateLiveTicker();
  loadMultiPriceBanner();
  loadMultiIsbnBanner();
  window._fuzzyDone = false;
  initWageCenterSelector();   // ஆண்டு மாறினால், அந்த ஆண்டுக்குண்டான ஊதிய மையங்களே காட்டப்பட வேண்டும்
  if (document.getElementById('page-send').classList.contains('active')) loadSendSets();
  if (document.getElementById('page-reclaim').classList.contains('active')) loadReclaimPoolStatus();
  if (document.getElementById('page-kavani') && document.getElementById('page-kavani').classList.contains('active')) loadKavaniPage();
  // Admin இந்த ஆண்டையே dclstaff-க்கும் active ஆக்கும் (server-side setting)
  if (window.CURRENT_ROLE === 'admin') {
    fetch('/api/years/staff_view', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ year: val })
    }).catch(() => {});
  }
}

// ==================== WAGE CENTER (ஊதிய மையம்) SELECTOR — Admin மட்டும் ====================
// அதிகபட்சம் 3 ஊதிய மையங்கள் வரை Admin தேர்ந்தெடுக்கலாம் (checkbox panel). இந்த selector
// Admin-க்கு மட்டுமே காட்டப்படும். Admin-ன் சொந்த பார்வையை இது பாதிக்காது — Admin எப்போதும்
// அனைத்து ஊதிய மையங்களையும் பார்ப்பார். இந்த தேர்வு dclstaff வேலை செய்யும் ஊதிய மைய(ங்க)ளாக
// server-side setting வழியாக சேமிக்கப்பட்டு, dclstaff தானாக பின்பற்றுவார்கள் (அவர்களுக்கு
// எந்த selector-ம் காட்டப்படாது).
let _wageCenterAvailable = [];

async function initWageCenterSelector() {
  if (window.CURRENT_ROLE === 'admin') {
    const btn = document.getElementById('wageCenterBtn');
    if (!btn) return;
    try {
      const [centers, activeRes] = await Promise.all([
        fetch('/api/wage_centers/available?year=' + encodeURIComponent(currentYear)).then(r => r.json()),
        fetch('/api/wage_centers/active').then(r => r.json())
      ]);
      _wageCenterAvailable = centers;
      adminConfigWageCenters = (activeRes.active_wage_centers || []).filter(c => centers.includes(c));
      renderWageCenterCheckboxes();
      updateWageCenterButtonLabel();
    } catch (e) {
      _wageCenterAvailable = [];
      adminConfigWageCenters = [];
      updateWageCenterButtonLabel();
    }
    workWageCenters = [];   // Admin எப்போதும் அனைத்து ஊதிய மையங்களையும் பார்ப்பார்
  } else {
    // dclstaff — Admin configure செய்ததையே தானாக பின்பற்றும், UI இல்லை
    try {
      const activeRes = await fetch('/api/wage_centers/active').then(r => r.json());
      workWageCenters = activeRes.active_wage_centers || [];
    } catch (e) { workWageCenters = []; }
  }
}

function renderWageCenterCheckboxes() {
  const list = document.getElementById('wageCenterCheckboxList');
  if (!list) return;
  list.innerHTML = _wageCenterAvailable.map((c, idx) => `
    <div class="checkbox-item${adminConfigWageCenters.includes(c) ? ' checked' : ''}" style="padding:8px 10px;margin-bottom:6px;color:#1e293b;" onclick="toggleWageCenterCheckbox('${escAttr(c)}')">
      <input type="checkbox" id="wc_cb_${idx}" value="${escAttr(c)}" ${adminConfigWageCenters.includes(c) ? 'checked' : ''} onclick="event.stopPropagation(); toggleWageCenterCheckbox('${escAttr(c)}')">
      <label style="color:#1e293b;">${escHtml(c)}</label>
    </div>`).join('') || '<div style="padding:8px;color:var(--muted);font-size:0.85rem;">ஊதிய மையங்கள் இல்லை</div>';
}

function toggleWageCenterCheckbox(val) {
  const idx = adminConfigWageCenters.indexOf(val);
  if (idx >= 0) {
    adminConfigWageCenters.splice(idx, 1);
  } else {
    if (adminConfigWageCenters.length >= WAGE_CENTER_MAX) {
      toast(`⚠️ அதிகபட்சம் ${WAGE_CENTER_MAX} ஊதிய மையங்கள் மட்டுமே தேர்வு செய்ய முடியும்`, 'error');
      return;
    }
    adminConfigWageCenters.push(val);
  }
  renderWageCenterCheckboxes();
  updateWageCenterButtonLabel();
  saveWageCenterConfig();
}

function clearWageCenterSelection() {
  adminConfigWageCenters = [];
  renderWageCenterCheckboxes();
  updateWageCenterButtonLabel();
  saveWageCenterConfig();
}

async function saveWageCenterConfig() {
  try {
    await fetch('/api/wage_centers/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wage_centers: adminConfigWageCenters })
    });
    toast(adminConfigWageCenters.length
      ? ('🏷️ dcl staff இப்போது இவற்றில் மட்டும் வேலை செய்வார்: ' + wageCenterDisplayLabel())
      : '🏷️ dcl staff அனைத்து ஊதிய மையங்களிலும் வேலை செய்வார்', 'success');
  } catch (e) {
    toast('❌ சேமிப்பில் பிழை', 'error');
  }
}

function updateWageCenterButtonLabel() {
  const btn = document.getElementById('wageCenterBtn');
  if (!btn) return;
  btn.textContent = adminConfigWageCenters.length
    ? `${adminConfigWageCenters.length}/${WAGE_CENTER_MAX} தேர்வு: ${wageCenterDisplayLabel()}`
    : '— அனைத்தும் —';
}

function toggleWageCenterPanel() {
  const panel = document.getElementById('wageCenterPanel');
  if (!panel) return;
  panel.style.display = panel.style.display === 'none' || !panel.style.display ? 'block' : 'none';
}

function closeWageCenterPanel() {
  const panel = document.getElementById('wageCenterPanel');
  if (panel) panel.style.display = 'none';
}

// panel-க்கு வெளியே click செய்தால் மூடிவிடும்
document.addEventListener('click', (e) => {
  const wrap = document.getElementById('wageCenterWrap');
  if (wrap && !wrap.contains(e.target)) closeWageCenterPanel();
});

// ==================== PAGE SWITCH ====================
function showPage(id, btn) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  if (btn) btn.classList.add('active');
  if (id === 'page-send') loadSendSets();
  if (id === 'page-reports') { loadR5Libs(); }
  if (id === 'page-distribute') { loadMultiPriceBanner(); loadMultiIsbnBanner(); }
  if (id === 'page-kavani') loadKavaniPage();
  if (id === 'page-reclaim') { loadReclaimPoolStatus(); document.getElementById('reclaimRowsSection').style.display = 'none'; }
}

// ==================== TOAST ====================
function toast(msg, type='') {
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ==================== LOADING ====================
function showLoading(msg='⏳ பதிவு செய்கிறது...') {
  document.getElementById('loadingMsg').textContent = msg;
  document.getElementById('loadingOverlay').style.display = 'flex';
}
function hideLoading() { document.getElementById('loadingOverlay').style.display = 'none'; }

// ==================== MODAL ====================
function closeModal(id) { document.getElementById(id).style.display = 'none'; }

// ==================== LIVE TICKER ====================
async function updateLiveTicker() {
  try {
    const data = await fetch('/api/ticker_data?year=' + encodeURIComponent(currentYear)).then(r => r.json());
    if (!data || data.status !== 'success') return;
    const unassigned = data.received - data.assigned;
    const el = document.getElementById('tickerContent');
    if (!el) return;
    el.innerHTML =
      '📚 பெறப்பட்ட நூல்கள் : <span class="ticker-highlight">' + data.received.toLocaleString('ta-IN') + '</span>' +
      '<span class="ticker-dot">◆</span>' +
      '✅ பிரிக்கப்பட்டது : <span class="ticker-highlight">' + data.assigned.toLocaleString('ta-IN') + '</span>' +
      '<span class="ticker-dot">◆</span>' +
      '⏳ மீதம் பிரிக்க வேண்டியது : <span class="ticker-pending">' + unassigned.toLocaleString('ta-IN') + '</span>' +
      '<span class="ticker-dot">◆</span>' +
      '📤 அனுப்பப்பட்டது : <span class="ticker-sent">' + data.sent.toLocaleString('ta-IN') + '</span>' +
      '<span class="ticker-dot">◆</span>' +
      '🗓️ இன்று (' + data.today + ') பிரிக்கப்பட்டது : <span class="ticker-today">' + data.todayAssigned + '</span>' +
      '<span class="ticker-dot">◆</span>';
  } catch(e) {}
}

// ==================== MULTI-PRICE DASHBOARD BANNER ====================
async function loadMultiPriceBanner() {
  try {
    const items = await fetch('/api/multi_price_titles?year=' + encodeURIComponent(currentYear)).then(r => r.json());
    const banner = document.getElementById('multiPriceBanner');
    const list = document.getElementById('multiPriceList');
    if (!items || !items.length) { banner.style.display = 'none'; return; }
    banner.style.display = 'block';
    list.innerHTML = items.map(item =>
      `<div class="alert-card" onclick="searchTitle('${escAttr(item.title)}')">
        <div class="alert-card-title">📖 ${escHtml(item.title)}</div>
        <div class="alert-card-prices">💰 ${item.prices.map(p => '₹' + p).join(' | ')}</div>
      </div>`
    ).join('');
  } catch(e) {}
}

function searchTitle(title) {
  document.getElementById('searchInput').value = title;
  doSearch();
}

// ==================== MULTI-ISBN DASHBOARD BANNER ====================
async function loadMultiIsbnBanner() {
  try {
    const items = await fetch('/api/multi_isbn_titles?year=' + encodeURIComponent(currentYear)).then(r => r.json());
    const banner = document.getElementById('multiIsbnBanner');
    const list = document.getElementById('multiIsbnList');
    if (!banner || !list) return;
    if (!items || !items.length) { banner.style.display = 'none'; return; }
    banner.style.display = 'block';
    list.innerHTML = items.map(item =>
      `<div class="alert-card" onclick="searchTitle('${escAttr(item.title)}')">
        <div class="alert-card-title">📖 ${escHtml(item.title)}</div>
        <div class="alert-card-prices">🏷️ ISBN: ${item.isbns.map(i => escHtml(String(i))).join(' | ')}</div>
      </div>`
    ).join('');
  } catch(e) {}
}

// ==================== கவனிக்க TAB ====================
async function resetFuzzyCache() {
  const btn = document.getElementById('fuzzyResetBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner" style="width:12px;height:12px;border-width:2px;margin-right:4px;"></span>தொடங்குகிறது...';
  window._fuzzyDone = false;
  document.getElementById('kavaniPageList').innerHTML = '';
  document.getElementById('kavaniPageStatus').textContent = '';
  try {
    await fetch('/api/fuzzy_reset', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ year: currentYear })
    });
  } catch(e) {}
  btn.disabled = false;
  btn.innerHTML = '🔄 மீண்டும் கணக்கிடு';
  document.getElementById('fuzzyProgressWrap').style.display = 'block';
  document.getElementById('fuzzyProgressBar').style.width = '0%';
  document.getElementById('fuzzyProgressPct').textContent = '0%';
  pollFuzzy();
}

async function loadKavaniMultiPrice() {
  var list = document.getElementById('kavaniMultiPriceList');
  var status = document.getElementById('kavaniMultiPriceStatus');
  if (!list) return;
  list.innerHTML = '<div style="color:#92400e;padding:8px">ஏற்றுகிறது...</div>';
  status.textContent = '';
  fetch('/api/multi_price_titles?year=' + encodeURIComponent(currentYear))
    .then(function(r){ return r.json(); })
    .then(function(items) {
      if (!items || !items.length) {
        list.innerHTML = '<div style="color:#2e7d32;font-weight:600;padding:12px">இல்லை</div>';
        return;
      }
      status.textContent = 'மொத்தம் ' + items.length + ' தலைப்புகளில் வேறு விலைகள் உள்ளன';
      var html = '';
      for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var ph = '';
        for (var j = 0; j < item.prices.length; j++) {
          if (j > 0) ph += ' vs ';
          ph += '<span style="background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:10px;font-weight:700">Rs.' + escHtml(String(item.prices[j])) + '</span>';
        }
        var t = escAttr(item.title);
        html += '<div data-title="' + t + '" onclick="searchByTitle(this)" style="background:white;border-left:4px solid #e53935;border:1px solid #fca5a5;border-radius:8px;padding:10px 14px;margin-bottom:8px;cursor:pointer">';
        html += '<div style="font-weight:600;color:#1f2937;margin-bottom:6px">' + escHtml(item.title) + '</div>';
        html += '<div>' + ph + '</div>';
        html += '</div>';
      }
      list.innerHTML = html;
    })
    .catch(function(err) {
      list.innerHTML = '<div style="color:red">பிழை: ' + err + '</div>';
    });
}

function searchByTitle(el) {
  var title = el.getAttribute('data-title');
  if (title) searchTitle(title);
}

async function loadKavaniMultiIsbn() {
  var list = document.getElementById('kavaniMultiIsbnList');
  var status = document.getElementById('kavaniMultiIsbnStatus');
  if (!list) return;
  list.innerHTML = '<div style="color:#5b21b6;padding:8px">ஏற்றுகிறது...</div>';
  status.textContent = '';
  fetch('/api/multi_isbn_titles?year=' + encodeURIComponent(currentYear))
    .then(function(r){ return r.json(); })
    .then(function(items) {
      if (!items || !items.length) {
        list.innerHTML = '<div style="color:#2e7d32;font-weight:600;padding:12px">இல்லை</div>';
        return;
      }
      status.textContent = 'மொத்தம் ' + items.length + ' தலைப்புகளில் வேறு வேறு ISBN உள்ளன';
      var html = '';
      for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var isbnHtml = '';
        for (var j = 0; j < item.isbns.length; j++) {
          var isbn = String(item.isbns[j]);
          var isAdmin = (window.CURRENT_ROLE === 'admin');
          isbnHtml += '<span style="display:inline-flex;align-items:center;gap:6px;background:#ede9fe;color:#5b21b6;padding:2px 10px;border-radius:10px;font-weight:700;margin:2px 6px 2px 0;">' +
            'ISBN: ' + escHtml(isbn) +
            (isAdmin ? ' <button onclick="event.stopPropagation();openRenameIsbnModal(\'' + escAttr(isbn) + '\',\'' + escAttr(item.title) + '\')" style="border:none;background:#6d28d9;color:#fff;border-radius:6px;padding:2px 8px;font-size:0.75rem;cursor:pointer;">✏️ மாற்று</button>' : '') +
            '</span>';
        }
        var t = escAttr(item.title);
        html += '<div data-title="' + t + '" onclick="searchByTitle(this)" style="background:white;border:1px solid #c4b5fd;border-radius:8px;padding:10px 14px;margin-bottom:8px;cursor:pointer">';
        html += '<div style="font-weight:600;color:#1f2937;margin-bottom:6px">' + escHtml(item.title) + '</div>';
        html += '<div>' + isbnHtml + '</div>';
        html += '</div>';
      }
      list.innerHTML = html;
    })
    .catch(function(err) {
      list.innerHTML = '<div style="color:red">பிழை: ' + err + '</div>';
    });
}

// ==================== ADMIN-ONLY: RENAME TITLE / EDIT ISBN ====================
async function openRenameIsbnModal(isbn, currentTitle) {
  if (window.CURRENT_ROLE !== 'admin') { toast('இது Admin-க்கு மட்டும் அனுமதிக்கப்பட்டது', 'error'); return; }
  document.getElementById('renameIsbnOld').value = isbn;
  document.getElementById('renameIsbnCurrentTitle').value = currentTitle;
  document.getElementById('renameIsbnVendor').value = '⏳ ஏற்றுகிறது...';
  document.getElementById('renameIsbnAuthor').value = '⏳ ஏற்றுகிறது...';
  document.getElementById('renameIsbnPrice').value = '⏳ ஏற்றுகிறது...';
  document.getElementById('renameIsbnNewTitle').value = currentTitle;
  document.getElementById('renameIsbnNewIsbn').value = '';
  document.getElementById('renameIsbnMsg').textContent = '';
  document.getElementById('modalRenameIsbn').style.display = 'flex';
  try {
    const info = await fetch('/api/isbn_info?isbn=' + encodeURIComponent(isbn) + '&year=' + encodeURIComponent(currentYear)).then(r => r.json());
    document.getElementById('renameIsbnVendor').value = info.vendor_name || '—';
    document.getElementById('renameIsbnAuthor').value = info.author || '—';
    document.getElementById('renameIsbnPrice').value = info.price || '—';
  } catch(e) {
    document.getElementById('renameIsbnVendor').value = '—';
    document.getElementById('renameIsbnAuthor').value = '—';
    document.getElementById('renameIsbnPrice').value = '—';
  }
}

async function submitRenameByIsbn() {
  var msgEl = document.getElementById('renameIsbnMsg');
  var oldIsbn = document.getElementById('renameIsbnOld').value.trim();
  var newTitle = document.getElementById('renameIsbnNewTitle').value.trim();
  var newIsbn = document.getElementById('renameIsbnNewIsbn').value.trim();
  if (!newTitle && !newIsbn) {
    msgEl.style.color = '#b91c1c';
    msgEl.textContent = 'புதிய தலைப்பு அல்லது புதிய ISBN — ஏதேனும் ஒன்றை கொடுக்கவும்';
    return;
  }
  msgEl.style.color = '#6b7280';
  msgEl.textContent = 'சேமிக்கிறது...';
  try {
    const res = await fetch('/api/admin/rename_by_isbn', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        year: currentYear,
        old_isbn: oldIsbn,
        new_title: newTitle || null,
        new_isbn: newIsbn || null
      })
    }).then(r => r.json());
    if (res.success) {
      msgEl.style.color = '#166534';
      msgEl.textContent = '✅ ' + res.message;
      toast('✅ தலைப்பு/ISBN புதுப்பிக்கப்பட்டது', 'success');
      loadKavaniMultiIsbn();
      loadMultiIsbnBanner();
      setTimeout(() => closeModal('modalRenameIsbn'), 900);
    } else {
      msgEl.style.color = '#b91c1c';
      msgEl.textContent = '❌ ' + res.error;
    }
  } catch(e) {
    msgEl.style.color = '#b91c1c';
    msgEl.textContent = '❌ பிழை: ' + e;
  }
}

// ==================== DASHBOARD: பதிப்பகம் SEARCH ====================
let publisherSearchTimeout = null;
let publisherSearchSelected = null;

function openPublisherSearchModal() {
  document.getElementById('publisherSearchInput').value = '';
  document.getElementById('publisherSearchStatus').textContent = '';
  document.getElementById('publisherSearchResults').style.display = 'none';
  document.getElementById('publisherSearchResults').innerHTML = '';
  document.getElementById('publisherSearchSelected').style.display = 'none';
  document.getElementById('publisherSearchMsg').textContent = '';
  document.getElementById('publisherSearchConfirmBtn').disabled = true;
  publisherSearchSelected = null;
  document.getElementById('modalPublisherSearch').style.display = 'flex';
  setTimeout(() => document.getElementById('publisherSearchInput').focus(), 100);
}

function onPublisherSearchInput() {
  clearTimeout(publisherSearchTimeout);
  // புதிதாக தட்டச்சு செய்யும்போது முந்தைய தேர்வு தள்ளுபடி
  publisherSearchSelected = null;
  document.getElementById('publisherSearchSelected').style.display = 'none';
  document.getElementById('publisherSearchConfirmBtn').disabled = true;
  publisherSearchTimeout = setTimeout(doPublisherSearch, 300);
}

async function doPublisherSearch() {
  const q = document.getElementById('publisherSearchInput').value.trim();
  const status = document.getElementById('publisherSearchStatus');
  const resultsEl = document.getElementById('publisherSearchResults');
  if (q.length < 4) {
    status.textContent = 'குறைந்தது 4 எழுத்துகள் தட்டச்சு செய்யவும்...';
    resultsEl.style.display = 'none';
    resultsEl.innerHTML = '';
    return;
  }
  status.innerHTML = '<span class="loading"><span class="spinner"></span> தேடுகிறது...</span>';
  try {
    const res = await fetch('/api/publisher_search?q=' + encodeURIComponent(q) + '&year=' + encodeURIComponent(currentYear)).then(r => r.json());
    if (res.error) { status.textContent = res.error; resultsEl.style.display = 'none'; return; }
    if (!res.length) {
      status.textContent = 'பொருந்தும் பதிப்பகம் இல்லை';
      resultsEl.style.display = 'none';
      resultsEl.innerHTML = '';
      return;
    }
    status.textContent = `${res.length} பதிப்பகங்கள் கிடைத்தன — ஒன்றைத் தேர்வு செய்யவும்`;
    resultsEl.innerHTML = res.map(v =>
      `<div onclick="selectPublisher('${escAttr(v)}')" style="padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--border);font-size:0.88rem;" onmouseover="this.style.background='#f0fdfa'" onmouseout="this.style.background=''">${escHtml(v)}</div>`
    ).join('');
    resultsEl.style.display = 'block';
  } catch(e) {
    status.textContent = '❌ பிழை: ' + e;
    resultsEl.style.display = 'none';
  }
}

function selectPublisher(vendor) {
  publisherSearchSelected = vendor;
  document.getElementById('publisherSearchResults').style.display = 'none';
  const sel = document.getElementById('publisherSearchSelected');
  sel.style.display = 'block';
  sel.textContent = '✅ தேர்ந்தெடுக்கப்பட்டது: ' + vendor;
  document.getElementById('publisherSearchConfirmBtn').disabled = false;
  document.getElementById('publisherSearchMsg').textContent = '';
}

async function confirmPublisherReport() {
  if (!publisherSearchSelected) { toast('பதிப்பகம் தேர்வு செய்யவும்!', 'error'); return; }
  if (!confirm(`நீங்கள் தேர்வு செய்த பதிப்பகம்:\\n\\n🏢  ${publisherSearchSelected}\\n\\nஇதுதான் என்பதை உறுதிப்படுத்துகிறீர்களா?`)) return;
  const msgEl = document.getElementById('publisherSearchMsg');
  msgEl.style.color = '#6b7280';
  msgEl.textContent = '⏳ அறிக்கை உருவாக்குகிறது...';
  try {
    const res = await fetch('/api/publisher_report', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({vendor: publisherSearchSelected, year: currentYear})
    }).then(r => r.json());
    if (res.success) {
      msgEl.style.color = '#166534';
      msgEl.textContent = '✅ ' + res.message;
      if (res.url) window.open(res.url, '_blank');
      toast('✅ அறிக்கை தயார்', 'success');
    } else {
      msgEl.style.color = '#b91c1c';
      msgEl.textContent = '❌ ' + (res.error || 'பிழை');
    }
  } catch(e) {
    msgEl.style.color = '#b91c1c';
    msgEl.textContent = '❌ பிழை: ' + e;
  }
}

async function loadKavaniPage() {
  // Section 1: வேறு விலைகள் எப்போதும் fresh load
  loadKavaniMultiPrice();
  // Section 1.5: வேறு வேறு ISBN எப்போதும் fresh load
  loadKavaniMultiIsbn();
  // Section 2: Fuzzy — already done check
  if (window._fuzzyDone) { return; }
  const list = document.getElementById('kavaniPageList');
  const status = document.getElementById('kavaniPageStatus');
  list.innerHTML = '';
  status.textContent = '';
  document.getElementById('fuzzyProgressWrap').style.display = 'block';
  document.getElementById('fuzzyProgressBar').style.width = '0%';
  document.getElementById('fuzzyProgressPct').textContent = '0%';
  pollFuzzy();
}

async function pollFuzzy() {
  const list = document.getElementById('kavaniPageList');
  const status = document.getElementById('kavaniPageStatus');
  try {
    const res = await fetch('/api/fuzzy_alert_titles?year=' + encodeURIComponent(currentYear)).then(r => r.json());
    if (res.status === 'running') {
      const pct = res.progress || 0;
      document.getElementById('fuzzyProgressBar').style.width = pct + '%';
      document.getElementById('fuzzyProgressPct').textContent = pct + '%';
      setTimeout(pollFuzzy, 2000);
      return;
    }
    // Done
    document.getElementById('fuzzyProgressWrap').style.display = 'none';
    window._fuzzyDone = true;
    const clusters = res.clusters || [];
    if (!clusters.length) {
      list.innerHTML = '<div style="color:#2e7d32;font-weight:600;padding:20px;">✅ 85% ஒத்த தலைப்புகள் எதுவும் இல்லை</div>';
      return;
    }
    status.textContent = `மொத்தம் ${clusters.length} குழுக்கள் கண்டறியப்பட்டன`;
    const COLORS = ['fuzzy-card-0','fuzzy-card-1','fuzzy-card-2','fuzzy-card-3','fuzzy-card-4','fuzzy-card-5','fuzzy-card-6','fuzzy-card-7'];
    list.innerHTML = clusters.map((c, i) =>
      `<div class="alert-card ${COLORS[i % COLORS.length]}" style="border-width:2px;margin-bottom:10px;">
        <div class="alert-card-title" style="font-size:0.95rem;cursor:pointer;" onclick="askChangeFuzzyTitle('${escAttr(c.canonical)}')" title="இந்த தலைப்பை மாற்ற கிளிக் செய்யவும்">🔀 ${i+1}. ${escHtml(c.canonical)}</div>
        ${c.variants.slice(1).map(v => `<div class="fuzzy-variant" style="padding:3px 0;cursor:pointer;" onclick="askChangeFuzzyTitle('${escAttr(v)}')" title="இந்த தலைப்பை மாற்ற கிளிக் செய்யவும்">• ${escHtml(v)}</div>`).join('')}
        <div class="alert-card-prices" style="margin-top:8px;">💰 ${c.allPrices.map(p => '₹' + p).join(' | ')} &nbsp;|&nbsp; 📚 ${c.count} புத்தகங்கள்</div>
      </div>`
    ).join('');
  } catch(e) {
    document.getElementById('fuzzyProgressWrap').style.display = 'none';
    list.innerHTML = '<div style="color:red;padding:20px;">கண்டறிய இயலவில்லை: ' + e + '</div>';
  }
}

// கவனிக்க தாவலில் ஒரு தலைப்பைக் கிளிக் செய்தால் — மாற்ற விரும்புகிறீர்களா என்று கேட்டு,
// "ஆம்" எனில் Master Title Change modal-ஐ அதே தலைப்புடன் திறந்து, அதே Master Title Change
// முறையிலேயே (பதிப்பகம் தேர்வு -> புதிய தலைப்பு -> Admin Password) தலைப்பு மாறும்.
function askChangeFuzzyTitle(title) {
  const ok = confirm(`"${title}" — இந்த தலைப்பை மாற்ற விரும்புகிறீர்களா?`);
  if (!ok) return;
  openTitleChangeModal(title);
}

// ==================== SEARCH ====================
function onSearch() {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(doSearch, 300);
}

async function doSearch() {
  const q = document.getElementById('searchInput').value.trim();
  if (q.length < 1) {
    document.getElementById('resultsBody').innerHTML = '<tr><td colspan="7"><div class="empty-state"><div class="icon">📖</div><div>தேட ஆரம்பிக்கவும்...</div></div></td></tr>';
    document.getElementById('searchStatus').textContent = '';
    selectedRow = null;
    return;
  }
  document.getElementById('searchStatus').innerHTML = '<span class="loading"><span class="spinner"></span> தேடுகிறது...</span>';
  let data;
  try {
    const res = await fetch('/api/search?q=' + encodeURIComponent(q) + '&year=' + encodeURIComponent(currentYear));
    if (!res.ok) throw new Error('Server பிழை (' + res.status + ')');
    data = await res.json();
  } catch (e) {
    document.getElementById('resultsBody').innerHTML = '<tr><td colspan="7"><div class="empty-state"><div class="icon">⚠️</div><div>தேடலில் பிழை — மீண்டும் முயற்சிக்கவும்</div></div></td></tr>';
    document.getElementById('searchStatus').textContent = '';
    return;
  }
  const tbody = document.getElementById('resultsBody');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="7"><div class="empty-state"><div class="icon">🔍</div><div>முடிவுகள் இல்லை</div></div></td></tr>';
    document.getElementById('searchStatus').textContent = '';
    return;
  }
  document.getElementById('searchStatus').textContent = `${data.length} புத்தக தலைப்புகள் கிடைத்தன`;
  tbody.innerHTML = data.map((r,i) => {
    // சிவப்பு = வேறு விலை, ஆரஞ்சு = ஒத்த தலைப்பு duplicate
    const rowClass = r.isMultiPrice ? ' multi-price-row' : (r.isFuzzyDup ? ' fuzzy-dup-row' : '');
    const badge = r.isMultiPrice
      ? '<span class="multi-price-badge">🔴 வேறு விலை!</span>'
      : (r.isFuzzyDup ? '<span class="fuzzy-dup-badge">🟠 ஒத்த தலைப்பு!</span>' : '');
    // முகப்புப் படம் column — "ஒரே தலைப்பில் வேறு விலை" புத்தகங்களுக்கு மட்டுமல்ல,
    // Book Id உள்ள எந்த புத்தகத்திற்கும் (Book Id/தலைப்பு தேடி அப்லோட் செய்தவைக்கும்) காட்டப்படும்.
    const isAdminUser = (window.CURRENT_ROLE === 'admin');
    let coverCell = '';
    if (r.bookId) {
      const viewBtn = r.hasCover
        ? `<button type="button" class="btn btn-outline btn-sm" onclick="event.stopPropagation();viewBookCover('${escAttr(r.bookId)}','${escAttr(r.title)}')">🖼️ பார்க்க</button>`
        : '';
      // "மாற்று" (ஏற்கனவே cover உள்ள புத்தகத்தை மாற்றும் பட்டன்) இனி காட்டப்படாது —
      // cover இல்லாத புத்தகங்களுக்கு மட்டும் "ஏற்று" பட்டன் காட்டப்படும்.
      let uploadBtn = '';
      if (r.hasCover) {
        uploadBtn = '';
      } else if (isAdminUser) {
        uploadBtn = `<button type="button" class="btn btn-outline btn-sm" onclick="event.stopPropagation();openBookCoverUploadModalFor('${escAttr(r.bookId)}','${escAttr(r.title)}','${escAttr(r.vendor)}','${escAttr(r.price)}',false)">➕ ஏற்று</button>`;
      } else {
        uploadBtn = `<span style="color:var(--muted);font-size:0.8rem;">படம் இல்லை</span>`;
      }
      coverCell = `<div style="display:flex;gap:6px;flex-wrap:wrap;">${viewBtn}${uploadBtn}</div>`;
    } else if (r.isMultiPrice) {
      coverCell = `<span style="color:var(--muted);font-size:0.8rem;">Book Id இல்லை</span>`;
    } else {
      coverCell = '—';
    }
    return `<tr class="${rowClass}" onclick="selectRow(this,'${escAttr(r.title)}','${escAttr(r.price)}')" data-title="${escAttr(r.title)}" data-price="${escAttr(r.price)}">
      <td data-label="#">${i+1}</td>
      <td data-label="தலைப்பு" style="font-weight:500;white-space:normal;word-break:break-word;">${escHtml(r.title)}${badge}</td>
      <td data-label="எழுதியவர்" style="white-space:normal;word-break:break-word;font-size:0.85rem;">${r.author ? escHtml(r.author) : '—'}</td>
      <td data-label="புத்தக முகப்பு">${coverCell}</td>
      <td data-label="பதிப்பகம்" style="max-width:110px;white-space:normal;word-break:break-word;font-size:0.85rem;">${escHtml(r.vendor)}</td>
      <td data-label="விலை">₹${escHtml(r.price)}</td>
      <td data-label="எண்ணிக்கை"><span class="badge badge-teal">${r.count}</span></td>
    </tr>`;
  }).join('');
  selectedRow = null;
  document.getElementById('selectedInfo').textContent = '';
}

function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function escAttr(s) { return String(s).replace(/'/g,"\\'").replace(/"/g,'&quot;'); }

function selectRow(tr, title, price) {
  document.querySelectorAll('#resultsBody tr').forEach(r=>r.classList.remove('selected'));
  tr.classList.add('selected');
  selectedRow = { title, price };
  document.getElementById('selectedInfo').textContent = `தேர்ந்தெடுக்கப்பட்டது: ${title.substring(0,40)}...`;
}

// ==================== BOOK DETAIL ====================
async function openBookDetail() {
  if (!selectedRow) { toast('ஒரு வரியைத் தேர்ந்தெடுக்கவும்', 'error'); return; }
  const d = await fetch(`/api/book_detail?title=${encodeURIComponent(selectedRow.title)}&price=${encodeURIComponent(selectedRow.price)}&year=${encodeURIComponent(currentYear)}`).then(r=>r.json());
  if (d.error) { toast(d.error, 'error'); return; }
  currentBook = d;
  if (d.remaining <= 0) { toast('அனைத்து புத்தகங்களும் ஏற்கனவே பிரிக்கப்பட்டுவிட்டன.', ''); return; }
  document.getElementById('detailTable').innerHTML = [
    ['தலைப்பு', d.title],
    ['ஆசிரியர்', d.author],
    ['பதிப்பகம்', d.vendor],
    ['விலை', '₹' + d.price],
    ['மொத்த புத்தகங்கள்', d.total],
    ['பிரிக்கப்பட்டவை', `<span class="badge badge-green">${d.assigned}</span>`],
    ['⏳ மீதம் உள்ளவை', `<span class="badge badge-amber" style="font-size:1rem;padding:6px 14px;">${d.remaining}</span>`],
  ].map(([k,v]) => `<tr><td>${k} :</td><td>${v}</td></tr>`).join('');
  document.getElementById('confirmLabel').textContent = `மீதமுள்ள ${d.remaining} புத்தகங்கள் என்பதை உறுதிப்படுத்துகிறேன்`;
  document.getElementById('confirmCheck').checked = false;
  document.getElementById('proceedBtn').disabled = true;
  document.getElementById('proceedBtn').textContent = workWageCenters.length
    ? `🏷️ நூலகங்கள் (${workWageCenters.join(', ')}) →`
    : '🏷️ நூலக வகை தேர்வு →';
  document.getElementById('modalDetail').style.display = 'flex';
}

function toggleConfirm() {
  const cb = document.getElementById('confirmCheck');
  cb.checked = !cb.checked;
  updateProceedBtn();
}
function updateProceedBtn() {
  document.getElementById('proceedBtn').disabled = !document.getElementById('confirmCheck').checked;
}

// ==================== LIB TYPE ====================
async function openLibTypeModal() {
  closeModal('modalDetail');
  // ஊதிய மையம் தேர்ந்தெடுக்கப்பட்டிருந்தால் — நூலக வகை படி என்று படி இல்லாமல்
  // நேரடியாக அந்த ஊதிய மையத்திற்குண்டான அனைத்து நூலகங்களையும் காட்டு
  if (workWageCenters.length) {
    await openLibrariesModalForWageCenter();
    return;
  }
  const sel = document.getElementById('libTypeSelect');
  sel.innerHTML = currentBook.lib_types.map(t => `<option value="${escAttr(t)}">${escHtml(t)}</option>`).join('');
  document.getElementById('modalLibType').style.display = 'flex';
}

// ==================== LIBRARIES (ஊதிய மையம் வழி — வகை தேர்வு இல்லாமல்) ====================
async function openLibrariesModalForWageCenter() {
  const libs = await fetch(`/api/libraries_for_wage_center?title=${encodeURIComponent(currentBook.title)}&price=${encodeURIComponent(currentBook.price)}&wage_center=${encodeURIComponent(wageCenterQueryParam())}&year=${encodeURIComponent(currentYear)}`).then(r=>r.json());
  if (!libs.length) { toast('இந்த ஊதிய மைய(ங்க)ளில் நூலகங்கள் இல்லை', 'error'); return; }
  currentBook.selectedLibType = null;   // பல வகைகள் கலந்திருக்கலாம் — assign-ல் library_type கட்டுப்பாடு தேவையில்லை
  currentLibs = libs;
  document.getElementById('libTypeInfo').textContent = `ஊதிய மையம்: ${workWageCenters.join(', ')}  |  தலைப்பு: ${currentBook.title.substring(0,60)}`;
  const grid = document.getElementById('libsCheckboxGrid');
  grid.innerHTML = libs.map((lib, idx) => `
    <div class="checkbox-item" onclick="toggleCheckbox('asgn_cb_${idx}',this)">
      <input type="checkbox" id="asgn_cb_${idx}" value="${escAttr(lib)}" onchange="updateAssignCount()">
      <label for="asgn_cb_${idx}">${escHtml(lib)}</label>
    </div>`).join('');
  document.getElementById('assignSelectAll').checked = false;
  updateAssignCount();
  document.getElementById('modalLibraries').style.display = 'flex';
}

// ==================== LIBRARIES (நூலக வகை வழி — பழைய நடத்தை) ====================
async function openLibrariesModal() {
  const libType = document.getElementById('libTypeSelect').value;
  closeModal('modalLibType');
  const libs = await fetch(`/api/libraries_for_type?title=${encodeURIComponent(currentBook.title)}&price=${encodeURIComponent(currentBook.price)}&lib_type=${encodeURIComponent(libType)}&year=${encodeURIComponent(currentYear)}`).then(r=>r.json());
  if (!libs.length) { toast('இந்த வகையில் நூலகங்கள் இல்லை', 'error'); return; }
  currentBook.selectedLibType = libType;
  currentLibs = libs;
  document.getElementById('libTypeInfo').textContent = `வகை: ${libType}  |  தலைப்பு: ${currentBook.title.substring(0,60)}`;
  const grid = document.getElementById('libsCheckboxGrid');
  grid.innerHTML = libs.map((lib, idx) => `
    <div class="checkbox-item" onclick="toggleCheckbox('asgn_cb_${idx}',this)">
      <input type="checkbox" id="asgn_cb_${idx}" value="${escAttr(lib)}" onchange="updateAssignCount()">
      <label for="asgn_cb_${idx}">${escHtml(lib)}</label>
    </div>`).join('');
  document.getElementById('assignSelectAll').checked = false;
  updateAssignCount();
  document.getElementById('modalLibraries').style.display = 'flex';
}

function toggleCheckbox(id, wrapper) {
  const cb = document.getElementById(id);
  if (event.target === cb) return;
  cb.checked = !cb.checked;
  wrapper.classList.toggle('checked', cb.checked);
  updateAssignCount();
}

function toggleAssignSelectAll() {
  const checked = document.getElementById('assignSelectAll').checked;
  document.querySelectorAll('#libsCheckboxGrid input[type=checkbox]').forEach(cb => {
    cb.checked = checked;
    cb.closest('.checkbox-item').classList.toggle('checked', checked);
  });
  updateAssignCount();
}

function updateAssignCount() {
  const cnt = document.querySelectorAll('#libsCheckboxGrid input:checked').length;
  document.getElementById('assignCheckCount').textContent = cnt + ' தேர்வு';
}

async function assignBooks() {
  const selected = [...document.querySelectorAll('#libsCheckboxGrid input:checked')].map(cb => cb.value);
  if (!selected.length) { toast('குறைந்தது ஒரு நூலகத்தை தேர்ந்தெடுக்கவும்!', 'error'); return; }
  const setNumber = document.getElementById('setNumSelect').value;

  // 0) இதே தலைப்புள்ள நூல் வேறு விலைக்கு ஏற்கனவே இந்த நூலகங்களுக்கு
  //    பிரிக்கப்பட்டு/அனுப்பப்பட்டிருந்தால் எச்சரிக்கை காட்டு — block செய்யாது,
  //    உண்மையாகவே தேவை என்றால் "ஆம்" கொடுத்து தொடரலாம்.
  try {
    const priceChk = await fetch('/api/assign/price_check', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ title: currentBook.title, price: currentBook.price, libraries: selected, year: currentYear })
    }).then(r => r.json());
    const warnings = priceChk.warnings || [];
    if (warnings.length) {
      const msg = warnings.map(w => w.message).join('\n\n') +
        '\n\nஉண்மையாகவே இந்த விலையிலான பிரதிகளையும் இந்த நூலகத்திற்கு அனுப்ப வேண்டுமா?\n"ஆம்" என்றால் தொடரும், "இல்லை" என்றால் ரத்து செய்யப்படும்.';
      if (!confirm(msg)) return;
    }
  } catch (e) { /* check தோல்வியானாலும் normal assign தொடரும் */ }

  // 1) reclaim pool-ல் ஏதேனும் இந்த நூலகங்களுக்கு பொருந்துமா என்று check பண்ணி,
  //    இருந்தால் ஒரே combined popup-ல் கேட்போம்.
  let useReclaimed = false;
  try {
    const chk = await fetch('/api/assign/reclaim_check', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ libraries: selected, year: currentYear })
    }).then(r => r.json());
    const branchEntries = Object.entries(chk.branch || {});
    if ((chk.central && chk.central.length) || branchEntries.length) {
      let msg = 'இவை முன்பு reclaim (மீளப்பெறப்பட்ட) எண்கள் — இந்த batch-க்கு பயன்படுத்தலாமா?\n\n';
      if (chk.central && chk.central.length) {
        msg += `மைய நூலக எண்கள் (${chk.central.length}): ${chk.central.join(', ')}\n`;
      }
      branchEntries.forEach(([lib, nums]) => {
        msg += `${lib} — கிளை நூலக எண்: ${nums.join(', ')}\n`;
      });
      msg += '\n"ஆம்" என்றால் இவை முதலில் பயன்படுத்தப்பட்டு, மீதி புத்தகங்களுக்கு வழக்கமான அடுத்த எண் தொடரும்.';
      useReclaimed = confirm(msg);
    }
  } catch (e) { /* check தோல்வியானாலும் normal assign தொடரும் */ }

  showLoading('⏳ பதிவு செய்கிறது...');
  try {
    const res = await fetch('/api/assign', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ title: currentBook.title, price: currentBook.price, lib_type: currentBook.selectedLibType, libraries: selected, set_number: setNumber, use_reclaimed: useReclaimed, year: currentYear }) }).then(r=>r.json());
    hideLoading();
    if (res.success) {
      closeModal('modalLibraries');
      toast('✅ ' + res.message, 'success');
      doSearch();
      updateLiveTicker();
    } else { toast('❌ ' + res.error, 'error'); }
  } catch(e) { hideLoading(); toast('❌ பிழை: ' + e, 'error'); }
}

// ==================== SEND ====================
async function refreshSendSets() {
  const btn = document.getElementById('sendRefreshBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;margin-right:6px;"></span>புதுப்பிக்கிறது...';
  await loadSendSets();
  btn.disabled = false;
  btn.innerHTML = '🔄 புதுப்பி';
}

async function loadSendSets() {
  const sel = document.getElementById('sendSetSelect');
  sel.innerHTML = '<option>-- ஏற்றுகிறது --</option>';
  document.getElementById('sendLibsSection').style.display = 'none';
  document.getElementById('sendInfo').style.display = 'none';
  const data = await fetch('/api/send/sets?year=' + encodeURIComponent(currentYear) + '&wage_center=' + encodeURIComponent(wageCenterQueryParam())).then(r=>r.json());
  if (!data.length) { sel.innerHTML = '<option>-- அனுப்ப வேண்டியவை இல்லை --</option>'; return; }
  sel.innerHTML = data.map(d => `<option value="${escAttr(d.set)}">${escHtml(d.set)}  (${d.count} புத்தகங்கள்)</option>`).join('');
}

async function loadSendLibraries() {
  const val = document.getElementById('sendSetSelect').value;
  if (!val || val.includes('இல்லை') || val.includes('ஏற்று')) { toast('SET NUMBER தேர்வு செய்யவும்!', 'error'); return; }
  const setNum = val.split('  (')[0].trim();
  const data = await fetch(`/api/send/libraries?set=${encodeURIComponent(setNum)}&year=${encodeURIComponent(currentYear)}&wage_center=${encodeURIComponent(wageCenterQueryParam())}`).then(r=>r.json());
  const infoEl = document.getElementById('sendInfo');
  if (!data.libraries.length) { infoEl.textContent = `'${setNum}' — அனுப்ப வேண்டிய நூலகங்கள் இல்லை.`; infoEl.style.display='block'; document.getElementById('sendLibsSection').style.display='none'; return; }
  infoEl.textContent = `SET: ${setNum}  |  மொத்தம் ${data.total} புத்தகங்கள்  |  ${data.libraries.length} நூலகங்கள்`;
  infoEl.style.display = 'block';
  const grid = document.getElementById('sendLibsGrid');
  grid.innerHTML = data.libraries.map((d, idx) => `
    <div class="checkbox-item" onclick="toggleSendCheckbox(this)">
      <input type="checkbox" value="${escAttr(d.lib)}" onchange="updateSendCount()">
      <label>${escHtml(d.lib)} <span class="badge badge-teal">${d.count}</span></label>
    </div>`).join('');
  document.getElementById('sendSelectAll').checked = false;
  updateSendCount();
  document.getElementById('sendLibsSection').style.display = 'block';
  window._sendActiveSet = setNum;
}

function toggleSendCheckbox(wrapper) {
  const cb = wrapper.querySelector('input');
  if (event.target === cb) return;
  cb.checked = !cb.checked;
  wrapper.classList.toggle('checked', cb.checked);
  updateSendCount();
}

function toggleSendSelectAll() {
  const checked = document.getElementById('sendSelectAll').checked;
  document.querySelectorAll('#sendLibsGrid input[type=checkbox]').forEach(cb => {
    cb.checked = checked;
    cb.closest('.checkbox-item').classList.toggle('checked', checked);
  });
  updateSendCount();
}

function updateSendCount() {
  const cnt = document.querySelectorAll('#sendLibsGrid input:checked').length;
  document.getElementById('sendCheckCount').textContent = cnt + ' தேர்வு';
}

async function markSent() {
  const selected = [...document.querySelectorAll('#sendLibsGrid input:checked')].map(cb => cb.value);
  if (!selected.length) { toast('குறைந்தது ஒரு நூலகத்தை தேர்ந்தெடுக்கவும்!', 'error'); return; }
  if (!confirm(`SET: ${window._sendActiveSet}\\n${selected.length} நூலகங்களுக்கு புத்தகங்கள் அனுப்பப்பட்டதாக பதிவு செய்யவா?`)) return;
  showLoading('⏳ அனுப்பியதாக பதிவு செய்கிறது...');
  try {
    const res = await fetch('/api/send/mark', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ set_number: window._sendActiveSet, libraries: selected, year: currentYear }) }).then(r=>r.json());
    hideLoading();
    if (res.success) {
      toast('✅ ' + res.message, 'success');
      loadSendSets();
      document.getElementById('sendLibsSection').style.display='none';
      document.getElementById('sendInfo').style.display='none';
      updateLiveTicker();
    } else { toast('❌ ' + res.error, 'error'); }
  } catch(e) { hideLoading(); toast('❌ பிழை: ' + e, 'error'); }
}

// ==================== REPORTS ====================
async function genReport(num, rtype) {
  showLoading(`⏳ அறிக்கை ${num} உருவாக்குகிறது...`);
  let url = '/api/report/' + num + '?year=' + encodeURIComponent(currentYear);
  if (rtype) url += '&rtype=' + encodeURIComponent(rtype);
  const res = await fetch(url).then(r=>r.json());
  hideLoading();
  if (res.success) {
    toast('✅ ' + res.message, 'success');
    if (res.url) window.open(res.url, '_blank');
  }
  else toast('❌ ' + (res.error || 'பிழை'), 'error');
}

// ---- அறிக்கை 4: வகை தேர்வு modal ----
function openReport4TypeModal() {
  document.getElementById('modalReport4Type').style.display = 'flex';
}
function chooseReport4Type(rtype) {
  closeModal('modalReport4Type');
  openReportChoice({ kind: 'get', num: 4, rtype: rtype });
}

// ---- அறிக்கை 1,2,3,4,5,7 அனைத்திற்கும் பொதுவான PDF/Excel தேர்வு modal ----
function openReportChoice(pending) {
  window._pendingReport = pending;
  document.getElementById('modalReportChoice').style.display = 'flex';
}

async function chooseReportView() {
  closeModal('modalReportChoice');
  const p = window._pendingReport;
  if (!p) return;
  if (p.kind === 'get') await genReport(p.num, p.rtype);
  else if (p.kind === 'post5') await genReport5Do(p.payload);
  else if (p.kind === 'post7') await genReport7Do(p.payload);
}

async function chooseReportExcelDownload() {
  closeModal('modalReportChoice');
  const p = window._pendingReport;
  if (!p) return;
  showLoading('⏳ Excel தயார் செய்யப்படுகிறது...');
  try {
    let url, opts = {};
    if (p.kind === 'get') {
      url = '/api/report/' + p.num + '/excel?year=' + encodeURIComponent(currentYear);
      if (p.rtype) url += '&rtype=' + encodeURIComponent(p.rtype);
    } else if (p.kind === 'post5') {
      url = '/api/report5/excel';
      opts = { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p.payload) };
    } else if (p.kind === 'post7') {
      url = '/api/report7/excel';
      opts = { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p.payload) };
    } else { hideLoading(); return; }

    const res = await fetch(url, opts);
    const ct = res.headers.get('Content-Type') || '';
    if (ct.includes('application/json')) {
      const err = await res.json();
      hideLoading();
      toast('❌ ' + (err.error || 'பிழை'), 'error');
      return;
    }
    const blob = await res.blob();
    hideLoading();
    let fname = 'அறிக்கை.xlsx';
    const cd = res.headers.get('Content-Disposition') || '';
    const m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^\";]+)"?/i.exec(cd);
    if (m) fname = decodeURIComponent(m[1]);
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = fname;
    document.body.appendChild(link);
    link.click();
    link.remove();
    toast('✅ Excel பதிவிறக்கம் ஆனது', 'success');
  } catch (e) {
    hideLoading();
    toast('❌ பிழை: ' + e, 'error');
  }
}

async function loadR5Libs() {
  const sel = document.getElementById('r5LibSelect');
  const libs = await fetch('/api/report5_libs?year=' + encodeURIComponent(currentYear)).then(r=>r.json());
  sel.innerHTML = libs.map(l => `<option value="${escAttr(l)}">${escHtml(l)}</option>`).join('');
}

function genReport5() {
  const lib = document.getElementById('r5LibSelect').value;
  if (!lib || lib.includes('ஏற்று')) { toast('நூலகம் தேர்வு செய்யவும்!', 'error'); return; }
  if (!confirm(`நீங்கள் தேர்வு செய்த நூலகம்:\\n\\n🏛️  ${lib}\\n\\nஇதுதான் என்பதை உறுதிப்படுத்துகிறீர்களா?`)) return;
  openReportChoice({ kind: 'post5', payload: { lib_name: lib, year: currentYear } });
}

async function genReport5Do(payload) {
  showLoading('⏳ அறிக்கை 5 உருவாக்குகிறது...');
  const res = await fetch('/api/report5', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) }).then(r=>r.json());
  hideLoading();
  if (res.success) {
    toast('✅ ' + res.message, 'success');
    if (res.url) window.open(res.url, '_blank');
  }
  else toast('❌ ' + (res.error || 'பிழை'), 'error');
}

let _r7Ranges = [];
async function loadR7Ranges() {
  document.getElementById('r7LoadBtn').textContent = '⏳ ஏற்றுகிறது...';
  try {
    const res = await fetch('/api/report7/ranges?year=' + encodeURIComponent(currentYear)).then(r=>r.json());
    if (res.error) { toast('❌ ' + res.error, 'error'); return; }
    _r7Ranges = res.ranges;
    const info = document.getElementById('r7TotalInfo');
    info.textContent = `மொத்தம் ${res.total} நூல்கள் | ${res.cn_min}–${res.cn_max} | ${res.ranges.length} பகுதிகள்`;
    const itemsDiv = document.getElementById('r7Items');
    itemsDiv.innerHTML = '';
    res.ranges.forEach(r => {
      const id = `r7c_${r.idx}`;
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid #e5e7eb;';
      row.innerHTML = `<input type="checkbox" id="${id}" data-idx="${r.idx}" style="accent-color:var(--primary);width:15px;height:15px;">
        <label for="${id}" style="cursor:pointer;font-size:0.83rem;flex:1;">
          பகுதி ${r.idx} &nbsp;|&nbsp; <strong>${r.start}–${r.end}</strong> &nbsp;|&nbsp; ${r.count} நூல்கள்
        </label>`;
      itemsDiv.appendChild(row);
    });
    document.getElementById('r7ChunkList').style.display = 'block';
    document.getElementById('r7SelectAll').checked = false;
  } catch(e) { toast('❌ பிழை: ' + e.message, 'error'); }
  finally { document.getElementById('r7LoadBtn').textContent = '🔄 பகுதிகள் ஏற்று'; }
}
function r7ToggleAll(cb) {
  document.querySelectorAll('#r7Items input[type=checkbox]').forEach(c => c.checked = cb.checked);
}
function genReport7() {
  const checked = [...document.querySelectorAll('#r7Items input[type=checkbox]:checked')];
  if (checked.length === 0) { toast('⚠️ குறைந்தது ஒரு பகுதியாவது தேர்வு செய்யவும்', 'error'); return; }
  const selected = checked.map(c => {
    const idx = parseInt(c.dataset.idx);
    const r = _r7Ranges.find(x => x.idx === idx);
    return {idx: r.idx, start: r.start, end: r.end};
  });
  openReportChoice({ kind: 'post7', payload: { selected, year: currentYear } });
}

async function genReport7Do(payload) {
  showLoading(`⏳ அறிக்கை 7 — ${payload.selected.length} பகுதி(கள்) உருவாக்குகிறது...`);
  const res = await fetch('/api/report7', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  }).then(r=>r.json());
  hideLoading();
  if (res.success) {
    toast('✅ ' + res.message, 'success');
    if (res.urls) res.urls.forEach(u => window.open(u, '_blank'));
  }
  else toast('❌ ' + (res.error || 'பிழை'), 'error');
}

// ==================== ADMIN EXCEL DOWNLOAD ====================
function openDownloadExcelModal() {
  const lbl = document.getElementById('downloadExcelYearLabel');
  if (lbl) lbl.textContent = currentYear;
  document.getElementById('modalDownloadExcel').style.display = 'flex';
}
async function downloadExcelData(type) {
  closeModal('modalDownloadExcel');
  const year = currentYear;
  toast('⏳ Excel தயார் செய்யப்படுகிறது... (பெரிய தரவுத் தொகுப்புகளுக்கு சில நிமிடங்கள் ஆகலாம்)', 'success');
  try {
    await fetch('/api/admin/download_excel/start?type=' + encodeURIComponent(type) + '&year=' + encodeURIComponent(year));
    pollExcelExport(type, year);
  } catch (e) {
    toast('❌ தொடங்க முடியவில்லை: ' + e, 'error');
  }
}

async function pollExcelExport(type, year) {
  try {
    const res = await fetch('/api/admin/download_excel/status?type=' + encodeURIComponent(type) + '&year=' + encodeURIComponent(year)).then(r => r.json());
    if (res.status === 'running') {
      setTimeout(() => pollExcelExport(type, year), 3000);
      return;
    }
    if (res.status === 'error') {
      toast('❌ Excel தயார் செய்ய முடியவில்லை: ' + (res.error || 'பிழை'), 'error');
      return;
    }
    if (res.status === 'done') {
      toast('✅ Excel தயார் — பதிவிறக்கம் தொடங்குகிறது', 'success');
      window.location.href = '/api/admin/download_excel/file?type=' + encodeURIComponent(type) + '&year=' + encodeURIComponent(year);
      return;
    }
    setTimeout(() => pollExcelExport(type, year), 3000);
  } catch (e) {
    toast('❌ பிழை: ' + e, 'error');
  }
}

// ==================== EXIT ====================
async function exitApp() {
  if (!confirm('வெளியேற விரும்புகிறீர்களா?')) return;
  window.location.href = '/logout';
}

// ==================== INIT ====================
window.onload = async () => {
  await initYearSelector();
  await initWageCenterSelector();

  // Admin மட்டும் பார்க்க வேண்டிய பட்டன்கள் — staff-க்கு மறைக்கப்படும்
  if (window.CURRENT_ROLE !== 'admin') {
    ['btnRenumber', 'btnRestore', 'btnReclaim', 'btnChangePwd', 'btnDownloadExcel', 'btnLibrarianYear', 'btnUploadExcel', 'btnUploadStateAcc', 'btnUploadBookCover'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
  }

  // ஆண்டு + ஊதிய மையம் selector-கள் — Admin-க்கு மட்டுமே காட்டப்படும்.
  // dclstaff-க்கு இரண்டும் மறைக்கப்படும் — Admin தேர்ந்தெடுத்ததையே அவர்கள் தானாக பின்பற்றுவார்கள்.
  const yearWrapEl = document.getElementById('yearWrap');
  const wageCenterWrapEl = document.getElementById('wageCenterWrap');
  if (window.CURRENT_ROLE === 'admin') {
    if (yearWrapEl) yearWrapEl.style.display = 'flex';
    if (wageCenterWrapEl) wageCenterWrapEl.style.display = 'flex';
  } else {
    if (yearWrapEl) yearWrapEl.style.display = 'none';
    if (wageCenterWrapEl) wageCenterWrapEl.style.display = 'none';
  }

  // Set number options
  document.getElementById('setNumSelect').innerHTML = Array.from({length:30},(_,i)=>`<option value="SET${i+1}">SET${i+1}</option>`).join('');

  // Data status check
  const statusEl = document.getElementById('dataStatus');
  try {
    const ok = await fetch('/api/search?q=test').then(r=>r.ok);
    statusEl.textContent = ok ? '✅ data ஏற்றப்பட்டது' : '❌ data பிழை';
  } catch(e) {
    statusEl.textContent = '❌ இணைப்பு பிழை';
  }

  // Live ticker — now + every 60 seconds
  updateLiveTicker();
  setInterval(updateLiveTicker, 60000);

  // Multi-price / Multi-ISBN banners on distribute page (default)
  loadMultiPriceBanner();
  loadMultiIsbnBanner();
};

// ==================== மைய/கிளைப் பதிவெண் மாற்ற + Master Data Restore ====================
function openRenumberChoice() {
  document.getElementById('modalRenumberChoice').style.display = 'flex';
}
function chooseRenumberCentral() {
  closeModal('modalRenumberChoice');
  document.getElementById('renumberCentralInput').value = '';
  document.getElementById('modalRenumberCentral').style.display = 'flex';
}
// ஒவ்வொரு நூலகத்திற்கும் admin type செய்யும் புதிய கிளைப்பதிவெண்-ஐ pageக்கு page தாண்டியும்
// நினைவில் வைக்க இந்த state object பயன்படுகிறது: { "நூலகம் பெயர்": "20001", ... }
const renumberBranchState = { edits: {}, allLibraries: [] };

function chooseRenumberBranch() {
  closeModal('modalRenumberChoice');
  renumberBranchState.edits = {};
  document.getElementById('modalRenumberBranch').style.display = 'flex';
  const searchBox = document.getElementById('renumberBranchSearchInput');
  if (searchBox) searchBox.value = '';
  renumberBranchLoadAll();
}

// 150 நூலகங்களும் ஒரே request-ல் load செய்யப்பட்டு, search box மூலம் உடனடியாக filter செய்யப்படும்
// (இதனால் "அடுத்தது" என்பதை பல முறை கிளிக் செய்ய வேண்டிய தேவை இல்லை).
async function renumberBranchLoadAll() {
  const tbody = document.getElementById('renumberBranchTableBody');
  tbody.innerHTML = '<tr><td colspan="4" style="padding:14px;text-align:center;color:var(--muted);">ஏற்றுகிறது...</td></tr>';
  try {
    const res = await fetch('/api/renumber/branch/library_list?page=1&page_size=1000&year=' + encodeURIComponent(currentYear));
    const data = await res.json();
    renumberBranchState.allLibraries = data.libraries;
    renumberBranchRenderRows(renumberBranchState.allLibraries);
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="4" style="padding:14px;text-align:center;color:var(--muted);">பிழை ஏற்பட்டது</td></tr>';
  }
}

function renumberBranchRenderRows(list) {
  const tbody = document.getElementById('renumberBranchTableBody');
  const label = document.getElementById('renumberBranchPageLabel');
  if (label) {
    label.textContent = 'மொத்தம் ' + renumberBranchState.allLibraries.length + ' நூலகங்கள்' +
      (list.length !== renumberBranchState.allLibraries.length ? ' (' + list.length + ' தேடலில் கிடைத்தது)' : '');
  }
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="padding:14px;text-align:center;color:var(--muted);">நூலகங்கள் இல்லை</td></tr>';
    return;
  }
  tbody.innerHTML = list.map(lib => {
    const safeName = lib.library_name.replace(/"/g, '&quot;');
    const existingVal = renumberBranchState.edits[lib.library_name] || '';
    return '<tr>' +
      '<td style="padding:8px;border-bottom:1px solid var(--border);">' + lib.serial + '</td>' +
      '<td style="padding:8px;border-bottom:1px solid var(--border);">' + lib.library_name + '</td>' +
      '<td style="padding:8px;border-bottom:1px solid var(--border);">' + lib.current_label + '</td>' +
      '<td style="padding:8px;border-bottom:1px solid var(--border);">' +
      '<input type="number" data-lib="' + safeName + '" value="' + existingVal + '" placeholder="புதிய எண்" ' +
      'style="width:110px;padding:6px;border:1px solid var(--border);border-radius:6px;" ' +
      'oninput="renumberBranchEditInput(this)">' +
      '</td></tr>';
  }).join('');
  renumberBranchUpdateNote();
}

function renumberBranchFilter() {
  const box = document.getElementById('renumberBranchSearchInput');
  const q = box ? box.value.trim() : '';
  if (!q) {
    renumberBranchRenderRows(renumberBranchState.allLibraries);
    return;
  }
  const filtered = renumberBranchState.allLibraries.filter(lib => lib.library_name.indexOf(q) !== -1);
  renumberBranchRenderRows(filtered);
}

function renumberBranchEditInput(input) {
  const lib = input.getAttribute('data-lib');
  const val = input.value.trim();
  if (val === '') {
    delete renumberBranchState.edits[lib];
  } else {
    renumberBranchState.edits[lib] = val;
  }
  renumberBranchUpdateNote();
}

function renumberBranchUpdateNote() {
  const count = Object.keys(renumberBranchState.edits).length;
  const note = document.getElementById('renumberBranchEditedNote');
  note.textContent = count ? ('✏️ ' + count + ' நூலகங்களுக்கு புதிய எண் type செய்யப்பட்டுள்ளது (எல்லா பக்கங்களிலும் சேர்த்து).') : '';
}

async function saveCentralRenumberStart() {
  const val = document.getElementById('renumberCentralInput').value.trim();
  if (!val || isNaN(val)) { alert('சரியான எண் பதிவிடவும்'); return; }
  const newStart = parseInt(val);
  showLoading('⏳ தொடக்க மதிப்பு சேவ் செய்கிறது...');
  let result;
  try {
    let res = await fetch('/api/renumber/central', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({new_start: newStart, apply_existing: false, year: currentYear})
    });
    result = await res.json();
  } catch (e) {
    hideLoading();
    alert('பிழை: ' + e);
    return;
  }
  hideLoading();
  if (result.error) { alert('பிழை: ' + result.error); return; }
  closeModal('modalRenumberCentral');

  const cont = confirm('மையப் பதிவெண் தொடக்க மதிப்பு ' + newStart + ' ஆக சேவ் செய்யப்பட்டது.\\n\\n' +
    'ஏற்கனவே assign ஆன மையப்பதிவெண்களையும் இந்த தொடக்க எண்ணிலிருந்து (' + newStart + ') மீண்டும் வரிசைப்படுத்த வேண்டுமா?\\n' +
    '(மாற்றும் முன் master_data.xlsx-ன் backup CSV ஆக சேவ் செய்யப்படும்)');
  if (!cont) return;

  showLoading('⏳ மையப் பதிவெண்கள் மீண்டும் வரிசைப்படுத்துகிறது...');
  try {
    const res = await fetch('/api/renumber/central', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({new_start: newStart, apply_existing: true, year: currentYear})
    });
    result = await res.json();
  } catch (e) {
    hideLoading();
    alert('பிழை: ' + e);
    return;
  }
  hideLoading();
  if (result.error) { alert('பிழை: ' + result.error); return; }
  let msg = '';
  if (result.backup_file) msg += '✅ Backup எடுக்கப்பட்டது: ' + result.backup_file + '\\n\\n';
  msg += result.message;
  alert(msg);
  location.reload();
}

async function saveBranchRenumberBulk() {
  const entries = Object.entries(renumberBranchState.edits);
  if (!entries.length) { alert('குறைந்தது ஒரு நூலகத்திற்காவது புதிய கிளைப்பதிவெண் type செய்யவும்'); return; }

  const items = entries.map(([library_name, val]) => ({ library_name, new_start: parseInt(val) }));
  const invalid = items.find(it => isNaN(it.new_start));
  if (invalid) { alert("'" + invalid.library_name + "' க்கு சரியான எண் பதிவிடவும்"); return; }

  const ok = confirm(items.length + ' நூலகங்களின் கிளைப் பதிவெண்களை மீண்டும் வரிசைப்படுத்த உறுதிப்படுத்துகிறீர்களா?\\n' +
    '(மாற்றும் முன் backup எடுக்கப்படும், தேவைப்பட்டால் பின்னர் Restore செய்யலாம்)');
  if (!ok) return;

  showLoading('⏳ ' + items.length + ' நூலகங்களின் கிளைப் பதிவெண்கள் மீண்டும் வரிசைப்படுத்துகிறது...');
  try {
    const res = await fetch('/api/renumber/branch/bulk_save', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ items, year: currentYear })
    });
    const result = await res.json();
    hideLoading();
    if (result.error) { alert('பிழை: ' + result.error); return; }
    closeModal('modalRenumberBranch');
    let msg = '';
    if (result.backup_file) msg += '✅ Backup எடுக்கப்பட்டது: ' + result.backup_file + '\\n\\n';
    msg += result.message;
    alert(msg);
    location.reload();
  } catch (e) {
    hideLoading();
    alert('பிழை: ' + e);
  }
}

// ==================== MASTER DATA — மெனு ====================
function openMasterDataMenu() {
  document.getElementById('modalMasterDataMenu').style.display = 'flex';
}

async function openRestoreModal() {
  document.getElementById('modalRestore').style.display = 'flex';
  document.getElementById('restorePwdInput').value = '';
  document.getElementById('restoreMsg').textContent = '';
  const sel = document.getElementById('restoreSelect');
  sel.innerHTML = '<option>-- ஏற்றுகிறது --</option>';
  showLoading('⏳ Backup பட்டியல் ஏற்றுகிறது...');
  try {
    const res = await fetch('/api/backups/list');
    const list = await res.json();
    if (!list.length) { sel.innerHTML = '<option value="">backup கோப்புகள் இல்லை</option>'; return; }
    sel.innerHTML = '<option value="">-- தேதி தேர்வு செய்யவும் --</option>' +
      list.map(b => `<option value="${b.filename}">${b.label}</option>`).join('');
  } catch (e) {
    sel.innerHTML = '<option value="">பிழை ஏற்பட்டது</option>';
  } finally {
    hideLoading();
  }
}

async function restoreBackup() {
  const filename = document.getElementById('restoreSelect').value;
  const password = document.getElementById('restorePwdInput').value;
  const msgBox = document.getElementById('restoreMsg');
  if (!filename) { alert('தேதி தேர்வு செய்யவும்'); return; }
  if (!password) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'Admin Password கட்டாயம்'; return; }
  const ok = confirm('இந்த backup-ஐ பயன்படுத்தி தற்போதைய master_data.xlsx முழுவதும் மீளமைக்கப்படும். தொடரவா?');
  if (!ok) return;
  showLoading('⏳ Master Data மீட்டமைக்கிறது...');
  try {
    const res = await fetch('/api/backups/restore', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({filename: filename, password: password})
    });
    const result = await res.json();
    hideLoading();
    if (result.error) { msgBox.style.color = '#c0392b'; msgBox.textContent = result.error; return; }
    closeModal('modalRestore');
    alert(result.message);
    location.reload();
  } catch (e) {
    hideLoading();
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'பிழை: ' + e;
  }
}

// ==================== MASTER DATA CLEAR ====================
async function openMasterClearModal() {
  document.getElementById('modalMasterClear').style.display = 'flex';
  document.getElementById('masterClearConfirmInput').value = '';
  document.getElementById('masterClearPwdInput').value = '';
  document.getElementById('masterClearMsg').textContent = '';
  const sel = document.getElementById('masterClearYearSelect');
  sel.innerHTML = '<option>-- ஏற்றுகிறது --</option>';
  try {
    const data = await fetch('/api/years/available').then(r => r.json());
    const years = data.years && data.years.length ? data.years : ['2024-2025'];
    sel.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join('');
    sel.value = currentYear && years.includes(currentYear) ? currentYear : years[0];
  } catch (e) {
    sel.innerHTML = `<option value="${currentYear || '2024-2025'}">${currentYear || '2024-2025'}</option>`;
  }
}

async function doMasterDataClear() {
  const year = document.getElementById('masterClearYearSelect').value;
  const confirmText = document.getElementById('masterClearConfirmInput').value.trim();
  const password = document.getElementById('masterClearPwdInput').value;
  const msgBox = document.getElementById('masterClearMsg');
  if (!year) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'ஆண்டு தேர்வு செய்யவும்'; return; }
  if (confirmText !== 'CLEAR') {
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'உறுதி செய்ய "CLEAR" என சரியாக தட்டச்சு செய்யவும்';
    return;
  }
  if (!password) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'Admin Password கட்டாயம்'; return; }
  const ok = confirm(`${year} ஆண்டுக்கான Master Data முழுவதும் நிரந்தரமாக அழிக்கப்படும். மற்ற ஆண்டுகள் பாதிக்கப்படாது. தொடரவா?`);
  if (!ok) return;
  showLoading(`⏳ ${year} ஆண்டின் Master Data அழிக்கிறது...`);
  try {
    const res = await fetch('/api/admin/master_data/clear', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({year: year, password: password})
    });
    const result = await res.json();
    hideLoading();
    if (result.error) { msgBox.style.color = '#c0392b'; msgBox.textContent = result.error; return; }
    closeModal('modalMasterClear');
    alert(result.message);
    location.reload();
  } catch (e) {
    hideLoading();
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'பிழை: ' + e;
  }
}

// ==================== MASTER ASSIGNING DATA CLEAR ====================
async function openAssignClearModal() {
  document.getElementById('modalAssignClear').style.display = 'flex';
  document.getElementById('assignClearPwdInput').value = '';
  document.getElementById('assignClearMsg').textContent = '';
  const sel = document.getElementById('assignClearYearSelect');
  sel.innerHTML = '<option>-- ஏற்றுகிறது --</option>';
  try {
    const data = await fetch('/api/years/available').then(r => r.json());
    const years = data.years && data.years.length ? data.years : ['2024-2025'];
    sel.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join('');
    sel.value = currentYear && years.includes(currentYear) ? currentYear : years[0];
  } catch (e) {
    sel.innerHTML = `<option value="${currentYear || '2024-2025'}">${currentYear || '2024-2025'}</option>`;
  }
}

async function doAssignDataClear() {
  const year = document.getElementById('assignClearYearSelect').value;
  const password = document.getElementById('assignClearPwdInput').value;
  const msgBox = document.getElementById('assignClearMsg');
  if (!year) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'ஆண்டு தேர்வு செய்யவும்'; return; }
  if (!password) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'Admin Password கட்டாயம்'; return; }
  const ok = confirm(`${year} ஆண்டுக்கான பிரிக்க/அனுப்பு தரவு அனைத்தும் அழிக்கப்பட்டு, Central/Branch Number spool-ம் காலியாகும். தொடரவா?`);
  if (!ok) return;
  showLoading('⏳ Assigning Data அழிக்கிறது...');
  try {
    const res = await fetch('/api/admin/master_data/assign_clear', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({year: year, password: password})
    });
    const result = await res.json();
    hideLoading();
    if (result.error) { msgBox.style.color = '#c0392b'; msgBox.textContent = result.error; return; }
    closeModal('modalAssignClear');
    alert(result.message);
    location.reload();
  } catch (e) {
    hideLoading();
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'பிழை: ' + e;
  }
}

// ==================== MASTER PUBLISHER CLEAR ====================
let pubClearSearchTimeout = null;
let pubClearSelectedVendor = null;
let pubClearSelectedCount = 0;

async function openPublisherClearModal() {
  document.getElementById('modalPublisherClear').style.display = 'flex';
  document.getElementById('pubClearSearchInput').value = '';
  document.getElementById('pubClearSearchStatus').textContent = '';
  document.getElementById('pubClearSearchResults').style.display = 'none';
  document.getElementById('pubClearSearchResults').innerHTML = '';
  document.getElementById('pubClearCountBox').style.display = 'none';
  document.getElementById('pubClearPwdInput').value = '';
  document.getElementById('pubClearMsg').textContent = '';
  document.getElementById('pubClearDeleteBtn').disabled = true;
  pubClearSelectedVendor = null;
  pubClearSelectedCount = 0;

  const sel = document.getElementById('pubClearYearSelect');
  sel.innerHTML = '<option>-- ஏற்றுகிறது --</option>';
  try {
    const data = await fetch('/api/years/available').then(r => r.json());
    const years = data.years && data.years.length ? data.years : ['2024-2025'];
    sel.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join('');
    sel.value = currentYear && years.includes(currentYear) ? currentYear : years[0];
  } catch (e) {
    sel.innerHTML = `<option value="${currentYear || '2024-2025'}">${currentYear || '2024-2025'}</option>`;
  }
  setTimeout(() => document.getElementById('pubClearSearchInput').focus(), 100);
}

function onPubClearYearChange() {
  // ஆண்டு மாறினால், தேர்ந்தெடுத்த பதிப்பகம்/count ரத்து செய்யப்படும் — மீண்டும் தேர்வு செய்யவும்.
  pubClearSelectedVendor = null;
  pubClearSelectedCount = 0;
  document.getElementById('pubClearCountBox').style.display = 'none';
  document.getElementById('pubClearDeleteBtn').disabled = true;
  document.getElementById('pubClearMsg').textContent = '';
}

function onPubClearSearchInput() {
  clearTimeout(pubClearSearchTimeout);
  document.getElementById('pubClearCountBox').style.display = 'none';
  document.getElementById('pubClearDeleteBtn').disabled = true;
  pubClearSelectedVendor = null;
  pubClearSelectedCount = 0;
  document.getElementById('pubClearMsg').textContent = '';
  pubClearSearchTimeout = setTimeout(doPubClearSearch, 300);
}

async function doPubClearSearch() {
  const q = document.getElementById('pubClearSearchInput').value.trim();
  const year = document.getElementById('pubClearYearSelect').value;
  const status = document.getElementById('pubClearSearchStatus');
  const resultsEl = document.getElementById('pubClearSearchResults');
  if (q.length < 4) {
    status.textContent = 'குறைந்தது 4 எழுத்துகள் தட்டச்சு செய்யவும்';
    resultsEl.style.display = 'none';
    return;
  }
  status.textContent = '⏳ தேடுகிறது...';
  try {
    const res = await fetch('/api/publisher_search?q=' + encodeURIComponent(q) + '&year=' + encodeURIComponent(year)).then(r => r.json());
    if (res.error) { status.textContent = res.error; resultsEl.style.display = 'none'; return; }
    if (!res.length) { status.textContent = 'பொருந்தும் பதிப்பகம் இல்லை'; resultsEl.style.display = 'none'; return; }
    status.textContent = `${res.length} பதிப்பகங்கள் கிடைத்தன — ஒன்றைத் தேர்வு செய்யவும்`;
    resultsEl.style.display = 'block';
    resultsEl.innerHTML = res.map(v =>
      `<div onclick="selectPublisherForClear('${escAttr(v)}')" style="padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--border);font-size:0.88rem;" onmouseover="this.style.background='#f0fdfa'" onmouseout="this.style.background=''">${escHtml(v)}</div>`
    ).join('');
  } catch (e) {
    status.textContent = 'பிழை: ' + e;
    resultsEl.style.display = 'none';
  }
}

async function selectPublisherForClear(vendor) {
  pubClearSelectedVendor = vendor;
  document.getElementById('pubClearSearchResults').style.display = 'none';
  document.getElementById('pubClearSearchStatus').textContent = '🏢 ' + vendor;
  const year = document.getElementById('pubClearYearSelect').value;
  const countBox = document.getElementById('pubClearCountBox');
  countBox.style.display = 'block';
  countBox.textContent = '⏳ புத்தகங்கள் எண்ணிக்கை பார்க்கிறது...';
  document.getElementById('pubClearDeleteBtn').disabled = true;
  try {
    const res = await fetch('/api/admin/master_publisher_clear/count?vendor=' + encodeURIComponent(vendor) + '&year=' + encodeURIComponent(year)).then(r => r.json());
    if (res.error) { countBox.textContent = '⚠️ ' + res.error; return; }
    pubClearSelectedCount = res.count;
    if (res.count === 0) {
      countBox.textContent = `🏢 ${vendor} — ${year} ஆண்டில் புத்தகங்கள் இல்லை`;
      document.getElementById('pubClearDeleteBtn').disabled = true;
    } else {
      countBox.textContent = `🏢 ${vendor} — ${year} ஆண்டில் தற்போது மொத்தம் ${res.count} புத்தகங்கள் உள்ளன. இவை அனைத்தும் நீக்கப்படும்.`;
      document.getElementById('pubClearDeleteBtn').disabled = false;
    }
  } catch (e) {
    countBox.textContent = 'பிழை: ' + e;
  }
}

async function doMasterPublisherClear() {
  const msgBox = document.getElementById('pubClearMsg');
  if (!pubClearSelectedVendor) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'பதிப்பகம் தேர்வு செய்யவும்'; return; }
  const year = document.getElementById('pubClearYearSelect').value;
  const password = document.getElementById('pubClearPwdInput').value;
  if (!password) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'Admin Password கட்டாயம்'; return; }
  const ok = confirm(`"${pubClearSelectedVendor}" பதிப்பகத்தின் ${year} ஆண்டுக்குரிய ${pubClearSelectedCount} புத்தகங்களும் நிரந்தரமாக நீக்கப்படும். இதை திரும்பப் பெற முடியாது. தொடரவா?`);
  if (!ok) return;
  showLoading(`⏳ "${pubClearSelectedVendor}" பதிப்பகத்தின் புத்தகங்கள் நீக்குகிறது...`);
  try {
    const res = await fetch('/api/admin/master_publisher_clear', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({vendor: pubClearSelectedVendor, year: year, password: password})
    });
    const result = await res.json();
    hideLoading();
    if (result.error) { msgBox.style.color = '#c0392b'; msgBox.textContent = result.error; return; }
    closeModal('modalPublisherClear');
    alert(result.message);
    location.reload();
  } catch (e) {
    hideLoading();
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'பிழை: ' + e;
  }
}

// ==================== MASTER TITLE CHANGE ====================
let titleChangeSearchTimeout = null;
let titleChangeSelectedTitle = null;
let titleChangeSelectedVendor = null;
let titleChangeSelectedCount = 0;
let titleChangeSelectedBookId = null;
let titleChangeBookIdOptions = [];

function resetTitleChangeBookIdUI() {
  document.getElementById('titleChangeBookIdWrap').style.display = 'none';
  document.getElementById('titleChangeBookIdInput').value = '';
  document.getElementById('titleChangeBookIdInput').style.display = 'block';
  document.getElementById('titleChangeBookIdSelect').style.display = 'none';
  document.getElementById('titleChangeBookIdSelect').innerHTML = '';
  document.getElementById('titleChangeBookIdHint').style.display = 'none';
  titleChangeSelectedBookId = null;
  titleChangeBookIdOptions = [];
}

async function openTitleChangeModal(presetTitle) {
  document.getElementById('modalTitleChange').style.display = 'flex';
  document.getElementById('titleChangeSearchInput').value = presetTitle || '';
  document.getElementById('titleChangeSearchStatus').textContent = '';
  document.getElementById('titleChangeSearchResults').style.display = 'none';
  document.getElementById('titleChangeSearchResults').innerHTML = '';
  document.getElementById('titleChangeVendorWrap').style.display = 'none';
  document.getElementById('titleChangeVendorSelect').innerHTML = '';
  document.getElementById('titleChangeCountBox').style.display = 'none';
  resetTitleChangeBookIdUI();
  document.getElementById('titleChangeNewTitleWrap').style.display = 'none';
  document.getElementById('titleChangeNewTitleInput').value = '';
  document.getElementById('titleChangePwdInput').value = '';
  document.getElementById('titleChangeMsg').textContent = '';
  document.getElementById('titleChangeSaveBtn').disabled = true;
  titleChangeSelectedTitle = null;
  titleChangeSelectedVendor = null;
  titleChangeSelectedCount = 0;
  titleChangeSelectedBookId = null;
  titleChangeBookIdOptions = [];

  const sel = document.getElementById('titleChangeYearSelect');
  sel.innerHTML = '<option>-- ஏற்றுகிறது --</option>';
  try {
    const data = await fetch('/api/years/available').then(r => r.json());
    const years = data.years && data.years.length ? data.years : ['2024-2025'];
    sel.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join('');
    sel.value = currentYear && years.includes(currentYear) ? currentYear : years[0];
  } catch (e) {
    sel.innerHTML = `<option value="${currentYear || '2024-2025'}">${currentYear || '2024-2025'}</option>`;
  }

  if (presetTitle) {
    // கவனிக்க தாவலிலிருந்து வந்தால் — தலைப்பு ஏற்கனவே தெரியும், நேரடியாக பதிப்பக பட்டியலை காட்டு
    document.getElementById('titleChangeSearchStatus').textContent = '📖 ' + presetTitle;
    await selectTitleForChange(presetTitle);
  } else {
    setTimeout(() => document.getElementById('titleChangeSearchInput').focus(), 100);
  }
}

function onTitleChangeYearChange() {
  // ஆண்டு மாறினால், தேர்ந்தெடுத்த தலைப்பு/பதிப்பகம் ரத்து செய்யப்படும் — மீண்டும் தேர்வு செய்யவும்.
  titleChangeSelectedTitle = null;
  titleChangeSelectedVendor = null;
  titleChangeSelectedCount = 0;
  document.getElementById('titleChangeVendorWrap').style.display = 'none';
  document.getElementById('titleChangeCountBox').style.display = 'none';
  resetTitleChangeBookIdUI();
  document.getElementById('titleChangeNewTitleWrap').style.display = 'none';
  document.getElementById('titleChangeSaveBtn').disabled = true;
  document.getElementById('titleChangeMsg').textContent = '';
}

function onTitleChangeSearchInput() {
  clearTimeout(titleChangeSearchTimeout);
  document.getElementById('titleChangeVendorWrap').style.display = 'none';
  document.getElementById('titleChangeCountBox').style.display = 'none';
  resetTitleChangeBookIdUI();
  document.getElementById('titleChangeNewTitleWrap').style.display = 'none';
  document.getElementById('titleChangeSaveBtn').disabled = true;
  titleChangeSelectedTitle = null;
  titleChangeSelectedVendor = null;
  titleChangeSelectedCount = 0;
  document.getElementById('titleChangeMsg').textContent = '';
  titleChangeSearchTimeout = setTimeout(doTitleChangeSearch, 300);
}

async function doTitleChangeSearch() {
  const q = document.getElementById('titleChangeSearchInput').value.trim();
  const year = document.getElementById('titleChangeYearSelect').value;
  const status = document.getElementById('titleChangeSearchStatus');
  const resultsEl = document.getElementById('titleChangeSearchResults');
  if (q.length < 4) {
    status.textContent = 'குறைந்தது 4 எழுத்துகள் தட்டச்சு செய்யவும்';
    resultsEl.style.display = 'none';
    return;
  }
  status.textContent = '⏳ தேடுகிறது...';
  try {
    const res = await fetch('/api/title_search?q=' + encodeURIComponent(q) + '&year=' + encodeURIComponent(year)).then(r => r.json());
    if (res.error) { status.textContent = res.error; resultsEl.style.display = 'none'; return; }
    if (!res.length) { status.textContent = 'பொருந்தும் தலைப்பு இல்லை'; resultsEl.style.display = 'none'; return; }
    status.textContent = `${res.length} தலைப்புகள் கிடைத்தன — ஒன்றைத் தேர்வு செய்யவும்`;
    resultsEl.style.display = 'block';
    resultsEl.innerHTML = res.map(t =>
      `<div onclick="selectTitleForChange('${escAttr(t)}')" style="padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--border);font-size:0.88rem;" onmouseover="this.style.background='#f5f3ff'" onmouseout="this.style.background=''">${escHtml(t)}</div>`
    ).join('');
  } catch (e) {
    status.textContent = 'பிழை: ' + e;
    resultsEl.style.display = 'none';
  }
}

// தலைப்பு தேர்ந்தெடுத்தவுடன் — அந்த தலைப்பை எந்தெந்த பதிப்பகங்கள் கொடுத்துள்ளன
// என்பதன் பட்டியலை காட்டுதல் (ஒரே தலைப்பு வெவ்வேறு பதிப்பகங்களில் இருக்கலாம்).
async function selectTitleForChange(title) {
  titleChangeSelectedTitle = title;
  titleChangeSelectedVendor = null;
  titleChangeSelectedCount = 0;
  document.getElementById('titleChangeSearchResults').style.display = 'none';
  document.getElementById('titleChangeSearchStatus').textContent = '📖 ' + title;
  const year = document.getElementById('titleChangeYearSelect').value;

  const vendorWrap = document.getElementById('titleChangeVendorWrap');
  const vendorSel = document.getElementById('titleChangeVendorSelect');
  const countBox = document.getElementById('titleChangeCountBox');
  resetTitleChangeBookIdUI();
  document.getElementById('titleChangeNewTitleWrap').style.display = 'none';
  document.getElementById('titleChangeSaveBtn').disabled = true;
  countBox.style.display = 'none';
  vendorWrap.style.display = 'block';
  vendorSel.innerHTML = '<option>-- ஏற்றுகிறது --</option>';

  try {
    const res = await fetch('/api/title_vendors?title=' + encodeURIComponent(title) + '&year=' + encodeURIComponent(year)).then(r => r.json());
    if (res.error) { vendorSel.innerHTML = `<option>${res.error}</option>`; return; }
    if (!res.length) { vendorSel.innerHTML = '<option>பதிப்பகம் இல்லை</option>'; return; }
    vendorSel.innerHTML = res.map(v =>
      `<option value="${escAttr(v.vendor_name)}">${escHtml(v.vendor_name)} (${v.count} பிரதிகள்)</option>`
    ).join('');
    // ஒரே ஒரு பதிப்பகம் மட்டும் இருந்தால், தானாகவே தேர்ந்தெடுக்கப்பட்டு count காட்டப்படும்.
    // பல பதிப்பகங்கள் இருந்தால், Admin கைமுறையாக தேர்ந்தெடுக்க வேண்டும்.
    onTitleChangeVendorSelected();
  } catch (e) {
    vendorSel.innerHTML = `<option>பிழை: ${e}</option>`;
  }
}

async function onTitleChangeVendorSelected() {
  const vendorSel = document.getElementById('titleChangeVendorSelect');
  const vendor = vendorSel.value;
  titleChangeSelectedVendor = vendor;
  const year = document.getElementById('titleChangeYearSelect').value;
  const countBox = document.getElementById('titleChangeCountBox');
  document.getElementById('titleChangeNewTitleWrap').style.display = 'none';
  document.getElementById('titleChangeSaveBtn').disabled = true;
  resetTitleChangeBookIdUI();
  if (!vendor) { countBox.style.display = 'none'; return; }

  countBox.style.display = 'block';
  countBox.textContent = '⏳ பிரதிகள் எண்ணிக்கை பார்க்கிறது...';
  try {
    const res = await fetch('/api/admin/master_title_change/count?title=' + encodeURIComponent(titleChangeSelectedTitle) +
      '&vendor=' + encodeURIComponent(vendor) + '&year=' + encodeURIComponent(year)).then(r => r.json());
    if (res.error) { countBox.textContent = '⚠️ ' + res.error; return; }
    titleChangeBookIdOptions = res.book_ids || [];

    if (res.total_count === 0) {
      countBox.textContent = `📖 "${titleChangeSelectedTitle}" (${vendor}) — ${year} ஆண்டில் பிரதிகள் இல்லை`;
      return;
    }

    const distinctBookIds = titleChangeBookIdOptions.filter(b => b.book_id);

    if (distinctBookIds.length > 1) {
      // ஒன்றுக்கும் மேற்பட்ட Book Id — Admin ஒன்றை கட்டாயம் தேர்ந்தெடுக்க வேண்டும்.
      countBox.textContent = `📖 "${titleChangeSelectedTitle}" — பதிப்பகம்: ${vendor} — ${year} ஆண்டில் மொத்தம் ${res.total_count} பிரதிகள் (${distinctBookIds.length} வெவ்வேறு Book Id-களில்). கீழே ஒரு Book Id-ஐ தேர்ந்தெடுக்கவும்.`;

      const bookIdWrap = document.getElementById('titleChangeBookIdWrap');
      const bookIdInput = document.getElementById('titleChangeBookIdInput');
      const bookIdSelect = document.getElementById('titleChangeBookIdSelect');
      const bookIdHint = document.getElementById('titleChangeBookIdHint');
      bookIdInput.style.display = 'none';
      bookIdSelect.style.display = 'block';
      bookIdHint.style.display = 'block';
      bookIdSelect.innerHTML = '<option value="">-- Book Id தேர்ந்தெடுக்கவும் --</option>' +
        distinctBookIds.map(b => `<option value="${escAttr(b.book_id)}">${escHtml(b.book_id)} (${b.count} பிரதிகள்)</option>`).join('');
      bookIdWrap.style.display = 'block';
    } else {
      // ஒரே ஒரு Book Id (அல்லது Book Id இல்லை) — நேரடியாக தொடரலாம்.
      titleChangeSelectedCount = res.total_count;
      titleChangeSelectedBookId = distinctBookIds.length === 1 ? distinctBookIds[0].book_id : null;
      countBox.textContent = `📖 "${titleChangeSelectedTitle}" — பதிப்பகம்: ${vendor} — ${year} ஆண்டில் தற்போது மொத்தம் ${res.total_count} பிரதிகள் உள்ளன. இவை மட்டும் புதுப்பிக்கப்படும்.`;

      const bookIdWrap = document.getElementById('titleChangeBookIdWrap');
      const bookIdInput = document.getElementById('titleChangeBookIdInput');
      bookIdInput.style.display = 'block';
      document.getElementById('titleChangeBookIdSelect').style.display = 'none';
      bookIdInput.value = titleChangeSelectedBookId || 'இல்லை';
      bookIdWrap.style.display = 'block';

      document.getElementById('titleChangeNewTitleInput').value = titleChangeSelectedTitle;
      document.getElementById('titleChangeNewTitleWrap').style.display = 'block';
      document.getElementById('titleChangeSaveBtn').disabled = false;
    }
  } catch (e) {
    countBox.textContent = 'பிழை: ' + e;
  }
}

// Admin பல Book Id-களில் இருந்து ஒன்றை தேர்ந்தெடுத்தவுடன் — அதற்குரிய
// பிரதிகள் எண்ணிக்கை காட்டி, "புதிய தலைப்பு" உள்ளீட்டை செயல்படுத்துதல்.
async function onTitleChangeBookIdSelected() {
  const bookIdSelect = document.getElementById('titleChangeBookIdSelect');
  const bookId = bookIdSelect.value;
  const countBox = document.getElementById('titleChangeCountBox');
  const year = document.getElementById('titleChangeYearSelect').value;
  document.getElementById('titleChangeNewTitleWrap').style.display = 'none';
  document.getElementById('titleChangeSaveBtn').disabled = true;
  titleChangeSelectedBookId = null;
  titleChangeSelectedCount = 0;
  if (!bookId) return;

  try {
    const res = await fetch('/api/admin/master_title_change/count?title=' + encodeURIComponent(titleChangeSelectedTitle) +
      '&vendor=' + encodeURIComponent(titleChangeSelectedVendor) + '&year=' + encodeURIComponent(year) +
      '&book_id=' + encodeURIComponent(bookId)).then(r => r.json());
    if (res.error) { countBox.textContent = '⚠️ ' + res.error; return; }
    titleChangeSelectedBookId = bookId;
    titleChangeSelectedCount = res.count;
    countBox.textContent = `📖 "${titleChangeSelectedTitle}" — பதிப்பகம்: ${titleChangeSelectedVendor} — Book Id: ${bookId} — ${year} ஆண்டில் ${res.count} பிரதிகள் உள்ளன. இவை மட்டும் புதுப்பிக்கப்படும்.`;
    document.getElementById('titleChangeNewTitleInput').value = titleChangeSelectedTitle;
    document.getElementById('titleChangeNewTitleWrap').style.display = 'block';
    document.getElementById('titleChangeSaveBtn').disabled = false;
  } catch (e) {
    countBox.textContent = 'பிழை: ' + e;
  }
}

async function doMasterTitleChange() {
  const msgBox = document.getElementById('titleChangeMsg');
  if (!titleChangeSelectedTitle) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'தலைப்பு தேர்வு செய்யவும்'; return; }
  if (!titleChangeSelectedVendor) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'பதிப்பகம் தேர்வு செய்யவும்'; return; }
  if (titleChangeBookIdOptions.filter(b => b.book_id).length > 1 && !titleChangeSelectedBookId) {
    msgBox.style.color = '#c0392b'; msgBox.textContent = 'Book Id தேர்வு செய்யவும்'; return;
  }
  const year = document.getElementById('titleChangeYearSelect').value;
  const newTitle = document.getElementById('titleChangeNewTitleInput').value.trim();
  const password = document.getElementById('titleChangePwdInput').value;
  if (!newTitle) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'புதிய தலைப்பு கட்டாயம்'; return; }
  if (!password) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'Admin Password கட்டாயம்'; return; }
  if (newTitle === titleChangeSelectedTitle) {
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'புதிய தலைப்பு, தற்போதைய தலைப்பை விட வேறுபட்டதாக இருக்க வேண்டும்';
    return;
  }
  const bookIdNote = titleChangeSelectedBookId ? ` — Book Id: ${titleChangeSelectedBookId}` : '';
  const ok = confirm(`"${titleChangeSelectedTitle}" (பதிப்பகம்: ${titleChangeSelectedVendor}${bookIdNote}) — ${year} ஆண்டுக்குரிய ${titleChangeSelectedCount} பிரதிகளும் "${newTitle}" எனப் புதுப்பிக்கப்படும். மற்ற Book Id / பதிப்பகங்களின் அதே தலைப்பு பாதிக்கப்படாது. தொடரவா?`);
  if (!ok) return;
  showLoading(`⏳ ${titleChangeSelectedCount} பிரதிகளும் புதுப்பிக்கிறது...`);
  try {
    const res = await fetch('/api/admin/master_title_change', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({old_title: titleChangeSelectedTitle, vendor: titleChangeSelectedVendor, book_id: titleChangeSelectedBookId || '', new_title: newTitle, year: year, password: password})
    });
    const result = await res.json();
    hideLoading();
    if (result.error) { msgBox.style.color = '#c0392b'; msgBox.textContent = result.error; return; }
    closeModal('modalTitleChange');
    alert(result.message);
    location.reload();
  } catch (e) {
    hideLoading();
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'பிழை: ' + e;
  }
}

// ==================== கடவுச்சொல் மாற்ற (Admin மட்டும்) ====================
function openChangePwdModal() {
  document.getElementById('pwdUserSelect').value = 'admin';
  document.getElementById('pwdNewInput').value = '';
  document.getElementById('pwdConfirmInput').value = '';
  document.getElementById('pwdChangeMsg').textContent = '';
  document.getElementById('modalChangePwd').style.display = 'flex';
}

async function saveChangePassword() {
  const username = document.getElementById('pwdUserSelect').value;
  const newPwd = document.getElementById('pwdNewInput').value;
  const confirmPwd = document.getElementById('pwdConfirmInput').value;
  const msgBox = document.getElementById('pwdChangeMsg');

  if (newPwd.length < 6) {
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'Password குறைந்தது 6 எழுத்துக்கள் இருக்க வேண்டும்';
    return;
  }
  if (newPwd !== confirmPwd) {
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'இரண்டு password-களும் ஒத்துப்போகவில்லை';
    return;
  }

  showLoading('⏳ Password மாற்றுகிறது...');
  try {
    const res = await fetch('/api/admin/change_password', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: username, new_password: newPwd})
    });
    const result = await res.json();
    hideLoading();
    if (result.error) {
      msgBox.style.color = '#c0392b';
      msgBox.textContent = result.error;
      return;
    }
    closeModal('modalChangePwd');
    alert(result.message);
  } catch (e) {
    hideLoading();
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'Server பிழை: ' + e;
  }
}

// ==================== நூலகர் பார்வை ஆண்டு (Admin) ====================
async function openLibrarianYearModal() {
  document.getElementById('librarianYearMsg').textContent = '';
  const sel = document.getElementById('librarianYearSelect');
  sel.innerHTML = '<option>ஏற்றுகிறது...</option>';
  document.getElementById('modalLibrarianYear').style.display = 'flex';
  try {
    const data = await fetch('/api/years/librarian_view').then(r => r.json());
    const years = data.years || ['2024-2025'];
    sel.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join('');
    sel.value = data.active_year;
  } catch (e) {
    sel.innerHTML = '<option value="2024-2025">2024-2025</option>';
  }
}

async function saveLibrarianYear() {
  const year = document.getElementById('librarianYearSelect').value;
  const msgBox = document.getElementById('librarianYearMsg');
  showLoading('⏳ சேமிக்கிறது...');
  try {
    const res = await fetch('/api/years/librarian_view', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ year })
    });
    const result = await res.json();
    hideLoading();
    if (result.error) {
      msgBox.style.color = '#c0392b';
      msgBox.textContent = result.error;
      return;
    }
    msgBox.style.color = '#16a34a';
    msgBox.textContent = `✅ நூலகர் இப்போது ${year} ஆண்டைத்தான் பார்ப்பார்.`;
    toast('✅ நூலகர் பார்வை ஆண்டு: ' + year, 'success');
  } catch (e) {
    hideLoading();
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'Server பிழை: ' + e;
  }
}

// ==================== Excel Upload (Admin) ====================
async function openUploadExcelModal() {
  document.getElementById('uploadExcelFile').value = '';
  document.getElementById('uploadExcelMsg').textContent = '';
  const yearSel = document.getElementById('uploadExcelYear');
  try {
    const data = await fetch('/api/years/available').then(r => r.json());
    const years = data.years || ['2024-2025'];
    // அடுத்த புதிய ஆண்டையும் ஒரு option-ஆக சேர்க்க (இன்னும் data இல்லாத ஆண்டு)
    yearSel.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join('');
  } catch (e) {
    yearSel.innerHTML = '<option value="2024-2025">2024-2025</option>';
  }
  document.getElementById('modalUploadExcel').style.display = 'flex';
}

async function onUploadExcelFileChange() {
  const f = document.getElementById('uploadExcelFile').files[0];
  if (!f) return;
  try {
    const res = await fetch('/api/admin/upload_excel/detect_year', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ filename: f.name })
    }).then(r => r.json());
    const msgBox = document.getElementById('uploadExcelMsg');
    if (res.year) {
      const yearSel = document.getElementById('uploadExcelYear');
      if (![...yearSel.options].some(o => o.value === res.year)) {
        yearSel.insertAdjacentHTML('afterbegin', `<option value="${res.year}">${res.year}</option>`);
      }
      yearSel.value = res.year;
      msgBox.style.color = '#16a34a';
      msgBox.textContent = `✅ கோப்பு பெயரில் இருந்து ஆண்டு கண்டறியப்பட்டது: ${res.year}`;
    } else {
      msgBox.style.color = '#b45309';
      msgBox.textContent = '⚠️ கோப்பு பெயரில் ஆண்டு கிடைக்கவில்லை — கீழே சரியான ஆண்டைத் தேர்ந்தெடுக்கவும்.';
    }
  } catch (e) { /* ignore — கீழே manual-ஆக ஆண்டு தேர்ந்தெடுக்கலாம் */ }
}

async function doUploadExcel() {
  const f = document.getElementById('uploadExcelFile').files[0];
  const year = document.getElementById('uploadExcelYear').value;
  const msgBox = document.getElementById('uploadExcelMsg');
  if (!f) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'கோப்பை தேர்ந்தெடுக்கவும்'; return; }

  const formData = new FormData();
  formData.append('file', f);
  formData.append('year', year);

  showLoading('⏳ Excel அப்லோட் செய்கிறது...');
  try {
    const res = await fetch('/api/admin/upload_excel', { method: 'POST', body: formData });
    const result = await res.json();
    hideLoading();
    if (result.error) {
      msgBox.style.color = '#c0392b';
      msgBox.textContent = result.error;
      return;
    }
    msgBox.style.color = '#16a34a';
    msgBox.textContent = '✅ ' + result.message;
    toast('✅ ' + result.message, 'success');
    await initYearSelector();
    updateLiveTicker();
  } catch (e) {
    hideLoading();
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'Server பிழை: ' + e;
  }
}

// ==================== மாநிலப் பதிவெண் Bulk Update (Admin) ====================
function openUploadStateAccModal() {
  document.getElementById('uploadStateAccFile').value = '';
  document.getElementById('uploadStateAccMsg').textContent = '';
  document.getElementById('modalUploadStateAcc').style.display = 'flex';
}

async function doUploadStateAcc() {
  const f = document.getElementById('uploadStateAccFile').files[0];
  const msgBox = document.getElementById('uploadStateAccMsg');
  if (!f) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'கோப்பை தேர்ந்தெடுக்கவும்'; return; }

  const formData = new FormData();
  formData.append('file', f);

  showLoading('⏳ மாநிலப் பதிவெண் புதுப்பிக்கப்படுகிறது...');
  try {
    const res = await fetch('/api/admin/upload_state_acc_update', { method: 'POST', body: formData });
    const result = await res.json();
    hideLoading();
    if (result.error) {
      msgBox.style.color = '#c0392b';
      msgBox.textContent = result.error;
      return;
    }
    msgBox.style.color = '#16a34a';
    msgBox.textContent = '✅ ' + result.message;
    toast('✅ ' + result.message, 'success');
    updateLiveTicker();
  } catch (e) {
    hideLoading();
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'Server பிழை: ' + e;
  }
}

// ==================== BOOK COVER — VIEW (எல்லோருக்கும்) ====================
function viewBookCover(bookId, title) {
  document.getElementById('bookCoverViewTitle').textContent = title || '';
  document.getElementById('bookCoverViewImg').src = '/api/book_cover/' + encodeURIComponent(bookId) + '?t=' + Date.now();
  document.getElementById('modalBookCoverView').style.display = 'flex';
}

// ==================== BOOK COVER — UPLOAD (Admin மட்டும்) ====================
let bookCoverDropdownItems = [];   // "ஒரே தலைப்பில் வேறு விலை" quick-pick dropdown
let selectedBookCoverItem = null;  // தற்போது தேர்ந்தெடுக்கப்பட்ட புத்தகம் (search அல்லது dropdown எதிலிருந்தும்)
let bookCoverSearchTimeout = null;

async function openBookCoverUploadModal() {
  document.getElementById('bookCoverUploadMsg').textContent = '';
  document.getElementById('bookCoverUploadFile').value = '';
  document.getElementById('bookCoverSearchInput').value = '';
  document.getElementById('bookCoverSearchStatus').textContent = '';
  document.getElementById('bookCoverSearchResults').innerHTML = '';
  const titleBox = document.getElementById('bookCoverUploadTitle');
  titleBox.style.display = 'none';
  titleBox.innerHTML = '';
  selectedBookCoverItem = null;

  const sel = document.getElementById('bookCoverBookIdSelect');
  sel.innerHTML = '<option value="">ஏற்றுகிறது...</option>';
  document.getElementById('modalBookCoverUpload').style.display = 'flex';
  try {
    bookCoverDropdownItems = await fetch('/api/admin/multi_price_book_ids?year=' + encodeURIComponent(currentYear)).then(r => r.json());
    if (!bookCoverDropdownItems.length) {
      sel.innerHTML = '<option value="">ஒரே தலைப்பில் வேறு விலை உள்ள Book Id எதுவும் இல்லை</option>';
      return;
    }
    sel.innerHTML = '<option value="">-- Book Id தேர்ந்தெடுக்கவும் --</option>' +
      bookCoverDropdownItems.map(it =>
        `<option value="${escAttr(it.bookId)}">${escHtml(it.bookId)} — ${escHtml((it.title||'').substring(0,40))} (₹${escHtml(it.price)})${it.hasCover ? ' ✅' : ''}</option>`
      ).join('');
  } catch (e) {
    sel.innerHTML = '<option value="">பிழை — மீண்டும் முயற்சிக்கவும்</option>';
  }
}

// "பிரிக்க" தேடல் அட்டவணையில் இருந்து நேரடியாக ஒரு குறிப்பிட்ட Book Id-க்கு
// முகப்புப் படம் ஏற்ற/மாற்ற — Modal-ஐ அந்த புத்தகம் ஏற்கனவே தேர்ந்தெடுக்கப்பட்ட
// நிலையில் திறக்கும் (மீண்டும் தேட வேண்டியதில்லை).
async function openBookCoverUploadModalFor(bookId, title, vendor, price, hasCover) {
  await openBookCoverUploadModal();
  selectedBookCoverItem = { bookId, title, vendor, price, hasCover };
  document.getElementById('bookCoverBookIdSelect').value = '';
  document.getElementById('bookCoverSearchInput').value = '';
  _showSelectedBookCoverItem();
}

function _showSelectedBookCoverItem() {
  const titleBox = document.getElementById('bookCoverUploadTitle');
  const item = selectedBookCoverItem;
  if (!item) { titleBox.style.display = 'none'; titleBox.innerHTML = ''; return; }
  titleBox.style.display = 'block';
  titleBox.innerHTML = `📖 <strong>${escHtml(item.title)}</strong> (Book Id: ${escHtml(item.bookId)}) — பதிப்பகம்: ${escHtml(item.vendor || '—')} — விலை: ₹${escHtml(item.price)}` +
    (item.hasCover ? ' <span style="color:#16a34a;">(ஏற்கனவே படம் உள்ளது — புதிதாக அப்லோட் செய்தால் மாற்றப்படும்)</span>' : '');
}

// ---- வழி 1: Book Id / தலைப்பு தேடி தேர்வு (எந்த புத்தகமும்) ----
function onBookCoverSearchInput() {
  clearTimeout(bookCoverSearchTimeout);
  bookCoverSearchTimeout = setTimeout(doBookCoverSearch, 300);
}

async function doBookCoverSearch() {
  const q = document.getElementById('bookCoverSearchInput').value.trim();
  const status = document.getElementById('bookCoverSearchStatus');
  const results = document.getElementById('bookCoverSearchResults');
  if (q.length < 2) { status.textContent = ''; results.innerHTML = ''; return; }
  status.innerHTML = '<span class="loading"><span class="spinner"></span> தேடுகிறது...</span>';
  try {
    const items = await fetch('/api/admin/search_book_for_cover?q=' + encodeURIComponent(q) + '&year=' + encodeURIComponent(currentYear)).then(r => r.json());
    if (!items.length) {
      status.textContent = 'பொருந்தும் புத்தகம் இல்லை';
      results.innerHTML = '';
      return;
    }
    status.textContent = `${items.length} புத்தகங்கள் கிடைத்தன — ஒன்றைத் தேர்வு செய்யவும்`;
    results.innerHTML = items.map((it, i) =>
      `<div data-idx="${i}" onclick="selectBookCoverSearchResult(${i})" style="padding:8px 10px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px;cursor:pointer;font-size:0.85rem;">
        <div style="font-weight:600;">${escHtml(it.title)} ${it.hasCover ? '✅' : ''}</div>
        <div style="color:var(--muted);">Book Id: ${escHtml(it.bookId)} • பதிப்பகம்: ${escHtml(it.vendor || '—')} • ₹${escHtml(it.price)}</div>
      </div>`
    ).join('');
    window._bookCoverSearchItems = items;
  } catch (e) {
    status.textContent = 'தேடலில் பிழை';
    results.innerHTML = '';
  }
}

function selectBookCoverSearchResult(idx) {
  const item = (window._bookCoverSearchItems || [])[idx];
  if (!item) return;
  selectedBookCoverItem = item;
  document.getElementById('bookCoverBookIdSelect').value = '';   // dropdown-ல் இருந்தால் அதை clear செய்
  document.getElementById('bookCoverUploadMsg').textContent = '';
  _showSelectedBookCoverItem();
}

// ---- வழி 2: "ஒரே தலைப்பில் வேறு விலை" quick-pick dropdown ----
function onBookCoverBookIdChange() {
  const bookId = document.getElementById('bookCoverBookIdSelect').value;
  document.getElementById('bookCoverUploadMsg').textContent = '';
  if (!bookId) { selectedBookCoverItem = null; _showSelectedBookCoverItem(); return; }
  const item = bookCoverDropdownItems.find(it => it.bookId === bookId);
  if (item) {
    selectedBookCoverItem = item;
    // dropdown-ல் தேர்வு செய்தால், search box-ஐ clear செய்
    document.getElementById('bookCoverSearchInput').value = '';
    document.getElementById('bookCoverSearchResults').innerHTML = '';
    document.getElementById('bookCoverSearchStatus').textContent = '';
    _showSelectedBookCoverItem();
  }
}

async function doUploadBookCover() {
  const item = selectedBookCoverItem;
  const f = document.getElementById('bookCoverUploadFile').files[0];
  const msgBox = document.getElementById('bookCoverUploadMsg');

  if (!item || !item.bookId) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'மேலே ஒரு புத்தகத்தை தேடி அல்லது பட்டியலில் தேர்ந்தெடுக்கவும்'; return; }
  if (!f) { msgBox.style.color = '#c0392b'; msgBox.textContent = 'முகப்புப் படத்தை தேர்ந்தெடுக்கவும்'; return; }

  const ext = f.name.substring(f.name.lastIndexOf('.')).toLowerCase();
  if (!['.jpg', '.jpeg', '.jfif'].includes(ext)) {
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'jpg / jpeg / jfif படங்கள் மட்டுமே அனுமதிக்கப்படும்';
    return;
  }

  const formData = new FormData();
  formData.append('book_id', item.bookId);
  formData.append('title', item.title || '');
  formData.append('file', f);

  showLoading('⏳ முகப்புப் படம் அப்லோட் செய்கிறது...');
  try {
    const res = await fetch('/api/admin/book_cover/upload', { method: 'POST', body: formData });
    const result = await res.json();
    hideLoading();
    if (result.error) {
      msgBox.style.color = '#c0392b';
      msgBox.textContent = result.error;
      return;
    }
    msgBox.style.color = '#16a34a';
    msgBox.textContent = '✅ ' + result.message;
    toast('✅ ' + result.message, 'success');
    item.hasCover = true;
    _showSelectedBookCoverItem();
  } catch (e) {
    hideLoading();
    msgBox.style.color = '#c0392b';
    msgBox.textContent = 'Server பிழை: ' + e;
  }
}

// ==================== ISBN → இணையம் மூலம் தலைப்பு தேடு ====================
function openIsbnLookupModal() {
  document.getElementById('isbnLookupInput').value = '';
  document.getElementById('isbnLookupStatus').textContent = '';
  document.getElementById('isbnLookupResult').style.display = 'none';
  document.getElementById('isbnLookupResult').innerHTML = '';
  document.getElementById('modalIsbnLookup').style.display = 'flex';
  setTimeout(() => document.getElementById('isbnLookupInput').focus(), 100);
}

async function searchIsbnOnline() {
  const raw = document.getElementById('isbnLookupInput').value.trim();
  const isbn = raw.replace(/[-\s]/g, '');
  const statusEl = document.getElementById('isbnLookupStatus');
  const resultEl = document.getElementById('isbnLookupResult');
  resultEl.style.display = 'none';
  resultEl.innerHTML = '';
  if (!isbn) { statusEl.textContent = 'ISBN எண்ணை கொடுக்கவும்'; return; }
  statusEl.innerHTML = '<span class="loading"><span class="spinner"></span> இணையத்தில் தேடுகிறது...</span>';

  function showResult(title, authors, publisher, pubDate, source) {
    statusEl.textContent = '';
    resultEl.innerHTML = `
      <div><strong>📖 தலைப்பு:</strong> ${escHtml(title || '—')}</div>
      <div><strong>✍️ ஆசிரியர்:</strong> ${escHtml(authors || '—')}</div>
      <div><strong>🏢 பதிப்பகம்:</strong> ${escHtml(publisher || '—')}</div>
      <div><strong>📅 பதிப்பு தேதி:</strong> ${escHtml(pubDate || '—')}</div>
      <div style="margin-top:6px;font-size:0.78rem;color:#0f766e;">மூலம்: ${escHtml(source)}</div>
    `;
    resultEl.style.display = 'block';
  }

  function showNotFound() {
    statusEl.innerHTML = '';
    resultEl.style.display = 'block';
    resultEl.style.background = '#fff7ed';
    resultEl.style.borderColor = '#ea580c';
    resultEl.innerHTML = `
      <div>❌ இந்த ISBN-க்கு Google Books / Open Library இரண்டிலும் விவரம் கிடைக்கவில்லை
      (சில Indian பதிப்பக புத்தகங்கள் இந்த தரவுத்தளங்களில் பதிவு செய்யப்படாமல் இருக்கலாம்).</div>
      <div style="margin-top:8px;">
        <a href="https://www.google.com/search?q=${encodeURIComponent(isbn)}" target="_blank" style="color:#0d9488;font-weight:600;">🔍 Google-ல் நேரடியாக தேட (புதிய tab)</a>
      </div>
    `;
  }

  // 1) Google Books
  try {
    const data = await fetch('https://www.googleapis.com/books/v1/volumes?q=isbn:' + encodeURIComponent(isbn) + '&key=' + GOOGLE_BOOKS_API_KEY).then(r => r.json());
    const item = (data.items && data.items[0]) ? data.items[0].volumeInfo : null;
    if (item) {
      const title = item.title ? (item.subtitle ? item.title + ' — ' + item.subtitle : item.title) : '—';
      showResult(title, (item.authors || []).join(', '), item.publisher, item.publishedDate, 'Google Books');
      return;
    }
  } catch(e) { /* Google Books தோல்வி — Open Library-ஐ முயற்சி செய்ய தொடரும் */ }

  // 2) Open Library (fallback)
  try {
    const olData = await fetch(
      'https://openlibrary.org/api/books?bibkeys=ISBN:' + encodeURIComponent(isbn) + '&format=json&jscmd=data',
      { headers: { 'Accept': 'application/json' } }
    ).then(r => r.json());
    const key = 'ISBN:' + isbn;
    const book = olData[key];
    if (book) {
      const authors = (book.authors || []).map(a => a.name).join(', ');
      const publisher = (book.publishers || []).map(p => p.name).join(', ');
      showResult(book.title, authors, publisher, book.publish_date, 'Open Library');
      return;
    }
  } catch(e) { /* Open Library-உம் தோல்வி — கீழே "கிடைக்கவில்லை" காட்டப்படும் */ }

  showNotFound();
}

// ==================== தவறான பதிவு நீக்கம் (RECLAIM) ====================
let reclaimSearchTimeout = null;
let reclaimCurrentRows = [];

async function loadReclaimPoolStatus() {
  const el = document.getElementById('reclaimPoolStatus');
  el.textContent = 'ஏற்றுகிறது...';
  try {
    const data = await fetch('/api/reclaim/pool_status?year=' + encodeURIComponent(currentYear)).then(r => r.json());
    const parts = [];
    if (data.central && data.central.length) {
      parts.push(`<div>🔢 <strong>மைய நூலக எண்கள்</strong> (${data.central.length}) — அனைத்து நூலகங்களுக்கும் பொருந்தும்: ${data.central.join(', ')}</div>`);
    } else {
      parts.push('<div>🔢 மைய நூலக எண்கள் pool-ல் இல்லை.</div>');
    }
    if (data.branch && data.branch.length) {
      parts.push('<div style="margin-top:6px;">🏷️ <strong>கிளை நூலக எண்கள்</strong> (நூலகம் வாரியாக):<br>' +
        data.branch.map(b => `&nbsp;&nbsp;${escHtml(b.library_name_tm)} — ${b.numbers.join(', ')}`).join('<br>') + '</div>');
    } else {
      parts.push('<div style="margin-top:6px;">🏷️ கிளை நூலக எண்கள் pool-ல் இல்லை.</div>');
    }
    el.innerHTML = parts.join('');
  } catch (e) {
    el.textContent = 'பிழை ஏற்பட்டது';
  }
}

function onReclaimSearch() {
  clearTimeout(reclaimSearchTimeout);
  reclaimSearchTimeout = setTimeout(doReclaimSearch, 300);
}

async function doReclaimSearch() {
  const q = document.getElementById('reclaimSearchInput').value.trim();
  const tbody = document.getElementById('reclaimSearchBody');
  if (q.length < 2) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state"><div class="icon">📖</div><div>தேட ஆரம்பிக்கவும்...</div></div></td></tr>';
    document.getElementById('reclaimSearchStatus').textContent = '';
    return;
  }
  document.getElementById('reclaimSearchStatus').innerHTML = '<span class="loading"><span class="spinner"></span> தேடுகிறது...</span>';
  const data = await fetch('/api/reclaim/search?q=' + encodeURIComponent(q)).then(r => r.json());
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state"><div class="icon">🔍</div><div>பிரிக்கப்பட்ட முடிவுகள் இல்லை</div></div></td></tr>';
    document.getElementById('reclaimSearchStatus').textContent = '';
    return;
  }
  document.getElementById('reclaimSearchStatus').textContent = `${data.length} தலைப்புகள் கிடைத்தன`;
  tbody.innerHTML = data.map((r, i) => `
    <tr onclick="loadReclaimRows('${escAttr(r.title)}','${escAttr(r.price)}')" style="cursor:pointer;">
      <td data-label="#">${i + 1}</td>
      <td data-label="தலைப்பு" style="font-weight:500;">${escHtml(r.title)}</td>
      <td data-label="பதிப்பகம்">${escHtml(r.vendor)}</td>
      <td data-label="விலை">₹${escHtml(r.price)}</td>
      <td data-label="பிரிக்கப்பட்ட எண்ணிக்கை"><span class="badge badge-teal">${r.count}</span></td>
    </tr>`).join('');
}

async function loadReclaimRows(title, price) {
  showLoading('⏳ ஏற்றுகிறது...');
  try {
    const data = await fetch(`/api/reclaim/rows?title=${encodeURIComponent(title)}&price=${encodeURIComponent(price)}&year=${encodeURIComponent(currentYear)}`).then(r => r.json());
    hideLoading();
    reclaimCurrentRows = data;
    document.getElementById('reclaimRowsTitle').textContent = `📋 ${title} (₹${price}) — பிரிக்கப்பட்ட நூலகங்கள்`;
    const tbody = document.getElementById('reclaimRowsBody');
    tbody.innerHTML = data.map((r, i) => `
      <tr>
        <td><input type="checkbox" class="reclaimRowCb" value="${r.id}" onchange="updateReclaimCount()"></td>
        <td data-label="வ.எண்">${i + 1}</td>
        <td data-label="நூலகம் பெயர்">${escHtml(r.library_name_tm)}</td>
        <td data-label="மைய நூலக சேர்க்கை எண்" style="text-align:center;">${r.central_number ?? '—'}</td>
        <td data-label="கிளை நூலக சேர்க்கை எண்" style="text-align:center;">${r.branch_number ?? '—'}</td>
        <td data-label="Set">${escHtml(r.set_number)}</td>
        <td data-label="அனுப்பப்பட்டதா">${r.sent ? '✅ ஆம்' : '⏳ இல்லை'}</td>
      </tr>`).join('');
    document.getElementById('reclaimSelectAll').checked = false;
    updateReclaimCount();
    document.getElementById('reclaimRowsSection').style.display = 'block';
  } catch (e) {
    hideLoading();
    toast('❌ பிழை: ' + e, 'error');
  }
}

function toggleReclaimSelectAll() {
  const checked = document.getElementById('reclaimSelectAll').checked;
  document.querySelectorAll('.reclaimRowCb').forEach(cb => cb.checked = checked);
  updateReclaimCount();
}

function updateReclaimCount() {
  const cnt = document.querySelectorAll('.reclaimRowCb:checked').length;
  document.getElementById('reclaimCheckCount').textContent = cnt + ' தேர்வு';
}

async function reclaimSelected() {
  const ids = [...document.querySelectorAll('.reclaimRowCb:checked')].map(cb => parseInt(cb.value));
  if (!ids.length) { toast('குறைந்தது ஒரு வரியை தேர்ந்தெடுக்கவும்!', 'error'); return; }
  const ok = confirm(`${ids.length} வரிகளை மீளப்பெற (Reclaim) செய்யவா? இவை மறுபடியும் 'பிரிக்க' பட்டியலில் unassigned-ஆக தெரியும்.`);
  if (!ok) return;
  showLoading('⏳ மீளப்பெறுகிறது...');
  try {
    const res = await fetch('/api/reclaim/execute', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ ids, year: currentYear })
    }).then(r => r.json());
    hideLoading();
    if (res.success) {
      toast('✅ ' + res.message, 'success');
      document.getElementById('reclaimRowsSection').style.display = 'none';
      doReclaimSearch();
      loadReclaimPoolStatus();
      updateLiveTicker();
    } else {
      toast('❌ ' + res.error, 'error');
    }
  } catch (e) {
    hideLoading();
    toast('❌ பிழை: ' + e, 'error');
  }
}

// வேறு மாவட்ட DB-ல் இருந்து (Dindigul) முகப்புப் படங்களை தலைப்பு பொருத்தி இறக்குமதி
async function _postJsonSafe(url, body) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const text = await resp.text();
  try {
    return JSON.parse(text);
  } catch (e) {
    return { error: 'Server சரியான பதில் தரவில்லை (HTTP ' + resp.status + '). Render Logs-ஐப் பார்க்கவும்; வேலை நடுவில் நின்றிருக்கலாம் — மீண்டும் "இறக்குமதி செய்" அழுத்தினால் மீதமுள்ளவை தொடரும்.' };
  }
}

async function runCoverImport(dryRun) {
  const url = document.getElementById('coverImportSourceUrl').value.trim();
  const overwrite = document.getElementById('coverImportOverwrite').checked;
  const box = document.getElementById('coverImportMsg');
  if (!url) { box.style.color = '#c0392b'; box.textContent = 'Dindigul DB-ன் Database URL-ஐ உள்ளிடவும்'; return; }
  if (!dryRun && !confirm('பொருந்தும் முகப்புப் படங்களை இந்த DB-ல் சேர்க்கலாமா?')) return;

  showLoading(dryRun ? '⏳ சரிபார்க்கிறது...' : '⏳ படங்களை இறக்குமதி செய்கிறது...');
  try {
    let r = await _postJsonSafe('/api/admin/book_covers/import_from_db',
      { source_url: url, dry_run: dryRun, overwrite, offset: 0 });
    if (r.error) { hideLoading(); box.style.color = '#c0392b'; box.textContent = r.error; return; }

    const first = r;                 // முதல் அழைப்பின் புள்ளிவிவரம் (பொருந்தியவை போன்றவை)
    let totalApplied = r.applied || 0;
    let guard = 0;
    while (!dryRun && r.next_offset !== null && r.next_offset !== undefined && guard < 500) {
      guard++;
      showLoading('⏳ படங்களை இறக்குமதி செய்கிறது... (' + r.next_offset + ' / ' + r.plan_total + ')');
      r = await _postJsonSafe('/api/admin/book_covers/import_from_db',
        { source_url: url, dry_run: false, overwrite, offset: r.next_offset });
      if (r.error) {
        hideLoading();
        box.style.color = '#c0392b';
        box.textContent = r.error + ' (இதுவரை சேர்க்கப்பட்டவை: ' + totalApplied + ')';
        return;
      }
      totalApplied += r.applied || 0;
    }
    hideLoading();

    const list = (arr) => arr && arr.length
      ? '<br><span style="color:#6b7280;">' + arr.map(x => escHtml(String(x || '').substring(0, 50))).join(' • ') + '</span>' : '';
    box.style.color = '#1e293b';
    box.innerHTML =
      (dryRun ? '🔍 <b>சரிபார்ப்பு முடிவு</b> (இன்னும் சேர்க்கவில்லை)' : '✅ <b>இறக்குமதி முடிந்தது</b>') + '<br>' +
      'மூலத்தில் உள்ள படங்கள்: <b>' + first.source_total + '</b><br>' +
      'பொருந்தியவை: <b>' + first.matched_titles + '</b><br>' +
      (dryRun ? 'சேர்க்கப்படப்போகும் Book Id: <b>' + first.to_apply + '</b>' : 'சேர்க்கப்பட்ட Book Id: <b>' + totalApplied + '</b>') + '<br>' +
      'ஏற்கனவே படம் உள்ளவை: <b>' + first.already_have_cover + '</b><br>' +
      'பொருந்தாதவை (விடப்பட்டன): <b>' + first.no_match + '</b>' + list(first.no_match_samples) + '<br>' +
      'தெளிவில்லாதவை (விடப்பட்டன): <b>' + first.ambiguous + '</b>' + list(first.ambiguous_samples);
    if (!dryRun) toast('✅ ' + totalApplied + ' முகப்புப் படங்கள் சேர்க்கப்பட்டன', 'success');
  } catch (e) {
    hideLoading();
    box.style.color = '#c0392b';
    box.textContent = 'Server பிழை: ' + e;
  }
}

// Dindigul DB-ல் திருத்தப்பட்ட தலைப்புகளை Book Id மூலம் இங்கு ஒத்திசைக்க
async function runTitleSync(dryRun) {
  const url = document.getElementById('titleSyncSourceUrl').value.trim();
  const year = document.getElementById('titleSyncYear').value.trim() || '2025-2026';
  const box = document.getElementById('titleSyncMsg');
  if (!url) { box.style.color = '#c0392b'; box.textContent = 'Dindigul DB-ன் Database URL-ஐ உள்ளிடவும்'; return; }
  if (!dryRun && !confirm(year + ' ஆண்டு புத்தகங்களின் தலைப்புகளை Dindigul தலைப்புகளுக்கு மாற்றலாமா?')) return;

  showLoading(dryRun ? '⏳ சரிபார்க்கிறது...' : '⏳ தலைப்புகளை மாற்றுகிறது...');
  try {
    const res = await fetch('/api/admin/book_titles/sync_from_db', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_url: url, dry_run: dryRun, year })
    });
    const r = await res.json();
    hideLoading();
    if (r.error) { box.style.color = '#c0392b'; box.textContent = r.error; return; }
    const samples = (r.samples || []).map(s =>
      '<div style="margin-top:4px;"><span style="color:#6b7280;">' + escHtml(s.book_id) + '</span><br>' +
      '<span style="text-decoration:line-through;color:#c0392b;">' + escHtml(s.old || '') + '</span> → ' +
      '<b style="color:#15803d;">' + escHtml(s.new || '') + '</b></div>').join('');
    box.style.color = '#1e293b';
    box.innerHTML =
      (dryRun ? '🔍 <b>சரிபார்ப்பு முடிவு</b> (இன்னும் மாற்றவில்லை)' : '✅ <b>தலைப்பு ஒத்திசைவு முடிந்தது</b>') + ' — ஆண்டு ' + escHtml(r.year) + '<br>' +
      (r.year_filtered_source ? '' : '⚠️ மூல DB-ல் academic_year இல்லை; முழு table படிக்கப்பட்டது<br>') +
      'மூல Book Id-கள்: <b>' + r.source_book_ids + '</b> | இங்குள்ள Book Id-கள்: <b>' + r.target_book_ids + '</b><br>' +
      'மாறும் தலைப்புகள்: <b>' + r.titles_to_change + '</b> (வரிசைகள்: <b>' + r.rows_to_change + '</b>)' +
      (dryRun ? '' : ' → மாற்றப்பட்ட வரிசைகள்: <b>' + (r.updated_rows || 0) + '</b>') + '<br>' +
      'ஏற்கனவே ஒரே தலைப்பு (வரிசைகள்): <b>' + r.already_same_rows + '</b><br>' +
      'மூலத்தில் இல்லாத Book Id: <b>' + r.not_in_source + '</b> | மூலத்தில் முரண்: <b>' + r.source_conflicts + '</b>' + samples;
    if (!dryRun) toast('✅ ' + (r.updated_rows || 0) + ' வரிசைகளின் தலைப்பு மாற்றப்பட்டது', 'success');
  } catch (e) {
    hideLoading();
    box.style.color = '#c0392b';
    box.textContent = 'Server பிழை: ' + e;
  }
}
