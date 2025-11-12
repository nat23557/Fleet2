(async function(){
  const $ = (sel) => document.querySelector(sel);
  const kpiRow = $('#kpi-row');
  const riskList = $('#risk-list');
  const actList = $('#activity-list');
  const anoList = $('#anomaly-list');
  const benchBody = $('#bench-tbody');
  const riskChip = $('#smd-risk-chip');
  const updated = $('#smd-updated');
  const configConsole = $('#config-console');

  const endpoints = {
    kpis: '/api/dashboard/system-manager/kpis/',
    activity: '/api/dashboard/system-manager/activity/',
    anomalies: '/api/dashboard/system-manager/anomalies/',
    config: '/api/dashboard/system-manager/config/',
    benchmarks: '/api/dashboard/system-manager/benchmarks/',
    risk: '/api/dashboard/system-manager/risk-score/'
  };

  function nowStr(){ return new Date().toLocaleString(); }
  function setUpdated(){ updated.textContent = `Last update: ${nowStr()}`; }

  async function jget(url){ const r = await fetch(url); if(!r.ok) throw new Error(`${r.status}`); return r.json(); }

  // ====== UI helpers ======
  function countTo(el, value, duration=700){
    const start = 0, end = Number(value)||0;
    const steps = Math.max(12, Math.floor(duration/16));
    let i=0; const fmt = (n)=> (Math.abs(end) >= 1000 ? n.toLocaleString() : n.toFixed( (String(end).includes('.')?2:0) ));
    const tick = ()=>{ i++; const v = start + (end-start)*(i/steps); el.textContent = fmt(i>=steps? end : v); if(i<steps) requestAnimationFrame(tick); };
    tick();
  }
  function sparkline(points){
    if(!points || points.length===0) return '';
    const w=100, h=32, p=points.map(Number);
    const min=Math.min(...p), max=Math.max(...p), span=max-min || 1;
    const step = w/(p.length-1 || 1);
    const d = p.map((v,i)=> `${i===0?'M':'L'} ${i*step} ${h - ((v-min)/span)*h}`).join(' ');
    return `<svg class="smd-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <path d="${d}" fill="none" stroke="currentColor" stroke-width="2" opacity=".9"/>
    </svg>`;
  }
  function severityClass(s){ return s==='high'?'bg-danger':(s==='medium'?'bg-warning':'bg-secondary'); }
  function riskChipClass(score){
    if(score>=75) return 'smd-chip smd-chip--high';
    if(score>=40) return 'smd-chip smd-chip--medium';
    if(score>=0) return 'smd-chip smd-chip--low';
    return 'smd-chip smd-chip--neutral';
  }

  // ====== Renderers ======
  function renderKpis(payload){
    kpiRow.innerHTML = '';
    const cards = payload?.cards || [];
    if(cards.length===0){
      kpiRow.innerHTML = `<div class="smd-skel" style="height:48px"></div>`;
      return;
    }
    cards.forEach((c)=>{
      const up = (c.trend && typeof c.trend.pct_7d === 'number' && c.trend.pct_7d>=0);
      const trendClass = up ? 'smd-trend-up' : 'smd-trend-down';
      const el = document.createElement('div');
      el.className = 'smd-card smd-kpi';
      el.innerHTML = `
        <div class="k-label">${c.label}</div>
        <div class="k-value" id="kval-${c.key}">0</div>
        <div class="k-sub ${trendClass}">
          ${c.trend && c.trend.pct_7d!==undefined ? `${c.trend.pct_7d>=0?'+':''}${c.trend.pct_7d}% 7d` : ''}
          ${c.unit ? ` · ${c.unit}` : ''}
        </div>
        ${c.trend && Array.isArray(c.trend.series) ? sparkline(c.trend.series) : ''}
        ${c.note ? `<div class="text-muted small mt-1">${c.note}</div>` : ''}`;
      kpiRow.appendChild(el);
      countTo(el.querySelector(`#kval-${c.key}`), Number(c.value)||0);
    });
    if(Array.isArray(payload?.top_risks)) renderTopRisks(payload.top_risks);
  }

  function renderTopRisks(risks){
    riskList.innerHTML='';
    if(!risks || risks.length===0){ riskList.innerHTML = `<li class="list-group-item text-muted">No risks</li>`; return; }
    risks.forEach(r=>{
      const li = document.createElement('li');
      li.className = 'list-group-item d-flex justify-content-between align-items-center';
      li.textContent = r.title;
      const badge = document.createElement('span');
      badge.className = `badge ${severityClass(r.severity)}`;
      badge.textContent = r.count ?? r.severity;
      li.appendChild(badge);
      riskList.appendChild(li);
    });
  }

  function renderActivity(data){
    actList.innerHTML='';
    const events = data?.recent_events || [];
    if(events.length===0){ actList.innerHTML = `<li class="list-group-item text-muted">No recent events</li>`; return; }
    events.slice(0,10).forEach(ev=>{
      const li = document.createElement('li');
      li.className = 'list-group-item';
      li.textContent = `${ev.ts} • ${ev.actor} • ${ev.type}${ev.desc?` — ${ev.desc}`:''}`;
      actList.appendChild(li);
    });
  }

  function renderAnomalies(alerts){
    anoList.innerHTML='';
    if(!alerts || alerts.length===0){ anoList.innerHTML = `<li class="list-group-item text-muted">No anomalies</li>`; return; }
    alerts.forEach(a=>{
      const li = document.createElement('li');
      li.className = 'list-group-item d-flex justify-content-between align-items-center';
      li.textContent = `${a.title} (${a.entity})`;
      const badge = document.createElement('span');
      badge.className = `badge ${severityClass(a.severity)}`;
      badge.textContent = a.severity;
      li.appendChild(badge);
      anoList.appendChild(li);
    });
  }

  function renderBenchmarks(rows){
    benchBody.innerHTML='';
    if(!rows || rows.length===0){ benchBody.innerHTML = `<tr><td colspan="6" class="text-muted">No benchmark data</td></tr>`; return; }
    rows.forEach(r=>{
      const tr = document.createElement('tr');
      const cap = Number(r.capacity_utilization||0);
      const health = cap<70 ? 'smd-ok' : (cap<85?'smd-warn':'smd-bad');
      tr.innerHTML = `
        <td><span class="smd-dot ${health}"></span> ${r.name}</td>
        <td>${cap.toFixed(1)}%</td>
        <td>${Number(r.stock_qtl||0).toLocaleString()}</td>
        <td>${Number(r.open_pos||0)}</td>
        <td>${Number(r.on_time_inbound||0).toFixed(1)}%</td>
        <td>${Number(r.qc_fail_7d||0)}</td>`;
      benchBody.appendChild(tr);
    });
  }

  function renderRiskScore(payload){
    const score = typeof payload?.score === 'number' ? payload.score : -1;
    const reasons = payload?.reasons?.join('; ') || '—';
    $('#risk-score').textContent = score>=0 ? `${Math.round(score)}/100` : '—';
    $('#risk-reasons').textContent = score>=0 ? reasons : 'No risk model available';
    riskChip.className = riskChipClass(score);
    riskChip.textContent = score>=0 ? `Risk: ${score>=75?'High':score>=40?'Medium':'Low'}` : 'Risk: —';
  }

  function renderConfig(cfg){
    configConsole.innerHTML='';
    configConsole.classList.remove('text-muted');
    if(!cfg.widgets || Object.keys(cfg.widgets).length===0){
      configConsole.classList.add('text-muted');
      configConsole.textContent='No configurable widgets';
      return;
    }
    const table=document.createElement('table');
    table.className='table table-dark table-striped';
    const thead=document.createElement('thead');
    const headRow=document.createElement('tr');
    headRow.innerHTML='<th>Widget</th><th>Show</th>';
    thead.appendChild(headRow); table.appendChild(thead);
    const tbody=document.createElement('tbody');
    Object.entries(cfg.widgets).forEach(([k,v])=>{
      const tr=document.createElement('tr');
      tr.innerHTML=`<td>${k}</td><td><input type="checkbox" class="form-check-input" data-key="${k}" ${v?'checked':''}></td>`;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody); configConsole.appendChild(table);
    const btn=document.createElement('button'); btn.className='btn btn-primary mt-2'; btn.textContent='Save';
    btn.addEventListener('click',async()=>{
      const widgets={};
      configConsole.querySelectorAll('input[data-key]').forEach(i=>widgets[i.dataset.key]=i.checked);
      try{
        await fetch(endpoints.config,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':getCsrf()},body:JSON.stringify({role:cfg.role,widgets})});
      }catch(err){console.error(err);}
    });
    configConsole.appendChild(btn);
  }

  function getCsrf(){
    return document.cookie.split(';').map(c=>c.trim()).find(c=>c.startsWith('csrftoken='))?.split('=')[1]||'';
  }

  // ====== Load all ======
  async function loadAll(){
    try{
      const [kpis, act, anom, bench, risk, cfg] = await Promise.allSettled([
        jget(endpoints.kpis), jget(endpoints.activity), jget(endpoints.anomalies),
        jget(endpoints.benchmarks), jget(endpoints.risk), jget(endpoints.config)
      ]);
      if(kpis.status==='fulfilled') renderKpis(kpis.value); else kpiRow.innerHTML = `<div class="text-danger">Error loading KPIs</div>`;
      if(act.status==='fulfilled') renderActivity(act.value); else actList.innerHTML = `<li class="list-group-item text-danger">Error loading activity</li>`;
      if(anom.status==='fulfilled') renderAnomalies(anom.value?.alerts); else anoList.innerHTML = `<li class="list-group-item text-danger">Error loading anomalies</li>`;
      if(bench.status==='fulfilled') renderBenchmarks(bench.value?.rows); else renderBenchmarks([]);
      if(risk.status==='fulfilled') renderRiskScore(risk.value); else renderRiskScore(null);
      if(cfg.status==='fulfilled') renderConfig(cfg.value); else {
        configConsole.textContent='Error loading config';
        configConsole.classList.remove('text-muted');
        configConsole.classList.add('text-danger');
      }
      setUpdated();
    }catch(e){
      console.error(e);
    }
  }

  // manual refresh & export
  $('#smd-refresh')?.addEventListener('click', loadAll);
  $('#smd-export')?.addEventListener('click', async ()=>{
    const out = {};
    for (const [key,url] of Object.entries(endpoints)){
      try{ out[key] = await jget(url); }catch{ out[key] = {error:true}; }
    }
    const blob = new Blob([JSON.stringify(out, null, 2)], {type:'application/json'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = `sm-dashboard-snapshot-${Date.now()}.json`; a.click();
    URL.revokeObjectURL(a.href);
  });

  await loadAll();
  setInterval(loadAll, 60000);
})();
