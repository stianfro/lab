import http from 'node:http';
import {readFileSync, createReadStream, statSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {randomBytes, scryptSync, timingSafeEqual, createHash} from 'node:crypto';

const config=JSON.parse(readFileSync(process.env.AUTH_FILE||'/run/auth/auth.json'));
const dataDir=resolve(process.env.DATA_DIR||'/data');
const manifest=JSON.parse(readFileSync(join(dataDir,'manifest.json')));
const base='/accountant/'+config.link;
if(!/^[A-Za-z0-9_-]{40,}$/.test(config.link)||!config.origin?.startsWith('https://'))throw Error('Invalid access configuration');
const sessions=new Map(), attempts=new Map();
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const html=(title,body)=>`<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow,noarchive"><title>${esc(title)}</title><body>${body}</body></html>`;
const cookieName='__Secure-fc_portal';
function headers(res){
 res.setHeader('Cache-Control','private, no-store, max-age=0');res.setHeader('Pragma','no-cache');
 res.setHeader('X-Robots-Tag','noindex, nofollow, noarchive');res.setHeader('Referrer-Policy','no-referrer');
 res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('X-Frame-Options','DENY');
 res.setHeader('Content-Security-Policy',"default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; sandbox allow-forms allow-same-origin allow-downloads");
 res.setHeader('Strict-Transport-Security','max-age=31536000');
}
function send(res,status,body,type='text/html; charset=utf-8'){res.writeHead(status,{'Content-Type':type});res.end(body);}
function redirect(res,path){res.writeHead(303,{Location:path});res.end();}
function login(res,message='',status=200){send(res,status,html('資料閲覧ログイン',`<h1>資料閲覧ログイン</h1><p>${esc(message)}</p><form method="post" action="${base}/login"><p><label>ユーザー名 / Username <input name="username" autocomplete="username" required maxlength="80"></label></p><p><label>パスワード / Password <input name="password" type="password" autocomplete="current-password" required maxlength="200"></label></p><button>ログイン / Log in</button></form>`));}
async function body(req){let s='';for await(const chunk of req){s+=chunk;if(Buffer.byteLength(s)>4096)throw Error('Body too large');}return new URLSearchParams(s);}
function session(req){const token=(req.headers.cookie||'').split(';').map(s=>s.trim()).find(s=>s.startsWith(cookieName+'='))?.slice(cookieName.length+1);const key=token&&createHash('sha256').update(token).digest('hex');const s=sessions.get(key);return s&&s.until>Date.now()?{...s,key}:null;}
function file(res,doc,download){
 const path=resolve(dataDir,'files',doc.file);if(!path.startsWith(dataDir+'/files/')||!statSync(path).isFile())throw Error('Invalid document path');
 const safeInline=['application/pdf','image/png','image/jpeg'].includes(doc.mime);
 res.setHeader('Content-Disposition',`${download||!safeInline?'attachment':'inline'}; filename="document.${doc.file.split('.').pop()}"; filename*=UTF-8''${encodeURIComponent(doc.name)}`);
 res.writeHead(200,{'Content-Type':doc.mime,'Content-Length':statSync(path).size});createReadStream(path).pipe(res);
}
function index(res,url){
 const q=(url.searchParams.get('q')||'').slice(0,150);const docs=manifest.documents.filter(d=>[d.title,d.date,d.note,d.name].join(' ').toLowerCase().includes(q.toLowerCase()));
 const table=group=>`<h2>${esc(group)}</h2><table border="1" cellpadding="5"><thead><tr><th>日付</th><th>資料</th><th>金額（原通貨）</th><th>確認事項</th><th>操作</th></tr></thead><tbody>${docs.filter(d=>d.group===group).map(d=>`<tr><td>${esc(d.date||'未確認')}</td><td>${esc(d.title)}</td><td>${esc(d.amount||'—')}</td><td>${esc(d.note)}</td><td><a href="${base}/file/${d.id}">開く</a> <a href="${base}/file/${d.id}?download=1">保存</a></td></tr>`).join('')}</tbody></table>`;
 send(res,200,html('FC3 決算資料',`<h1>株式会社フロイスタインコンサルティング 第3期 決算資料</h1><p>対象期間：2025年8月1日〜2026年7月31日</p><p><strong>準備中・税理士確認用</strong> — ${esc(manifest.updated)}時点。申告・承認済みの決算書ではありません。</p><p>原本${manifest.documents.length}件。第4期の資料は含みません。金額は原通貨の資料記載額であり、経費合計・損金算入額を表しません。</p><p><a href="${base}/all.zip">全資料をまとめて保存（ZIP）</a></p><form method="get" action="${base}/"><label>資料を検索 <input name="q" value="${esc(q)}"></label> <button>検索</button> <a href="${base}/">すべて表示</a></form><h2>確認をお願いしたいこと</h2><ul>${manifest.questions.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>${['通帳・銀行原本','経費・請求書・領収証','区分・重複の確認用'].map(table).join('')}<p>原本は変更せず保存しています。検索中もZIPには全資料が入ります。CSV・HTML・HEIFはダウンロードしてご確認ください。</p><form method="post" action="${base}/logout"><button>ログアウト</button></form>`));
}
const server=http.createServer(async(req,res)=>{
 headers(res);
 try{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/healthz'&&req.method==='GET')return send(res,200,'ok','text/plain');
  if(url.pathname!==base&&!url.pathname.startsWith(base+'/'))return send(res,404,'Not found','text/plain');
  if(!['GET','HEAD','POST'].includes(req.method))return send(res,405,'Method not allowed','text/plain');
  if(req.method==='POST'&&req.headers.origin!==config.origin)return send(res,403,'Forbidden','text/plain');
  if(url.pathname===base+'/login'&&req.method==='POST'){
   const now=Date.now();const ip=req.socket.remoteAddress||'unknown';
   const key=ip;const a=attempts.get(key)||{count:0,until:now+900000};if(a.until<now){a.count=0;a.until=now+900000;}a.count++;attempts.set(key,a);
   if(a.count>15){res.setHeader('Retry-After','900');return login(res,'しばらく待ってから再度お試しください。',429);}
   const form=await body(req);const user=config.users.find(u=>u.username===form.get('username')&&!u.disabled);const candidate=scryptSync((form.get('password')||'').slice(0,200),user?.salt||'invalid-user-salt',64);
   if(!user||!timingSafeEqual(candidate,Buffer.from(user.hash,'hex')))return login(res,'ユーザー名またはパスワードをご確認ください。',401);
   const token=randomBytes(32).toString('base64url');sessions.set(createHash('sha256').update(token).digest('hex'),{user:user.username,until:now+8*3600000});
   res.setHeader('Set-Cookie',`${cookieName}=${token}; Path=${base}/; Max-Age=28800; HttpOnly; Secure; SameSite=Strict`);return redirect(res,base+'/');
  }
  const auth=session(req);
  if(!auth)return req.method==='GET'||req.method==='HEAD'?login(res):send(res,401,'Unauthorized','text/plain');
  if(url.pathname===base+'/logout'&&req.method==='POST'){sessions.delete(auth.key);res.setHeader('Set-Cookie',`${cookieName}=; Path=${base}/; Max-Age=0; HttpOnly; Secure; SameSite=Strict`);return redirect(res,base+'/');}
  if(req.method!=='GET'&&req.method!=='HEAD')return send(res,405,'Method not allowed','text/plain');
  if(url.pathname===base+'/all.zip'){const path=join(dataDir,'all.zip');res.writeHead(200,{'Content-Type':'application/zip','Content-Disposition':'attachment; filename="FC3-documents.zip"','Content-Length':statSync(path).size});return createReadStream(path).pipe(res);}
  if(url.pathname.startsWith(base+'/file/')){const id=url.pathname.slice((base+'/file/').length);const doc=manifest.documents.find(d=>d.id===id);return doc?file(res,doc,url.searchParams.has('download')):send(res,404,'Not found','text/plain');}
  if(url.pathname===base||url.pathname===base+'/')return index(res,url);
  send(res,404,'Not found','text/plain');
 }catch{if(!res.headersSent)send(res,400,'Request failed','text/plain');else res.destroy();}
});
server.requestTimeout=15000;server.headersTimeout=10000;
setInterval(()=>{const now=Date.now();for(const[k,s]of sessions)if(s.until<now)sessions.delete(k);for(const[k,a]of attempts)if(a.until<now)attempts.delete(k);},60000).unref();
server.listen(Number(process.env.PORT||8080),'0.0.0.0');
