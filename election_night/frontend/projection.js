/* Historical party-multiplier sensitivity scenario. No win probability. */
(function(root){
 const nominees={D:['Rebecca White','Joe Major','Elizabeth Burrows'],R:['Andrea Murray','Jack Williams','Jonathan Gleason']};
 function project(primary,baseline,cross,scale=1,calibration){
  if(!Number.isFinite(scale)||scale<=0)throw Error('Turnout scale must be positive');
  if(!calibration?.parties?.D||!calibration?.parties?.R)throw Error('2024 party calibration is required');
  const switched=new Map(cross.rows.map(r=>[r.town,r.assumed]));
  const switchers=[...switched.values()].reduce((s,v)=>s+v,0),turnout=baseline.reduce((s,r)=>s+r.ballots,0)*scale,ordinaryBallots=turnout-switchers;
  if(ordinaryBallots<=0)throw Error('Target turnout must exceed assumed switchers');
  const results=Object.entries(nominees).flatMap(([party,names])=>names.map(name=>{
   const raw=primary.totals[party][name];
   if(!Number.isFinite(raw))throw Error('Missing primary votes for '+name);
   let removed=0;
   for(const town of primary.towns){const s=switched.get(town.town)||0;if(s<0||s>town.D.ballots)throw Error('Invalid switching pool for '+town.town);if(party==='D')removed+=s*(town.D.votes[name]||0)/town.D.ballots;}
   const multiplier=calibration.parties[party].multiplier,retainedPrimary=raw-removed,ordinaryGeneral=retainedPrimary*multiplier*scale,switchGeneral=party==='R'?switchers:0;
   return {name,party,raw,removed,retainedPrimary,multiplier,ordinaryGeneral,switchGeneral,projected:ordinaryGeneral+switchGeneral,noSwitch:raw*multiplier*scale};
  }));
  if(results.some(c=>c.ordinaryGeneral>ordinaryBallots+1e-6||c.ordinaryGeneral<0))throw Error('Candidate projection exceeds available ballots; revise assumptions');
  if(results.reduce((s,c)=>s+c.ordinaryGeneral,0)>3*ordinaryBallots+1e-6)throw Error('Projected choices exceed the vote-for-three ballot budget; revise assumptions');
  // Turnout-weighted visualization allocation, not a prediction of candidate town geography.
  // Fixed switching votes stay in their assumed towns; ordinary totals use remaining ballot weights.
  const towns=baseline.map(t=>{
   const s=switched.get(t.town)||0,target=t.ballots*scale;if(target<s)throw Error('Turnout below assumed switchers in '+t.town);
   const weight=(target-s)/ordinaryBallots;
   return {town:t.town,target,switched:s,weight,votes:Object.fromEntries(results.map(c=>[c.name,c.ordinaryGeneral*weight+(c.party==='R'?s:0)]))};
  });
  const ranked=results.sort((a,b)=>b.projected-a.projected);
  ranked.forEach(c=>{c.rank=1+ranked.filter(o=>o.projected>c.projected).length;c.delta=c.projected-c.noSwitch;});
  return {results:ranked,towns,turnout,switchers,multipliers:{D:calibration.parties.D.multiplier,R:calibration.parties.R.multiplier}};
 }
 project.footprintTotals=function(projection,rows){
  const included=new Set(rows.filter(r=>r.status!=='unreported').map(r=>r.town));
  return Object.fromEntries(projection.results.map(c=>[c.name,projection.towns.filter(t=>included.has(t.town)).reduce((s,t)=>s+t.votes[c.name],0)]));
 };
 if(typeof module!=='undefined')module.exports=project;else root.projectOSCAGeneral=project;
})(typeof window!=='undefined'?window:globalThis);
