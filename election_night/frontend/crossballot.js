/* Aggregate sensitivity model: attribution assumptions are not inferred voter identities. */
(function(root){
 function calculate(data,attribution=1,method='flat'){
  if(!Number.isFinite(attribution)||attribution<0||attribution>1)throw Error('Attribution must be between 0 and 1');
  if(!['flat','district-growth'].includes(method))throw Error('Unknown baseline');
  const target=data.towns.filter(r=>r.rshare>data.threshold),other=data.towns.filter(r=>r.rshare<=data.threshold);
  const sum=(rows,k)=>rows.reduce((s,r)=>s+r[k],0);
  const naturalGrowth=method==='district-growth'?sum(other,'d26')/sum(other,'d24'):1;
  const rows=target.map(r=>({...r,expected:r.d24*naturalGrowth,excess:Math.max(0,r.d26-r.d24*naturalGrowth),assumed:Math.max(0,r.d26-r.d24*naturalGrowth)*attribution}));
  const assumed=sum(rows,'assumed');
  return {rows,assumed,naturalGrowth,excess:sum(rows,'excess'),d24:sum(target,'d24'),d26:sum(target,'d26'),r24:sum(target,'r24'),r26:sum(target,'r26'),
   districtShare:assumed/data.district['2026'].dem,
   targetShare:assumed/sum(target,'d26'),
   hypotheticalDistrictDem:data.district['2026'].dem-assumed,hypotheticalDistrictRep:data.district['2026'].rep+assumed,
   hypotheticalTargetRep:sum(target,'r26')+assumed};
 }
 if(typeof module!=='undefined')module.exports=calculate;else root.calculateOSCACrossballot=calculate;
})(typeof window!=='undefined'?window:globalThis);
