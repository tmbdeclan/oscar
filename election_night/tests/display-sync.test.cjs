const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const code=fs.readFileSync('election_night/frontend/display-sync.js','utf8'),peers=[],contexts=[],store=new Map();let now=1000,ids=0,writes=0;
class Channel{constructor(name){this.name=name;peers.push(this);}postMessage(data){for(const peer of peers)if(peer!==this&&!peer.closed&&peer.name===this.name)peer.onmessage?.({data:structuredClone(data)});}close(){this.closed=true;}}
function runtime(withChannel=true){
 const timers=new Map(),intervals=new Map(),listeners=new Map(),owner={};contexts.push({owner,listeners});
 const context={window:owner,crypto:{randomUUID:()=>String(++ids)},Date:{now:()=>now},JSON,BroadcastChannel:withChannel?Channel:class{constructor(){throw Error('Unavailable');}},
 setTimeout:fn=>{const id=++ids;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),setInterval:fn=>{const id=++ids;intervals.set(id,fn);return id;},clearInterval:id=>intervals.delete(id),
 localStorage:{getItem:key=>store.get(key)||null,setItem(key,value){store.set(key,value);writes++;for(const c of contexts)if(c.owner!==owner)c.listeners.get('storage')?.({key,newValue:value});}}};
 owner.addEventListener=(name,fn)=>listeners.set(name,fn);owner.removeEventListener=name=>listeners.delete(name);
 vm.runInNewContext(code,context);
 return {create:owner.createOSCADisplaySync,flush(){const work=[...timers.values()];timers.clear();work.forEach(fn=>fn());},tick(){[...intervals.values()].forEach(fn=>fn());}};
}
const a=runtime(),b=runtime();let payload={selected:3,settings:{scale:'90'},state:{demo:false}},received=[],status='';
const controller=a.create({key:'live',isDisplay:false,read:()=>payload,onUpdate:()=>assert.fail('Control cannot receive display state'),onStatus:()=>{}});a.flush();
const display=b.create({key:'live',isDisplay:true,read:()=>assert.fail('Display cannot publish'),onUpdate:v=>received.push(v),onStatus:v=>status=v});a.flush();
assert.equal(received.at(-1).selected,3);
assert.equal(status,'Connected to control panel');
payload={...payload,selected:4,settings:{scale:'100'}};controller.publish();a.flush();
assert.equal(received.at(-1).selected,4);assert.equal(received.at(-1).settings.scale,'100');
const before=writes;display.publish(true);b.flush();assert.equal(writes,before);
const other=runtime();let crossed=false;other.create({key:'demo',isDisplay:true,read:()=>{},onUpdate:()=>crossed=true,onStatus:()=>{}});controller.publish(true);a.flush();assert.equal(crossed,false);
controller.close();now+=16000;b.tick();assert(status.includes('disconnected'));
display.close();
// Storage-only fallback stays connected and synchronizes without BroadcastChannel.
const c=runtime(false),d=runtime(false);let fallbackValue,warning;
const fallback=c.create({key:'fallback',isDisplay:false,read:()=>({selected:9}),onUpdate:()=>{},onStatus:()=>{}});c.flush();
d.create({key:'fallback',isDisplay:true,read:()=>{},onUpdate:v=>fallbackValue=v,onStatus:v=>warning=v});
now+=6000;c.tick();c.flush();assert.equal(fallbackValue.selected,9);assert.equal(warning,'Connected to control panel');fallback.close();
console.log('Display sync checks passed: startup, settings, read-only behavior, demo isolation, disconnect status, storage fallback.');
