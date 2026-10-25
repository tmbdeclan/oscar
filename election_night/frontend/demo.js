/* Deterministic synthetic election-night fixture. NOT a forecast or SOS data. */
(function(root){
 function makeDemo(baseline,keys,blank,timing){
  const towns=baseline.map(r=>r.town);
  if(!timing?.snapshots?.length)throw Error('Primary timing fixture is missing');
  const first=new Map(timing.towns.map(t=>[t.town,t]));
  const final=new Map(baseline.map((b,i)=>{
   const ballots=Math.round(b.ballots*(.76+(i%5)*.035)),wave=Math.sin((i+2)*1.7);
   const rates={White:.56,Major:.49,Burrows:.43+.14*wave,Murray:.44-.10*wave,Williams:.35,Gleason:.31,Izzo:.025};
   return [b.town,{town:b.town,status:'complete',ballots,votes:Object.fromEntries(keys.map(k=>[k,Math.round(ballots*rates[k])])),source:'SIMULATION — synthetic',note:`Primary first observed: ${first.get(b.town).first_observed_primary}. Counts and completion status are synthetic, not primary results.`}];
  }));
  const history=[{time:'2026-11-03T19:00:00-05:00',source:'SIMULATION · empty starting point (invented)',rows:towns.map(blank)}];
  for(const [index,snap] of timing.snapshots.entries()){
   const match=snap.label.match(/(\d+):(\d+)\s*(AM|PM)/),hour=Number(match[1])%12+(match[3]==='PM'?12:0);
   const date=snap.label.startsWith('Aug 12')?'2026-11-04':'2026-11-03';
   const represented=new Set(snap.towns);
   history.push({time:`${date}T${String(hour).padStart(2,'0')}:${match[2]}:00-05:00`,source:'SIMULATION · primary timing '+snap.label,
    primarySource:snap.source,primaryLabel:snap.label,
    rows:towns.map(t=>{
     if(!represented.has(t))return {...blank(t),source:'SIMULATION — not reported'};
     const r=structuredClone(final.get(t));
     // Hartford has a later recorded update. The revision magnitude is invented;
     // primary snapshot metadata does not establish its completion percentage.
     const lastUpdate=timing.snapshots.reduce((last,s,i)=>s.current.includes(t)?i:last,-1);
     if(index<lastUpdate){r.ballots=Math.floor(r.ballots*.94);r.votes=Object.fromEntries(keys.map(k=>[k,Math.floor(r.votes[k]*.94)]));r.note+=' Later update staged with invented 94% counts; not an observed primary fraction.';}
     return r;
    })});
  }
  return history;
 }
 if(typeof module!=='undefined')module.exports=makeDemo;else root.makeOSCADemo=makeDemo;
})(typeof window!=='undefined'?window:globalThis);
