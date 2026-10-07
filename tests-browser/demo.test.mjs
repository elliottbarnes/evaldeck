import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {strictJSON,evaluate,pointer} from '../demo/core.mjs';
import {fixtures} from '../demo/fixtures.mjs';

test('all fixture checks and edge cases match the native Python evaluator',()=>{
  const cases=fixtures.flatMap(f=>['baseline','candidate'].map(which=>({output:f[which],checks:f.checks})));
  for(const output of ['{"x":true}','{"x":1}','{"x":null}','{"x":"1"}','{}','{"x":1,"x":2}','{"x":NaN}','{"x":"\\ud800"}','{"a/b":{"~key":[4]}}'])cases.push({output,checks:[{type:'json'},{type:'equals',path:'/x',value:1},{type:'number_range',path:'/x',min:0,max:2},{type:'equals',path:'/a~1b/~0key/0',value:4}]});
  cases.push({output:'[1,2]',checks:[{type:'equals',path:'/01',value:2},{type:'equals',path:'/1',value:2}]});
  const run=spawnSync(process.env.PYTHON||'python3',['-c',"import json,sys;sys.path.insert(0,'src');from evaldeck.checks import evaluate;print(json.dumps([[c['passed'] for c in evaluate(v['output'],v['checks'])] for v in json.load(sys.stdin)]))"],{input:JSON.stringify(cases),encoding:'utf8',timeout:20000});
  assert.equal(run.status,0,run.stderr);const native=JSON.parse(run.stdout);cases.forEach((v,i)=>assert.deepEqual(evaluate(v.output,v.checks).map(r=>r.passed),native[i],v.output));
  assert.equal(fixtures.filter(f=>evaluate(f.candidate,f.checks).every(c=>c.passed)).length,3);
});
test('strict JSON rejects duplicates, nonfinite numbers, surrogate errors and excess nesting',()=>{
  for(const s of ['{"a":1,"a":2}','{"a":"\\ud800"}','1e400','NaN','9007199254740993','[1,]','01','"bad\nstring"','['.repeat(130)+'0'+']'.repeat(130)])assert.throws(()=>strictJSON(s),s);
  assert.equal(strictJSON('"\\ud83d\\ude00"'),'😀');assert.equal(strictJSON('{"__proto__":3}').__proto__,3);assert.throws(()=>strictJSON(' '.repeat(20001)));
});
test('JSON pointers distinguish null, missing, object properties and array indexes',()=>{
  const value=strictJSON('{"x":null,"list":[1],"constructor":3}');assert.equal(pointer(value,'/x'),null);assert.equal(pointer(value,'/constructor'),3);for(const p of ['/missing','/list/01','/list/-1'])assert.throws(()=>pointer(value,p));
});
