'use strict';
const $ = id => document.getElementById(id);
const state = {data: null, rows: [], filtered: [], page: 0, size: 75, selected: null};
const fmt = n => Number(n).toLocaleString('ru-RU', {maximumFractionDigits: 3});
const ms = ns => `${fmt(ns / 1e6)} мс`;
function elem(tag, text, cls) {const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e;}
function error(message) {$('error').textContent = message; $('error').hidden = !message;}
function position(p) {return p && ['x','y','z'].every(k => Number.isFinite(p[k])) ? [p.x,p.y,p.z].join(' ') : '—';}
function normalize(profile) {
  const d = profile.data || profile;
  if (!d || !d.blocks || !d.entities || !Number.isInteger(d.ticks) || d.ticks < 0) throw new Error('Файл не похож на профиль Observable 5.4.4.');
  const rows = [];
  for (const kind of ['blocks','entities']) {
    if (typeof d[kind] !== 'object' || Array.isArray(d[kind])) throw new Error('Неверный формат измерений.');
    for (const [dim, entries] of Object.entries(d[kind])) {
      if (!Array.isArray(entries)) throw new Error('Неверный формат записей.');
      for (const e of entries) {
        if (!e || typeof e !== 'object' || !Number.isFinite(e.rate) || e.rate < 0 || !Number.isInteger(e.ticks) || e.ticks < 0) throw new Error('В отчёте есть некорректные записи.');
        rows.push({...e, kind, dim, type:String(e.type || 'Неизвестно'), load: d.ticks ? e.rate * e.ticks / d.ticks : 0, index: rows.length});
      }
    }
  }
  return {d, rows};
}
function load(profile, label) {
  const {d, rows} = normalize(profile);
  state.data = d; state.rows = rows; state.page = 0; state.selected = null;
  $('selected').hidden = true;
  const dims = [...new Set(rows.map(e => e.dim))];
  $('entries').textContent = fmt(rows.length); $('ticks').textContent = `${fmt(d.ticks)} тиков`;
  $('load').textContent = ms(rows.reduce((s,e) => s+e.load,0)); $('dimensions').textContent = dims.length;
  $('dimension').replaceChildren(new Option('Все измерения','all'), ...dims.map(d => new Option(d,d)));
  $('diagnostics').textContent = profile.diagnostics ? JSON.stringify(profile.diagnostics,null,2) : 'В этом файле нет диагностики.';
  $('status').textContent = label;
  renderTrace($('server-traces'), d.traces);
  filter(); error('');
}
function filter() {
  const q = $('search').value.trim().toLowerCase(), kind = $('kind').value, dim = $('dimension').value, sort = $('sort').value;
  state.filtered = state.rows.filter(e => (kind === 'all' || e.kind === kind) && (dim === 'all' || e.dim === dim) && (!q || `${e.type} ${e.dim} ${position(e.position)} ${e.entityId ?? ''}`.toLowerCase().includes(q)));
  state.filtered.sort((a,b) => b[sort]-a[sort]); state.page = 0; render();
}
function render() {
  const pages = Math.max(1,Math.ceil(state.filtered.length/state.size));
  state.page = Math.min(state.page,pages-1);
  const fragment = document.createDocumentFragment();
  for (const e of state.filtered.slice(state.page*state.size,(state.page+1)*state.size)) {
    const tr = elem('tr'), name = elem('td'), button = elem('button',e.type,'entry');
    button.addEventListener('click', () => select(e)); name.append(button,elem('small',`${e.kind === 'blocks' ? 'Блок' : 'Сущность'}${e.entityId == null ? '' : ` · ID ${e.entityId}`}`));
    tr.append(name,elem('td',e.dim),elem('td',position(e.position)),elem('td',ms(e.rate)),elem('td',ms(e.load)),elem('td',fmt(e.ticks))); fragment.append(tr);
  }
  if (!fragment.childNodes.length) {const tr = elem('tr'), td = elem('td',state.data ? 'Нет записей по выбранным фильтрам' : 'Профиль ещё не открыт','empty'); td.colSpan=6;tr.append(td);fragment.append(tr);}
  $('rows').replaceChildren(fragment); $('count').textContent = `${fmt(state.filtered.length)} из ${fmt(state.rows.length)} записей`;
  $('page').textContent = `${state.page+1} / ${pages}`; $('prev').disabled = !state.page; $('next').disabled = state.page+1 >= pages;
}
function renderTrace(target, tree) {
  target.replaceChildren();
  if (!tree || (!tree.count && !(tree.children || []).length)) {target.append(elem('p','Стек отсутствует. Для записи стека включите сбор сэмплов в Observable.','hint'));return;}
  let budget = 4000;
  const rootCount = Number(tree.count) || 1;
  function node(t, depth) {
    if (--budget < 0 || depth > 80 || !t || typeof t !== 'object') return elem('p','Дерево сокращено для быстрого отображения. Полные данные — в исходнике.');
    const d = elem('details'), s = elem('summary'); d.open = depth < 1;
    s.append(elem('span',`${fmt(Number(t.count)||0)} · ${fmt(100*(Number(t.count)||0)/rootCount)}%`,'samples'),document.createTextNode(`${String(t.className || '(корень)')}.${String(t.methodName || '')}`));d.append(s);
    // Populate each branch only when opened, keeping large stacks responsive.
    let expanded = false;
    const expand = () => {if (expanded || !d.open) return; expanded = true;for (const child of Array.isArray(t.children) ? t.children : []) {d.append(node(child,depth+1));if(budget<0)break;}};
    d.addEventListener('toggle',expand); expand();return d;
  }
  target.append(node(tree,0));
}
function select(e) {
  state.selected=e; $('selected').hidden=false; $('selected-title').textContent=e.type;
  $('selected-info').textContent=`${e.dim} · ${position(e.position)} · ${ms(e.rate)} за вызов · ${fmt(e.ticks)} вызовов`;
  $('copy-tp').disabled = position(e.position)==='—' || !/^[a-z0-9_.-]+:[a-z0-9_./-]+$/.test(e.dim);
  renderTrace($('entry-traces'),e.traces); $('selected').scrollIntoView({behavior:'smooth',block:'start'});
}
document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click',()=>{
  document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));
  for(const id of ['entries','traces','diagnostics']) $(id+'-panel').hidden=id!==b.dataset.tab;
}));
for (const id of ['search','kind','dimension','sort']) $(id).addEventListener(id==='search'?'input':'change',filter);
$('prev').addEventListener('click',()=>{state.page--;render();}); $('next').addEventListener('click',()=>{state.page++;render();});
$('copy-tp').addEventListener('click',async()=>{
  const e = state.selected; if(!e)return;
  const command = `/execute in ${e.dim} run tp @s ${position(e.position)}`;
  try {await navigator.clipboard.writeText(command); $('copy-tp').textContent='Команда скопирована';setTimeout(()=>{$('copy-tp').textContent='Скопировать команду телепортации';},2000);}
  catch {error(`Скопируйте команду: ${command}`);}
});
$('file').addEventListener('change',async event=>{
  const file=event.target.files[0]; if(!file)return;
  try {
    if(file.size>32*1024*1024)throw new Error('Файл больше 32 МиБ.');
    let stream=file.stream(); const magic=new Uint8Array(await file.slice(0,2).arrayBuffer());
    if(magic[0]===31&&magic[1]===139) {if(!globalThis.DecompressionStream)throw new Error('Этот браузер не поддерживает gzip. Распакуйте файл вручную.');stream=stream.pipeThrough(new DecompressionStream('gzip'));}
    const reader=stream.getReader(),chunks=[];let total=0;
    while(true){const {value,done}=await reader.read();if(done)break;total+=value.length;if(total>32*1024*1024){await reader.cancel();throw new Error('Распакованный файл больше 32 МиБ.');}chunks.push(value);}
    const raw=new Uint8Array(total);let offset=0;for(const c of chunks){raw.set(c,offset);offset+=c.length;}
    load(JSON.parse(new TextDecoder().decode(raw)),`Локальный файл: ${file.name}`); $('download').hidden=true;history.replaceState(null,'','/');
  } catch(e){error(`Не удалось открыть файл: ${e.message}`);}
});
(async()=>{
  const match=location.pathname.match(/^\/report\/([a-f0-9]{32})\/?$/);if(!match)return;
  $('status').textContent='Загружаю отчёт…';
  try {const r=await fetch(`/api/report/${match[1]}`);if(!r.ok)throw new Error(r.status===410?'Срок хранения истёк.':'Отчёт недоступен.');load(await r.json(),`Отчёт ${match[1].slice(0,8)}`);$('download').href=`/download/${match[1]}`;$('download').hidden=false;}
  catch(e){error(e.message);$('status').textContent='Не удалось загрузить отчёт. Можно открыть локальный файл.';}
})();
