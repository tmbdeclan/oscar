const assert=require('node:assert/strict'),T=require('../frontend/feed-timing.js');
const t={publishedAt:'2026-11-04T00:00:00+00:00',lastCheckedAt:'2026-11-04T00:04:00+00:00',estimatedNextAt:'2026-11-04T00:05:00+00:00',sourceCacheSeconds:60,cadenceBasis:'assumed five-minute cadence'};
let d=T.describe(t,Date.parse('2026-11-04T00:04:15Z'),{watching:true});assert(d.published.includes('7:00:00 PM'));assert(d.next.includes('0m 45s'));assert.equal(d.watch,'Checking every 15 seconds');assert(d.note.includes('estimate'));
d=T.describe(t,Date.parse('2026-11-04T00:06:00Z'),{watching:true});assert(d.next.includes('window passed'));assert(d.watch.includes('delayed'));
assert(T.describe({...t,error:'Network error'},Date.now()).checked.includes('failed'));
assert.equal(T.describe({},Date.now(),{demo:true,watching:true}).watch,'Simulation · polling off');
assert.equal(T.describe({publishedAt:'invalid'}).published,'Not checked yet');
assert.equal(T.describe(t).watch,'Automatic checks off');
console.log('Feed timing checks passed: Eastern timestamps, estimated countdown, overdue window, delayed checks, errors, and demo isolation.');
