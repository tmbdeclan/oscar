/* Same-browser control/display transport. Displays never publish or save results. */
(function(root){
 root.createOSCADisplaySync=function({key,isDisplay,read,onUpdate,onStatus}){
  let channel=null,pending=null,lastReceived=0,lastPublished='',lastMessage=null,closed=false;
  const cacheKey=key+'-results-display',id=crypto.randomUUID();
  try{channel=new BroadcastChannel(cacheKey);}catch(e){}
  function send(message){try{channel?.postMessage({...message,sender:id});}catch(e){}}
  function receive(message,cached=false){
   if(!message||message.sender===id)return;
   if(!isDisplay){if(message.type==='request')publish(true);return;}
   if(message.type==='heartbeat'){lastReceived=Date.now();onStatus('Connected to control panel');return;}
   if(message.type!=='state'||message.messageId===lastMessage)return;lastMessage=message.messageId;
   try{onUpdate(message.payload);if(!cached)lastReceived=Date.now();onStatus(cached?'Saved display snapshot · waiting for control panel':'Connected to control panel');}catch(e){onStatus('Display update rejected · previous results retained');}
  }
  function publish(force=false){
   if(isDisplay||closed)return;
   clearTimeout(pending);
   pending=setTimeout(()=>{
    const payload=read(),serialized=JSON.stringify(payload);
    if(!force&&serialized===lastPublished)return;
    lastPublished=serialized;const message={type:'state',payload,sender:id,messageId:crypto.randomUUID()};
    send(message);try{localStorage.setItem(cacheKey,JSON.stringify(message));}catch(e){}
   },60);
  }
  if(channel)channel.onmessage=e=>receive(e.data);
  const storage=e=>{if(e.key===cacheKey&&e.newValue){try{receive(JSON.parse(e.newValue));}catch(err){}}};
  if(isDisplay){
   window.addEventListener('storage',storage);
   try{const cached=localStorage.getItem(cacheKey);if(cached)receive(JSON.parse(cached),true);}catch(e){}
   send({type:'request'});
   onStatus(lastReceived?'Connected to control panel':'Waiting for control panel · open the control panel in this browser');
  }else publish(true);
  const heartbeat=setInterval(()=>{
   if(isDisplay){if(!lastReceived||Date.now()-lastReceived>15000){onStatus('Control panel disconnected · showing last received snapshot');send({type:'request'});}}
   else if(channel)send({type:'heartbeat'});else publish(true);
  },5000);
  return {publish,close(){closed=true;clearTimeout(pending);clearInterval(heartbeat);channel?.close();window.removeEventListener('storage',storage);}};
 };
})(window);
