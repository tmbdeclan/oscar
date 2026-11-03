/* OSCA: browser-local entry, immutable reporting snapshots, and explicit SOS refresh. */
(async function(){
'use strict';
const hostArgs=await window.OSCABridge.ready;
const $=s=>document.querySelector(s), M=OSCAModel, H=OSCAHouse, fmt=n=>Math.round(n).toLocaleString('en-US'), signed=n=>(n>=0?'+':'−')+fmt(Math.abs(n));
const [base,geo,primaryTiming,crossData,primaryCandidates,partyCalibration,houseCatalog,houseGeo]=await Promise.all(['data/baseline.json','data/towns.geojson','data/primary-timing.json','data/crossballot.json','data/primary-candidates-2026.json','data/party-multipliers-2024.json','data/house-races.json','data/house-towns.geojson'].map(u=>fetch(u).then(r=>{if(!r.ok)throw Error('Missing local data');return r.json();})));
const config=[['White','Rebecca White','#62a8ff'],['Major','Joe Major','#ff9a4d'],['Burrows','Elizabeth Burrows','#64d68b'],['Murray','Andrea Murray','#ff82bd'],['Williams','Jack Williams','#b59cff'],['Gleason','Jonathan Gleason','#4ddbd2'],['Izzo','Joe Izzo','#c4cbd1']];
const isDemo=window.OSCABridge.embedded?Boolean(hostArgs.demo):new URLSearchParams(location.search).get('demo')==='1';
const isDisplay=window.OSCABridge.embedded?Boolean(hostArgs.display):new URLSearchParams(location.search).get('display')==='1';
if(isDisplay){document.body.classList.add('results-display');document.title='OSCA · Results display';document.querySelector('.layout').append(document.querySelector('.scenario'));document.querySelector('.performance-legend').textContent='Arrows versus the selected 2024 comparator: ↑ / ↓ 2–<5 percentage points; ↑↑ / ↓↓ 5 points or more. Complete towns only. No arrow near baseline or without data. Hover for the calculation.';}
const candidates=config.map(([key,name,color])=>({key,name,color})),keys=candidates.map(c=>c.key),towns=base.rows.map(r=>r.town),STORE=isDemo?'osca-simulation-v1':'osca-general-election-v1';
const blank=town=>({town,status:'unreported',ballots:null,votes:Object.fromEntries(keys.map(k=>[k,null])),source:'Not reported'});
const requestedComparators={Burrows:'Joe Major',Major:'Alison H. Clarkson',Izzo:'Marc Nemeth'};
const requestedComparatorIds=Object.fromEntries(Object.entries(requestedComparators).map(([key,name])=>[key,base.candidates.find(c=>c.name===name)?.key||'']));
const empty=()=>({version:1,demo:isDemo,comparatorDefaultsVersion:1,official:towns.map(blank),manual:{},house:null,houseFocus:{},comparators:Object.fromEntries(candidates.map(c=>[c.key,requestedComparatorIds[c.key]||base.candidates.find(b=>b.name===c.name)?.key||''])),history:[]});
let state=empty(),selected=0,dirty=false,interval=null,busy=false,generalProjection=null,displaySync=null;
function checkedSession(s){
 if(Boolean(s?.demo)!==isDemo)throw Error('Simulation and live sessions cannot be mixed');
 if(s?.version!==1||!Array.isArray(s.official)||!s.manual||!Array.isArray(s.history)||!s.comparators)throw Error('Not an OSCA session');
 function checkRows(rows){if(rows.length!==25||new Set(rows.map(r=>r.town)).size!==25||rows.some(r=>!towns.includes(r.town)||!['complete','partial','unreported'].includes(r.status)||!r.votes||M.validate(r,keys).length))throw Error('Invalid town rows in session');}
 checkRows(s.official);for(const [town,row] of Object.entries(s.manual)){if(row.town!==town||!towns.includes(town)||M.validate(row,keys).length)throw Error('Invalid manual row');}
 if(s.history.length>3000)throw Error('Session exceeds 3,000 snapshots');
 for(const h of s.history){checkRows(h.rows);if(!Number.isFinite(Date.parse(h.time))||typeof h.source!=='string')throw Error('Invalid snapshot');}
 if(s.house)H.validate(s.house,houseCatalog);for(const h of s.history)if(h.house)H.validate(h.house,houseCatalog);
 if(!s.houseFocus||typeof s.houseFocus!=='object'||Array.isArray(s.houseFocus))s.houseFocus={};
 for(const k of keys)if(s.comparators[k]&&!base.candidates.some(c=>c.key===s.comparators[k]))throw Error('Unknown comparator');
 return s;
}
try{const stored=localStorage.getItem(STORE);if(stored)state=checkedSession(JSON.parse(stored));}catch(e){$('#feedStatus').textContent='Saved session could not be loaded. Import a valid backup to restore it.';}
// Apply the user's new defaults once to older sessions, preserving later manual choices.
if(!state.comparatorDefaultsVersion){Object.assign(state.comparators,requestedComparatorIds);state.comparatorDefaultsVersion=1;persist();}
if(isDemo){state=empty();state.timingProvenance=primaryTiming;state.history=makeOSCADemo(base.rows,keys,blank,primaryTiming);state.official=structuredClone(state.history.at(-1).rows);$('#demoBanner').hidden=false;$('#refresh').disabled=true;$('#auto').disabled=true;$('#demoLink').hidden=true;$('#save').hidden=true;$('#save').parentElement.querySelector('h2').textContent='Simulated town results';$('#save').parentElement.querySelector('p').textContent='Read-only synthetic totals follow the reporting snapshot selected above. Return to the live workspace for manual entry.';$('#feedStatus').textContent=`SIMULATION: ${primaryTiming.snapshots.length} recorded 2026 primary snapshots plus an empty starting point. Clocks shifted to general-election dates; SOS polling disabled. Playback advances one snapshot every 2.5 seconds.`;document.title='SIMULATION · OSCA Election Night';}
if(isDemo){const demos=H.demo(houseCatalog,state.history);state.history.forEach((h,i)=>h.house=demos[i]);state.house=demos.at(-1);}
function merged(){return state.official.map(r=>structuredClone(state.manual[r.town]||r));}
function persist(){if(isDisplay)return;try{localStorage.setItem(STORE,JSON.stringify(state));$('#saveStatus').textContent='Saved in this browser';}catch(e){$('#saveStatus').textContent='Browser storage unavailable or full—export this session now';}}
function snapshot(source,meta={}){
 state.history.push({time:new Date().toISOString(),source,rows:merged(),house:structuredClone(state.house||null),...meta});selected=state.history.length-1;persist();draw();
}
if(!state.history.length)state.history.push({time:new Date().toISOString(),source:'No results entered',rows:merged()});selected=isDemo?Math.floor(state.history.length/2):state.history.length-1;
function el(tag,text,parent){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(parent)parent.append(n);return n;}
function option(select,value,text){const o=el('option',text,select);o.value=value;}
for(const c of candidates)option($('#focus'),c.key,c.name);$('#focus').value='Burrows';
for(const c of candidates){const item=el('span',null,$('#candidateLegend'));const dot=el('i',null,item);dot.className='swatch';dot.style.background=c.color;el('span',c.name,item);}
for(const [name,color] of [['2024 only: Alison H. Clarkson','#cfb886'],['2024 only: Marc Nemeth','#8094ac']]){const item=el('span',null,$('#candidateLegend'));const dot=el('i',null,item);dot.className='swatch';dot.style.background=color;dot.style.borderStyle='dashed';el('span',name,item);}
function input(type,value,label){const n=document.createElement('input');n.type=type;n.value=value??'';n.setAttribute('aria-label',label);if(type==='number'){n.min=0;n.step=1;}return n;}
function performanceBadge(parent,rows,c,aggregate=false){
 const comparator=state.comparators[c.key],result=M.performance(rows,base.rows,keys,c.key,comparator);
 if(!result?.level)return;
 const name=base.candidates.find(b=>b.key===comparator).name;
 const degree=result.level===2?'Much':'Somewhat',arrow=result.direction==='higher'?'↑':'↓';
 const text=`${c.name}: ${degree.toLowerCase()} ${result.direction} versus ${name}’s 2024 support. ${Math.abs(result.points).toFixed(1)} percentage points ${result.direction==='higher'?'above':'below'}; ${fmt(result.actual)} reported versus ${fmt(result.expected)} expected across ${fmt(result.ballots)} ballots in ${result.towns} complete town${result.towns===1?'':'s'}.`+(aggregate?' Indicator excludes partial and unreported towns; the reported total includes all reported towns.':'');
 const badge=el('span',arrow.repeat(result.level),parent);badge.className='performance-badge '+result.direction;badge.title=text;badge.setAttribute('aria-label',text);badge.setAttribute('role','img');badge.tabIndex=0;
}
function updateEntryIndicators(){
 const rows=isDemo?state.history[selected].rows:merged();
 for(const tr of document.querySelectorAll('#entryTable tbody tr')){
  tr.querySelectorAll('.performance-badge').forEach(b=>b.remove());
  if(tr.dataset.edited)continue;
  const row=rows.find(r=>r.town===tr.dataset.town);
  for(const c of candidates)performanceBadge(tr.querySelector(`[data-candidate="${c.key}"]`).parentElement,[row],c);
 }
}
function renderEntry(){
 const head=$('#entryTable thead'),body=$('#entryTable tbody');head.replaceChildren();body.replaceChildren();const tr=el('tr',null,head);
 ['Town / source','Status','Ballots',...keys,'Source note',''].forEach(h=>{const th=el('th',h,tr);if(keys.includes(h))th.className='vote-heading';});
 for(const row of (isDemo?state.history[selected].rows:merged())){
  const tr=el('tr',null,body);tr.dataset.town=row.town;const cell=el('td',null,tr);el('div',row.town,cell);el('div',row.source,cell).className='source';
  const status=el('select',null,el('td',null,tr));status.setAttribute('aria-label',row.town+' status');for(const s of ['unreported','partial','complete'])option(status,s,s);status.value=row.status;status.dataset.field='status';
  const ballots=input('number',row.ballots,row.town+' ballots');ballots.dataset.field='ballots';el('td',null,tr).append(ballots);
  for(const c of candidates){const field=input('number',row.votes[c.key],row.town+' '+c.name+' votes');field.dataset.candidate=c.key;const cell=el('td',null,tr);cell.className='vote-cell';cell.append(field);}
  const note=input('text',row.note||'',row.town+' source note');note.dataset.field='note';note.maxLength=300;el('td',null,tr).append(note);
  const release=el('button','Use SOS',el('td',null,tr));release.disabled=!state.manual[row.town];release.addEventListener('click',()=>{if(dirty&&!confirm('Discard unsaved table edits before releasing this town?'))return;delete state.manual[row.town];dirty=false;snapshot('Manual override released: '+row.town);renderEntry();});
 }
 if(isDemo)for(const control of body.querySelectorAll('input,select,button'))control.disabled=true;
 updateEntryIndicators();filter();
}
function filter(){const term=$('#filter').value.toUpperCase();document.querySelectorAll('#entryTable tbody tr').forEach(tr=>tr.hidden=!tr.dataset.town.includes(term));}
$('#filter').addEventListener('input',filter);
$('#entryTable').addEventListener('input',e=>{const tr=e.target.closest('tr');if(tr){tr.dataset.edited='1';tr.querySelectorAll('.performance-badge').forEach(b=>b.remove());}dirty=true;$('#saveStatus').textContent='Unsaved edits—save a snapshot to update charts';});
$('#entryTable').addEventListener('change',e=>{const tr=e.target.closest('tr');if(tr){tr.dataset.edited='1';tr.querySelectorAll('.performance-badge').forEach(b=>b.remove());}dirty=true;$('#saveStatus').textContent='Unsaved edits—save a snapshot to update charts';});
$('#save').addEventListener('click',()=>{
 const errors=[],pending={},previous=merged();
 for(const tr of document.querySelectorAll('#entryTable tbody tr')){
  const town=tr.dataset.town,row={town,status:tr.querySelector('[data-field=status]').value,ballots:null,votes:{},source:'Manual preliminary',note:tr.querySelector('[data-field=note]').value.trim()};
  const parse=n=>n.value.trim()===''?null:Number(n.value);
  row.ballots=parse(tr.querySelector('[data-field=ballots]'));for(const f of tr.querySelectorAll('[data-candidate]'))row.votes[f.dataset.candidate]=parse(f);
  errors.push(...M.validate(row,keys).map(e=>town+': '+e));
  const prior=previous.find(r=>r.town===town);
  if(JSON.stringify([row.status,row.ballots,row.votes,row.note])!==JSON.stringify([prior.status,prior.ballots,prior.votes,prior.note||'']))pending[town]=row;
 }
 $('#errors').replaceChildren();if(errors.length){for(const e of errors)el('p',e,$('#errors'));return;}
 if(!Object.keys(pending).length){dirty=false;renderEntry();$('#saveStatus').textContent='No changed rows';return;}
 Object.assign(state.manual,pending);dirty=false;snapshot('Manual preliminary entry');renderEntry();
});
function townInfo(town){const r=state.history[selected].rows.find(r=>r.town===town),b=base.rows.find(r=>r.town===town);$('#townDetails').textContent=`${town}: ${r.status} · ${r.ballots===null?'unknown ballots':fmt(r.ballots)+' ballots'} · 2024: ${fmt(b.ballots)} ballots. `+candidates.map(c=>`${c.key}: ${r.votes[c.key]==null?'—':fmt(r.votes[c.key])}`).join(' · ');}
function drawMap(){
 const svg=d3.select('#map'),width=$('#map').clientWidth||350,height=$('#map').clientHeight||560;svg.attr('viewBox',`0 0 ${width} ${height}`);svg.selectAll('*').remove();
 const snap=state.history[selected],prev=state.history[Math.max(0,selected-1)],rows=new Map(snap.rows.map(r=>[r.town,r]));
 const path=d3.geoPath(d3.geoMercator().fitExtent([[12,10],[width-12,height-10]],geo));
 svg.selectAll('path').data(geo.features).join('path').attr('class','town').attr('tabindex',isDisplay?-1:0).attr('d',path).attr('fill',f=>{
  const r=rows.get(f.properties.TOWNNAME.toUpperCase()),old=prev.rows.find(p=>p.town===r.town);
  if(selected>0&&JSON.stringify(r)!==JSON.stringify(old))return '#ff9a4d';return {complete:'#62c985',partial:'#e2c575',unreported:'#1d2630'}[r.status];
 }).attr('aria-label',f=>f.properties.TOWNNAME+' '+rows.get(f.properties.TOWNNAME.toUpperCase()).status).on('click',(_,f)=>townInfo(f.properties.TOWNNAME.toUpperCase())).on('keydown',(e,f)=>{if(e.key==='Enter'||e.key===' ')townInfo(f.properties.TOWNNAME.toUpperCase());}).append('title').text(f=>f.properties.TOWNNAME);
 // Label every district town; separate close labels and connect displaced names.
 const labels=geo.features.map(f=>{const [x,y]=path.centroid(f),name=f.properties.TOWNNAME.toLowerCase().replace(/\b\w/g,c=>c.toUpperCase());return {name,ax:x,ay:y,x,y,w:name.length*5.2+4};});
 for(const label of labels)label.x=Math.max(label.w/2+3,Math.min(width-label.w/2-3,label.x));
 for(let pass=0;pass<60;pass++){
  for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++){
   const a=labels[i],b=labels[j],overlapX=(a.w+b.w)/2+3-Math.abs(a.x-b.x),overlapY=13-Math.abs(a.y-b.y);
   if(overlapX>0&&overlapY>0){const direction=a.y<b.y?-1:1;a.y+=direction*overlapY/2;b.y-=direction*overlapY/2;}
  }
  for(const label of labels)label.y=Math.max(10,Math.min(height-10,label.y));
 }
 svg.append('g').attr('aria-hidden','true').attr('pointer-events','none').selectAll('line').data(labels.filter(l=>Math.hypot(l.x-l.ax,l.y-l.ay)>5)).join('line').attr('x1',l=>l.ax).attr('y1',l=>l.ay).attr('x2',l=>l.x).attr('y2',l=>l.y).attr('stroke','#c4d1dc').attr('stroke-width',.8);
 svg.append('g').attr('pointer-events','none').selectAll('text').data(labels).join('text').attr('class','town-label').attr('x',l=>l.x).attr('y',l=>l.y).attr('dy','.35em').attr('text-anchor','middle').attr('font-size',10).attr('fill','#eff4f8').attr('stroke','#0f1419').attr('stroke-width',2.5).attr('paint-order','stroke').text(l=>l.name);

 const complete=snap.rows.filter(r=>r.status==='complete').length,partial=snap.rows.filter(r=>r.status==='partial').length;
 const coverage=snap.rows.filter(r=>r.status==='complete').reduce((s,r)=>s+base.rows.find(b=>b.town===r.town).ballots,0)/36121;
 $('#coverage').textContent=`${complete}/25 towns complete · ${partial} partial · ${(coverage*100).toFixed(1)}% of 2024 ballots in complete towns.`;
}
function historic(snap,c){const key=state.comparators[c.key];if(!key)return null;const included=new Set(snap.rows.filter(r=>r.status!=='unreported').map(r=>r.town));return base.rows.filter(r=>included.has(r.town)).reduce((s,r)=>s+(r.votes[key]||0),0);}
function chart(selector,series,height,isMargin=false){
 const node=$(selector),w=node.clientWidth||700,h=height,svg=d3.select(node);svg.attr('viewBox',`0 0 ${w} ${h}`);svg.selectAll('*').remove();
 const margin={left:54,right:w<620?16:105,top:12,bottom:36},last=state.history.length-1;
 const x=d3.scaleLinear().domain([0,Math.max(1,last)]).range([margin.left,w-margin.right]);
 const values=series.flatMap(s=>s.values).filter(v=>v!==null),extent=d3.extent(values.length?values:[0,1]);
 const y=d3.scaleLinear().domain(isMargin?[Math.min(0,extent[0])-30,Math.max(0,extent[1])+30]:[0,Math.max(1,extent[1])*1.08]).nice().range([h-margin.bottom,margin.top]);
 svg.append('g').attr('class','grid').attr('transform',`translate(${margin.left},0)`).call(d3.axisLeft(y).ticks(4).tickSize(-(w-margin.left-margin.right)).tickFormat(''));
 svg.append('g').attr('class','axis').attr('transform',`translate(${margin.left},0)`).call(d3.axisLeft(y).ticks(4).tickFormat(d3.format(isMargin?'+,':',')));
 const ticks=Array.from(new Set([0,...d3.ticks(0,last,Math.max(2,Math.floor(w/140))).map(Math.round),last]));
 svg.append('g').attr('class','axis').attr('transform',`translate(0,${h-margin.bottom})`).call(d3.axisBottom(x).tickValues(ticks).tickFormat(i=>i===0?'Start':new Date(state.history[i]?.time).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/New_York'})));
 if(isMargin)svg.append('line').attr('x1',margin.left).attr('x2',w-margin.right).attr('y1',y(0)).attr('y2',y(0)).attr('stroke','#92a3af').attr('stroke-dasharray','4 4');
 const labels=[];
 for(const s of series){const line=d3.line().defined(v=>v!==null).x((v,i)=>x(i)).y(v=>y(v));svg.append('path').datum(s.values).attr('class',s.model?'switch-model-line':s.dashed?'historical-line':'reported-line').attr('d',line).attr('fill','none').attr('stroke',s.color).attr('stroke-width',s.model?2.6:s.dashed?1.5:2.3).attr('stroke-dasharray',s.model?'2 5':s.dashed?'6 5':null).attr('opacity',s.model?.95:s.dashed?.5:1).append('title').text(s.model?'Hypothetical switching model':s.dashed?'Actual 2024 votes in the same towns':'Reported / entered 2026 votes');
  const v=s.values[selected];if(v!==null){svg.append('circle').attr('cx',x(selected)).attr('cy',y(v)).attr('r',s.model?4.5:s.dashed?3:4).attr('fill',s.model?'#10171d':s.color).attr('stroke',s.color).attr('stroke-width',s.model?2:0);if(!s.dashed)labels.push({y:y(v),color:s.color,text:`${s.short} ${isMargin?signed(v):fmt(v)}`});}
 }
 if(w>=620){labels.sort((a,b)=>a.y-b.y);let ly=margin.top-14;for(const l of labels){l.y=Math.max(l.y,ly+14);ly=l.y;}const overflow=Math.max(0,ly-(h-margin.bottom));for(const l of labels)svg.append('text').attr('x',w-margin.right+6).attr('y',l.y-overflow+4).attr('fill',l.color).attr('font-size',10).text(l.text);}
 svg.append('line').attr('class','cursor').attr('x1',x(selected)).attr('x2',x(selected)).attr('y1',margin.top).attr('y2',h-margin.bottom);
 svg.append('rect').attr('x',margin.left).attr('y',0).attr('width',w-margin.left-margin.right).attr('height',h).attr('fill','transparent').style('cursor','ew-resize').on('pointerdown',e=>{e.currentTarget.setPointerCapture(e.pointerId);move(e);}).on('pointermove',e=>{if(e.buttons)move(e);});
 function move(e){selected=Math.min(last,Math.max(0,Math.round(x.invert(d3.pointer(e)[0]))));draw();}
}
function drawCharts(){
 const totals=state.history.map(s=>M.totals(s.rows,keys));const series=candidates.map(c=>({color:c.color,short:c.key,values:totals.map(t=>t[c.key])}));
 const showSwitch=$('#switchOverlay').checked&&generalProjection;
 const switchTotals=showSwitch?state.history.map(s=>projectOSCAGeneral.footprintTotals(generalProjection,s.rows)):null;
 if(showSwitch)for(const c of candidates)if(generalProjection.results.some(r=>r.name===c.name))series.push({color:c.color,model:true,dashed:true,values:switchTotals.map(t=>t[c.name])});
 if($('#overlay').checked)for(const b of base.candidates){const match=candidates.find(c=>c.name===b.name);series.push({color:match?.color||(b.name.includes('Clarkson')?'#cfb886':'#8094ac'),dashed:true,values:state.history.map(s=>{const represented=new Set(s.rows.filter(r=>r.status!=='unreported').map(r=>r.town));return base.rows.filter(r=>represented.has(r.town)).reduce((n,r)=>n+(r.votes[b.key]||0),0);})});}
 chart('#votes',series,300);
 const focus=$('#focus').value,fc=candidates.find(c=>c.key===focus),pressure=[{color:fc.color,short:focus,values:totals.map(t=>M.margin(t,focus))}];
 if(showSwitch&&generalProjection.results.some(r=>r.name===fc.name))pressure.push({color:fc.color,model:true,dashed:true,values:switchTotals.map(t=>M.margin(t,fc.name))});
 if($('#overlay').checked&&state.comparators[focus])pressure.push({color:'#b8c2cd',dashed:true,values:state.history.map(s=>{const v={};for(const b of base.candidates){const reported=new Set(s.rows.filter(r=>r.status!=='unreported').map(r=>r.town));v[b.key]=base.rows.filter(r=>reported.has(r.town)).reduce((n,r)=>n+(r.votes[b.key]||0),0);}return M.margin(v,state.comparators[focus]);})});
 chart('#pressure',pressure,230,true);
 displaySync?.publish();
 $('#switchOverlayStatus').textContent=!$('#switchOverlay').checked?'Switching-model overlay off.':!generalProjection?'Switching-model overlay unavailable: resolve model input errors below.':`${fmt(generalProjection.switchers)} assumed switchers · ${fmt(generalProjection.turnout)} district scenario ballots · dotted lines sum full modeled town totals for the ${state.history[selected].rows.filter(r=>r.status!=='unreported').length} towns represented at this cursor. `+(generalProjection.results.some(r=>r.name===fc.name)?`${fc.name}: ${fmt(switchTotals[selected][fc.name])} modeled votes; margin ${signed(M.margin(switchTotals[selected],fc.name))} among six modeled nominees.`:'Joe Izzo has no switching-model projection.');
}
function drawModel(){
 const rows=state.history[selected].rows,scale=Number($('#scale').value),model=M.scenario(rows,base.rows,keys,scale/100),totals=M.totals(rows,keys),body=$('#modelTable tbody');body.replaceChildren();
 $('#modelStatus').textContent=!Number.isFinite(scale)||scale<1||scale>300?'Enter a turnout scale from 1% to 300%.':model?`Scenario only · ${model.complete}/25 complete towns · ${(model.coverage*100).toFixed(1)}% historical ballot coverage · ${fmt(36121*scale/100)} hypothetical district ballots. Remaining towns use pooled support from completed towns.`:'Awaiting at least one complete town with ballots and all candidate counts. No projection is inferred from missing results.';
 if(isDisplay)$('#modelStatus').textContent=model?`${model.complete}/25 complete towns · ${scale}% of 2024 turnout · hypothetical scenario`:'Awaiting complete town returns';
 const valid=model&&scale>=1&&scale<=300,ranked=valid?[...candidates].sort((a,b)=>model.votes[b.key]-model.votes[a.key]):candidates;
 for(const c of ranked){const tr=el('tr',null,body);el('td',c.name,tr).style.color=c.color;const reported=el('td',fmt(totals[c.key]),tr);reported.className='vote-cell';performanceBadge(reported,rows,c,true);el('td',valid?fmt(model.votes[c.key]):'—',tr);el('td',valid?String(1+candidates.filter(o=>model.votes[o.key]>model.votes[c.key]).length):'—',tr);
  if(isDisplay){const comparator=base.candidates.find(b=>b.key===state.comparators[c.key])?.name||'No comparator';tr.firstChild.title='2024 comparator: '+comparator;el('td',comparator,tr);continue;}
  const sel=el('select',null,el('td',null,tr));sel.setAttribute('aria-label',c.name+' 2024 comparator');option(sel,'','No comparator');for(const b of base.candidates)option(sel,b.key,b.name);sel.value=state.comparators[c.key];sel.addEventListener('change',()=>{state.comparators[c.key]=sel.value;persist();drawCharts();drawModel();updateEntryIndicators();});
 }
}
function houseChartSvg(parent,id,label){const node=document.createElementNS('http://www.w3.org/2000/svg','svg');node.id=id;node.setAttribute('role','img');node.setAttribute('aria-label',label);parent.append(node);return node;}
function drawHouse(){
 const snap=state.history[selected],bundle=snap.house,previous=state.history[Math.max(0,selected-1)].house,body=$('#houseCards');body.replaceChildren();
 const races=bundle?.races||houseCatalog.races;
 const jump=$('#houseJump');if(!jump.options.length){option(jump,'','Select a House race');for(const race of houseCatalog.races)option(jump,'house-'+race.key.toLowerCase().replace(/[^a-z0-9]+/g,'-'),race.name);jump.addEventListener('change',()=>{const target=document.getElementById(jump.value);if(target)target.scrollIntoView({block:'start'});});}
 $('#houseFeedStatus').textContent=(state.houseWarning?state.houseWarning+' Previous House results retained. ': '')+(isDemo?'SIMULATION · synthetic House votes. External-town reporting times are invented; no House forecast is implied.':bundle?`SOS ${bundle.official?'official':'unofficial'} · House feed fetched ${new Date(bundle.fetchedAt).toLocaleString('en-US',{timeZone:'America/New_York'})} ET.`:'No House feed saved at this reporting snapshot. Pull SOS results to begin.');
 for(const race of races){
  const id='house-'+race.key.toLowerCase().replace(/[^a-z0-9]+/g,'-'),card=el('section',null,body);card.className='panel house-race';card.id=id;
  const header=el('div',null,card);header.className='section-head';const title=el('div',null,header);el('h2',race.name,title);el('span',isDemo?'SIMULATION · SYNTHETIC RESULTS':bundle?(bundle.official?'SOS OFFICIAL':'SOS UNOFFICIAL'):'AWAITING SOS RESULTS',title).className='house-source-badge'+(isDemo?' synthetic':'');el('p',`${race.seats} seat${race.seats===1?'':'s'} · `+race.rows.map(r=>r.town.toLowerCase().replace(/\b\w/g,c=>c.toUpperCase())+(r.partialTown?' (part)':'')).join(' · '),title).className='house-note';
  const controls=el('label','Margin focus ',header);controls.className='house-controls';const focus=el('select',null,controls);focus.setAttribute('aria-label',race.name+' House margin focus');option(focus,'','Final-seat gap');for(const c of race.candidates)option(focus,c.key,c.name);
  const focusKey=race.candidates.some(c=>c.key===state.houseFocus?.[race.key])?state.houseFocus[race.key]:'';focus.value=focusKey;focus.addEventListener('change',()=>{state.houseFocus??={};state.houseFocus[race.key]=focus.value;persist();drawHouse();displaySync?.publish();});
  const layout=el('div',null,card);layout.className='house-layout';const mapPanel=el('div',null,layout),map=el('div',null,mapPanel);map.innerHTML='<svg class="house-map" role="img"></svg>';const svgNode=map.firstChild;svgNode.setAttribute('aria-label',race.name+' reporting map');
  const coverage=el('p',`${race.rows.filter(r=>r.status==='complete').length}/${race.rows.length} towns complete · ${race.rows.filter(r=>r.status==='partial').length} partial`,mapPanel);coverage.className='house-coverage';
  el('p','Green: complete · Gold: partial · Orange: new/revised · Gray: not reported',mapPanel).className='house-note';
  const townDetail=el('p','Select a town for its House results.',mapPanel);townDetail.className='house-town-detail';
  const outside=race.rows.filter(r=>!towns.includes(r.town)).map(r=>r.town.toLowerCase().replace(/\b\w/g,c=>c.toUpperCase()));
  if(outside.length)el('p','Includes the full House district, including '+outside.join(', ')+' outside the Windsor Senate district.',mapPanel).className='house-note';
  if(race.rows.some(r=>r.partialTown))el('p','Hartford outline shows the whole town; only this House district’s split is counted. Reporting may remain partial until all town splits report.',mapPanel).className='house-note';
  const features=houseGeo.features.filter(f=>race.rows.some(r=>r.town===f.properties.TOWNNAME.toUpperCase())),geoSubset={type:'FeatureCollection',features};
  const width=mapPanel.clientWidth||260,height=svgNode.clientHeight||280,svg=d3.select(svgNode).attr('viewBox',`0 0 ${width} ${height}`),path=d3.geoPath(d3.geoMercator().fitExtent([[16,16],[width-16,height-16]],geoSubset));
  const rowMap=new Map(race.rows.map(r=>[r.town,r])),oldRows=previous?.races?.find(r=>r.key===race.key)?.rows;
  svg.selectAll('path').data(features).join('path').attr('class','town').attr('tabindex',isDisplay?-1:0).attr('d',path).attr('fill',f=>{const r=rowMap.get(f.properties.TOWNNAME.toUpperCase()),old=oldRows?.find(o=>o.town===r.town);if(selected>0&&r.status!=='unreported'&&(!old||JSON.stringify([r.status,r.votes])!==JSON.stringify([old.status,old.votes])))return '#ff9a4d';return {complete:'#62c985',partial:'#e2c575',unreported:'#1d2630'}[r.status];}).attr('aria-label',f=>race.name+' '+f.properties.TOWNNAME+' '+rowMap.get(f.properties.TOWNNAME.toUpperCase()).status).on('click',(_,f)=>inspect(f)).on('keydown',(e,f)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();inspect(f);}}).append('title').text(f=>f.properties.TOWNNAME);
  function inspect(f){const row=rowMap.get(f.properties.TOWNNAME.toUpperCase());townDetail.textContent=`${row.town}${row.partialTown?' (House split only)':''}: ${row.status} · `+race.candidates.map(c=>`${c.name}: ${row.votes[c.key]==null?'—':fmt(row.votes[c.key])}`).join(' · ');}
  const labels=features.map(f=>{const [x,y]=path.centroid(f);return {x,y,name:f.properties.TOWNNAME.toLowerCase().replace(/\b\w/g,c=>c.toUpperCase())+(rowMap.get(f.properties.TOWNNAME.toUpperCase()).partialTown?' (part)':'')};});
  for(let pass=0;pass<30;pass++)for(let a=0;a<labels.length;a++)for(let b=a+1;b<labels.length;b++){const l=labels[a],r=labels[b],dy=16-Math.abs(l.y-r.y);if(Math.abs(l.x-r.x)<(l.name.length+r.name.length)*2.9&&dy>0){const direction=l.y<r.y?-1:1;l.y+=direction*dy/2;r.y-=direction*dy/2;}}
  svg.append('g').selectAll('text').data(labels).join('text').attr('class','house-map-label').attr('x',l=>Math.max(l.name.length*2.9+3,Math.min(width-l.name.length*2.9-3,l.x))).attr('y',l=>l.y).attr('dy','.35em').attr('text-anchor','middle').text(l=>l.name);
  const charts=el('div',null,layout);charts.className='house-charts';el('h3','Candidate totals',charts);const votesDiv=el('div',null,charts);houseChartSvg(votesDiv,id+'-votes',race.name+' cumulative House candidate totals');
  const marginTitle=el('h3',race.seats===2?'Two-seat margin':'One-seat margin',charts);marginTitle.style.marginTop='12px';const focusName=race.candidates.find(c=>c.key===focusKey)?.name;
  el('p',focusName?`${focusName} minus ${race.seats===2?'second':'first'}-highest other candidate`:`Final-seat gap: ${race.seats===2?'second minus third':'first minus second'} place.`,charts).className='house-margin-note';
  const marginDiv=el('div',null,charts);houseChartSvg(marginDiv,id+'-margin',race.name+' final-seat margin');
  const palette=['#62a8ff','#ff9a4d','#64d68b','#ff82bd','#b59cff','#4ddbd2','#c4cbd1'],colors=new Map(race.candidates.map((c,i)=>[c.key,palette[i%palette.length]]));
  const historicRaces=state.history.map(h=>h.house?.races?.find(r=>r.key===race.key)||null),historicTotals=historicRaces.map(r=>r?H.totals(r):null);
  chart('#'+id+'-votes',race.candidates.map(c=>({color:colors.get(c.key),short:c.name,values:historicTotals.map(t=>t?.[c.key]??null)})),210);
  const margins=historicTotals.map(t=>t?(focusKey?H.margin(t,focusKey,race.seats):H.seatGap(t,race.seats)?.value??null):null);
  chart('#'+id+'-margin',[{color:'#64d68b',short:focusName||'Final seat',values:margins}],150,true);
  if(!margins.some(v=>v!==null))d3.select('#'+id+'-margin').append('text').attr('x','50%').attr('y','45%').attr('text-anchor','middle').attr('fill','#a2b0bc').attr('font-size',11).text(race.candidates.length<=race.seats?'No named challenger for final seat':'Awaiting House returns');
  const summary=el('div',null,layout);summary.className='house-summary';el('h3','Reported House votes',summary);const table=el('table',null,summary);table.className='house-totals';const th=el('tr',null,el('thead',null,table));['Candidate','Votes'].forEach(v=>el('th',v,th));const tb=el('tbody',null,table),totals=H.totals(race);
  for(const c of [...race.candidates].sort((a,b)=>totals[b.key]-totals[a.key]||a.name.localeCompare(b.name))){const tr=el('tr',null,tb),name=el('td',null,tr);el('div',c.name,name).style.color=colors.get(c.key);el('div',c.party+(c.writeIn?' · named write-in':''),name).className='house-party';el('td',bundle?fmt(totals[c.key]):'—',tr);}
  const gap=H.seatGap(totals,race.seats),nameOf=key=>race.candidates.find(c=>c.key===key)?.name;
  el('p',gap?`Final-seat gap: ${fmt(gap.value)} votes · ${nameOf(gap.inside)} over ${nameOf(gap.outside)}${gap.value===0?' (tied)':''}.`:!Object.values(totals).some(v=>v>0)?'Awaiting reported House votes.':'No named challenger for the final seat; no competitive margin calculated.',summary).className='house-gap';
  const writeIns=race.rows.filter(r=>r.status!=='unreported').reduce((n,r)=>n+(r.otherWriteIns||0),0);el('p',`Other / unallocated write-ins: ${bundle?fmt(writeIns):'—'}. Shown separately, never treated as one candidate in the margin. Named write-ins are included. No winner is called.`,summary).className='house-note';
 }
}

function draw(){
 if(!state.history.length)return;const snap=state.history[selected];$('#timeline').max=state.history.length-1;$('#timeline').value=selected;
 const t=new Date(snap.time).toLocaleString('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
 $('#snapshotLabel').textContent=`${selected+1}/${state.history.length} · ${t} ET · ${snap.source}`;
 $('#modeBadge').textContent=isDemo?'SIMULATION':selected===state.history.length-1?'Latest snapshot':'Reviewing history';drawMap();drawCharts();drawModel();drawHouse();if(isDemo&&!isDisplay)renderEntry();displaySync?.publish();
}
$('#timeline').addEventListener('input',e=>{selected=Number(e.target.value);draw();});$('#focus').addEventListener('change',drawCharts);$('#overlay').addEventListener('change',drawCharts);$('#switchOverlay').addEventListener('change',drawCharts);$('#scale').addEventListener('input',()=>{drawModel();displaySync?.publish();});
async function refresh(){
 if(isDemo)return;
 if(busy)return;if(dirty){$('#feedStatus').textContent='SOS refresh paused: save or resolve unsaved table edits first.';return;}
 let incomingHouse=null,houseProblem='';
 busy=true;$('#refresh').disabled=true;$('#feedStatus').textContent='Reading official SOS election index, Senate results, House results, and turnout…';
 try{
  let data;
  if(window.OSCABridge.embedded)data=await window.OSCABridge.refresh();
  else{const response=await fetch('/api/sos',{cache:'no-store'});data=await response.json();if(!response.ok)throw Error(data.error||'SOS request failed');}
  if(data.year!==2026||!Array.isArray(data.rows)||!Array.isArray(data.candidates))throw Error('Unexpected SOS schema');
  houseProblem=data.houseError||'';if(data.house){try{incomingHouse=H.validate(data.house,houseCatalog);}catch(e){houseProblem='House update rejected: '+e.message;}}
  const idMap={};for(const c of data.candidates){const match=candidates.find(x=>c.name.toLowerCase()===x.name.toLowerCase());if(!match)throw Error('SOS candidate roster changed: '+c.name+'. Update adapter before applying.');idMap[c.key]=match.key;}
  if(new Set(Object.values(idMap)).size!==keys.length)throw Error('SOS roster is incomplete; prior results retained');
  const mapped=data.rows.map(r=>{const votes=Object.fromEntries(keys.map(k=>[k,null]));for(const [id,v] of Object.entries(r.votes)){if(idMap[id])votes[idMap[id]]=v;}return {...r,votes,source:data.official?'SOS official':'SOS unofficial',note:r.warning||''};});
  if(new Set(mapped.map(r=>r.town)).size!==mapped.length||mapped.some(r=>!towns.includes(r.town)))throw Error('Unexpected or duplicate SOS towns');
  for(const r of mapped){if(r.status==='complete'&&M.validate(r,keys).length)r.status='partial';if(M.validate(r,keys).some(e=>!e.includes('more votes')&&!e.includes('three times')))throw Error('Invalid SOS numbers');}
  // Inconsistent partial vote/turnout payloads keep vote counts but omit ballots until reconciled.
  for(const r of mapped)if(M.validate(r,keys).length){r.ballots=null;r.status='partial';r.note='SOS turnout and vote payloads are not yet synchronized';}
  const next=towns.map(t=>mapped.find(r=>r.town===t)||blank(t));
  const changed=JSON.stringify(state.official)!==JSON.stringify(next)||(incomingHouse&&JSON.stringify(state.house?.races)!==JSON.stringify(incomingHouse.races));state.official=next;if(incomingHouse)state.house=incomingHouse;state.houseWarning=houseProblem;
  if(changed)snapshot(data.official?'SOS official refresh':'SOS unofficial refresh',{feedUpdated:data.feedUpdated,urls:data.urls});else persist();
  renderEntry();drawHouse();$('#feedStatus').textContent=`SOS ${data.official?'official':'unofficial'} · feed updated ${data.feedUpdated||'not supplied'} (SOS label) · fetched ${new Date(data.fetchedAt).toLocaleString('en-US',{timeZone:'America/New_York'})} ET · ${changed?'new snapshot saved':'no changed results'} · ${Object.keys(state.manual).length} manual overrides retained. ${houseProblem||((incomingHouse?.races.length||0)+' House contests refreshed.')}`;
 }catch(e){if(incomingHouse){state.house=incomingHouse;snapshot('House SOS refresh · Senate update retained');$('#feedStatus').textContent='House results updated; previous Senate results retained. '+e.message;}else $('#feedStatus').textContent='SOS refresh failed; previous results retained. '+e.message;}
 finally{busy=false;$('#refresh').disabled=false;displaySync?.publish();}
}
$('#refresh').addEventListener('click',refresh);$('#auto').addEventListener('change',()=>{clearInterval(interval);if($('#auto').checked){refresh();interval=setInterval(refresh,60000);}});
$('#export').addEventListener('click',()=>{const blob=new Blob([JSON.stringify(state,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=(isDemo?'SIMULATION-':'')+'osca-session-'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);});
$('#import').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>30e6)throw Error('Session exceeds 30 MB');const imported=checkedSession(JSON.parse(await file.text()));if(!confirm('Replace this browser’s current session with this imported session? Export first if needed.'))return;state=imported;dirty=false;if(!state.history.length)snapshot('Imported session');selected=state.history.length-1;persist();renderEntry();draw();}catch(e){$('#errors').textContent='Import rejected: '+e.message;}finally{$('#import').value='';}});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
if(window.OSCABridge.embedded){
 $('#demoLink').addEventListener('click',e=>{e.preventDefault();window.OSCABridge.navigate(true);});
 $('#demoBanner a').addEventListener('click',e=>{e.preventDefault();window.OSCABridge.navigate(false);});
}
let playback=null;
function pause(){clearInterval(playback);playback=null;$('#playDemo').textContent='▶ Play simulation';}
$('#playDemo').addEventListener('click',()=>{if(playback){pause();return;}if(selected===state.history.length-1)selected=0;$('#playDemo').textContent='Ⅱ Pause simulation';draw();playback=setInterval(()=>{selected=Math.min(state.history.length-1,selected+1);draw();if(selected===state.history.length-1)pause();},2500);});
$('#restartDemo').addEventListener('click',()=>{pause();selected=0;draw();});
$('#timeline').addEventListener('input',pause);
const bh=el('tr',null,$('#baselineTable thead'));['Town','Ballots',...base.candidates.map(c=>c.name)].forEach(h=>el('th',h,bh));
const timingHead=el('tr',null,$('#timingTable thead'));['Town','First observed in primary replay','Recorded source'].forEach(h=>el('th',h,timingHead));
function drawCrossballot(){
 const percent=Number($('#crossAttribution').value),method=$('#crossBaseline').value,result=calculateOSCACrossballot(crossData,percent/100,method);
 $('#crossPercent').textContent=percent+'%';
 $('#crossSummary').textContent=`Hypothesis: approximately ${fmt(result.assumed)} switched ballots · ${(result.districtShare*100).toFixed(1)}% of all 2026 Democratic primary ballots · ${(result.targetShare*100).toFixed(1)}% of Democratic ballots in these eight towns.`;
 $('#crossCounterfactual').textContent=`Observed in the eight towns: Democratic ${fmt(result.d24)} → ${fmt(result.d26)}; Republican ${fmt(result.r24)} → ${fmt(result.r26)}. Under this assumption, district Democratic ballots excluding assumed switchers would be ${fmt(result.hypotheticalDistrictDem)}; Republican ballots in these towns would be ${fmt(result.hypotheticalTargetRep)} if every assumed switcher had instead taken an R ballot.`;
 $('#crossMethod').textContent=method==='flat'?'Baseline: no growth in non-switching Democratic participation since 2024. Every additional D ballot is eligible for your attribution assumption.':'Alternative baseline: non-switching D participation grows '+((result.naturalGrowth-1)*100).toFixed(1)+'%, matching the other 17 towns. Only each town’s positive excess above that expectation is eligible; negative excess is set to zero. This baseline is also an assumption.';
 const body=$('#crossTable tbody');body.replaceChildren();for(const r of [...result.rows,{town:'TOTAL',d24:result.d24,d26:result.d26,r24:result.r24,r26:result.r26,assumed:result.assumed}]){const tr=el('tr',null,body);for(const k of ['town','d24','d26','r24','r26','assumed'])el('td',k==='town'?r[k]:fmt(r[k]),tr);}
 drawGeneralProjection(result);
}
function drawGeneralProjection(cross){
 const body=$('#projectionTable tbody'),audit=$('#projectionAudit tbody');body.replaceChildren();audit.replaceChildren();$('#projectionErrors').textContent='';
 try{
  const scale=Number($('#projectionScale').value);if(!Number.isFinite(scale)||scale<50||scale>150)throw Error('Choose turnout from 50% to 150% of 2024.');
  const p=projectOSCAGeneral(primaryCandidates,base.rows,cross,scale/100,partyCalibration);
  generalProjection=p;
  $('#projectionStatus').textContent=`HISTORICAL-MULTIPLIER SCENARIO · D ${p.multipliers.D.toFixed(3)}× / R ${p.multipliers.R.toFixed(3)}× · ${fmt(p.switchers)} fixed assumed switchers, each selecting all three Republicans · ${fmt(p.turnout)} assumed district ballots. D selections removed before multiplication; returning switchers added after multiplication.`;
  for(const c of p.results){const tr=el('tr',null,body),actual=base.totals[c.name];for(const value of [c.name,fmt(c.noSwitch),fmt(c.projected),signed(c.delta),String(c.rank),actual===undefined?'—':fmt(actual)])el('td',value,tr);tr.firstChild.style.color=c.party==='D'?'#8cbfff':'#ffb09d';const a=el('tr',null,audit);for(const value of [c.name,fmt(c.raw),fmt(c.removed),fmt(c.ordinaryGeneral),fmt(c.switchGeneral)])el('td',value,a);}
  const focus=p.results.find(c=>c.name==='Elizabeth Burrows'),other=p.results.filter(c=>c.name!==focus.name).sort((a,b)=>b.projected-a.projected);
  $('#projectionMargin').textContent=`Under these assumptions only: Burrows’s margin over the third-highest other modeled candidate (${other[2].name}) is ${signed(focus.projected-other[2].projected)} votes. No winner is called.`;
 }catch(e){generalProjection=null;$('#projectionErrors').textContent=e.message;$('#projectionStatus').textContent='No scenario calculated';$('#projectionMargin').textContent='';}
 drawCharts();
}
$('#projectionScale').addEventListener('input',drawCrossballot);
$('#crossAttribution').addEventListener('input',drawCrossballot);$('#crossBaseline').addEventListener('change',drawCrossballot);drawCrossballot();
if(['#ballotSwitch','#generalProjection'].includes(location.hash)){$('#ballotSwitch').open=true;requestAnimationFrame(()=>$(location.hash).scrollIntoView());}
for(const r of primaryTiming.towns){const tr=el('tr',null,$('#timingTable tbody'));el('td',r.town,tr);el('td',r.first_observed_primary,tr);el('td',r.source_label,tr);}
for(const r of [...base.rows,{town:'DISTRICT TOTAL',ballots:36121,votes:Object.fromEntries(base.candidates.map(c=>[c.key,base.rows.reduce((s,r)=>s+(r.votes[c.key]||0),0)]))}]){const tr=el('tr',null,$('#baselineTable tbody'));el('td',r.town,tr);el('td',fmt(r.ballots),tr);for(const c of base.candidates)el('td',fmt(r.votes[c.key]||0),tr);}
if(!isDisplay)renderEntry();draw();
const settingIds=['focus','overlay','switchOverlay','scale','crossAttribution','crossBaseline','projectionScale'];
function displayPayload(){return {state,selected,settings:Object.fromEntries(settingIds.map(id=>[id,$('#'+id).type==='checkbox'?$('#'+id).checked:$('#'+id).value])),feedStatus:$('#feedStatus').textContent};}
displaySync=createOSCADisplaySync({key:STORE,isDisplay,read:displayPayload,onStatus:text=>{$('#displayConnection').textContent=text;},onUpdate:payload=>{
 const incoming=checkedSession(payload.state);if(!incoming.history.length)throw Error('Empty display history');
 state=incoming;selected=Math.min(state.history.length-1,Math.max(0,Number.isInteger(payload.selected)?payload.selected:state.history.length-1));
 for(const id of settingIds){const value=payload.settings?.[id],control=$('#'+id);if(control.type==='checkbox'){if(typeof value==='boolean')control.checked=value;}else if(typeof value==='string'&&value.length<100){if(control.tagName!=='SELECT'||[...control.options].some(o=>o.value===value))control.value=value;}}
 $('#feedStatus').textContent=typeof payload.feedStatus==='string'?payload.feedStatus:'';drawCrossballot();draw();
}});
const displayTarget=new URL(window.OSCABridge.embedded?(document.referrer||location.href):location.href);displayTarget.pathname=window.OSCABridge.embedded?'/':location.pathname;displayTarget.search='';displayTarget.hash='';displayTarget.searchParams.set('display','1');if(isDemo)displayTarget.searchParams.set('demo','1');
$('#openDisplay').href=displayTarget.href;
$('#openDisplay').addEventListener('click',()=>{
 displaySync.publish(true);
 $('#displayHelp').textContent='The results display opens separately. If your browser opens a tab, drag it into its own window or onto another screen. It follows this control panel in the same browser.';
});

let resize;new ResizeObserver(()=>{clearTimeout(resize);resize=setTimeout(draw,80);}).observe($('.layout'));
})().catch(e=>{document.querySelector('#feedStatus').textContent='App could not start: '+e.message;});
