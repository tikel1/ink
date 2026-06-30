"""Build the Ink-branded captive portal page into captive_index.h.

Embeds a subsetted Fraunces woff2 (the real Ink display font) + the animated
ink-blob (inline vector SVG), shows a tappable list of scanned networks, and
talks to the same firmware endpoints (/config.json, /wifisave) as the stock page.

Regenerate after editing: run this script from this directory.
"""
import base64, gzip, pathlib

HERE = pathlib.Path(__file__).parent
FONT_B64 = base64.b64encode((HERE / "fraunces-ink.woff2").read_bytes()).decode()

HTML = """<!DOCTYPE html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Ink · Connect to Wi-Fi</title>
<style>
@font-face{font-family:'Fraunces';font-style:normal;font-weight:600 800;font-display:swap;src:url(data:font/woff2;base64,__FONT__) format('woff2')}
:root{--paper:#e7dfce;--paper2:#efe9db;--ink:#1b1813;--soft:#4a4438;--muted:#8b8473;--line:#cfc6b1}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(120% 80% at 50% -10%,#efe9db,#e7dfce 60%);color:var(--ink);font-family:-apple-system,Segoe UI,Roboto,sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px}
.card{width:100%;max-width:400px;background:var(--paper2);border:1.5px solid var(--line);border-radius:18px;padding:24px 22px;box-shadow:0 10px 40px rgba(27,24,19,.12)}
.brand{display:flex;align-items:center;gap:10px;justify-content:center;margin-bottom:4px}
.brand b{font-family:'Fraunces',Georgia,serif;font-weight:800;font-size:32px;letter-spacing:-.01em;line-height:1}
.mark{width:30px;height:30px}.mark svg{width:100%;height:100%;display:block}
.bl{fill:var(--ink);transform-origin:80px 80px;animation:drift 7s cubic-bezier(.2,.7,.2,1) infinite}
.b2{animation-delay:-1.4s}.b3{animation-delay:-2.8s}.b4{animation-delay:-4.2s}.b5{animation-delay:-5.6s}
@keyframes drift{0%,100%{transform:translate(0,0) scale(1)}20%{transform:translate(13px,-10px) scale(1.12)}40%{transform:translate(-9px,8px) scale(.9)}60%{transform:translate(10px,9px) scale(1.08)}80%{transform:translate(-7px,-6px) scale(.96)}}
@media (prefers-reduced-motion:reduce){.bl{animation:none}}
.eyebrow{text-align:center;text-transform:uppercase;letter-spacing:.22em;font-size:11px;color:var(--muted);font-weight:600;margin:0 0 18px}
h1{font-family:'Fraunces',Georgia,serif;font-size:22px;font-weight:600;text-align:center;margin:0 0 4px}
p.sub{color:var(--soft);text-align:center;font-size:14px;margin:0 0 16px;line-height:1.5}
.nets{list-style:none;padding:0;margin:0 0 6px;border:1.5px solid var(--line);border-radius:12px;overflow:hidden;background:#fff}
.nets li{display:flex;align-items:center;gap:10px;padding:13px 14px;border-top:1px solid var(--line);cursor:pointer;font-size:15px}
.nets li:first-child{border-top:none}.nets li:active{background:var(--paper)}
.nets .ssid{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500}
.nets .bars{font-size:13px;width:14px;text-align:center}.nets .lock{color:var(--muted);font-size:13px}
.nets .empty{color:var(--muted);cursor:default;justify-content:center}
label{display:block;font-size:12px;font-weight:600;color:var(--soft);margin:12px 0 0}
input{width:100%;margin-top:6px;padding:13px;font-size:16px;border:1.5px solid var(--line);border-radius:10px;background:#fff;color:var(--ink)}
input:focus{outline:none;border-color:var(--ink)}
button{width:100%;margin-top:18px;padding:15px;font-size:15px;font-weight:600;color:var(--paper);background:var(--ink);border:none;border-radius:10px;cursor:pointer}
button:active{opacity:.85}
.appbtn{display:block;text-align:center;text-decoration:none;margin-top:18px;padding:15px;font-size:15px;font-weight:600;color:var(--paper);background:var(--ink);border-radius:10px}
.foot{text-align:center;color:var(--muted);font-size:12px;margin-top:14px;line-height:1.5}
.ok{text-align:center}.ok .spin{width:34px;height:34px;border:3px solid var(--line);border-top-color:var(--ink);border-radius:50%;animation:s 1s linear infinite;margin:14px auto}
@keyframes s{to{transform:rotate(360deg)}}
</style></head><body>
<div class=card>
  <div class=brand><b>Ink</b><span class=mark><svg viewBox="0 0 160 160" xmlns="http://www.w3.org/2000/svg"><defs><filter id="goo"><feGaussianBlur in="SourceGraphic" stdDeviation="5" result="b"/><feColorMatrix in="b" mode="matrix" values="1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 20 -9"/></filter></defs><g filter="url(#goo)"><circle class="bl b1" cx="80" cy="80" r="24"/><circle class="bl b2" cx="80" cy="80" r="17"/><circle class="bl b3" cx="80" cy="80" r="13"/><circle class="bl b4" cx="80" cy="80" r="19"/><circle class="bl b5" cx="80" cy="80" r="10"/></g></svg></span></div>
  <p class=eyebrow>A daily work of art</p>
  <div id=form>
    <h1>Connect your frame</h1>
    <p class=sub>Pick your home Wi-Fi so your Ink frame can fetch each morning's artwork.</p>
    <ul class=nets id=nets><li class=empty>Scanning for networks…</li></ul>
    <form action=/wifisave method=get>
      <label for=ssid>Wi-Fi network</label>
      <input id=ssid name=ssid placeholder="Tap a network above, or type it" autocomplete=off required>
      <label for=psk>Password</label>
      <input id=psk name=psk type=password placeholder="Wi-Fi password" autocomplete=off>
      <button type=submit>Connect</button>
    </form>
    <p class=foot>After connecting, your frame shows a pairing code to enter in the Ink app.</p>
  </div>
  <div id=done class=ok style=display:none>
    <h1>Frame connected</h1>
    <p class=sub>Your Ink frame is joining your Wi-Fi. Continue in the Ink app — your frame will show a pairing code to scan or enter.</p>
    <a class=appbtn href="https://tikel1.github.io/ink/">Open the Ink app &rarr;</a>
    <p class=foot>Didn't open? Reconnect to your home Wi-Fi, then open Ink.</p>
  </div>
</div>
<script>
if(location.search.indexOf('save')>=0){document.getElementById('form').style.display='none';document.getElementById('done').style.display='block';
  /* Best-effort hand-off to the Ink app. The OS captive browser usually opens
     this in the real browser once Wi-Fi reconnects; the button is the fallback. */
  setTimeout(function(){try{location.href='https://tikel1.github.io/ink/';}catch(e){}},2500);}
else{fetch('/config.json').then(function(r){return r.json()}).then(function(d){
  var ul=document.getElementById('nets'),seen={},rows=[];
  (d.aps||[]).filter(function(a){return a&&a.ssid}).sort(function(a,b){return b.rssi-a.rssi}).forEach(function(a){
    if(seen[a.ssid])return;seen[a.ssid]=1;
    var bars=a.rssi>=-60?'▇':a.rssi>=-72?'▄':'▁';
    var li=document.createElement('li');
    li.innerHTML='<span class=bars>'+bars+'</span><span class=ssid></span>'+(a.lock?'<span class=lock>🔒</span>':'');
    li.querySelector('.ssid').textContent=a.ssid;
    li.onclick=function(){document.getElementById('ssid').value=a.ssid;document.getElementById('psk').focus();};
    rows.push(li);
  });
  ul.innerHTML='';
  if(rows.length){rows.forEach(function(li){ul.appendChild(li);});}else{ul.innerHTML='<li class=empty>No networks found — type yours below</li>';}
}).catch(function(){document.getElementById('nets').innerHTML='<li class=empty>Type your network below</li>';});}
</script>
</body></html>
"""

html = HTML.replace("__FONT__", FONT_B64)
(HERE / "_index.html").write_text(html, encoding="utf-8")

gz = gzip.compress(html.encode("utf-8"), 9)
body = ",\n    ".join(", ".join(f"0x{b:02x}" for b in gz[i:i+19]) for i in range(0, len(gz), 19))
header = f"""#pragma once
// Ink-branded captive portal page (overrides the stock ESPHome one).
// Regenerate with: python build_captive.py  (in this directory).

#include "esphome/core/hal.h"

namespace esphome {{
namespace captive_portal {{

const uint8_t INDEX_GZ[] PROGMEM = {{
    {body}
}};

}}  // namespace captive_portal
}}  // namespace esphome
"""
(HERE / "captive_index.h").write_text(header)
print(f"html={len(html)}B  gzip={len(gz)}B  font_b64={len(FONT_B64)}B")
