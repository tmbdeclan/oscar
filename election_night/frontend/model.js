/* Pure calculations shared by UI and meaningful regression tests. */
(function(root){
  function validate(row, keys){
    const errors=[];
    const integer=v=>Number.isSafeInteger(v)&&v>=0;
    if(row.ballots!==null&&!integer(row.ballots))errors.push('Ballots must be a nonnegative integer');
    for(const k of keys)if(row.votes[k]!=null&&!integer(row.votes[k]))errors.push('Votes must be nonnegative integers');
    if(row.status==='complete'&&(!(row.ballots>0)||keys.some(k=>row.votes[k]==null)))errors.push('Complete towns need positive ballots and every candidate count (use 0 explicitly)');
    if(row.ballots!==null){
      if(keys.some(k=>(row.votes[k]||0)>row.ballots))errors.push('A candidate cannot have more votes than ballots');
      if(keys.reduce((s,k)=>s+(row.votes[k]||0),0)>row.ballots*3)errors.push('Candidate votes cannot exceed three times ballots');
    }
    if(row.status==='unreported'&&(row.ballots>0||keys.some(k=>(row.votes[k]||0)>0)))errors.push('A town with counts must be partial or complete');
    return errors;
  }
  function scenario(rows,baseline,keys,scale=1){
    if(!Number.isFinite(scale)||scale<=0)return null;
    const complete=rows.filter(r=>r.status==='complete'&&validate(r,keys).length===0);
    const ballots=complete.reduce((s,r)=>s+r.ballots,0);
    if(!ballots)return null;
    const bases=new Map(baseline.map(r=>[r.town,r.ballots]));
    const known=new Set(complete.map(r=>r.town));
    const remaining=baseline.filter(r=>!known.has(r.town)).reduce((s,r)=>s+r.ballots,0)*scale;
    const projected={};
    for(const k of keys){
      const rate=complete.reduce((s,r)=>s+(r.votes[k]||0),0)/ballots;
      projected[k]=complete.reduce((s,r)=>s+(r.votes[k]||0)/r.ballots*bases.get(r.town)*scale,0)+rate*remaining;
    }
    return {votes:projected,complete:complete.length,coverage:complete.reduce((s,r)=>s+bases.get(r.town),0)/baseline.reduce((s,r)=>s+r.ballots,0),ballots,remaining};
  }
  function totals(rows,keys){return Object.fromEntries(keys.map(k=>[k,rows.filter(r=>r.status!=='unreported').reduce((s,r)=>s+(r.votes[k]||0),0)]));}
  function margin(votes,key){const other=Object.entries(votes).filter(([k])=>k!==key).map(([,v])=>v).sort((a,b)=>b-a);return (votes[key]||0)-(other[2]||0);}
  // Compare only complete, valid rows against their own historical support rates.
  // Candidate support is votes per ballot, not share of all candidate selections.
  function performance(rows,baseline,keys,candidate,comparator){
    if(!comparator)return null;
    const bases=new Map(baseline.map(r=>[r.town,r]));
    let ballots=0,actual=0,expected=0,towns=0;
    for(const row of rows){
      const b=bases.get(row.town),v=b?.votes?.[comparator];
      if(row.status!=='complete'||validate(row,keys).length||!Number.isSafeInteger(b?.ballots)||b.ballots<=0||!Number.isSafeInteger(v)||v<0||v>b.ballots)continue;
      if(!Number.isSafeInteger(row.votes[candidate]))continue;
      ballots+=row.ballots;actual+=row.votes[candidate];expected+=row.ballots*v/b.ballots;towns++;
    }
    if(!ballots)return null;
    const points=(actual-expected)/ballots*100,magnitude=Math.abs(points);
    const level=magnitude+1e-9>=5?2:magnitude+1e-9>=2?1:0;
    return {ballots,actual,expected,towns,points,level,direction:points>=0?'higher':'lower'};
  }
  const api={validate,scenario,totals,margin,performance};
  if(typeof module!=='undefined')module.exports=api;else root.OSCAModel=api;
})(typeof window!=='undefined'?window:globalThis);
