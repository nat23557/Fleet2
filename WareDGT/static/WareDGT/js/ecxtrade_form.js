// Dynamic multi-warehouse ECX trade form
document.addEventListener('DOMContentLoaded', () => {
  window.__ecxMulti = true;
  const groupsEl = document.getElementById('groups');
  const addBtn = document.getElementById('add_group');
  let hiddenPayload = document.getElementById('id_groups_json');
  const form = document.getElementById('ecx-trade-form');

  if (!groupsEl || !addBtn || !form) return;

  let seedTypes = [];
  let warehouses = {};
  const KNOWN_CATS = ['COFFEE','SESAME','BEANS'];
  const OTHER_SYMBOLS = ['NS'];

  Promise.all([
    fetch('/api/seed-type-details/', { credentials: 'same-origin' }).then(r => r.ok ? r.json() : Promise.reject('seed types')),
    fetch('/api/warehouses/', { credentials: 'same-origin' }).then(r => r.ok ? r.json() : Promise.reject('warehouses')),
  ]).then(([seedData, whData]) => {
    const items = Array.isArray(seedData) ? seedData : seedData.results;
    if (Array.isArray(items)) seedTypes = items; else console.error('Unexpected seed type data', seedData);
    if (Array.isArray(whData)) whData.forEach(w => { warehouses[w.id] = w; }); else console.error('Unexpected warehouse data', whData);
    addGroup(); // start with one group
  }).catch(err => console.error('Failed to fetch', err));

  addBtn.addEventListener('click', () => addGroup());

  form.addEventListener('submit', () => {
    if (!hiddenPayload) {
      hiddenPayload = document.createElement('input');
      hiddenPayload.type = 'hidden';
      hiddenPayload.name = 'groups_json';
      hiddenPayload.id = 'id_groups_json';
      form.appendChild(hiddenPayload);
    }
    const payload = collectGroups();
    hiddenPayload.value = JSON.stringify(payload);
  });

  function createEl(tag, attrs={}, children=[]) {
    const el = document.createElement(tag);
    Object.entries(attrs).forEach(([k,v]) => {
      if (k === 'class') el.className = v; else if (k === 'for') el.htmlFor = v; else el.setAttribute(k, v);
    });
    (Array.isArray(children) ? children : [children]).forEach(ch => {
      if (typeof ch === 'string') el.appendChild(document.createTextNode(ch)); else if (ch) el.appendChild(ch);
    });
    return el;
  }

  function addGroup() {
    const idx = groupsEl.children.length + 1;
    const wrap = createEl('div', { class: 'ecx-group', 'data-idx': idx, style: 'border:1px solid #2b3942;padding:12px;margin-bottom:10px;border-radius:6px;' });

    const cat = createEl('select', { class: 'ecx-cat', name: `cat_${idx}` });
    const sym = createEl('select', { class: 'ecx-sym', name: `sym_${idx}` });
    const grd = createEl('select', { class: 'ecx-grd', name: `grd_${idx}` });
    const wh = createEl('select', { class: 'ecx-wh', name: `wh_${idx}` });
    const txt = createEl('textarea', { class: 'ecx-entries', rows: '3', placeholder: "WRN1:10.5\nWRN2:5" });
    const rm = createEl('button', { type: 'button', class: 'erp-btn danger', style: 'margin-left:8px;' }, 'Remove');

    [cat, sym, grd, wh].forEach(s => { s.appendChild(createEl('option', { value: '' }, '---------')); s.disabled = true; });
    populateCategories(cat);

    // Layout
    wrap.appendChild(createEl('div', {}, [createEl('label', {}, 'Seed Category:'), cat]));
    wrap.appendChild(createEl('div', {}, [createEl('label', {}, 'Seed Type:'), sym]));
    wrap.appendChild(createEl('div', {}, [createEl('label', {}, 'Grade:'), grd]));
    wrap.appendChild(createEl('div', {}, [createEl('label', {}, 'Warehouse:'), wh]));
    wrap.appendChild(createEl('div', {}, [createEl('label', {}, "Receipt & Qty Pairs:"), txt]));
    wrap.appendChild(createEl('div', {}, rm));

    // Events
    cat.addEventListener('change', () => populateSymbols(cat, sym, grd, wh));
    sym.addEventListener('change', () => populateGrades(cat, sym, grd, wh));
    grd.addEventListener('change', () => populateWarehouses(cat, sym, grd, wh));
    rm.addEventListener('click', () => { wrap.remove(); });

    groupsEl.appendChild(wrap);
  }

  function populateCategories(catSel) {
    catSel.innerHTML = '';
    const placeholder = createEl('option', { value: '' }, '---------');
    catSel.appendChild(placeholder);
    ;['COFFEE','SESAME','BEANS','OTHER'].forEach(c => {
      catSel.appendChild(createEl('option', { value: c }, c));
    });
    catSel.disabled = false;
  }

  function populateSymbols(catSel, symSel, grdSel, whSel) {
    const cat = catSel.value;
    symSel.innerHTML = '<option value="">---------</option>';
    const symbols = new Set(
      seedTypes
        .filter(s => (
          cat === 'OTHER'
            ? (!KNOWN_CATS.includes(s.category) || OTHER_SYMBOLS.includes(s.symbol))
            : s.category === cat
        ))
        .map(s => s.symbol)
    );
    symbols.forEach(sym => symSel.appendChild(createEl('option', { value: sym }, sym)));
    symSel.disabled = !symbols.size;
    grdSel.innerHTML = '<option value="">---------</option>';
    grdSel.disabled = true;
    whSel.innerHTML = '<option value="">---------</option>';
    whSel.disabled = true;
  }

  function populateGrades(catSel, symSel, grdSel, whSel) {
    const cat = catSel.value;
    const sym = symSel.value;
    grdSel.innerHTML = '<option value="">---------</option>';
    const grades = new Set();
    seedTypes.filter(s => ((cat === 'OTHER' ? (!KNOWN_CATS.includes(s.category) || OTHER_SYMBOLS.includes(s.symbol)) : s.category === cat)) && s.symbol === sym).forEach(s => {
      s.grade.split(',').forEach(g => grades.add(g.trim()));
    });
    grades.forEach(g => grdSel.appendChild(createEl('option', { value: g }, g)));
    grdSel.disabled = !grades.size;
    whSel.innerHTML = '<option value="">---------</option>';
    whSel.disabled = true;
  }

  function populateWarehouses(catSel, symSel, grdSel, whSel) {
    const cat = catSel.value;
    const sym = symSel.value;
    const grade = grdSel.value;
    whSel.innerHTML = '<option value="">---------</option>';
    seedTypes.forEach(s => {
      if (((cat === 'OTHER' ? (!KNOWN_CATS.includes(s.category) || OTHER_SYMBOLS.includes(s.symbol)) : s.category === cat)) && s.symbol === sym && s.grade.includes(grade)) {
        const w = warehouses[s.delivery_location];
        if (w) whSel.appendChild(createEl('option', { value: w.id }, w.name));
      }
    });
    whSel.disabled = whSel.options.length <= 1;
  }

  function collectGroups() {
    const groups = [];
    groupsEl.querySelectorAll('.ecx-group').forEach(group => {
      const cat = group.querySelector('.ecx-cat')?.value || '';
      const sym = group.querySelector('.ecx-sym')?.value || '';
      const grd = group.querySelector('.ecx-grd')?.value || '';
      const wh = group.querySelector('.ecx-wh')?.value || '';
      const entries = group.querySelector('.ecx-entries')?.value || '';
      if (wh && sym && grd && entries.trim()) {
        groups.push({ category: cat, symbol: sym, grade: grd, warehouse: wh, receipt_entries: entries });
      }
    });
    return groups;
  }
});
