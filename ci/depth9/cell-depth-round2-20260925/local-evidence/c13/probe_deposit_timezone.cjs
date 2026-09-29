const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('go/application/frontend/consumer/rental-deposit.js','utf8');
const declaration=source.match(/const utcDate=value=>\{[\s\S]*?\n  \};/)[0];
const utcDate=vm.runInNewContext(declaration+' utcDate;');
for (const value of ['2026-09-26T09:00:00','2026-09-26T09:00:00Z','2026-09-26T17:00:00+08:00']) assert.equal(utcDate(value).toISOString(),'2026-09-26T09:00:00.000Z');
assert.throws(()=>utcDate('invalid'));
console.log(JSON.stringify({timezone:process.env.TZ,tests:4,status:'PASS',source_sha256:require('node:crypto').createHash('sha256').update(source).digest('hex')}));
