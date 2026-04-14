"""
trang_chat.py — Web Chat v3.0
Port: 5000

Cải tiến:
  ✅ Fix bug api_rate (không dùng get_answer() như object)
  ✅ Streaming animation: hiện "suy nghĩ" từng bước + đáp án từng từ
  ✅ Chào user bằng tên đăng nhập
  ✅ Đáp án nằm chính giữa, không trong khung vuông cứng
  ✅ Nguồn hiển thị ở cuối đáp án
  ✅ Loading page khi admin vào trang quản trị
  ✅ Nạp Gemini API key từ cấu hình
"""
from flask import (Flask, jsonify, request, session as flask_session,
                   redirect, render_template_string, Response, stream_with_context)
from pathlib import Path
import json, time, uuid, logging, hashlib, subprocess, threading, re as _re

from dau_nao import (lay_dau_nao, doc_json, luu_json, khoi_tao_thu_muc,
                     FILE_CHUA_BIET)
from nguoi_dung import (
    dang_ky, dang_nhap, lay_ho_so, cap_nhat_ten,
    luu_phien_user, lay_danh_sach_phien_user, lay_phien_user,
    xoa_phien_user, lay_phien_khach, luu_phien_khach,
    lay_danh_sach_phien_khach, xoa_phien_khach,
)
from app_config import tai_cai_dat, luu_cai_dat, kiem_tra_admin_key

import os
import logging
# Tắt thông báo từ Hugging Face và Transformers
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

BASE_DIR    = Path(__file__).resolve().parent
NGROK_TOKEN = "3Ah7Q1b3lpfRwTaOiCGu3PS61xO_2YjSr6dpZ5d7Jt5eR6WdW"
_PUBLIC_URL = ""

app = Flask(__name__)
app.secret_key = hashlib.sha256(b"ai_chat1_key_2024").hexdigest()
app.config["SESSION_PERMANENT"]           = True
app.config["PERMANENT_SESSION_LIFETIME"]  = __import__("datetime").timedelta(days=30)
app.config["SESSION_COOKIE_SAMESITE"]     = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"]     = True
khoi_tao_thu_muc()

_SESSIONS: dict[str, dict] = {}

# ─── Quản lý session ─────────────────────────────────────────────────────────
def _get_or_create_session(sid, uid):
    if sid and sid in _SESSIONS:
        return sid, _SESSIONS[sid]
    if sid:
        s = lay_phien_user(uid, sid) if uid else lay_phien_khach(sid)
        if s:
            _SESSIONS[sid] = {"messages": s.get("messages", []), "uid": uid}
            return sid, _SESSIONS[sid]
    new_sid = uuid.uuid4().hex[:10]
    _SESSIONS[new_sid] = {"messages": [], "uid": uid}
    return new_sid, _SESSIONS[new_sid]

def _save_session(uid, sid, messages):
    title = next((m["content"][:50] for m in messages if m.get("role") == "user"), "Cuộc trò chuyện")
    data = {"sid": sid, "title": title, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": messages}
    if uid: luu_phien_user(uid, data)
    else:   luu_phien_khach(data)


# ─── Trang quản trị loading page ─────────────────────────────────────────────
_ADMIN_LAUNCHING = False
_ADMIN_READY     = False

LOADING_PAGE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='0.85em' x='-0.05em' font-size='85'%3E🤓%3C/text%3E%3C/svg%3E">
<title>🛡️ Đang khởi động Admin...</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#080c14;color:#dde4f0;
  display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{text-align:center;padding:40px}
.orb{width:90px;height:90px;border-radius:50%;background:linear-gradient(135deg,#f59b42,#f06a6a);
  display:flex;align-items:center;justify-content:center;font-size:40px;margin:0 auto 28px;
  animation:pulse 1.8s ease-in-out infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(245,155,66,.4)}50%{box-shadow:0 0 0 20px rgba(245,155,66,0)}}
h2{font-size:22px;margin-bottom:10px}
p{color:#6b7a99;font-size:14px;margin-bottom:28px}
.steps{display:flex;flex-direction:column;gap:10px;margin-bottom:28px;max-width:360px;margin-left:auto;margin-right:auto}
.step{display:flex;align-items:center;gap:10px;padding:10px 16px;border-radius:10px;
  background:rgba(255,255,255,.04);border:1px solid rgba(100,160,255,.1);font-size:13px;text-align:left}
.step.done{border-color:rgba(46,200,126,.3);color:#2ec87e}
.step.active{border-color:rgba(91,156,246,.4);animation:blink .9s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.5}}
.step.wait{color:#6b7a99}
.dot{width:8px;height:8px;border-radius:50%;flex:0 0 8px}
.dot-done{background:#2ec87e}.dot-active{background:#5b9cf6;animation:blink .9s infinite}.dot-wait{background:#2d3448}
</style>
</head>
<body>
<div class="box">
  <div class="orb">🛡️</div>
  <h2>Đang khởi động Admin Panel</h2>
  <p>Vui lòng chờ trong giây lát...</p>
  <div class="steps" id="steps">
    <div class="step active" id="s1"><div class="dot dot-active"></div>Khởi động server quản trị...</div>
    <div class="step wait" id="s2"><div class="dot dot-wait"></div>Tạo đường dẫn công khai (ngrok)...</div>
    <div class="step wait" id="s3"><div class="dot dot-wait"></div>Sẵn sàng chuyển hướng...</div>
  </div>
  <p id="msg" style="font-size:12px">Thường mất 10–20 giây</p>
</div>
<script>
let step = 1;
function setStep(n) {
  for (let i=1; i<=3; i++) {
    const el = document.getElementById('s'+i);
    const dot = el.querySelector('.dot');
    if (i < n) { el.className='step done'; dot.className='dot dot-done'; }
    else if (i === n) { el.className='step active'; dot.className='dot dot-active'; }
    else { el.className='step wait'; dot.className='dot dot-wait'; }
  }
}
async function poll() {
  try {
    const r = await fetch('/admin/status');
    const d = await r.json();
    if (d.step >= 2) setStep(2);
    if (d.step >= 3) setStep(3);
    if (d.ready && d.url) {
      document.getElementById('msg').textContent = 'Đang chuyển hướng...';
      setTimeout(() => window.location.href = d.url, 600);
      return;
    }
  } catch(e) {}
  setTimeout(poll, 1800);
}
setTimeout(poll, 2000);
</script>
</body>
</html>"""

# ─── HTML CHAT ────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='0.85em' x='-0.05em' font-size='85'%3E🤓%3C/text%3E%3C/svg%3E">
<title> AI Học Tập</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Sora:wght@700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#080c14;--bg2:#0e1420;--card:#141c2e;--card2:#1a2336;
  --border:rgba(100,160,255,.1);--text:#dde4f0;--sub:#6b7a99;
  --blue:#5b9cf6;--blue2:#7eb3ff;--violet:#8b6ff7;--cyan:#3dd6f5;
  --grad:linear-gradient(135deg,#5b9cf6,#8b6ff7);
  --green:#2ec87e;--red:#f06a6a;--gold:#f5b942;
  --font:"Outfit",system-ui,sans-serif;--glow:0 0 40px rgba(91,156,246,.12);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;font-family:var(--font)}
body{background:var(--bg);color:var(--text);
  background-image:
    radial-gradient(ellipse 60% 40% at 20% 60%,rgba(91,156,246,.07) 0%,transparent 70%),
    radial-gradient(ellipse 50% 50% at 80% 20%,rgba(139,111,247,.06) 0%,transparent 70%)}
.app{display:flex;height:100vh}

/* SIDEBAR */
.sidebar{width:260px;flex:0 0 260px;background:var(--bg2);border-right:1px solid var(--border);
  display:flex;flex-direction:column;transition:transform .3s ease}
.sidebar.hidden{transform:translateX(-100%);position:absolute;height:100%;z-index:50}
.sb-top{padding:14px 12px 10px;border-bottom:1px solid var(--border)}
.brand{display:flex;align-items:center;gap:9px;margin-bottom:12px}
.brand-icon{width:36px;height:36px;border-radius:10px;background:var(--grad);
  display:flex;align-items:center;justify-content:center;font-size:18px;
  box-shadow:0 3px 14px rgba(91,156,246,.35)}
.brand-name{font-family:"Sora",sans-serif;font-size:14px;background:var(--grad);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.brand-sub{font-size:10px;color:var(--sub);margin-top:1px}
.btn-new{width:100%;padding:8px 12px;border-radius:10px;border:1px dashed rgba(91,156,246,.35);
  background:rgba(91,156,246,.07);color:var(--blue2);font:600 12px var(--font);
  cursor:pointer;transition:all .18s;display:flex;align-items:center;justify-content:center;gap:6px}
.btn-new:hover{background:var(--blue);color:#fff;border-color:var(--blue);box-shadow:0 3px 14px rgba(91,156,246,.3)}
.sb-auth{padding:10px 12px;border-bottom:1px solid var(--border)}
.user-row{display:flex;align-items:center;gap:9px;padding:7px 9px;border-radius:9px;
  background:rgba(255,255,255,.04);cursor:pointer;transition:background .15s}
.uav{width:32px;height:32px;border-radius:50%;background:var(--grad);
  display:flex;align-items:center;justify-content:center;font:700 13px var(--font);
  color:#fff;flex:0 0 32px;overflow:hidden;box-shadow:0 2px 8px rgba(91,156,246,.3)}
.uinfo{flex:1;min-width:0}
.uname{font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.uemail{font-size:10px;color:var(--sub);margin-top:1px}
.btn-login{width:100%;padding:8px;border-radius:9px;border:none;background:var(--grad);
  color:#fff;font:600 12px var(--font);cursor:pointer;box-shadow:0 3px 12px rgba(91,156,246,.25);transition:opacity .2s}
.btn-login:hover{opacity:.88}
.btn-logout{background:transparent;color:var(--sub);border:1px solid var(--border);
  font:500 10px var(--font);padding:3px 9px;border-radius:6px;cursor:pointer;margin-top:5px;
  transition:all .15s;width:100%}
.btn-logout:hover{background:rgba(240,106,106,.1);color:var(--red)}
.admin-links{display:none;flex-direction:column;gap:4px;margin-top:8px}
.admin-links.show{display:flex}
.adm-btn{display:flex;align-items:center;gap:7px;padding:7px 10px;border-radius:8px;
  background:rgba(255,255,255,.04);border:1px solid var(--border);
  color:var(--sub);font:600 11px var(--font);cursor:pointer;text-decoration:none;transition:all .15s}
.adm-btn:hover{color:var(--blue2);background:rgba(91,156,246,.1);border-color:rgba(91,156,246,.25)}
.adm-badge{background:var(--grad);color:#fff;font-size:9px;padding:2px 6px;border-radius:4px}
.sb-lbl{padding:8px 12px 3px;font-size:10px;font-weight:700;color:var(--sub);
  text-transform:uppercase;letter-spacing:.1em}
.sess-list{flex:1;overflow-y:auto;padding:3px 7px 8px}
.sess-list::-webkit-scrollbar{width:3px}
.sess-list::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.sess-item{display:flex;align-items:center;gap:8px;padding:7px;border-radius:9px;
  cursor:pointer;margin-bottom:1px;transition:all .15s}
.sess-item:hover{background:rgba(255,255,255,.05)}
.sess-item.active{background:rgba(91,156,246,.1);border:1px solid rgba(91,156,246,.2)}
.sess-ico{width:26px;height:26px;border-radius:7px;background:rgba(255,255,255,.06);
  display:flex;align-items:center;justify-content:center;font-size:12px;flex:0 0 26px}
.sess-info{flex:1;min-width:0}
.sess-title{font-size:11px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sess-date{font-size:10px;color:var(--sub);margin-top:1px}
.sess-del{border:none;background:transparent;color:rgba(255,255,255,.15);
  cursor:pointer;padding:3px 4px;border-radius:4px;font-size:13px;opacity:0;transition:all .15s}
.sess-item:hover .sess-del{opacity:1}
.sess-del:hover{color:var(--red)}

/* CHAT MAIN */
.chat-main{flex:1;display:flex;flex-direction:column;min-width:0}
.top-bar{display:flex;align-items:center;gap:10px;padding:11px 16px;
  border-bottom:1px solid var(--border);background:rgba(8,12,20,.9);backdrop-filter:blur(8px)}
.toggle-btn{width:34px;height:34px;border-radius:9px;background:var(--card2);
  border:1px solid rgba(91,156,246,.35);cursor:pointer;display:flex;align-items:center;
  justify-content:center;font-size:16px;color:#a0b4d0;transition:all .18s;flex:0 0 34px;font-weight:700}
.toggle-btn:hover{background:rgba(91,156,246,.15);color:var(--blue2)}
.top-title{font:600 13px var(--font);color:var(--sub);flex:1}
.pub-links{display:flex;gap:5px}
.pub-link{display:flex;align-items:center;gap:5px;padding:5px 10px;border-radius:7px;
  background:var(--card);border:1px solid var(--border);color:var(--sub);
  font:500 11px var(--font);text-decoration:none;cursor:pointer;transition:all .15s;white-space:nowrap}
.pub-link:hover{color:var(--blue2);border-color:rgba(91,156,246,.3)}

/* WELCOME */
.welcome{flex:1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:18px;padding:32px 20px;text-align:center}
.bot-orb{width:100px;height:100px;border-radius:50%;
  background:radial-gradient(circle at 35% 35%,rgba(91,156,246,.4),rgba(139,111,247,.4));
  border:1px solid rgba(91,156,246,.3);display:flex;align-items:center;justify-content:center;
  font-size:48px;animation:orbit 4s ease-in-out infinite;
  box-shadow:0 0 50px rgba(91,156,246,.2)}
@keyframes orbit{0%,100%{transform:translateY(0)}50%{transform:translateY(-12px)}}
.wc-title{font-family:"Sora",sans-serif;font-size:26px;background:var(--grad);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.wc-sub{font-size:13px;color:var(--sub);max-width:440px;line-height:1.7}
.chips{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;max-width:500px}
.chip{padding:7px 14px;border-radius:18px;background:var(--card);border:1px solid var(--border);
  font-size:12px;color:var(--sub);cursor:pointer;transition:all .18s}
.chip:hover{background:rgba(91,156,246,.15);color:var(--blue2);border-color:rgba(91,156,246,.3);transform:translateY(-2px)}

/* MESSAGES — nằm chính giữa, không có khung vuông cứng */
.messages{flex:1;overflow-y:auto;padding:24px 16px;display:flex;flex-direction:column;
  gap:16px;align-items:center}
.messages::-webkit-scrollbar{width:4px}
.messages::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.msg-wrapper{width:100%;max-width:780px;display:flex;flex-direction:column;gap:4px}
.msg{display:flex;gap:9px;animation:msgIn .25s cubic-bezier(.34,1.4,.64,1)}
@keyframes msgIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.msg.user{align-self:flex-end;flex-direction:row-reverse}
.msg.ai{align-self:flex-start;width:100%}
.av{width:32px;height:32px;border-radius:50%;flex:0 0 32px;display:flex;align-items:center;
  justify-content:center;font-size:15px;margin-top:4px}
.av.ai-av{background:var(--grad);box-shadow:0 2px 10px rgba(91,156,246,.3)}
.av.u-av{background:linear-gradient(135deg,var(--green),#14855a)}

/* Bubble: không khung cứng cho AI */
.bubble{padding:12px 16px;border-radius:16px;font-size:13.5px;line-height:1.8;word-break:break-word}
.msg.user .bubble{background:var(--grad);color:#fff;border-radius:16px 16px 4px 16px;
  box-shadow:0 3px 16px rgba(91,156,246,.22)}
.msg.ai .bubble{background:transparent;color:var(--text);
  border:none;white-space:pre-wrap;flex:1}
.msg.ai .bubble strong,.msg.ai .bubble b{color:var(--blue2);font-weight:700}
.msg.ai .bubble table{border-collapse:collapse;margin:8px 0;width:100%}
.msg.ai .bubble td,.msg.ai .bubble th{border:1px solid var(--border);padding:6px 10px;font-size:12px}
.msg.ai .bubble th{background:rgba(91,156,246,.1);color:var(--blue2)}

/* Thoughts — các bước suy nghĩ */
.thoughts{display:flex;flex-direction:column;gap:4px;margin-bottom:8px;padding-left:41px}
.thought-item{font-size:11px;color:var(--sub);display:flex;align-items:center;gap:6px;
  animation:fadeIn .3s ease}
@keyframes fadeIn{from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:none}}

/* Nguồn — hiển thị ở cuối đáp án */
.source-row{display:flex;align-items:center;gap:6px;margin-top:6px;padding-left:41px;flex-wrap:wrap}
.src-chip{display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:99px;
  font-size:10px;font-weight:600;border:1px solid var(--border);color:var(--sub);background:rgba(255,255,255,.03)}
.src-chip.kb{border-color:rgba(46,200,126,.3);color:var(--green)}
.src-chip.gemini{border-color:rgba(91,156,246,.3);color:var(--blue2)}
.src-chip.wiki{border-color:rgba(245,185,66,.3);color:var(--gold)}

/* Actions + Rating */
.msg-foot{display:flex;align-items:center;gap:8px;margin-top:6px;flex-wrap:wrap;padding-left:41px}
.msg-time{font-size:10px;color:var(--sub)}
.action-row{display:flex;gap:4px}
.act-btn{border:none;background:rgba(255,255,255,.06);color:var(--sub);
  font:500 10px var(--font);padding:4px 9px;border-radius:6px;cursor:pointer;transition:all .15s}
.act-btn:hover{background:rgba(91,156,246,.15);color:var(--blue2)}
.rating{display:flex;gap:2px;margin-left:4px}
.star{font-size:13px;cursor:pointer;color:rgba(255,255,255,.18);transition:all .15s}
.star:hover,.star.lit{color:var(--gold);text-shadow:0 0 7px rgba(245,185,66,.5)}

/* Typing indicator */
.typing-indicator{display:flex;gap:5px;padding:10px 0;align-items:center}
.dot{width:6px;height:6px;border-radius:50%;background:var(--sub);animation:bounce .8s infinite}
.dot:nth-child(2){animation-delay:.16s}.dot:nth-child(3){animation-delay:.32s}
@keyframes bounce{0%,80%,100%{transform:scale(.5);opacity:.3}40%{transform:scale(1);opacity:1}}

/* Input */
.input-bar{padding:12px 16px;border-top:1px solid var(--border);background:var(--bg2);
  display:flex;gap:9px;align-items:flex-end;justify-content:center}
.inp-wrap{flex:1;max-width:780px;display:flex;align-items:flex-end;gap:8px;
  background:var(--card);border:1px solid var(--border);
  border-radius:18px;padding:8px 13px;transition:border-color .2s,box-shadow .2s}
.inp-wrap:focus-within{border-color:rgba(91,156,246,.45);box-shadow:0 0 0 3px rgba(91,156,246,.1)}
.inp-wrap textarea{flex:1;border:none;background:transparent;font:13.5px var(--font);
  resize:none;outline:none;max-height:120px;min-height:22px;line-height:1.5;color:var(--text)}
.inp-wrap textarea::placeholder{color:var(--sub)}
.send-btn{width:38px;height:38px;border-radius:50%;background:var(--grad);
  border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;
  flex:0 0 38px;transition:all .18s;box-shadow:0 3px 12px rgba(91,156,246,.3)}
.send-btn:hover:not(:disabled){transform:scale(1.08)}
.send-btn:disabled{background:var(--card);box-shadow:none;cursor:not-allowed}
.send-btn svg{fill:#fff;width:15px;height:15px}

/* Auth Modal */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.65);backdrop-filter:blur(7px);
  display:none;align-items:center;justify-content:center;z-index:200;padding:20px}
.modal-bg.open{display:flex;animation:fadeIn .2s}
.modal{background:var(--bg2);border:1px solid var(--border);border-radius:18px;
  width:100%;max-width:400px;padding:26px;box-shadow:0 20px 60px rgba(0,0,0,.5),var(--glow);
  animation:slideUp .28s cubic-bezier(.34,1.4,.64,1)}
@keyframes slideUp{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:none}}
.modal-h{font-family:"Sora",sans-serif;font-size:20px;margin-bottom:3px}
.modal-s{font-size:12px;color:var(--sub);margin-bottom:18px}
.tabs{display:flex;gap:2px;background:rgba(255,255,255,.05);border-radius:8px;padding:3px;margin-bottom:16px}
.tab{flex:1;padding:7px;border-radius:6px;border:none;font:600 12px var(--font);
  cursor:pointer;background:transparent;color:var(--sub);transition:all .2s}
.tab.active{background:var(--card2);color:var(--text)}
.fg{margin-bottom:11px}
.fg label{display:block;font-size:11px;font-weight:600;color:var(--sub);margin-bottom:4px}
.fg input{width:100%;border:1px solid var(--border);border-radius:9px;
  padding:9px 13px;font:13px var(--font);outline:none;
  background:rgba(255,255,255,.05);color:var(--text);transition:all .2s}
.fg input:focus{border-color:rgba(91,156,246,.45);background:rgba(91,156,246,.04);
  box-shadow:0 0 0 3px rgba(91,156,246,.1)}
.btn-submit{width:100%;padding:11px;border-radius:10px;border:none;
  background:var(--grad);color:#fff;font:600 13px var(--font);cursor:pointer;
  margin-top:4px;box-shadow:0 3px 14px rgba(91,156,246,.3);transition:opacity .2s}
.btn-submit:hover{opacity:.88}
.err-msg{color:var(--red);font-size:11px;margin-top:5px;min-height:14px}
.skip-btn{display:block;text-align:center;margin-top:12px;border:none;
  background:transparent;color:var(--sub);font:13px var(--font);cursor:pointer}
.skip-btn:hover{color:var(--text)}
@media(max-width:650px){.sidebar{position:absolute;height:100%}.msg{max-width:92%}}
</style>
</head>
<body>
<div class="app">
  <div class="sidebar" id="sidebar">
    <div class="sb-top">
      <div class="brand">
        <div class="brand-icon">🎓</div>
        <div><div class="brand-name">AI Học Đường</div><div class="brand-sub">Một dự án của team HK</div></div>
      </div>
      <button class="btn-new" id="newBtn">💡 Cuộc trò chuyện mới</button>
    </div>
    <div class="sb-auth">
      <div id="guestView">
        <button class="btn-login" id="openLogin">🔑 Đăng nhập / Đăng ký</button>
      </div>
      <div id="userView" style="display:none">
        <div class="user-row">
          <div class="uav" id="uAv">U</div>
          <div class="uinfo">
            <div class="uname" id="uName">—</div>
            <div class="uemail" id="uEmail">—</div>
          </div>
        </div>
        <button class="btn-logout" onclick="logout()">Đăng xuất</button>
        <div class="admin-links" id="adminLinks">
          <a class="adm-btn" id="linkAdmin" href="#" onclick="launchAdmin(event)">
            <span>🛡️</span> Admin / Train <span class="adm-badge">Public</span>
          </a>
        </div>
      </div>
    </div>
    <div class="sb-lbl">Lịch sử chat</div>
    <div class="sess-list" id="sessList"></div>
  </div>

  <div class="chat-main">
    <div class="top-bar">
      <button class="toggle-btn" id="toggleBtn">☰</button>
      <div class="top-title" id="topTitle">AI Học Tập</div>
      <div class="pub-links" id="pubLinksBar"></div>
    </div>

    <div class="welcome" id="welcomeScreen">
      <div class="bot-orb">🤖</div>
      <div class="wc-title" id="wcTitle">Xin chào! Mình là AI Học Đường</div>
      <div class="wc-sub" id="wcSub">Trợ lý học tập thông minh — giúp bạn học tốt hơn, hiểu sâu hơn 🎯</div>
      <div class="chips">
        <div class="chip" onclick="chip('ADN là gì?')">🧬 ADN là gì?</div>
        <div class="chip" onclick="chip('Công thức tính đạo hàm')">📐 Đạo hàm</div>
        <div class="chip" onclick="chip('Cách phòng ngừa đột quỵ')">🏥 Phòng đột quỵ</div>
        <div class="chip" onclick="chip('Thì hiện tại hoàn thành trong tiếng Anh')">📘 Tiếng Anh</div>
        <div class="chip" onclick="chip('Bị co giật phải làm gì?')">🚨 Sơ cứu</div>
        <div class="chip" onclick="chip('Cách học thuộc bài nhanh')">📚 Học thuộc</div>
      </div>
    </div>

    <div class="messages" id="msgs" style="display:none"></div>

    <div class="input-bar">
      <div class="inp-wrap">
        <textarea id="qi" placeholder="Hỏi về bài học, y tế, kỹ thuật..." rows="1"></textarea>
      </div>
      <button class="send-btn" id="sendBtn">
        <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
      </button>
    </div>
  </div>
</div>

<!-- Auth Modal -->
<div class="modal-bg" id="authModal">
  <div class="modal">
    <div class="modal-h">Chào mừng 👋</div>
    <div class="modal-s">Đăng nhập để lưu lịch sử & cá nhân hóa trải nghiệm</div>
    <div class="tabs">
      <button class="tab active" id="tLogin" onclick="tab('login')">Đăng nhập</button>
      <button class="tab" id="tReg" onclick="tab('register')">Đăng ký</button>
    </div>
    <div id="fLogin">
      <div class="fg"><label>Tên đăng nhập hoặc Email</label>
        <input id="liU" placeholder="username hoặc email"></div>
      <div class="fg"><label>Mật khẩu</label><input id="liP" type="password" placeholder="••••••••"></div>
      <div class="fg"><label>Key admin <span style="color:var(--sub);font-weight:400">(tùy chọn)</span></label>
        <input id="liKey" placeholder="Nhập key nếu có"></div>
      <div class="err-msg" id="liErr"></div>
      <button class="btn-submit" onclick="doLogin()">Đăng nhập</button>
    </div>
    <div id="fReg" style="display:none">
      <div class="fg"><label>Tên đăng nhập</label><input id="rgU" placeholder="vd: nguyen_a"></div>
      <div class="fg"><label>Tên hiển thị <span style="color:var(--sub);font-weight:400">(AI gọi tên bạn)</span></label>
        <input id="rgN" placeholder="vd: Nguyễn Anh"></div>
      <div class="fg"><label>Email <span style="color:var(--sub);font-weight:400">(tùy chọn)</span></label>
        <input id="rgE" type="email" placeholder="email@..."></div>
      <div class="fg"><label>Mật khẩu</label><input id="rgP" type="password" placeholder="••••••••"></div>
      <div class="fg"><label>Key admin <span style="color:var(--sub);font-weight:400">(tùy chọn)</span></label>
        <input id="rgKey" placeholder="Nhập key nếu có"></div>
      <div class="err-msg" id="rgErr"></div>
      <button class="btn-submit" onclick="doReg()">Tạo tài khoản</button>
    </div>
    <button class="skip-btn" onclick="closeModal()">Bỏ qua — tiếp tục không cần đăng nhập</button>
  </div>
</div>

<script>
let cu=null, sid=null, msgs=[], sending=false;
const $=id=>document.getElementById(id);
const ta=$('qi');

ta.addEventListener('input',()=>{ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,120)+'px'});
ta.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
$('sendBtn').addEventListener('click',send);
$('newBtn').addEventListener('click',newChat);
$('toggleBtn').addEventListener('click',()=>$('sidebar').classList.toggle('hidden'));
$('openLogin').addEventListener('click',()=>$('authModal').classList.add('open'));
$('authModal').addEventListener('click',e=>{if(e.target===$('authModal'))closeModal()});

function t(){return new Date().toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'})}
function tab(v){$('fLogin').style.display=v==='login'?'':'none';$('fReg').style.display=v==='register'?'':'none';
  $('tLogin').classList.toggle('active',v==='login');$('tReg').classList.toggle('active',v==='register')}
function closeModal(){$('authModal').classList.remove('open')}
function esc(s){return String(s||'').replace(/</g,'&lt;')}
function sleep(ms){return new Promise(r=>setTimeout(r,ms))}

// ── Auth ──────────────────────────────────────────────────────────────────
async function doLogin(){
  const u=$('liU').value.trim(),p=$('liP').value,k=$('liKey').value;
  if(!u||!p){$('liErr').textContent='Vui lòng nhập đầy đủ';return}
  const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:u,password:p,admin_key:k})});
  const d=await r.json();
  if(d.ok){onLogin(d);closeModal()}else $('liErr').textContent=d.error||'Sai thông tin';
}
async function doReg(){
  const u=$('rgU').value.trim(),n=$('rgN').value.trim(),e=$('rgE').value.trim(),
        p=$('rgP').value,k=$('rgKey').value;
  if(!u||!p){$('rgErr').textContent='Cần tên và mật khẩu';return}
  if(p.length<6){$('rgErr').textContent='Mật khẩu ≥6 ký tự';return}
  const r=await fetch('/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:u,display_name:n,email:e,password:p,admin_key:k})});
  const d=await r.json();
  if(d.ok){onLogin({...d,email:e});closeModal()}else $('rgErr').textContent=d.error||'Lỗi';
}
async function logout(){
  await fetch('/api/auth/logout',{method:'POST'});
  cu=null;$('guestView').style.display='';$('userView').style.display='none';
  $('adminLinks').classList.remove('show');
  $('wcTitle').textContent='Xin chào! Mình là AI Học Đường';
  $('wcSub').textContent='Trợ lý học tập thông minh — giúp bạn học tốt hơn, hiểu sâu hơn 🎯';
  newChat();loadSessions();
}
function onLogin(d){
  cu={uid:d.uid,name:d.display_name||d.username,email:d.email||'',admin:!!d.admin_key_ok};
  $('guestView').style.display='none';$('userView').style.display='block';
  $('uName').textContent=cu.name;$('uEmail').textContent=cu.email||'Đã đăng nhập';
  $('uAv').textContent=(cu.name||'U')[0].toUpperCase();
  // Chào user bằng tên đăng nhập
  $('wcTitle').textContent=`Chào ${cu.name}! 👋`;
  $('wcSub').textContent=`✨Mình là AI Học Tập — sẵn sàng giúp ${cu.name} học tốt hơn mỗi ngày 🎯`;
  if(cu.admin) $('adminLinks').classList.add('show');
  _loadPublicLinks();loadSessions();
}

// ── Admin Launch ──────────────────────────────────────────────────────────
async function launchAdmin(e){
  e.preventDefault();
  const win=window.open('/admin/loading','_blank');
  if(!win) alert('Cho phép popup để mở trang Admin');
}

async function _loadPublicLinks(){
  try{
    const d=await fetch('/api/public-links').then(r=>r.json());
    const bar=$('pubLinksBar');
    if(d.admin_url&&d.admin_url!=='http://localhost:5002'){
      bar.innerHTML=`<a class="pub-link" onclick="window.open('/admin/loading','_blank');return false" href="#">🛡️ Admin</a>`;
      $('linkAdmin').href='/admin/loading';
    }
  }catch{}
}

// ── Sessions ──────────────────────────────────────────────────────────────
async function loadSessions(){
  const url=cu?'/api/phien':'/api/phien/khach';
  const list=await fetch(url).then(r=>r.json()).catch(()=>[]);
  const el=$('sessList');
  if(!list.length){el.innerHTML='<div style="padding:12px 8px;font-size:11px;color:var(--sub);text-align:center">Chưa có lịch sử</div>';return}
  el.innerHTML=list.map(s=>`
    <div class="sess-item ${s.sid===sid?'active':''}" data-sid="${s.sid}">
      <div class="sess-ico">💬</div>
      <div class="sess-info"><div class="sess-title">${esc(s.title||'...')}</div>
        <div class="sess-date">${(s.created||'').slice(5,10)} · ${s.count||0} tin</div></div>
      <button class="sess-del" data-del="${s.sid}" title="Xóa">×</button>
    </div>`).join('');
  el.querySelectorAll('.sess-item').forEach(item=>{
    item.addEventListener('click',e=>{if(e.target.dataset.del)return;loadSess(item.dataset.sid)});
  });
  el.querySelectorAll('.sess-del').forEach(btn=>{
    btn.addEventListener('click',async e=>{
      e.stopPropagation();
      const url=cu?`/api/phien/${btn.dataset.del}`:`/api/phien/khach/${btn.dataset.del}`;
      await fetch(url,{method:'DELETE'});
      if(btn.dataset.del===sid)newChat();loadSessions();
    });
  });
}
async function loadSess(s){
  const url=cu?`/api/phien/${s}`:`/api/phien/khach/${s}`;
  const d=await fetch(url).then(r=>r.json());
  if(!d.messages)return;
  sid=s;msgs=d.messages||[];
  const msgsEl=$('msgs');
  $('welcomeScreen').style.display='none';msgsEl.style.display='flex';msgsEl.innerHTML='';
  d.messages.forEach(m=>addMsg(m.role,m.content,m.time,m.answer_id,m.sources||[]));
  msgsEl.scrollTop=msgsEl.scrollHeight;loadSessions();
}
function newChat(){
  sid=null;msgs=[];
  $('welcomeScreen').style.display='';$('msgs').style.display='none';$('msgs').innerHTML='';
  document.querySelectorAll('.sess-item').forEach(e=>e.classList.remove('active'));
}

// ── Render ────────────────────────────────────────────────────────────────
function renderText(txt){
  return String(txt||'').replace(/</g,'&lt;')
    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.*?)\*/g,'<em>$1</em>')
    .replace(/\n/g,'<br>');
}

function buildSourceHtml(sources){
  if(!sources||!sources.length) return '';
  return '<div class="source-row">' +
    sources.map(s=>{
      const cls = s.source==='KB nội bộ'?'kb': s.source&&s.source.includes('Gemini')?'gemini':'wiki';
      return `<span class="src-chip ${cls}">📌 ${esc(s.source)}: ${esc((s.title||'').slice(0,40))}</span>`;
    }).join('') +
  '</div>';
}

function addMsg(role, text, timeStr, answerId, sources){
  const msgsEl=$('msgs');
  $('welcomeScreen').style.display='none';msgsEl.style.display='flex';
  const wrapper=document.createElement('div');wrapper.className='msg-wrapper';
  const div=document.createElement('div');div.className=`msg ${role}`;

  const avHtml=role==='user'?
    `<div class="av u-av">${cu?(cu.name[0]||'U').toUpperCase():'😊'}</div>`:
    '<div class="av ai-av">🤖</div>';

  const footHtml=role==='ai'?`
    <div class="msg-foot">
      <div class="action-row">
        <button class="act-btn" onclick="copyMsg(this)">📋 Sao chép</button>
        <button class="act-btn" onclick="report('${answerId}')">🚩 Báo cáo</button>
      </div>
      <span class="msg-time">${timeStr||''}</span>
      <div class="rating">${[1,2,3,4,5].map(n=>`<span class="star" onclick="rate('${answerId}',${n},this,'${(text||'').replace(/'/g,'').slice(0,80)}')">★</span>`).join('')}</div>
    </div>
    ${buildSourceHtml(sources)}`:'';

  div.innerHTML=`${avHtml}<div style="flex:1;min-width:0">
    <div class="bubble">${renderText(text)}</div>
    ${footHtml}
  </div>`;
  wrapper.appendChild(div);
  msgsEl.appendChild(wrapper);
  msgsEl.scrollTop=msgsEl.scrollHeight;
}

// ── Thoughts + Streaming animation ───────────────────────────────────────
function showTyping(){
  const msgsEl=$('msgs');
  $('welcomeScreen').style.display='none';msgsEl.style.display='flex';
  const wrapper=document.createElement('div');wrapper.className='msg-wrapper';wrapper.id='typingWrapper';
  wrapper.innerHTML=`<div class="msg ai">
    <div class="av ai-av">🤖</div>
    <div style="flex:1">
      <div class="thoughts" id="thoughtsList"></div>
      <div class="bubble"><div class="typing-indicator">
        <div class="dot"></div><div class="dot"></div><div class="dot"></div>
      </div></div>
    </div>
  </div>`;
  msgsEl.appendChild(wrapper);msgsEl.scrollTop=msgsEl.scrollHeight;
}

async function showThoughts(thoughts){
  const list=document.getElementById('thoughtsList');
  if(!list)return;
  for(const t of thoughts){
    const item=document.createElement('div');
    item.className='thought-item';
    item.innerHTML=`<span style="opacity:.5">···</span> ${renderText(t)}`;
    list.appendChild(item);
    await sleep(650);
    document.getElementById('msgs')?.scrollTo({top:99999,behavior:'smooth'});
  }
}

async function animateAnswer(text, wrapper, sources, answerId){
  if(!wrapper)return;
  const div=wrapper.querySelector('.msg.ai');
  if(!div)return;
  const avHtml=div.querySelector('.av')?.outerHTML||'';

  div.innerHTML=`${avHtml}<div class="ai-content" style="flex:1;min-width:0">
    <div class="bubble" id="streamBubble_${answerId}"></div>
  </div>`;

  const bubble=document.getElementById(`streamBubble_${answerId}`);
  if(!bubble)return;

  // Hiện từng từ
  const words=text.split(' ');
  let rendered='';
  for(let i=0;i<words.length;i++){
    rendered+=words[i]+(i<words.length-1?' ':'');
    bubble.innerHTML=renderText(rendered);
    document.getElementById('msgs')?.scrollTo({top:99999,behavior:'smooth'});
    await sleep(Math.min(25+Math.random()*15, 50));
  }

  // Thêm footer + sources
  const footHtml=`
    <div class="msg-foot">
      <div class="action-row">
        <button class="act-btn" onclick="copyMsg(this)">📋 Sao chép</button>
        <button class="act-btn" onclick="report('${answerId}')">🚩 Báo cáo</button>
      </div>
      <span class="msg-time">${t()}</span>
      <div class="rating">${[1,2,3,4,5].map(n=>`<span class="star" onclick="rate('${answerId}',${n},this,'')">★</span>`).join('')}</div>
    </div>
    ${buildSourceHtml(sources)}`;
  div.querySelector('.ai-content').insertAdjacentHTML('beforeend', footHtml);

  // QUAN TRỌNG: Xóa id để tránh conflit với tin nhắn tiếp theo
  wrapper.removeAttribute('id');
}

function removeTyping(){const e=document.getElementById('typingWrapper');if(e)e.remove()}

// ── Rate / Report / Copy ─────────────────────────────────────────────────
async function rate(aid,n,el,question){
  el.parentElement.querySelectorAll('.star').forEach((s,i)=>s.classList.toggle('lit',i<n));
  await fetch('/api/danh-gia',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({answer_id:aid,rating:n,question})});
}
function copyMsg(btn){
  const text=btn.closest('.msg')?.querySelector('.bubble')?.innerText||'';
  navigator.clipboard.writeText(text).then(()=>{const old=btn.textContent;btn.textContent='✅ Đã copy';setTimeout(()=>btn.textContent=old,1800)});
}
async function report(aid){
  const reason=prompt('Lý do báo cáo (tùy chọn):');
  if(reason===null)return;
  await fetch('/api/bao-cao',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({answer_id:aid,reason})});
  alert('Đã ghi nhận — cảm ơn phản hồi!');
}
function chip(txt){$('qi').value=txt;send()}

// ── SEND — main function ─────────────────────────────────────────────────
async function send(){
  if(sending)return;
  const q=$('qi').value.trim();if(!q)return;
  $('qi').value='';$('qi').style.height='auto';
  sending=true;$('sendBtn').disabled=true;
  addMsg('user',q,t());msgs.push({role:'user',content:q,time:t()});
  showTyping();

  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({query:q,sid,uid:cu?.uid||null,messages:msgs.slice(-12)})});
    const d=await r.json();
    sid=d.sid||sid;
    // Animate đáp án từng từ (không hiện thoughts trong chat)
    const wrapper=document.getElementById('typingWrapper');
    await animateAnswer(d.answer||'⚠️ Lỗi xử lý.',wrapper,d.sources||[],d.answer_id||'');
    msgs.push({role:'ai',content:d.answer,time:t(),answer_id:d.answer_id,sources:d.sources||[]});
    loadSessions();
  }catch(e){
    removeTyping();
    addMsg('ai','⚠️ Lỗi kết nối. Thử lại nhé.','','',[]);
  }
  sending=false;$('sendBtn').disabled=false;ta.focus();
}

// ── Init ─────────────────────────────────────────────────────────────────
window.addEventListener('beforeunload',()=>{
  if(sid)fetch('/api/phien/'+sid+'/dong',{method:'POST',keepalive:true});
});
(async()=>{
  const r=await fetch('/api/auth/toi');const d=await r.json();
  if(d.uid)onLogin(d);else loadSessions();
})();
</script>
</body>
</html>"""

# ═══ Routes ═══════════════════════════════════════════════════════════════════

@app.route("/")
def index(): return render_template_string(HTML)

# ── Admin Launch ──────────────────────────────────────────────────────────────
@app.route("/admin/loading")
def admin_loading():
    global _ADMIN_LAUNCHING, _ADMIN_READY
    if not _ADMIN_LAUNCHING:
        _ADMIN_LAUNCHING = True
        _ADMIN_READY = False
        threading.Thread(target=_launch_admin_server, daemon=True).start()
    return LOADING_PAGE

@app.route("/admin/status")
def admin_status():
    cfg = tai_cai_dat()
    admin_url = cfg.get("public_admin_url", "")
    if _ADMIN_READY and admin_url:
        return jsonify({"ready": True, "url": admin_url, "step": 3})
    elif _ADMIN_LAUNCHING:
        return jsonify({"ready": False, "step": 2})
    return jsonify({"ready": False, "step": 1})

def _launch_admin_server():
    global _ADMIN_READY
    try:
        import subprocess as sp, sys
        sp.Popen([sys.executable, str(BASE_DIR / "quan_tri.py")],
                 cwd=str(BASE_DIR))
        time.sleep(18)  # chờ ngrok khởi động
        _ADMIN_READY = True
    except Exception as e:
        logging.error(f"Launch admin error: {e}")
        _ADMIN_READY = True  # dù lỗi cũng set ready để không treo mãi

# ── Public Links ──────────────────────────────────────────────────────────────
@app.get("/api/public-links")
def api_public_links():
    cfg = tai_cai_dat()
    return jsonify({"admin_url": cfg.get("public_admin_url","") or "http://localhost:5002"})

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/api/auth/register")
def api_register():
    b = request.get_json(silent=True) or {}
    result = dang_ky(b.get("username",""), b.get("password",""),
                     b.get("display_name",""), b.get("email",""))
    if result["ok"]:
        flask_session.permanent = True
        flask_session["uid"] = result["uid"]
        ok = kiem_tra_admin_key(str(b.get("admin_key","")))
        flask_session["admin_key_ok"] = ok
        result["admin_key_ok"] = ok
    return jsonify(result)

@app.post("/api/auth/login")
def api_login():
    b = request.get_json(silent=True) or {}
    result = dang_nhap(b.get("username",""), b.get("password",""))
    if result["ok"]:
        flask_session.permanent = True
        flask_session["uid"] = result["uid"]
        ok = kiem_tra_admin_key(str(b.get("admin_key","")))
        flask_session["admin_key_ok"] = ok
        result["admin_key_ok"] = ok
    return jsonify(result)

@app.post("/api/auth/logout")
def api_logout():
    flask_session.clear()
    return jsonify({"ok": True})

@app.get("/api/auth/toi")
def api_me():
    uid = flask_session.get("uid")
    if not uid: return jsonify({"uid": None})
    p = lay_ho_so(uid)
    return jsonify({**p, "uid": uid, "admin_key_ok": bool(flask_session.get("admin_key_ok"))})

# ── Chat ──────────────────────────────────────────────────────────────────────
@app.post("/api/chat")
def api_chat():
    b = request.get_json(silent=True) or {}
    query = str(b.get("query","")).strip()
    uid   = b.get("uid") or flask_session.get("uid")
    sid, sess = _get_or_create_session(b.get("sid"), uid)

    cfg = tai_cai_dat()
    api_key = cfg.get("gemini_key", "") or cfg.get("anthropic_key", "") or ""

    ai_res = lay_dau_nao().get_answer(query, api_key)

    answer    = ai_res.get("answer", "⚠️ Lỗi xử lý câu hỏi.")
    sources   = ai_res.get("sources", [])
    thoughts  = ai_res.get("thoughts", [])
    answer_id = ai_res.get("answer_id", uuid.uuid4().hex[:8])

    now = time.strftime("%H:%M")
    sess["messages"].append({"role":"user","content":query,"time":now})
    sess["messages"].append({"role":"ai","content":answer,"time":now,
                              "answer_id":answer_id,"sources":sources})
    _save_session(uid, sid, sess["messages"])

    return jsonify({
        "answer": answer, "thoughts": thoughts,
        "sid": sid, "answer_id": answer_id, "sources": sources,
        "format_type": ai_res.get("format_type","")
    })

# ── Rating / Report ───────────────────────────────────────────────────────────
@app.post("/api/danh-gia")
def api_rate():
    b = request.get_json(silent=True) or {}
    lay_dau_nao().danh_gia(
        b.get("answer_id",""),
        int(b.get("rating",3)),
        b.get("question","")
    )
    return jsonify({"ok": True})

@app.post("/api/bao-cao")
def api_report():
    b = request.get_json(silent=True) or {}
    aid = b.get("answer_id",""); reason = b.get("reason","")
    items = doc_json(FILE_CHUA_BIET, [])
    items.insert(0, {"id": uuid.uuid4().hex[:10], "question": f"[Báo cáo] {aid}",
                     "report_reason": reason, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "status": "reported", "answer_id": aid})
    luu_json(items, FILE_CHUA_BIET)
    return jsonify({"ok": True})

# ── Sessions ──────────────────────────────────────────────────────────────────
@app.get("/api/phien")
def api_list_phien():
    uid = flask_session.get("uid")
    if not uid: return jsonify([])
    return jsonify(lay_danh_sach_phien_user(uid))

@app.get("/api/phien/<s>")
def api_get_phien(s):
    uid = flask_session.get("uid")
    if not uid: return jsonify({})
    return jsonify(lay_phien_user(uid, s) or {})

@app.delete("/api/phien/<s>")
def api_del_phien(s):
    uid = flask_session.get("uid")
    if not uid: return jsonify({"ok": False})
    return jsonify({"ok": xoa_phien_user(uid, s)})

@app.post("/api/phien/<s>/dong")
def api_dong(s):
    uid = flask_session.get("uid")
    if s in _SESSIONS:
        _save_session(uid, s, _SESSIONS[s]["messages"])
    return jsonify({"ok": True})

@app.get("/api/phien/khach")
def api_guest_list(): return jsonify(lay_danh_sach_phien_khach())

@app.get("/api/phien/khach/<s>")
def api_guest_get(s): return jsonify(lay_phien_khach(s) or {})

@app.delete("/api/phien/khach/<s>")
def api_guest_del(s): return jsonify({"ok": xoa_phien_khach(s)})

# ═══ MAIN ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import threading as _th

    def _start_ngrok():
        try:
            from pyngrok import ngrok
            ngrok.set_auth_token(NGROK_TOKEN)
            tunnel = ngrok.connect(5000)
            u = tunnel.public_url
            print(f"🌐 Chat: {u}")
            cfg = tai_cai_dat(); cfg["public_chat_url"] = u; luu_cai_dat(cfg)
        except Exception:
            try:
                import subprocess, sys
                proc = subprocess.Popen(
                    ["ngrok","http","5000","--authtoken",NGROK_TOKEN,"--log=stdout"],
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                for line in proc.stdout:
                    m = _re.search(r"https://[\w.-]+\.ngrok-free\.app", line)
                    if m:
                        u = m.group(0)
                        print(f"🌐 Chat: {u}")
                        cfg = tai_cai_dat(); cfg["public_chat_url"] = u; luu_cai_dat(cfg)
                        break
            except Exception as e2:
                print(f"Ngrok lỗi: {e2}")

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    _th.Thread(target=_start_ngrok, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
