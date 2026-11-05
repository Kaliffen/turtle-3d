// Drives real Chrome on the real GPU over the DevTools protocol: measures frame times and takes screenshots.
// node tools/check.mjs <outDir>
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = resolve(process.argv[2] || join(root, '.cache', 'shots')); mkdirSync(out, { recursive: true });
const profile = join(tmpdir(), `t3-prof-${Date.now()}`);
const port = 9333;
const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
  `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
  '--window-size=1920,1080', '--window-position=0,0', '--force-device-scale-factor=1',
  '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
  '--ignore-gpu-blocklist', ...(process.env.HEADED ? [] : ['--headless=new', '--use-angle=d3d11']), 'about:blank'], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
let target;
for (let i = 0; i < 40 && !target; i++) { await sleep(500);
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === 'page'); } catch {} }
if (!target) throw new Error('no chrome');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const wait = new Map(); const logs = [];
ws.onmessage = m => { const d = JSON.parse(m.data);
  if (d.id && wait.has(d.id)) { wait.get(d.id)(d); wait.delete(d.id); }
  if (d.method === 'Runtime.consoleAPICalled' && ['error','warning'].includes(d.params.type)) logs.push(d.params.type+': '+d.params.args.map(a => a.value ?? a.description).join(' ').slice(0,500));
  if (d.method === 'Runtime.exceptionThrown') logs.push('EXC: '+JSON.stringify(d.params.exceptionDetails).slice(0,500)); };
const send = (method, params = {}) => new Promise(r => { const i = ++id; wait.set(i, r); ws.send(JSON.stringify({ id:i, method, params })); });
const ev = async expr => { const r = await send('Runtime.evaluate', { expression: expr, returnByValue:true, awaitPromise:true });
  if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0,600)); return r.result?.result?.value; };
const shot = async name => { await ev('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  const r = await send('Page.captureScreenshot', { format:'jpeg', quality:88 }); writeFileSync(join(out, name+'.jpg'), Buffer.from(r.result.data, 'base64')); console.log('shot', name); };

await send('Runtime.enable'); await send('Page.enable');
await send('Page.bringToFront');
const t0 = Date.now();
await send('Page.navigate', { url: (process.env.BASE || pathToFileURL(join(root,'index.html')).href) + `?nofocus&noadapt&city=${process.env.CITY || 'paris'}` });
for (let i = 0; i < 480; i++) { await sleep(500); if (await ev('!!window.__ready')) break;
  if (i % 20 === 19) console.log(' loading', await ev("document.getElementById('loadMsg')?.textContent"), await ev("document.getElementById('bar')?.style.width")); }
const ready = await ev('!!window.__ready');
console.log('ready', ready, `${((Date.now()-t0)/1000).toFixed(1)}s`);
if (!ready) { console.log(logs.join('\n')); await shot('fail'); ws.close(); chrome.kill(); process.exit(1); }
console.log('gpu', await ev(`(()=>{const g=__t3.renderer.getContext(),e=g.getExtension('WEBGL_debug_renderer_info');return g.getParameter(e.UNMASKED_RENDERER_WEBGL)})()`));
console.log('size', await ev('[innerWidth,innerHeight,devicePixelRatio].join("x")'));
await sleep(1500); // let the fade-out finish before timing

const A = JSON.parse(await ev('JSON.stringify(__t3.landmark)'));
const hi = +(await ev(`document.getElementById('alt').textContent`));
// frame timing around the whole loop
const measure = expr => ev(`new Promise(res=>{ ${expr}; let prev=performance.now(),ts=[],t0=prev;
  function f(now){ ts.push(now-prev); prev=now; if(now-t0<4000) requestAnimationFrame(f); else {ts.shift(); ts.sort((a,b)=>a-b);
    const avg=ts.reduce((a,b)=>a+b)/ts.length; const i=__t3.renderInfo();
    res({fps:+(1000/avg).toFixed(1),p99:+ts[Math.floor(ts.length*.99)].toFixed(1),max:+ts.at(-1).toFixed(1),tris:i.triangles,calls:i.calls})} }
  requestAnimationFrame(f); })`);
for (const u of [.05,.3,.55,.8]) console.log(`u=${u} alt=${hi}`, JSON.stringify(await measure(`__t3.set(${u},${hi})`)));
const city = process.env.CITY || 'paris';
for (const [n,u,alt] of [['a',.02,hi],['b',.3,hi*.6],['c',.65,hi*.35]]) { await ev(`__t3.set(${u},${alt})`); await sleep(150); await shot(`${city}_${n}`); }
// first landmark, closest to screen centre
const u = await ev(`(()=>{ const [,la,lo]=__t3.landmark, [x,z]=__t3.world(la,lo); let best=0,bd=9;
  for(let u=0;u<1;u+=.002){ __t3.set(u,${hi*.55}); __t3.camera.updateMatrixWorld(); const p=__t3.camera.position.clone().set(x,60,z).project(__t3.camera);
    const d=Math.hypot(p.x,p.y); if(p.z<1&&d<bd){bd=d;best=u;} } return best; })()`);
await ev(`__t3.set(${u},${hi*.55})`); await sleep(150); await shot(`${city}_landmark`); console.log('landmark', A[0], 'u', u);

// optional close-up: JUMP=lat,lon,alt
if (process.env.JUMP) { const [la,lo,al] = process.env.JUMP.split(',').map(Number);
  await ev(`(()=>{const [x,z]=__t3.world(${la},${lo}); __t3.jump(x,z+${al}*.62,${al},-1.02,0);})()`); await sleep(150); await shot(`${city}_jump`); await ev('__t3.freeze(false)'); }

// play the game through the real input box
await ev(`__t3.set(.02,${hi})`);
const answer = await ev('__t3.answer');
const play = async name => { await ev(`(()=>{const q=document.getElementById('q'); q.value=${JSON.stringify(name)}; q.dispatchEvent(new Event('input')); q.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));})()`); await sleep(1500); };
const hud = () => ev(`JSON.stringify({alt:document.getElementById('alt').textContent,count:document.getElementById('count').textContent,rows:[...document.querySelectorAll('.row')].map(r=>r.innerText.replace(/\\s+/g,' ')),end:getComputedStyle(document.getElementById('end')).display})`);
console.log('start', await hud());
await play('tokyo'); console.log('tokyo', await hud());
await play('rome'); console.log('rome', await hud());
await play('nonsense-city'); console.log('invalid', await hud());
await play(answer.toLowerCase()); await sleep(1000); console.log('answer', await hud());
await shot(`${city}_won`);
// free flight, driven with real key events after the round has ended
const key = (type, code, extra = {}) => send('Input.dispatchKeyEvent', { type, code, key: extra.key || code, windowsVirtualKeyCode: extra.vk || 0, modifiers: extra.modifiers || 0 });
const cam = async () => JSON.parse(await ev('JSON.stringify({x:__t3.camera.position.x,y:__t3.camera.position.y,z:__t3.camera.position.z,on:__t3.free.on,rx:__t3.camera.rotation.x,ry:__t3.camera.rotation.y})'));
const dist = (a,b) => Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z);
await send('Emulation.setFocusEmulationEnabled', { enabled:true });
const c0 = await cam();
console.log('plane still flying before input:', !c0.on);
await key('rawKeyDown','KeyW',{key:'w',vk:87}); await sleep(1500); await key('keyUp','KeyW',{key:'w',vk:87}); await sleep(50);
const c1 = await cam();
await key('rawKeyDown','ShiftLeft',{key:'Shift',vk:16,modifiers:8}); await key('rawKeyDown','KeyW',{key:'w',vk:87,modifiers:8}); await sleep(1500);
await key('keyUp','KeyW',{key:'w',vk:87,modifiers:8}); await key('keyUp','ShiftLeft',{key:'Shift',vk:16}); await sleep(50);
const c2 = await cam();
console.log('free on:', c1.on, 'W moved', Math.round(dist(c0,c1)), 'm; Shift+W moved', Math.round(dist(c1,c2)), 'm');
await sleep(1500); const c3 = await cam(); await sleep(400); const c4 = await cam(); console.log('stopped after release:', Math.round(dist(c3,c4)*10)/10, 'm in 0.4 s');
console.log('panel hidden while flying:', await ev(`getComputedStyle(document.getElementById('panel')).display==='none'`));
await key('rawKeyDown','Escape',{key:'Escape',vk:27}); await key('keyUp','Escape',{key:'Escape',vk:27}); await sleep(100);
console.log('Esc brings the panel back:', await ev(`getComputedStyle(document.getElementById('panel')).display!=='none'`));
await send('Input.dispatchMouseEvent',{type:'mousePressed',x:300,y:300,button:'left',clickCount:1}); await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:300,y:300,button:'left',clickCount:1}); await sleep(400);
console.log('click captures pointer:', await ev(`document.pointerLockElement===document.querySelector('canvas')`), 'flying:', await ev(`document.body.classList.contains('flying')`));
if (await ev(`!!document.pointerLockElement`)) { const b = await cam(); await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:420,y:260}); await sleep(100); const a = await cam(); console.log('locked mouse look works:', a.ry !== b.ry); await ev('document.exitPointerLock()'); await sleep(150); console.log('release brings the panel back:', await ev(`getComputedStyle(document.getElementById('panel')).display!=='none'`)); }
// mouse: drag falls back when pointer lock is refused
const my0 = await cam();
await ev(`document.querySelector('canvas').dispatchEvent(new MouseEvent('mousemove',{bubbles:true,buttons:1,movementX:300,movementY:-200}))`);
const my1 = await cam(); console.log('mouse look changed yaw/pitch:', my1.ry !== my0.ry && my1.rx !== my0.rx);
// floor clamp, then views at the extremes
await ev(`(()=>{__t3.camera.position.y=-500})()`); await sleep(100); const fl = await cam(); console.log('ground clamp keeps camera above -500 request: y', Math.round(fl.y));
const view = async (name, la, lo, agl, pitch, yaw) => { await ev(`(()=>{const [x,z]=__t3.world(${la},${lo}); __t3.camera.position.set(x,__t3.camera.position.y*0+${agl}+${hi>0?0:0}+40,z); __t3.camera.rotation.set(${pitch},${yaw},0);})()`); await sleep(400); await shot(name); };
const [,la,lo] = A;
await view(`${city}_free_low`, la-.004, lo, 90, -.22, 0);
await view(`${city}_free_sky`, la-.004, lo, 500, .35, .8);
console.log('free low-level', JSON.stringify(await measure(`0`)));
console.log('console:', logs.slice(0,12).join('\n') || 'clean');
ws.close(); chrome.kill(); await sleep(800);
try { rmSync(profile, { recursive:true, force:true, maxRetries:3 }); } catch {}
process.exit(0);
