#!/usr/bin/env python3
"""Local UI → WiFi SSH or Bluetooth RFCOMM → Pi HID."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from envutil import getenv, load_dotenv, require

load_dotenv()

HOST = getenv("PIPI_HOST")
USER = getenv("PIPI_USER")
PASS = getenv("PIPI_PASS")
PORT = int(getenv("PIPI_UI_PORT", "8765") or "8765")
BT_ADDR = getenv("PIPI_BT")
BT_CHANNEL = int(getenv("PIPI_BT_CH", "1") or "1")
REMOTE = getenv(
    "PIPI_REMOTE",
    "cd ~/pi-hid/webui && ../hid-venv/bin/python -u agent.py",
)
MODE = (getenv("PIPI_MODE", "wifi") or "wifi").lower()  # wifi | bt

HTML = r"""<!DOCTYPE html>
<html lang="tr"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>pipi.type</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@450;600&family=Syne:wght@800&display=swap" rel="stylesheet"/>
<style>
:root{--bg:#0c0f0d;--ink:#e7efe8;--muted:#849288;--line:#243028;--a:#c8f542;--ok:#5ddea6;--bad:#ff6b4a;--hot:#ffb020;--pad:#1a3a4a;--bt:#6aa8ff}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;
font-family:"IBM Plex Mono",monospace;color:var(--ink);
background:radial-gradient(900px 420px at 0% 0%,#1a2a18,transparent 55%),var(--bg)}
.w{width:min(720px,100%);display:flex;flex-direction:column;gap:12px}
h1{font-family:Syne,sans-serif;font-size:clamp(1.8rem,5vw,2.4rem);margin:0;letter-spacing:-.04em}
h1 i{color:var(--a);font-style:normal}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.st{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);display:flex;gap:8px;align-items:center}
.dot{width:8px;height:8px;border-radius:50%;background:var(--bad)}.dot.on{background:var(--ok)}
.modes{display:flex;gap:6px}
.modes button{padding:8px 12px}
.modes button.on.wifi{background:var(--a);color:#10140f;border-color:var(--a)}
.modes button.on.bt{background:var(--bt);color:#061018;border-color:var(--bt)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
#grab,#pad{min-height:180px;border:1px dashed var(--line);background:#070907;padding:14px;outline:0;
display:flex;flex-direction:column;justify-content:center;gap:8px;user-select:none;touch-action:none}
#grab{cursor:pointer}#grab:focus,#grab.on{border-style:solid;border-color:var(--hot);box-shadow:0 0 0 3px rgba(255,176,32,.14)}
#pad{border-color:#2a4555;background:linear-gradient(180deg,#0b1216,#070b0e);cursor:crosshair}
#pad:active,#pad.drag{border-color:#4db8ff;box-shadow:0 0 0 3px rgba(77,184,255,.12)}
.big{font-family:Syne,sans-serif;font-size:1.1rem;font-weight:800}
.sub{color:var(--muted);font-size:.72rem;line-height:1.4}
#grab.on .big{color:var(--hot)}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
button,label{font:600 .72rem/1 "IBM Plex Mono",monospace;letter-spacing:.04em;text-transform:uppercase}
button{border:1px solid var(--line);background:0;color:var(--ink);padding:9px 11px;cursor:pointer}
button.p{background:var(--a);color:#10140f;border-color:var(--a)}
button.hot{background:var(--hot);color:#1a1200;border-color:var(--hot)}
button.pad{background:#2a6f8f;color:#eaf6ff;border-color:#2a6f8f}
label{color:var(--muted);display:flex;gap:6px;align-items:center}
textarea{width:100%;min-height:90px;resize:vertical;border:1px solid var(--line);background:#070907;color:var(--ink);
padding:10px;font:450 .9rem/1.45 "IBM Plex Mono",monospace;outline:0;caret-color:var(--a)}
.hint,.log{font-size:.7rem;color:var(--muted)}.log{color:#8fb01f;min-height:1em}.log.e{color:var(--bad)}
kbd{border:1px solid var(--line);padding:1px 5px;font-size:.65rem}
</style></head><body><div class="w">
<div class="row"><h1>pipi<i>.</i>type</h1>
<div class="st"><span class="dot" id="d"></span><span id="s">connecting</span></div></div>

<div class="row">
  <div class="modes">
    <button type="button" class="wifi" id="mWifi">WiFi SSH</button>
    <button type="button" class="bt" id="mBt">Bluetooth</button>
  </div>
  <span class="hint" id="modeHint"></span>
</div>

<div class="grid">
  <div id="grab" tabindex="0">
    <div class="big" id="gt">Grab keyboard</div>
    <div class="sub">Ctrl/Win/Alt → host<br/>Leave: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>G</kbd></div>
  </div>
  <div id="pad">
    <div class="big">Trackpad</div>
    <div class="sub">Drag = move · click = left · scroll = wheel</div>
  </div>
</div>

<div class="bar">
<button class="hot" id="tg">grab</button>
<button class="pad" id="lclick">left</button>
<button class="pad" id="rclick">right</button>
<button id="rel">release keys</button>
<label>sens <input id="sens" type="range" min="0.4" max="3" step="0.1" value="1.2" style="width:90px"/></label>
</div>

<textarea id="t" placeholder="bulk text (optional)" spellcheck="false"></textarea>
<div class="bar">
<label><input type="checkbox" id="live" checked/> live text</label>
<button class="p" id="all">send all</button>
<button id="clr">clear</button>
<button id="ent">enter</button>
</div>
<p class="hint">PC UI · WiFi SSH or Bluetooth RFCOMM · USB HID out</p>
<div class="log" id="log"></div>
</div>
<script>
const HID={
ControlLeft:0xE0,ShiftLeft:0xE1,AltLeft:0xE2,MetaLeft:0xE3,
ControlRight:0xE4,ShiftRight:0xE5,AltRight:0xE6,MetaRight:0xE7,
Escape:0x29,Tab:0x2B,CapsLock:0x39,Enter:0x28,Space:0x2C,Backspace:0x2A,
Minus:0x2D,Equal:0x2E,BracketLeft:0x2F,BracketRight:0x30,Backslash:0x31,
Semicolon:0x33,Quote:0x34,Backquote:0x35,Comma:0x36,Period:0x37,Slash:0x38,
ArrowRight:0x4F,ArrowLeft:0x50,ArrowDown:0x51,ArrowUp:0x52,
Insert:0x49,Delete:0x4C,Home:0x4A,End:0x4D,PageUp:0x4B,PageDown:0x4E,
PrintScreen:0x46,ScrollLock:0x47,Pause:0x48,ContextMenu:0x65,
F1:0x3A,F2:0x3B,F3:0x3C,F4:0x3D,F5:0x3E,F6:0x3F,F7:0x40,F8:0x41,F9:0x42,F10:0x43,F11:0x44,F12:0x45,
Digit1:0x1E,Digit2:0x1F,Digit3:0x20,Digit4:0x21,Digit5:0x22,Digit6:0x23,Digit7:0x24,Digit8:0x25,Digit9:0x26,Digit0:0x27,
KeyA:0x04,KeyB:0x05,KeyC:0x06,KeyD:0x07,KeyE:0x08,KeyF:0x09,KeyG:0x0A,KeyH:0x0B,KeyI:0x0C,KeyJ:0x0D,
KeyK:0x0E,KeyL:0x0F,KeyM:0x10,KeyN:0x11,KeyO:0x12,KeyP:0x13,KeyQ:0x14,KeyR:0x15,KeyS:0x16,KeyT:0x17,
KeyU:0x18,KeyV:0x19,KeyW:0x1A,KeyX:0x1B,KeyY:0x1C,KeyZ:0x1D,
};
const grab=document.getElementById('grab'), gt=document.getElementById('gt'), pad=document.getElementById('pad');
const t=document.getElementById('t'), live=document.getElementById('live'), log=document.getElementById('log');
const d=document.getElementById('d'), s=document.getElementById('s'), sens=document.getElementById('sens');
const mWifi=document.getElementById('mWifi'), mBt=document.getElementById('mBt'), modeHint=document.getElementById('modeHint');
let grabbed=false, last='', q=Promise.resolve(), down=new Set(), mode='wifi';
let ax=0, ay=0, aw=0, dragging=false, px=0, py=0, moved=false, raf=0;
const L=(m,e=false)=>{log.textContent=m;log.className='log'+(e?' e':'')};
const api=(p,b)=>fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})}).then(async r=>{if(!r.ok)throw new Error(await r.text());return r.json()});
const go=fn=>{q=q.then(fn).catch(e=>L(String(e),1));return q};

function paintMode(){
  mWifi.classList.toggle('on', mode==='wifi');
  mBt.classList.toggle('on', mode==='bt');
  modeHint.textContent = mode==='bt' ? 'RFCOMM · lower latency' : 'SSH · room WiFi';
}
async function setMode(m){
  if(m===mode) return;
  L('switching to '+m+'…');
  try{
    const j=await api('/mode',{mode:m});
    mode=j.mode||m; paintMode(); L('mode '+mode); st();
  }catch(e){L(String(e),1)}
}
mWifi.onclick=()=>setMode('wifi');
mBt.onclick=()=>setMode('bt');

function setGrab(on){
  grabbed=on; grab.classList.toggle('on',on);
  gt.textContent=on?'KEYBOARD GRABBED':'Grab keyboard';
  if(on){grab.focus(); L('grab on')} else {go(()=>api('/x',{})); down.clear(); L('grab off')}
}
grab.addEventListener('click',()=>{if(!grabbed)setGrab(true)});
document.getElementById('tg').onclick=()=>setGrab(!grabbed);
document.getElementById('rel').onclick=()=>go(()=>api('/x',{}).then(()=>{down.clear();L('keys up')}));
document.getElementById('lclick').onclick=()=>api('/c',{btn:'left'}).catch(e=>L(String(e),1));
document.getElementById('rclick').onclick=()=>api('/c',{btn:'right'}).catch(e=>L(String(e),1));

function isToggle(e){return e.ctrlKey && e.altKey && (e.code==='KeyG')}
window.addEventListener('keydown',e=>{
  if(isToggle(e)){e.preventDefault();setGrab(!grabbed);return}
  if(!grabbed) return;
  e.preventDefault(); if(e.repeat) return;
  const id=HID[e.code]; if(id==null) return;
  if(down.has(id)) return; down.add(id);
  api('/d',{id}).catch(e=>L(String(e),1));
}, true);
window.addEventListener('keyup',e=>{
  if(!grabbed) return; if(isToggle(e)){e.preventDefault();return}
  e.preventDefault();
  const id=HID[e.code]; if(id==null) return; down.delete(id);
  api('/u',{id}).catch(e=>L(String(e),1));
}, true);
window.addEventListener('blur',()=>{if(grabbed) go(()=>api('/x',{}).then(()=>down.clear()))});

function flushMove(){
  raf=0;
  const dx=Math.round(ax), dy=Math.round(ay), w=Math.round(aw);
  ax-=dx; ay-=dy; aw-=w;
  if(!dx && !dy && !w) return;
  api('/m',{dx,dy,w}).catch(e=>L(String(e),1));
}
function queueMove(dx,dy,w=0){
  ax+=dx*1.0; ay+=dy*1.0; aw+=w;
  if(!raf) raf=requestAnimationFrame(flushMove);
}

pad.addEventListener('pointerdown',e=>{
  pad.setPointerCapture(e.pointerId);
  dragging=true; moved=false; px=e.clientX; py=e.clientY; pad.classList.add('drag');
});
pad.addEventListener('pointermove',e=>{
  if(!dragging) return;
  const dx=(e.clientX-px)*parseFloat(sens.value);
  const dy=(e.clientY-py)*parseFloat(sens.value);
  px=e.clientX; py=e.clientY;
  if(Math.abs(dx)>0.2||Math.abs(dy)>0.2){moved=true; queueMove(dx,dy,0)}
});
function endPtr(e){
  if(!dragging) return;
  dragging=false; pad.classList.remove('drag');
  try{pad.releasePointerCapture(e.pointerId)}catch{}
  if(!moved) api('/c',{btn: e.button===2?'right':'left'}).catch(e=>L(String(e),1));
}
pad.addEventListener('pointerup',endPtr);
pad.addEventListener('pointercancel',endPtr);
pad.addEventListener('contextmenu',e=>e.preventDefault());
pad.addEventListener('wheel',e=>{
  e.preventDefault();
  queueMove(0,0, Math.max(-7, Math.min(7, -Math.sign(e.deltaY)*Math.ceil(Math.abs(e.deltaY)/40))));
},{passive:false});

t.addEventListener('input',()=>{
  if(grabbed||!live.checked){last=t.value;return}
  const cur=t.value;
  if(cur.startsWith(last)){const a=cur.slice(last.length); if(a) go(()=>api('/t',{text:a}).then(()=>L('→ '+JSON.stringify(a))));}
  else if(last.startsWith(cur)){const n=last.length-cur.length; go(()=>api('/b',{n}).then(()=>L('⌫ ×'+n)));}
  else {const n=last.length,text=cur; go(async()=>{if(n)await api('/b',{n}); if(text)await api('/t',{text}); L('resync')});}
  last=cur;
});
document.getElementById('all').onclick=()=>{const text=t.value; if(text) go(()=>api('/t',{text}).then(()=>L('sent '+text.length)));};
document.getElementById('clr').onclick=()=>{t.value='';last=''};
document.getElementById('ent').onclick=()=>go(()=>api('/e',{}).then(()=>L('↵')));
async function st(){
  try{
    const j=await(await fetch('/status')).json();
    mode=j.mode||mode; paintMode();
    d.classList.toggle('on',!!j.ok);
    const label=mode==='bt'?'bt+hid':'wifi+hid';
    s.textContent=j.ok?label:(j.error||'down');
  }catch{d.classList.remove('on');s.textContent='down'}
}
st(); setInterval(st,3000);
</script></body></html>
"""


class BaseTransport:
    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    @property
    def ok(self) -> bool:
        raise NotImplementedError

    def send(self, line: str) -> None:
        raise NotImplementedError

    def send_mouse(self, dx: int, dy: int, w: int = 0) -> None:
        raise NotImplementedError


class SshTransport(BaseTransport):
    """SSH stdin writer. Mouse uses coalesce + no-wait."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._wlock = threading.Lock()
        self._pending_m = [0, 0, 0]
        self._m_sched = False
        self._m_lock = threading.Lock()

    def start(self) -> None:
        if shutil.which("sshpass") is None:
            raise RuntimeError("sshpass required")
        host, user, password = require("PIPI_HOST"), require("PIPI_USER"), require("PIPI_PASS")
        self._proc = subprocess.Popen(
            [
                "sshpass", "-p", password, "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ServerAliveInterval=15",
                "-o", "TCPKeepAlive=yes",
                "-o", "Compression=no",
                f"{user}@{host}", REMOTE,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self._proc.stdout is not None
        line = self._proc.stdout.readline().strip()
        if line != "OK":
            err = self._proc.stderr.read() if self._proc.stderr else ""
            raise RuntimeError(f"ssh agent failed: {line!r} {err}")
        threading.Thread(target=self._drain, daemon=True).start()

    def stop(self) -> None:
        p = self._proc
        self._proc = None
        if p and p.poll() is None:
            try:
                if p.stdin:
                    p.stdin.write("Q\n")
                    p.stdin.flush()
            except Exception:
                pass
            try:
                p.terminate()
            except Exception:
                pass

    def _drain(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            for _ in self._proc.stdout:
                pass
        except Exception:
            pass

    @property
    def ok(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _write(self, line: str) -> None:
        if not self.ok:
            self.start()
        assert self._proc and self._proc.stdin
        with self._wlock:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()

    def send(self, line: str) -> None:
        self._write(line)

    def send_mouse(self, dx: int, dy: int, w: int = 0) -> None:
        with self._m_lock:
            self._pending_m[0] += dx
            self._pending_m[1] += dy
            self._pending_m[2] += w
            if self._m_sched:
                return
            self._m_sched = True
        threading.Timer(0.008, self._flush_mouse).start()

    def _flush_mouse(self) -> None:
        with self._m_lock:
            dx, dy, w = self._pending_m
            self._pending_m = [0, 0, 0]
            self._m_sched = False
        if dx or dy or w:
            self._write(f"M:{dx},{dy},{w}")


class BtTransport(BaseTransport):
    """RFCOMM client to Pi bt_server.py."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._wlock = threading.Lock()
        self._pending_m = [0, 0, 0]
        self._m_sched = False
        self._m_lock = threading.Lock()
        self._err: str | None = None

    def start(self) -> None:
        self.stop()
        self._err = None
        addr = require("PIPI_BT")
        channel = int(getenv("PIPI_BT_CH", "1") or "1")
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        s.settimeout(12)
        try:
            s.connect((addr, channel))
        except OSError as e:
            s.close()
            self._err = str(e)
            raise RuntimeError(f"bt connect {addr} ch{channel}: {e}") from e
        s.settimeout(None)
        # first line should be OK
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(64)
            if not chunk:
                s.close()
                raise RuntimeError("bt: closed before OK")
            buf += chunk
        line, rest = buf.split(b"\n", 1)
        if line.strip() != b"OK":
            s.close()
            raise RuntimeError(f"bt agent failed: {line!r}")
        self._sock = s
        threading.Thread(target=self._drain, args=(rest,), daemon=True).start()

    def stop(self) -> None:
        s = self._sock
        self._sock = None
        if s:
            try:
                s.sendall(b"Q\n")
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

    def _drain(self, rest: bytes = b"") -> None:
        s = self._sock
        if not s:
            return
        try:
            if rest:
                pass
            while True:
                if not s.recv(256):
                    break
        except Exception:
            pass

    @property
    def ok(self) -> bool:
        return self._sock is not None

    def _write(self, line: str) -> None:
        if not self.ok:
            self.start()
        assert self._sock is not None
        with self._wlock:
            self._sock.sendall((line + "\n").encode())

    def send(self, line: str) -> None:
        self._write(line)

    def send_mouse(self, dx: int, dy: int, w: int = 0) -> None:
        with self._m_lock:
            self._pending_m[0] += dx
            self._pending_m[1] += dy
            self._pending_m[2] += w
            if self._m_sched:
                return
            self._m_sched = True
        threading.Timer(0.004, self._flush_mouse).start()

    def _flush_mouse(self) -> None:
        with self._m_lock:
            dx, dy, w = self._pending_m
            self._pending_m = [0, 0, 0]
            self._m_sched = False
        if dx or dy or w:
            self._write(f"M:{dx},{dy},{w}")


class Router:
    def __init__(self) -> None:
        self.mode = "wifi" if MODE not in ("bt", "bluetooth") else "bt"
        self._ssh = SshTransport()
        self._bt = BtTransport()
        self._lock = threading.Lock()
        self.last_error: str | None = None

    @property
    def t(self) -> BaseTransport:
        return self._bt if self.mode == "bt" else self._ssh

    @property
    def ok(self) -> bool:
        return self.t.ok

    def start(self) -> None:
        with self._lock:
            self.t.start()

    def set_mode(self, mode: str) -> None:
        mode = "bt" if mode in ("bt", "bluetooth") else "wifi"
        with self._lock:
            if mode == self.mode and self.t.ok:
                return
            # stop both, start target
            self._ssh.stop()
            self._bt.stop()
            self.mode = mode
            try:
                self.t.start()
                self.last_error = None
            except Exception as e:
                self.last_error = str(e)
                raise

    def send(self, line: str) -> None:
        self.t.send(line)

    def send_mouse(self, dx: int, dy: int, w: int = 0) -> None:
        self.t.send_mouse(dx, dy, w)


agent = Router()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        pass

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            data = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/status":
            return self._json(
                200,
                {
                    "ok": agent.ok,
                    "mode": agent.mode,
                    "error": agent.last_error,
                    "bt": BT_ADDR,
                    "host": HOST,
                },
            )
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = self._read_json()
            if path == "/mode":
                agent.set_mode(str(data.get("mode", "wifi")))
                return self._json(200, {"ok": True, "mode": agent.mode})
            if path == "/t":
                text = data.get("text", "")
                if not isinstance(text, str) or not text:
                    return self._json(400, {"error": "empty"})
                safe = text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
                agent.send("T:" + safe)
                return self._json(200, {"ok": True})
            if path == "/b":
                agent.send(f"B:{int(data.get('n', 1))}")
                return self._json(200, {"ok": True})
            if path == "/e":
                agent.send("E")
                return self._json(200, {"ok": True})
            if path == "/d":
                agent.send(f"D:{int(data['id'])}")
                return self._json(200, {"ok": True})
            if path == "/u":
                agent.send(f"U:{int(data['id'])}")
                return self._json(200, {"ok": True})
            if path == "/x":
                agent.send("X")
                return self._json(200, {"ok": True})
            if path == "/m":
                dx, dy, w = int(data.get("dx", 0)), int(data.get("dy", 0)), int(data.get("w", 0))
                agent.send_mouse(dx, dy, w)
                return self._json(200, {"ok": True})
            if path == "/c":
                agent.send(f"C:{data.get('btn', 'left')}")
                return self._json(200, {"ok": True})
            if path == "/mp":
                agent.send(f"P:{data.get('btn', 'left')}")
                return self._json(200, {"ok": True})
            if path == "/mr":
                agent.send(f"R:{data.get('btn', 'left')}")
                return self._json(200, {"ok": True})
            self._json(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})


def main() -> None:
    print(f"starting {agent.mode} → pipi ...", flush=True)
    try:
        agent.start()
    except Exception as e:
        agent.last_error = str(e)
        print(f"warn: {agent.mode} start failed: {e}", flush=True)
        if agent.mode == "bt":
            print("falling back to wifi", flush=True)
            try:
                agent.set_mode("wifi")
            except Exception as e2:
                print(f"wifi also failed: {e2}", flush=True)
    print(f"UI: http://127.0.0.1:{PORT}  mode={agent.mode}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
