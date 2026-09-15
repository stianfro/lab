import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {scryptSync} from 'node:crypto';
import {spawn} from 'node:child_process';

test('all document endpoints require a session; unsafe originals are downloads; logout revokes access',async()=>{
 const root=mkdtempSync(join(tmpdir(),'fc-portal-test-'));mkdirSync(join(root,'files'));
 const link='a'.repeat(44),base='/accountant/'+link,origin='https://accounting.froystein.jp';
 writeFileSync(join(root,'auth.json'),JSON.stringify({link,origin,users:[{username:'test',salt:'test-salt',hash:scryptSync('test-password','test-salt',64).toString('hex')}]}));
 writeFileSync(join(root,'manifest.json'),JSON.stringify({updated:'test',questions:['<script>'],documents:[{id:'one',file:'one.pdf',name:'日本語.pdf',mime:'application/pdf',title:'<script>alert(1)</script>',group:'経費・請求書・領収証'},{id:'two',file:'two.html',name:'original.html',mime:'text/html',group:'区分・重複の確認用'}]}));
 writeFileSync(join(root,'files/one.pdf'),'%PDF-test-original');writeFileSync(join(root,'files/two.html'),'<script>evil()</script>');writeFileSync(join(root,'all.zip'),'zip-test');
 const port=18189;const server=spawn(process.execPath,[new URL('./server.mjs',import.meta.url).pathname],{env:{...process.env,PORT:String(port),AUTH_FILE:join(root,'auth.json'),DATA_DIR:root},stdio:'pipe'});
 const get=(path,options={})=>fetch('http://127.0.0.1:'+port+path,options);
 try{
  let ready=false;for(let n=0;n<50;n++){try{ready=(await get('/healthz')).ok;if(ready)break;}catch{}await new Promise(r=>setTimeout(r,50));}assert.ok(ready);
  assert.equal((await get('/')).status,404);assert.equal((await get('/accountant/wrong/')).status,404);
  for(const path of ['/', '/file/one','/all.zip']){const r=await get(base+path);assert.match(await r.text(),/ログイン/);assert.match(r.headers.get('cache-control'),/no-store/);}
  assert.equal((await get(base+'/')).headers.get('referrer-policy'),'same-origin');
  assert.equal((await get(base+'/login',{method:'POST',headers:{Origin:'null'},body:'username=test&password=test-password'})).status,403);
  assert.equal((await get(base+'/login',{method:'POST',headers:{Origin:'https://untrusted.example'},body:'username=test&password=test-password'})).status,403);
  assert.equal((await get(base+'/login',{method:'POST',body:'username=test&password=test-password'})).status,403);
  assert.equal((await get(base+'/login',{method:'POST',headers:{Origin:origin},body:'username=test&password=bad'})).status,401);
  const logged=await get(base+'/login',{method:'POST',headers:{Origin:origin},body:'username=test&password=test-password',redirect:'manual'});assert.equal(logged.status,303);
  const set=logged.headers.get('set-cookie');for(const flag of ['HttpOnly','Secure','SameSite=Strict'])assert.ok(set.includes(flag));const Cookie=set.split(';')[0];
  const page=await get(base+'/',{headers:{Cookie}});const content=await page.text();assert.ok(content.includes('&lt;script&gt;'));assert.ok(!content.includes('<script>'));
  const pdf=await get(base+'/file/one',{headers:{Cookie}});assert.equal(await pdf.text(),'%PDF-test-original');assert.match(pdf.headers.get('content-disposition'),/^inline/);
  const unsafe=await get(base+'/file/two',{headers:{Cookie}});assert.match(unsafe.headers.get('content-disposition'),/^attachment/);assert.match(unsafe.headers.get('content-security-policy'),/sandbox/);
  assert.equal(await(await get(base+'/all.zip',{headers:{Cookie}})).text(),'zip-test');
  assert.equal((await get(base+'/file/unknown',{headers:{Cookie}})).status,404);
  await get(base+'/logout',{method:'POST',headers:{Origin:origin,Cookie},redirect:'manual'});assert.match(await(await get(base+'/file/one',{headers:{Cookie}})).text(),/ログイン/);
  let last;for(let i=0;i<16;i++)last=await get(base+'/login',{method:'POST',headers:{Origin:origin},body:'username=test&password=bad'});assert.equal(last.status,429);
 }finally{server.kill();rmSync(root,{recursive:true,force:true});}
});
