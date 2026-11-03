/* House-contest validation and seat-aware arithmetic; no winner calls. */
(function(root){
 const integer=v=>Number.isSafeInteger(v)&&v>=0;
 function validate(bundle,catalog){
  if(!bundle||!Array.isArray(bundle.races)||bundle.races.length!==catalog.races.length)throw Error('Incomplete House contest set');
  const seen=new Set();
  for(const race of bundle.races){
   const expected=catalog.races.find(r=>r.key===race.key);
   if(!expected||seen.has(race.key)||race.seats!==expected.seats)throw Error('Unknown or duplicate House contest');seen.add(race.key);
   if(!Array.isArray(race.candidates)||!race.candidates.length||race.candidates.length>80||new Set(race.candidates.map(c=>c.key)).size!==race.candidates.length)throw Error('Invalid House roster');
   for(const c of race.candidates)if(typeof c.key!=='string'||!/^\d+$/.test(c.key)||typeof c.name!=='string'||c.name.length>200||typeof c.party!=='string'||c.party.length>100)throw Error('Invalid House candidate');
   const towns=new Set(expected.rows.map(r=>r.town)),keys=race.candidates.map(c=>c.key);
   if(!Array.isArray(race.rows)||race.rows.length!==towns.size||new Set(race.rows.map(r=>r.town)).size!==towns.size)throw Error('Missing or duplicate House town');
   for(const row of race.rows){
    if(!towns.has(row.town)||!['unreported','partial','complete'].includes(row.status)||!row.votes||Object.keys(row.votes).some(k=>!keys.includes(k))||keys.some(k=>row.votes[k]!=null&&!integer(row.votes[k]))||!integer(row.otherWriteIns??0))throw Error('Invalid House town counts');
    if(row.status==='complete'&&keys.some(k=>!integer(row.votes[k])))throw Error('Complete House town has missing counts');
    if(row.status==='unreported'&&(Object.values(row.votes).some(v=>v>0)||row.otherWriteIns>0))throw Error('Unreported House town has votes');
   }
  }
  return bundle;
 }
 function totals(race){return Object.fromEntries(race.candidates.map(c=>[c.key,race.rows.filter(r=>r.status!=='unreported').reduce((n,r)=>n+(r.votes[c.key]??0),0)]));}
 function margin(votes,key,seats){
  if(!Object.hasOwn(votes,key))return null;
  const other=Object.entries(votes).filter(([k])=>k!==key).map(([,v])=>v).sort((a,b)=>b-a);
  if(other.length<seats||!Object.values(votes).some(v=>v>0))return null;
  return (votes[key]??0)-other[seats-1];
 }
 function seatGap(votes,seats){
  const ranked=Object.entries(votes).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));
  if(ranked.length<=seats||!ranked.some(([,v])=>v>0))return null;
  return {value:ranked[seats-1][1]-ranked[seats][1],inside:ranked[seats-1][0],outside:ranked[seats][0]};
 }
 function demo(catalog,history){
  const first=new Map();history.forEach((h,i)=>h.rows.filter(r=>r.status!=='unreported').forEach(r=>{if(!first.has(r.town))first.set(r.town,i);}));
  return history.map((h,index)=>({source:'SIMULATION · synthetic House votes; external-town timing invented',official:false,fetchedAt:h.time,races:catalog.races.map(race=>({...race,candidates:race.candidates.map(c=>({...c})),rows:race.rows.map(row=>{
   const hash=[...row.town].reduce((n,c)=>n+c.charCodeAt(0),0),start=first.get(row.town)??(1+hash%Math.max(1,history.length-2)),reported=index>=start;
   const share=row.partialTown?(race.key==='WDR 4'?.16:.84):1,ballots=Math.round((row.baselineBallots||500)*.84*share);
   const rates=race.seats===2?[.64,.46,.43,.35]:[.55,.42,.02];
   const votes=Object.fromEntries(race.candidates.map((c,i)=>[c.key,reported?Math.round(ballots*Math.min(.9,Math.max(.01,(rates[i]??.01)+(i%2?-1:1)*(hash%9-4)*.007))):0]));
   return {...row,status:reported?'complete':'unreported',ballots:reported?ballots:null,votes,otherWriteIns:0};
  })}))}));
 }
 const api={validate,totals,margin,seatGap,demo};if(typeof module!=='undefined')module.exports=api;else root.OSCAHouse=api;
})(typeof window!=='undefined'?window:globalThis);
