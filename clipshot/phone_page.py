# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""The page "Photo from phone" for the phone's browser (served by phone.Receiver, nothing from the internet).

Why <input type="file" capture="environment"> and not the camera inside the page: a page from
http://192.168.x.x is not a secure context, browsers give it no getUserMedia (and no WebCrypto). The file input
with `capture` is not restricted to secure contexts: the round button opens the phone's own camera app, the photo
comes back to the page as a file. Details and sources: specs/.../foto-s-telefona/bezopasnost.md, section 4.

The page is one file: styles and the script inline with a nonce (Content-Security-Policy of phone.py), no fonts,
no links, no counters. After the camera (or the gallery) the photo is shown big with three buttons: "Send to
computer", "Retake", "Close". Before it is shown the photo is drawn into a canvas and saved as JPEG: that drops
EXIF with the GPS position, turns HEIC of an iPhone into JPEG and makes 50 MP photos smaller. Two sizes, a switch on
the page (remembered in localStorage): "Fit to computer screen" (default: scaled to fit the screen of the computer,
which tells its size, never enlarged) and "Original" (full size up to 60 MP). Sending shows "Sending... N %" with a
bar (XMLHttpRequest upload progress) and "Cancel". If the browser cannot draw the photo, a JPEG, PNG or WebP goes as it
is (phone.py checks the type again). If a key is lost (a response got lost, "Cancel" just as the computer took the
photo) the page asks /<code>/key for a fresh one before the next upload.
Texts: clipshot/i18n/<lang>/phone.json, keys phone.page_*; the window passes them in (phone_ui.page_texts).
"""

import html
import json

THEME_LIGHT = "#eceff3"       # the bar of the phone browser matches the page (light / dark theme of ClipSD)
THEME_DARK = "#111315"
PHOTO_SIDE = 2560          # when the computer did not tell its screen size: long side at most this
ORIGINAL_PIXELS = 60_000_000   # "Original": no downscale below this many pixels (phone.MAX_PIXELS)

_STYLE = """
/* The look of the ClipSD windows (1.32, skill desktop-app-design, palette of the card windows): a card with a header
   (the program logo, a bold title), a thin rule, steps in round numbered dots (blue now, green tick done, grey later),
   status rows, one green main button, quiet other buttons, an amber one for warnings. The dark theme follows the phone. */
:root{color-scheme:light dark;
  --page:#eceff3;--card:#ffffff;--edge:#d9dee6;--text:#16181c;--muted:#5a6270;--line:#c8d0db;--field:#ffffff;
  --soft:#f1f4f8;--track:#e3e8ef;--accent:#1e78ff;--link:#1660d0;--stage:#34383e;--rule:#e6e9ee;
  --green:#157a40;--green-hover:#126b38;--green-border:#0f5c30;--dot-now:#1660d0;--dot-todo:#5f6875;
  --ok-text:#157a40;--err-text:#b42318;--err-dot:#c0392b;--amber-dot:#f59e0b;
  --warn-bg:#fff5d6;--warn-edge:#efd27e;--warn-text:#4a3a06;--shadow:rgba(0,0,0,.12);
  --abtn-bg:#fff6e6;--abtn-text:#8a5200;--abtn-edge:#e0b572}
@media (prefers-color-scheme:dark){:root{
  --page:#111315;--card:#25282c;--edge:#3a3f46;--text:#f1f3f5;--muted:#aab1ba;--line:#4a5058;--field:#1d2023;
  --soft:#2f3338;--track:#3a3f46;--accent:#2d8ceb;--link:#58a4f2;--stage:#111315;--rule:#33383f;
  --dot-now:#2d8ceb;--dot-todo:#6a7480;
  --ok-text:#5fd08a;--err-text:#ff8a80;--err-dot:#ff8a80;--amber-dot:#f2c14e;
  --warn-bg:#3a3016;--warn-edge:#6b5619;--warn-text:#f5e3b0;--shadow:rgba(0,0,0,.4);
  --abtn-bg:#3a3016;--abtn-text:#f5e3b0;--abtn-edge:#6b5619}}
*{box-sizing:border-box}
/* Everything is in rem, and rem follows the width of the page: 18 px at 412 CSS px (a phone), proportionally more
   in the "Desktop site" mode of a phone browser (a layout 980 px wide, the viewport meta is ignored there). */
html{font-size:clamp(16px,4.37vw,44px)}
html,body{margin:0;min-height:100%;background:var(--page);color:var(--text);-webkit-text-size-adjust:100%}
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans",sans-serif;font-size:1rem;line-height:1.45}
main{min-height:100vh;min-height:100dvh;display:flex;flex-direction:column;max-width:28rem;margin:0 auto;padding:.7rem}
.card{flex:1;display:flex;flex-direction:column;background:var(--card);border:1px solid var(--edge);border-radius:.8rem;
  box-shadow:0 .7rem 2rem var(--shadow),0 1px 3px var(--shadow);}
.head{display:flex;align-items:center;gap:.8rem;padding:1.1rem 1.1rem .9rem}
.head img{width:2.7rem;height:2.7rem;display:block;flex:none}
.name{font-size:1.2rem;font-weight:700;line-height:1.25}
.sub{font-size:.9rem;color:var(--muted);margin-top:.15rem}
.rule{height:1px;background:var(--rule);margin:0 1.1rem}
.rows{padding:.6rem 1.1rem 0;display:flex;flex-direction:column;gap:.15rem}
.chip{display:flex;align-items:center;gap:.55rem;margin:0;font-size:.95rem;font-weight:500;color:var(--muted);text-align:left}
.chip::before{content:"";flex:none;width:.6rem;height:.6rem;border-radius:50%;background:var(--ok-text)}
.chip.ok{color:var(--muted)}
.chip.err{color:var(--err-text)}.chip.err::before{background:var(--err-dot)}
.chip.warn{color:var(--warn-text);background:var(--warn-bg);border:1px solid var(--warn-edge);border-radius:.5rem;padding:.5rem .7rem}
.chip.warn::before{background:var(--amber-dot)}
#qline{display:none}
.small{display:none;margin:0;font-size:.85rem;color:var(--muted);padding-left:1.15rem}
.small.amber{color:var(--warn-text);background:var(--warn-bg);border:1px solid var(--warn-edge);border-radius:.4rem;padding:.2rem .6rem}
h1{display:none;font-size:1.35rem;line-height:1.25;margin:1rem 1.1rem .4rem;text-wrap:balance}
[data-state=offline] h1,[data-state=closed] h1,[data-state=offer] h1,[data-state=ask] h1{display:block}
p{margin:0 0 .65rem;color:var(--muted);font-size:1rem}
#steps{display:none;flex-direction:column;padding:.4rem 1.1rem 1.1rem}
[data-state=wait] #steps,[data-state=processing] #steps,[data-state=ready] #steps,[data-state=sending] #steps,[data-state=sent] #steps{display:flex}
.step{display:flex;gap:.9rem;padding:.9rem 0}
.dot{flex:none;width:1.9rem;height:1.9rem;border-radius:50%;background:var(--dot-todo);color:#fff;font-weight:700;font-size:1rem;
  display:flex;align-items:center;justify-content:center}
#d1::before{content:"1"}#d2::before{content:"2"}
[data-state=wait] #d1,[data-state=processing] #d1,[data-state=sent] #d1,[data-state=ready] #d2,[data-state=sending] #d2{background:var(--dot-now)}
[data-state=ready] #d1,[data-state=sending] #d1,[data-state=sent] #d2{background:var(--green)}
[data-state=ready] #d1::before,[data-state=sending] #d1::before,[data-state=sent] #d2::before{content:"\\2713"}
.sb{flex:1;min-width:0}
.stitle{font-size:1.1rem;font-weight:700;line-height:1.3;margin-top:.2rem}
[data-state=wait] #s2 .stitle,[data-state=processing] #s2 .stitle{color:var(--muted);font-weight:600}
.sep{height:1px;background:var(--rule)}
#intro{display:block}
[data-state=ready] #intro,[data-state=sending] #intro,[data-state=sent] #intro,[data-state=processing] #intro,
[data-state=offline] #intro,[data-state=closed] #intro,[data-state=offer] #intro{display:none}
#view{display:none;padding:.7rem 0 0}
[data-state=ready] #view,[data-state=sending] #view{display:block}
#preview,#preview2{display:block;max-width:100%;max-height:34vh;border-radius:.5rem;border:1px solid var(--edge);background:var(--stage);margin:0 auto}
#preview{display:none}
[data-state=ready] #preview,[data-state=sending] #preview{display:block}
#dims{color:var(--muted);font-size:.85rem;text-align:center;margin:.35rem 0 0}
button,label{font:inherit}
.bar{display:none;flex-direction:column;align-items:stretch;gap:.6rem;padding:.8rem 0 0}
.btn{display:flex;align-items:center;justify-content:center;text-align:center;min-height:3.2rem;border-radius:.5rem;
  font-size:1.05rem;font-weight:600;padding:.6rem .9rem;border:1px solid var(--line);background:var(--field);
  color:var(--text);cursor:pointer;width:100%;-webkit-tap-highlight-color:transparent}
.btn:active{background:var(--soft)}
.btn.main{background:var(--green);color:#fff;border-color:var(--green-border);font-weight:700;min-height:3.5rem;font-size:1.1rem}
.btn.main:active{background:var(--green-hover)}
.btn.big{min-height:4.6rem;font-size:1.2rem}
.btn.amber{background:var(--abtn-bg);color:var(--abtn-text);border-color:var(--abtn-edge);font-weight:700}
[data-state=wait] #startbar,[data-state=ready] #readybar,[data-state=sending] #sendingbar,[data-state=sent] #sentbar{display:flex}
#note{color:var(--muted);font-size:.85rem;text-align:left;margin:.3rem 0 0}
.linkbtn{background:none;border:0;color:var(--link);font-size:.95rem;padding:.55rem;cursor:pointer;text-decoration:underline;align-self:center}
#smallrow{display:flex;justify-content:space-between}
/* the panel with the send buttons: fixed at the bottom while the photo is ready, so it is never below the fold */
[data-state=ready] #readybar{position:fixed;left:50%;bottom:0;transform:translateX(-50%);width:min(100%,28rem);z-index:5;
  background:var(--card);border-top:1px solid var(--edge);padding:.6rem 1rem calc(.4rem + env(safe-area-inset-bottom));gap:.5rem;
  box-shadow:0 -.4rem 1rem var(--shadow);border-radius:.8rem .8rem 0 0}
[data-state=ready] #d2,[data-state=ready] #s2>.sb>.stitle,[data-state=ready] .sep{display:none}
[data-state=ready] #s2{padding:0;gap:0}
[data-state=ready] #steps{padding-bottom:.4rem}
.phead{display:none;align-items:center;gap:.7rem}
[data-state=ready] .phead{display:flex}
.dotnow{width:1.6rem;height:1.6rem;font-size:.9rem;background:var(--dot-now)}
.phead .stitle{margin:0;font-size:1rem}
[data-state=ready] #preview{max-height:max(7rem,calc(100dvh - 28rem))}
[data-state=ready] #readybar .btn{min-height:3rem}
[data-state=ready] #readybar .btn.main{min-height:3.2rem}
#track,#ptrack{height:.7rem;border-radius:.35rem;background:var(--track);overflow:hidden}
#fill,#pfill{display:block;height:100%;width:0;background:var(--accent);transition:width .15s}
#pct{margin:.2rem 0 0;color:var(--text);font-size:1rem;font-weight:700}
#procbar{display:none;flex-direction:column;align-items:flex-start;gap:.8rem;padding:.9rem 0 0}
[data-state=processing] #procbar{display:flex}
.spin{width:2.6rem;height:2.6rem;border-radius:50%;border:.3rem solid var(--track);border-top-color:var(--accent);animation:spin .9s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
#ptrack{width:100%}
#offerbar,#offbar,#askbar{display:none;flex-direction:column;gap:.7rem;padding:.4rem 1.1rem 1.3rem}
[data-state=offer] #offerbar,[data-state=offline] #offbar,[data-state=closed] #offbar,[data-state=ask] #askbar{display:flex}
#offerdel{margin-top:.6rem}
#offertext,#offtext,#asktext{font-size:1.05rem;color:var(--text);margin:0}
[data-done] #offbar{display:none!important}
#unsent{display:none;margin:0;color:var(--warn-text);background:var(--warn-bg);border:1px solid var(--warn-edge);
  border-radius:.5rem;padding:.6rem .8rem;font-size:.95rem}
[data-unsent='1'] #unsent{display:block}
#preview2{display:none;opacity:.9;-webkit-touch-callout:default;user-select:auto}
[data-unsent='1'] #preview2{display:block}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;opacity:0;clip:rect(0 0 0 0)}
:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
@media (prefers-reduced-motion:reduce){.spin{animation-duration:2.4s}#fill,#pfill{transition:none}}
@media (forced-colors:active){.btn,.card,.chip{border:1px solid CanvasText}.btn.main{forced-color-adjust:none;background:Highlight;color:HighlightText}}
"""

_SCRIPT = """
(function(){
var C=JSON.parse(document.getElementById('cfg').textContent),T=C.t;
var app=document.getElementById('app'),st=document.getElementById('status'),h=document.getElementById('h');
var cam=document.getElementById('cam'),pick=document.getElementById('pick');
var prev=document.getElementById('preview'),dims=document.getElementById('dims');
var qline=document.getElementById('qline'),leftEl=document.getElementById('left'),pfill=document.getElementById('pfill');
var key=C.key,cur=null,q=[],sent=0,pumping=false,xhr=null,finishing=false,stalled=false,url=null,lastTiming='';
var needKey=false,lost=false,fails=0,before={s:'wait',h:''},busy=false,leftSec=null,leftAt=0,pct=0;
function S(){return app.getAttribute('data-state');}
function state(s){app.setAttribute('data-state',s);}
function status(text,kind){st.textContent=text;st.className='chip '+kind;}
function esc(t,o){var r=t;for(var k in o){r=r.replace('{'+k+'}',o[k]);}return r;}
function fmt(n){
  var mb=n/1048576,t=mb<10?mb.toFixed(1):String(Math.round(mb));
  try{t=mb.toLocaleString(document.documentElement.lang||undefined,{maximumFractionDigits:1,minimumFractionDigits:mb<10?1:0});}catch(e){}
  return t;
}
function rid(){var s='';for(var i=0;i<20;i++){s+=Math.floor(Math.random()*16).toString(16);}return s;}
/* ---------- photos that are not confirmed yet are kept in IndexedDB for an hour (bytes and time only) ---------- */
var HOUR=3600000,DB=null;
function dbOpen(cb){
  if(DB!==null){cb(DB||null);return;}
  try{
    var r=indexedDB.open('clipsd-photos',1);
    r.onupgradeneeded=function(){r.result.createObjectStore('p',{keyPath:'id'});};
    r.onsuccess=function(){DB=r.result;cb(DB);};
    r.onerror=function(){DB=false;cb(null);};
  }catch(e){DB=false;cb(null);}
}
function dbDo(kind,arg,cb){
  dbOpen(function(db){
    if(!db){cb&&cb(false);return;}
    try{
      var t=db.transaction('p',kind==='get'||kind==='all'?'readonly':'readwrite'),o=t.objectStore('p'),req;
      if(kind==='put'){req=o.put(arg);}else if(kind==='del'){req=o['delete'](arg);}else{req=o.getAll();}
      t.oncomplete=function(){cb&&cb(kind==='all'?req.result:true);};
      t.onerror=t.onabort=function(){cb&&cb(false);};
    }catch(e){cb&&cb(false);}
  });
}
function purge(done){
  dbDo('all',null,function(all){
    if(!all){done([]);return;}
    var keep=[],now=Date.now();
    all.forEach(function(it){if(now-it.ts>HOUR){dbDo('del',it.id);}else{keep.push(it);}});
    done(keep);
  });
}
/* the computer says which photos it has opened ("done") and which it could not open ("lost"): only then the copy goes */
function confirmed(j){
  if(!j)return;
  (j.done||[]).concat(j.lost||[]).forEach(function(id){dbDo('del',id);});
}
/* ---------- the lines of the page ---------- */
function unsentCount(){return q.length+(cur?1:0);}
function allSaved(){var n=0,s=0;q.concat(cur?[cur]:[]).forEach(function(i){n++;if(i.saved)s++;});return n>0&&n===s;}
function drawQ(){
  var n=sent+q.length;
  if(n<=0||['wait','offline','closed','offer','processing','ask'].indexOf(S())>=0){qline.style.display='none';return;}
  qline.style.display='block';
  qline.textContent=esc(T.page_queue,{sent:sent,queue:q.length})+(pumping&&pct?' ('+pct+' %)':'');
  qline.className='chip '+(stalled?'err':'ok');
  try{sessionStorage.setItem('clipsd_unsent',String(q.length));}catch(e){}
}
function clock(){
  var el=document.getElementById('left');
  if(leftSec===null||['wait','ready','sending','sent'].indexOf(S())<0){el.style.display='none';return;}
  var n=Math.max(0,leftSec-Math.round((Date.now()-leftAt)/1000));
  el.style.display='block';
  el.textContent=esc(T.page_left,{t:Math.floor(n/60)+':'+(n%60<10?'0':'')+(n%60)});
  el.className='small'+(n<=30?' amber':'');
}
setInterval(clock,1000);
function titleFor(){
  if(S()==='sent'){h.textContent=q.length?T.page_sending:T.page_sent;}
}
/* ---------- screens ---------- */
function closed(text,kind,done){
  pumping=false;busy=false;state('closed');
  if(done){app.setAttribute('data-done','1');h.textContent=T.page_done;}
  else{showOff(true);}
  status(text,kind||'warn');drawQ();
}
function showOff(final){
  var n=unsentCount();
  h.textContent=T.page_offline_title;
  document.getElementById('offtext').textContent=n?T.page_expired_unsent:T.page_offline_text;
  var u=document.getElementById('unsent');
  u.textContent=n?(allSaved()?T.page_saved:T.page_unsent):'';
  app.setAttribute('data-unsent',n?'1':'0');
  if(n&&url){document.getElementById('preview2').src=url;}
}
function offline(){
  var c=S();
  if(c==='offline'||c==='closed'||c==='sending'||c==='offer'||c==='ask')return;
  before={s:c,h:h.textContent};
  showOff(false);state('offline');status(T.page_offline_text,'err');drawQ();
}
function restore(){
  if(S()!=='offline')return;
  h.textContent=before.h;state(before.s==='sending'?'sent':before.s);status(T.page_link_ok,'ok');drawQ();
}
/* ---------- choosing a photo: nothing heavy is done on the phone, the file goes as it is ---------- */
/* the buttons of the "Photo is ready" screen sit in a panel at the bottom of the screen: always in view */
function layoutPanel(){
  var pn=document.getElementById('readybar'),m=document.getElementById('page');
  if(S()==='ready'){m.style.paddingBottom=(pn.offsetHeight+8)+'px';}else{m.style.paddingBottom='';}
}
window.addEventListener('resize',layoutPanel);
function persist(it){dbDo('put',{id:it.id,blob:it.blob,ts:Date.now()},function(ok){it.saved=!!ok;});}
function showReady(t0){
  persist(cur);
  if(url)URL.revokeObjectURL(url);
  url=URL.createObjectURL(cur.blob);
  prev.onload=function(){
    if(cur){cur.pick=Date.now()-t0;dims.textContent=prev.naturalWidth+' × '+prev.naturalHeight;}
  };
  prev.src=url;dims.textContent='';
  h.textContent=T.page_ready;state('ready');status(T.page_link_ok,'ok');drawQ();clock();layoutPanel();
}
function decode(f){
  return new Promise(function(done){
    function viaImg(){
      var u=URL.createObjectURL(f),img=new Image();
      img.onload=function(){URL.revokeObjectURL(u);done({img:img,w:img.naturalWidth,h:img.naturalHeight});};
      img.onerror=function(){URL.revokeObjectURL(u);done(null);};
      img.src=u;
    }
    if(window.createImageBitmap){createImageBitmap(f).then(function(bm){done({img:bm,w:bm.width,h:bm.height,bm:bm});},viaImg);}
    else{viaImg();}
  });
}
/* the fallback (HEIC from an iPhone, a file over the limit, an unknown type): the only case where the phone re-encodes */
function fallback(f,reason,t0){
  busy=true;state('processing');h.textContent=T.page_processing;status(T.page_link_ok,'ok');pfill.style.width='10%';
  decode(f).then(function(src){
    if(!src){busy=false;state(sent||q.length?'sent':'wait');status(reason==='heic'?T.page_heic:reason==='big'?T.page_too_big:T.page_bad_type,'err');return;}
    pfill.style.width='55%';
    try{
      var sw=C.screen&&C.screen[0]?C.screen[0]:C.side,sh=C.screen&&C.screen[1]?C.screen[1]:C.side;
      var k=Math.min(1,sw/src.w,sh/src.h),cv=document.createElement('canvas');
      cv.width=Math.max(1,Math.round(src.w*k));cv.height=Math.max(1,Math.round(src.h*k));
      var cx=cv.getContext('2d');cx.imageSmoothingQuality='high';cx.drawImage(src.img,0,0,cv.width,cv.height);
      if(src.bm&&src.bm.close){src.bm.close();}
      cv.toBlob(function(b){
        busy=false;
        if(!b||b.size>C.max){state(sent||q.length?'sent':'wait');status(T.page_too_big,'err');return;}
        cur={blob:b,id:rid(),t:Date.now(),fb:Date.now()-t0};showReady(t0);
      },'image/jpeg',0.92);
    }catch(e){busy=false;state(sent||q.length?'sent':'wait');status(T.page_bad_type,'err');}
  });
}
function setPending(on){try{if(on){sessionStorage.setItem('clipsd_pending','1');}else{sessionStorage.removeItem('clipsd_pending');}}catch(e){}}
function getPending(){try{return sessionStorage.getItem('clipsd_pending')==='1';}catch(e){return false;}}
function chosen(input){
  var f=input.files&&input.files[0];
  input.value='';
  setPending(false);
  if(!f||busy)return;
  if(cur){dbDo('del',cur.id);}
  var t0=Date.now(),type=(f.type||'').toLowerCase();
  if(/hei[cf]/.test(type)||/\\.hei[cf]$/i.test(f.name||'')){fallback(f,'heic',t0);return;}
  if(f.size>C.max){fallback(f,'big',t0);return;}
  if(type&&!/^image\\/(jpeg|png|webp)$/.test(type)){fallback(f,'type',t0);return;}
  cur={blob:f,id:rid(),t:Date.now()};
  showReady(t0);
}
/* ---------- the queue: nothing is lost silently, a repeated photo is not made twice (the id of each photo) ---------- */
function enqueue(item){
  item.tries=0;
  q.push(item);
  dbDo('put',{id:item.id,blob:item.blob,ts:Date.now()},function(ok){item.saved=!!ok;});
  stalled=false;
}
function freshKey(done,tries){
  var x=new XMLHttpRequest();x.open('GET',C.base+'/key');
  x.onload=function(){
    if(x.status===200){try{key=JSON.parse(x.responseText).key||key;}catch(e){}done(true);}
    else if(x.status===409&&(tries||0)<8){setTimeout(function(){freshKey(done,(tries||0)+1);},700);}
    else if(x.status===410){closed(T.page_closed);done(false);}
    else{done(false);}
  };
  x.onerror=x.ontimeout=function(){done(false);};
  x.timeout=5000;x.send();
}
function retryLater(it){
  pumping=false;xhr=null;pct=0;needKey=true;it.tries++;
  if(finishing){finishing=false;showAsk();return;}   /* "Finish" never loops: one attempt, then the person decides */
  if(it.tries>=6){stalled=true;drawQ();var b=document.getElementById('resend');b.style.display='flex';
    if(S()==='sending'){state('sent');titleFor();}status(T.page_failed,'err');return;}
  setTimeout(pump,Math.min(8000,1200*it.tries));
  drawQ();ping();
}
function pump(){
  if(pumping||!q.length||S()==='closed')return;
  var it=q[0];pumping=true;
  if(needKey){
    freshKey(function(ok){needKey=!ok;if(!ok){if(S()==='closed'){return;}retryLater(it);}else{pumping=false;pump();}});
    return;
  }
  var x=xhr=new XMLHttpRequest(),watch=false,t0=Date.now(),last=t0,loaded=0,upDone=0;
  /* never silent, but never false: 5 s with no first byte = no connection; 8 s without movement while the body goes;
     after the body is sent the computer answers at once (it opens the photo after the answer), 20 s is a real failure */
  var wd=setInterval(function(){
    if(xhr!==x){clearInterval(wd);return;}
    var now=Date.now();
    if((!upDone&&loaded===0&&now-t0>5000)||(!upDone&&loaded>0&&now-last>8000)||(upDone&&now-upDone>20000)){
      clearInterval(wd);watch=true;x.abort();}
  },500);
  x.open('POST',C.base+'/photo');x.setRequestHeader('X-ClipSD-Key',key);
  x.setRequestHeader('Content-Type',it.blob.type||'image/jpeg');
  x.setRequestHeader('X-ClipSD-Photo',it.id);
  x.setRequestHeader('X-ClipSD-Timing','pick='+(it.pick||0)+(it.fb?';fb='+it.fb:'')+';kb='+Math.round(it.blob.size/1024)+';n='+sent+(lastTiming?';'+lastTiming:''));
  x.upload.onload=function(){upDone=Date.now();};
  x.upload.onprogress=function(e){
    if(!e.lengthComputable)return;
    if(e.loaded!==loaded){loaded=e.loaded;last=Date.now();}
    pct=Math.min(100,Math.round(100*e.loaded/e.total));
    document.getElementById('fill').style.width=pct+'%';
    document.getElementById('pct').textContent=esc(T.page_progress,{n:pct});drawQ();
  };
  function end(){clearInterval(wd);}
  x.onload=function(){
    end();
    var j={};try{j=JSON.parse(x.responseText||'{}');}catch(e){}
    xhr=null;pumping=false;pct=0;
    if(x.status===200){
      key=j.key||key;lastTiming='send='+(Date.now()-t0)+';kb='+Math.round(it.blob.size/1024);
      q.shift();sent++;fails=0;
      /* the copy stays in the store, marked as accepted, until the computer says it has opened the photo */
      dbDo('put',{id:it.id,blob:it.blob,ts:Date.now(),acc:1});
      if(!q.length&&cur===null){titleFor();}
      drawQ();
      if(j.limit){closed(T.page_limit);return;}
      if(q.length){pump();}else{afterQueue();}
    }else if(x.status===410){closed(T.page_closed);}
    else if(x.status===429){closed(T.page_limit);}
    else if(x.status===413||x.status===415){
      q.shift();dbDo('del',it.id);
      status(j.error==='heic'?T.page_heic:x.status===413?T.page_too_big:T.page_bad_type,'err');
      drawQ();if(q.length){pump();}else{afterQueue(true);}
    }else{if(x.status===403)needKey=true;retryLater(it);}
  };
  x.onabort=function(){end();retryLater(it);};
  x.onerror=x.ontimeout=function(){end();if(!watch){retryLater(it);}};
  x.timeout=130000;
  needKey=false;x.send(it.blob);
}
function showAsk(){
  var n=q.length;
  h.textContent=esc(T.page_ask_title,{n:n});
  document.getElementById('asktext').textContent=T.page_ask_text;
  state('ask');status(T.page_failed,'err');drawQ();
}
function afterQueue(failedLast){
  if(finishing&&!failedLast){closeReception();return;}
  if(finishing){finishing=false;}
  if(S()==='sending'){state('sent');}
  titleFor();if(!failedLast){status(T.page_sent_more,'ok');}drawQ();
}
function closeReception(){
  var x=new XMLHttpRequest();x.open('POST',C.base+'/close');x.setRequestHeader('X-ClipSD-Key',key);
  if(lastTiming){x.setRequestHeader('X-ClipSD-Timing',lastTiming);lastTiming='';}   /* the send time of the last photo goes with the close */
  x.onload=function(){
    try{confirmed(JSON.parse(x.responseText||'{}'));}catch(e){}
    if(x.status===200||x.status===410){closed(T.page_done_hint,'ok',true);}
    else{finishing=false;state('sent');status(T.page_failed,'err');}
  };
  x.onerror=x.ontimeout=function(){finishing=false;if(S()==='sending')state('sent');status(T.page_failed,'err');};
  x.timeout=8000;x.send();
}
/* ---------- buttons ---------- */
function sendMore(){
  if(!cur)return;
  var it=cur;cur=null;enqueue(it);
  setPending(true);
  state('sent');titleFor();drawQ();
  cam.click();           /* in the same tap: the browser still allows to open the camera */
  pump();
}
function sendEnd(){
  if(!cur)return;
  var it=cur;cur=null;enqueue(it);
  finishing=true;h.textContent=T.page_sending;state('sending');status(T.page_link_ok,'ok');drawQ();pump();
}
function finish(){
  finishing=true;
  if(!q.length&&!pumping){closeReception();return;}
  h.textContent=T.page_sending;state('sending');drawQ();pump();
}
function discard(){
  if(cur){dbDo('del',cur.id);}
  cur=null;if(url){URL.revokeObjectURL(url);url=null;}
  if(sent||q.length){state('sent');titleFor();}else{state('wait');}
  status(T.page_link_ok,'ok');drawQ();
}
cam.addEventListener('change',function(){chosen(cam);});
pick.addEventListener('change',function(){chosen(pick);});
['shoot','shoot2'].forEach(function(id){document.getElementById(id).addEventListener('keydown',function(e){
  if(e.key==='Enter'||e.key===' '){e.preventDefault();cam.click();}});});
['shoot','shoot2','gal','gal2'].forEach(function(id){document.getElementById(id).addEventListener('click',function(){setPending(true);});});
['gal','gal2'].forEach(function(id){document.getElementById(id).addEventListener('click',function(){pick.click();});});
document.getElementById('sendmore').addEventListener('click',sendMore);
document.getElementById('sendend').addEventListener('click',sendEnd);
document.getElementById('retake').addEventListener('click',function(){if(!busy)cam.click();});
document.getElementById('cancel').addEventListener('click',discard);
document.getElementById('finish').addEventListener('click',finish);
document.getElementById('askagain').addEventListener('click',function(){
  q.forEach(function(i){i.tries=0;});needKey=true;stalled=false;finishing=true;
  h.textContent=T.page_sending;state('sending');status(T.page_link_ok,'ok');drawQ();pump();});
document.getElementById('askdrop').addEventListener('click',function(){
  q.forEach(function(i){dbDo('del',i.id);});q=[];pumping=false;finishing=true;
  try{sessionStorage.removeItem('clipsd_unsent');}catch(e){}
  closeReception();});
document.getElementById('resend').addEventListener('click',function(){
  this.style.display='none';stalled=false;q.forEach(function(i){i.tries=0;});needKey=true;status(T.page_link_ok,'ok');pump();});
window.addEventListener('focus',function(){setTimeout(function(){if(S()==='wait'||S()==='sent'){setPending(false);}},1500);});
/* back from the camera: a stalled upload is retried at once, the queue goes on */
function resume(){if(document.visibilityState==='visible'){
  if(xhr&&pumping){/* the watchdog decides */}
  else if(q.length&&!pumping){pump();}
  ping();}}
document.addEventListener('visibilitychange',resume);
window.addEventListener('pageshow',resume);
/* ---------- connection ---------- */
function ping(){
  if(S()==='closed')return;
  var x=new XMLHttpRequest();x.open('GET',C.base+'/alive');x.setRequestHeader('X-ClipSD-Key',key);
  if(lastTiming){x.setRequestHeader('X-ClipSD-Timing',lastTiming);lastTiming='';}
  x.onload=function(){
    if(x.status===410){closed(T.page_closed);return;}
    try{var j=JSON.parse(x.responseText||'{}');if(typeof j.left==='number'){leftSec=j.left;leftAt=Date.now();clock();}
      confirmed(j);
      if(j.failed&&j.failed.length){status(esc(T.page_pcfail,{n:j.failed.join(', ')}),'err');}}catch(e){}
    fails=0;lost=false;
    if(S()==='offline'){restore();}
    else if(st.className.indexOf('err')>=0&&st.textContent===T.page_link_lost){status(T.page_link_ok,'ok');}
  };
  x.onerror=x.ontimeout=function(){
    lost=true;fails++;
    if(fails>=2){offline();}
    else if(S()!=='closed'){status(T.page_link_lost,'err');}
  };
  x.timeout=2500;x.send();
}
setInterval(ping,3000);
/* ---------- start: leftovers of an earlier code, kept on this phone (same address and port only) ---------- */
(function(){
  var unsent=0;try{unsent=parseInt(sessionStorage.getItem('clipsd_unsent')||'0',10)||0;}catch(e){}
  if(getPending()){
    setPending(false);
    status(unsent?esc(T.page_lost_n,{n:unsent}):T.page_lost,'warn');
    try{sessionStorage.removeItem('clipsd_unsent');}catch(e){}
  }
  purge(function(all){
    var items=all.filter(function(i){return !i.acc;});   /* accepted ones are the computer's now */
    if(!items.length)return;
    h.textContent=esc(T.page_offer_title,{n:items.length});
    document.getElementById('offerbtns').setAttribute('data-n',String(items.length));
    state('offer');
    document.getElementById('offersend').onclick=function(){
      items.forEach(function(i){q.push({blob:i.blob,id:i.id,saved:true,tries:0});});
      needKey=false;state('sent');titleFor();status(T.page_link_ok,'ok');drawQ();pump();
    };
    document.getElementById('offerdel').onclick=function(){
      items.forEach(function(i){dbDo('del',i.id);});state('wait');status(T.page_link_ok,'ok');
    };
  });
})();
})();
"""


def _e(text) -> str:
    return html.escape(str(text or ""), quote=True)


def _json_for_script(data) -> str:
    """JSON inside <script type="application/json">: no "</script>" can close the element early."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_page(texts: dict, lang: str, base: str, key: str, nonce: str, max_bytes: int = None, screen=None) -> str:
    """screen: (width, height) of the computer's screen in physical pixels; "Fit to the computer screen" scales the
    photo to fit into it (never up). None: PHOTO_SIDE on the long side."""
    from .phone import MAX_BYTES
    t = {k: v for k, v in texts.items() if k.startswith("page_")}
    scr = [int(screen[0]), int(screen[1])] if screen and screen[0] and screen[1] else None
    cfg = {"base": base, "key": key, "max": max_bytes or MAX_BYTES, "side": PHOTO_SIDE, "screen": scr,
           "pixels": ORIGINAL_PIXELS, "t": t}
    g = lambda k: _e(texts.get(k))   # noqa: E731
    note = _e((texts.get("page_camera_note") or "").replace("{more}", texts.get("page_send_more") or "")
              .replace("{end}", texts.get("page_send_end") or ""))
    from .phone_logo import FAVICON_48, LOGO_160
    return (
        f'<!doctype html><html lang="{_e(lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        '<meta name="referrer" content="no-referrer"><meta name="robots" content="noindex">'
        '<meta name="color-scheme" content="light dark">'
        f'<meta name="theme-color" content="{THEME_LIGHT}" media="(prefers-color-scheme: light)">'
        f'<meta name="theme-color" content="{THEME_DARK}" media="(prefers-color-scheme: dark)">'
        f'<link rel="icon" type="image/png" href="{FAVICON_48}">'
        f'<title>ClipSD</title><style nonce="{_e(nonce)}">{_STYLE}</style></head>'
        '<body><main id="page"><div id="app" class="card" data-state="wait">'
        f'<header class="head"><img src="{LOGO_160}" alt="" width="48" height="48"><div><div class="name">{g("page_card_title")}</div>'
        f'<div id="intro" class="sub">{g("page_intro")}</div></div></header><div class="rule"></div>'
        '<div class="rows">'
        f'<p id="status" class="chip ok" role="status" aria-live="polite">{g("page_link_ok")}</p>'
        '<p id="qline" class="chip ok" role="status"></p><p id="left" class="small"></p></div>'
        '<h1 id="h">ClipSD</h1>'
        '<div id="steps">'
        f'<div class="step" id="s1"><div class="dot" id="d1" aria-hidden="true"></div><div class="sb"><div class="stitle">{g("page_step1")}</div>'
        '<section id="procbar" aria-live="polite"><div class="spin" aria-hidden="true"></div>'
        '<div id="ptrack"><span id="pfill"></span></div></section>'
        '<section id="view"><img id="preview" alt=""><p id="dims"></p></section>'
        f'<div id="startbar" class="bar">'
        f'<label id="shoot" class="btn main big" for="cam" role="button" tabindex="0">{g("page_shoot")}</label>'
        f'<button id="gal" class="btn" type="button">{g("page_choose")}</button>'
        f'<p id="note">{note}</p></div>'
        f'<div id="sentbar" class="bar">'
        f'<button id="resend" class="btn amber" type="button">{g("page_resend")}</button>'
        f'<label id="shoot2" class="btn main" for="cam" role="button" tabindex="0">{g("page_more")}</label>'
        f'<button id="gal2" class="btn" type="button">{g("page_choose_more")}</button>'
        f'<button id="finish" class="btn" type="button">{g("page_finish")}</button></div>'
        '</div></div>'
        '<div class="sep"></div>'
        f'<div class="step" id="s2"><div class="dot" id="d2" aria-hidden="true"></div><div class="sb"><div class="stitle">{g("page_step2")}</div>'
        f'<div id="readybar" class="bar"><div class="phead"><span class="dot dotnow">2</span>'
        f'<span class="stitle">{g("page_step2")}</span></div>'
        f'<button id="sendend" class="btn main" type="button">{g("page_send_end")}</button>'
        f'<button id="sendmore" class="btn" type="button">{g("page_send_more")}</button>'
        f'<div id="smallrow"><button id="retake" class="linkbtn" type="button">{g("page_retake")}</button>'
        f'<button id="cancel" class="linkbtn" type="button">{g("page_cancel")}</button></div></div>'
        f'<div id="sendingbar" class="bar"><div id="track"><span id="fill"></span></div><p id="pct"></p></div>'
        '</div></div></div>'
        f'<div id="askbar"><p id="asktext"></p><button id="askagain" class="btn main" type="button">{g("page_resend")}</button>'
        f'<button id="askdrop" class="btn" type="button">{g("page_finish_without")}</button></div>'
        f'<div id="offerbar"><p id="offertext">{g("page_offer_text")}</p><div id="offerbtns">'
        f'<button id="offersend" class="btn main" type="button">{g("page_offer_send")}</button>'
        f'<button id="offerdel" class="btn" type="button">{g("page_offer_delete")}</button></div></div>'
        f'<div id="offbar"><img id="preview2" alt=""><p id="offtext">{g("page_offline_text")}</p><p id="unsent">{g("page_unsent")}</p></div>'
        '<input id="cam" class="vh" type="file" accept="image/*" capture="environment" tabindex="-1">'
        '<input id="pick" class="vh" type="file" accept="image/*" tabindex="-1">'
        '</div></main>'
        f'<script type="application/json" id="cfg">{_json_for_script(cfg)}</script>'
        f'<script nonce="{_e(nonce)}">{_SCRIPT}</script></body></html>'
    )


def render_message(texts: dict, lang: str, message: str, nonce: str) -> str:
    """A page with one message: the code is used by another phone, the receiver is closed."""
    from .phone_logo import FAVICON_48, LOGO_160
    return (
        f'<!doctype html><html lang="{_e(lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="referrer" content="no-referrer"><meta name="robots" content="noindex">'
        '<meta name="color-scheme" content="light dark">'
        f'<meta name="theme-color" content="{THEME_LIGHT}" media="(prefers-color-scheme: light)">'
        f'<meta name="theme-color" content="{THEME_DARK}" media="(prefers-color-scheme: dark)">'
        f'<link rel="icon" type="image/png" href="{FAVICON_48}">'
        f'<title>ClipSD</title><style nonce="{_e(nonce)}">{_STYLE}</style></head>'
        f'<body><main><div class="card"><header><div class="brand"><img src="{LOGO_160}" alt="" width="48" height="48">'
        f'<span>ClipSD</span></div><p class="chip warn" role="alert">{_e(message)}</p></header></div></main></body></html>'
    )
