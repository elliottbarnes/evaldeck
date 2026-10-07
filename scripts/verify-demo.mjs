import {readdir,readFile,lstat} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
const allowed=['.nojekyll', 'app.mjs', 'core.mjs', 'index.html', 'style.css', 'ui.mjs', 'fixtures.mjs'];
assert.deepEqual((await readdir('demo')).sort(),allowed.sort(),'Only reviewed static files may be deployed');
for(const file of allowed){assert.ok((await lstat('demo/'+file)).isFile(),'No symlinks or directories');if(file.endsWith('.mjs')){const check=spawnSync(process.execPath,['--check','demo/'+file],{encoding:'utf8'});assert.equal(check.status,0,check.stderr);}}
const html=await readFile('demo/index.html','utf8');assert.ok(html.includes("connect-src 'none'"));assert.ok(html.includes('lang="en"'));assert.ok(!/<script(?![^>]*src=)[^>]*>/i.test(html),'No inline scripts');
for(const match of html.matchAll(/(?:src|href)="([^"]+)"/g)){if(!match[1].startsWith('http')&&!match[1].startsWith('#'))assert.ok(allowed.includes(match[1]),'Missing local asset '+match[1]);}
console.log('Verified explicit static demo artifact, CSP, module syntax, and local asset links.');
