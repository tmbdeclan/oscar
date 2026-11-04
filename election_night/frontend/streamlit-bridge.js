/* Streamlit components-v1 protocol adapter; inert in the standalone local app. */
(function(){
 const embedded=window.parent!==window, pending=new Map();let args={},mode=null,lastHeight=0;
 let resolveReady,readyRetry=null,readyAttempts=0;const ready=embedded?new Promise(resolve=>resolveReady=resolve):Promise.resolve({});
 const send=(type,fields={})=>window.parent.postMessage({isStreamlitMessage:true,type,...fields},'*');
 function height(){if(!embedded)return;const main=document.querySelector('main');const next=Math.ceil((main?.getBoundingClientRect().height||document.body.offsetHeight)+24);if(next!==lastHeight){lastHeight=next;send('streamlit:setFrameHeight',{height:next});}}
 if(embedded){
  window.addEventListener('message',event=>{
   if(event.source!==window.parent||event.data?.type!=='streamlit:render')return;
   if(readyRetry!==null&&status)status.textContent=initialStatus;
   clearInterval(readyRetry);readyRetry=null;
   args=event.data.args||{};
   if(mode!==null&&mode!==Boolean(args.demo)){location.reload();return;}
   mode=Boolean(args.demo);resolveReady(args);
   const response=args.sos_response;
   if(response&&pending.has(response.requestId)){const p=pending.get(response.requestId);clearTimeout(p.timer);pending.delete(response.requestId);if(response.error){const error=Error(response.error);error.timing=response.timing;p.reject(error);}else p.resolve(response.data);}
   height();
  });
  send('streamlit:componentReady',{apiVersion:1});
  // A cold hosted page can miss the initial component-ready message. Retry the
  // handshake until the parent supplies render arguments, without polling SOS.
  const status=document.querySelector('#feedStatus'),initialStatus=status?.textContent||'';if(status)status.textContent='Connecting to the hosted OSCA session…';
  readyRetry=setInterval(()=>{send('streamlit:componentReady',{apiVersion:1});if(++readyAttempts>=30){clearInterval(readyRetry);readyRetry=null;if(status)status.textContent='The hosted session has not connected. Reload this page to retry.';}},1000);
  new ResizeObserver(height).observe(document.querySelector('main'));
  window.addEventListener('load',height);window.addEventListener('resize',height);
 }
 window.OSCABridge={embedded,ready,get args(){return args;},
  refresh(knownVersion=null,force=false){
   if(!embedded)throw Error('Streamlit refresh is only available when embedded');
   const requestId=crypto.randomUUID();return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(requestId);reject(Error('SOS request timed out; previous results retained'));},95000);
    pending.set(requestId,{resolve,reject,timer});send('streamlit:setComponentValue',{dataType:'json',value:{action:'sos',requestId,knownVersion,force}});
   });
  },
  navigate(demo){send('streamlit:setComponentValue',{dataType:'json',value:{action:'mode',demo:Boolean(demo),requestId:crypto.randomUUID()}});}
 };
})();
