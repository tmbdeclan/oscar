/* Source timestamps and explicitly estimated release timing, independent of results. */
(function(root){
 function describe(timing,now=Date.now(),{demo=false,watching=false}={}){
  timing=timing&&typeof timing==='object'?timing:{};
  const stamp=value=>typeof value==='string'&&Number.isFinite(Date.parse(value))?Date.parse(value):null;
  const time=ms=>new Date(ms).toLocaleString('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit'})+' ET';
  if(demo)return {published:'Simulation — no SOS data',checked:'Not checked in simulation',next:'Not estimated in simulation',watch:'Simulation · polling off',note:'Synthetic data remains separate from the live feed.'};
  const published=stamp(timing.publishedAt),checked=stamp(timing.lastCheckedAt),next=stamp(timing.estimatedNextAt);
  let nextText='Waiting for a publication timestamp';
  if(next!==null){const remaining=Math.ceil((next-now)/1000);nextText=remaining>0?time(next)+` · about ${Math.floor(remaining/60)}m ${remaining%60}s`:'Estimated window passed · awaiting SOS';}
  return {published:published===null?(timing.feedUpdated?String(timing.feedUpdated)+' (SOS label)':'Not checked yet'):time(published),
   checked:checked===null?'Not checked yet':time(checked)+(timing.error?' · failed':''),next:nextText,
   watch:watching?(checked!==null&&now-checked>45000?'Watching · last check delayed':'Checking every 15 seconds'):'Automatic checks off',
   note:'Next release is an estimate ('+(timing.cadenceBasis||'assumed five-minute cadence')+'). '+(Number.isFinite(timing.sourceCacheSeconds)?`SOS advertises up to ${timing.sourceCacheSeconds}s of public caching; publication visibility may lag.`:'SOS caching may delay publication visibility.')};
 }
 const api={describe};if(typeof module!=='undefined')module.exports=api;else root.OSCAFeedTiming=api;
})(typeof window!=='undefined'?window:globalThis);
