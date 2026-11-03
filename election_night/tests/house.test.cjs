const assert=require('node:assert/strict'),fs=require('node:fs'),H=require('../frontend/house.js');
const catalog=JSON.parse(fs.readFileSync('election_night/frontend/data/house-races.json')),geo=JSON.parse(fs.readFileSync('election_night/frontend/data/house-towns.geojson'));
assert.equal(catalog.races.length,13);
for(const race of catalog.races)for(const row of race.rows){assert.equal(row.status,'unreported');assert(Object.values(row.votes).every(v=>v===null));assert(geo.features.some(f=>f.properties.TOWNNAME.toUpperCase()===row.town));}
const votes={a:100,b:90,c:80,d:70};
assert.equal(H.margin(votes,'b',2),10);assert.equal(H.margin(votes,'c',2),-10);assert.equal(H.margin(votes,'a',2),20);
assert.equal(H.margin(votes,'b',1),-10);assert.equal(H.margin(votes,'missing',1),null);
assert.deepEqual(H.seatGap(votes,2),{value:10,inside:'b',outside:'c'});
assert.equal(H.seatGap({a:100,b:90},2),null);assert.equal(H.margin({a:100,b:90},'a',2),null);
assert.equal(H.seatGap({a:0,b:0},1),null);assert.equal(H.seatGap({a:100,b:80,c:80},2).value,0);
const before=JSON.stringify(catalog),history=Array.from({length:15},(_,i)=>({time:new Date(2026,10,3,19,i).toISOString(),rows:[...new Set(catalog.races.flatMap(r=>r.rows.map(t=>t.town)))].map(t=>({town:t,status:i?'complete':'unreported'}))}));
const demo=H.demo(catalog,history);for(const snapshot of demo)H.validate(snapshot,catalog);
assert.equal(JSON.stringify(catalog),before);assert(demo[0].races.every(r=>Object.values(H.totals(r)).every(v=>v===0)));
assert(demo.at(-1).races.every(r=>Object.values(H.totals(r)).some(v=>v>0)));
const invalid=structuredClone(demo.at(-1));invalid.races[0].rows[0].votes[invalid.races[0].candidates[0].key]=-1;assert.throws(()=>H.validate(invalid,catalog));
const missing=structuredClone(demo.at(-1));missing.races.pop();assert.throws(()=>H.validate(missing,catalog));
const renamed=structuredClone(demo.at(-1));renamed.races[0].name='<svg onload=alert(1)>';assert.throws(()=>H.validate(renamed,catalog));
const hartford=catalog.races.filter(r=>r.rows.some(t=>t.town==='HARTFORD'));assert.equal(hartford.length,2);assert(hartford.every(r=>r.rows.find(t=>t.town==='HARTFORD').partialTown));
console.log('House checks passed: 13 rosters, full district geography, 1/2-seat margins, ties, uncontested races, zero/no reports, demo isolation, and snapshot validation.');
