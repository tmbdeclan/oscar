const assert=require('node:assert/strict');
const M=require('../frontend/model.js');
const keys=['a','b','c','d'];
const baseline=[{town:'A',ballots:100},{town:'B',ballots:300}];
const row=(town,ballots,votes,status='complete')=>({town,ballots,votes,status});
assert.equal(M.scenario([],baseline,keys),null);
const a=row('A',50,{a:40,b:25,c:15,d:10});
assert.deepEqual(M.validate(a,keys),[]);
let s=M.scenario([a],baseline,keys);
assert.equal(s.votes.a,320); // 40/50 * (100 + 300)
assert.equal(s.coverage,.25);
const b=row('B',600,{a:120,b:400,c:300,d:100});
s=M.scenario([a,b],baseline,keys);
assert.equal(s.votes.a,140); // town reweighting: 80 + 60, not pooled district rate
assert.equal(s.votes.b,250);
assert.equal(s.complete,2);
assert.equal(M.scenario([a,b],baseline,keys,2).votes.a,280);
assert.equal(M.scenario([a,row('B',10,{a:10,b:0,c:0,d:0},'partial')],baseline,keys).votes.a,320);
assert(M.validate(row('A',10,{a:11,b:0,c:0,d:0}),keys).length);
assert(M.validate(row('A',10,{a:10,b:10,c:10,d:10}),keys).length);
assert(M.validate(row('A',10,{a:0,b:null,c:0,d:0}),keys).length);
assert.deepEqual(M.validate(row('A',10,{a:0,b:0,c:0,d:0}),keys),[]);
assert(M.validate(row('A',10,{a:-1,b:0,c:0,d:0}),keys).length);
assert(M.validate(row('A',10,{a:1.5,b:0,c:0,d:0}),keys).length);
assert.equal(M.margin({a:30,b:50,c:40,d:20},'a'),10);
assert.equal(M.margin({a:20,b:50,c:40,d:30},'a'),-10);
console.log('Model checks passed: reweighting, partial exclusion, vote-for-three validation, cutoff margins.');
// Historical support comparisons use current ballots and matching town footprints.
const historical=[{town:'A',ballots:100,votes:{old:50}},{town:'B',ballots:100,votes:{old:10}}];
const perf=(votes,ballots=100,status='complete')=>M.performance([row('A',ballots,{a:votes,b:0,c:0,d:0},status)],historical,keys,'a','old');
assert.equal(perf(50).level,0);
assert.equal(perf(51).level,0);
assert.equal(perf(52).level,1);
assert.equal(perf(55).level,2);
assert.equal(perf(48).level,1);
assert.equal(perf(45).level,2);
assert.equal(perf(45).direction,'lower');
assert.equal(perf(0).level,2); // Explicit zero is data, not missing.
assert.equal(perf(100,200).level,0); // Doubling turnout alone is neutral.
assert.equal(perf(50,100,'partial'),null);
assert.equal(perf(null),null);
assert.equal(perf(101),null);
assert.equal(M.performance([a],historical,keys,'a',''),null);
assert.equal(M.performance([a],historical,keys,'a','missing'),null);
assert.equal(M.performance([a],[{town:'A',ballots:0,votes:{old:0}}],keys,'a','old'),null);
const aggregate=M.performance([row('A',100,{a:50,b:0,c:0,d:0}),row('B',900,{a:90,b:0,c:0,d:0}),row('C',100,{a:100,b:0,c:0,d:0},'partial')],historical,keys,'a','old');
assert.equal(aggregate.expected,140);
assert.equal(aggregate.actual,140);
assert.equal(aggregate.ballots,1000);
assert.equal(aggregate.towns,2);
assert.equal(aggregate.level,0); // Town mix does not imply underperformance.
assert.equal(M.performance([row('A',100,{a:10,b:0,c:0,d:0})],[{town:'A',ballots:100,votes:{old:0}}],keys,'a','old').level,2);
console.log('Performance checks passed: thresholds, matched-town weighting, turnout normalization, explicit zero, missing and partial exclusion.');
