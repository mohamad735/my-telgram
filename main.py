import json
import shutil
import os
import uuid
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Dict
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base 

# --- 1. تنظیمات و دیتابیس ---
if not os.path.exists("uploads"): os.makedirs("uploads")

SQLALCHEMY_DATABASE_URL = "sqlite:///./telegram_clone.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MessageModel(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String)
    content = Column(String)
    msg_type = Column(String) # text, image, audio, system
    time = Column(String)
    group_id = Column(String)
    reply_to_sender = Column(String, nullable=True)
    reply_to_content = Column(String, nullable=True)
    forward_from = Column(String, nullable=True)
    is_edited = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# --- 2. مدیریت اتصال‌ها ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[Dict] = []

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        self.active_connections.append({"ws": websocket, "username": username, "group": "general"})
        await self.broadcast_system_msg(f"{username} وارد شد", "general")
        await self.broadcast_user_list("general")

    async def disconnect(self, websocket: WebSocket):
        user = next((u for u in self.active_connections if u['ws'] == websocket), None)
        if user:
            self.active_connections.remove(user)
            await self.broadcast_system_msg(f"{user['username']} خارج شد", user['group'])
            await self.broadcast_user_list(user['group'])

    async def switch_group(self, websocket: WebSocket, new_group: str):
        user = next((u for u in self.active_connections if u['ws'] == websocket), None)
        if user:
            old_group = user['group']
            user['group'] = new_group
            await self.broadcast_user_list(old_group)
            await self.broadcast_user_list(new_group)

    async def broadcast_user_list(self, group_id: str):
        users = list(set([u['username'] for u in self.active_connections if u['group'] == group_id]))
        msg = json.dumps({"action": "user_list", "users": users, "count": len(users)})
        await self.broadcast_to_group_raw(msg, group_id)

    async def broadcast_to_group(self, message_data: dict, group_id: str):
        await self.broadcast_to_group_raw(json.dumps(message_data), group_id)

    async def broadcast_to_group_raw(self, msg_str: str, group_id: str):
        for u in self.active_connections:
            if u['group'] == group_id:
                try: await u['ws'].send_text(msg_str)
                except: pass
    
    async def broadcast_system_msg(self, text: str, group_id: str):
        await self.broadcast_to_group({"action": "new", "message": {
            "id": 0, "sender": "سیستم", "content": text, "msg_type": "system", 
            "time": datetime.now().strftime("%H:%M"), "is_pinned": False
        }}, group_id)

manager = ConnectionManager()

@app.post("/upload-file/")
async def upload_file(file: UploadFile = File(...)):
    ext = file.filename.split(".")[-1]
    name = f"{uuid.uuid4()}.{ext}"
    with open(f"uploads/{name}", "wb") as f: shutil.copyfileobj(file.file, f)
    return {"url": f"/uploads/{name}"}

# --- 3. فرانت‌اند (HTML/CSS/JS) ---
html = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Telegram Pro</title>
<style>
    :root { --bg:#fff; --sidebar:#fdfdfd; --chat:#728c9a; --mine:#effdde; --other:#fff; --text:#000; --border:#ddd; --accent:#0088cc; }
    [data-theme="dark"] { --bg:#181818; --sidebar:#212121; --chat:#0f0f0f; --mine:#2b5278; --other:#182533; --text:#fff; --border:#333; --accent:#40a7e3; }
    * { box-sizing: border-box; tap-highlight-color: transparent; }
    body { font-family: Tahoma, sans-serif; background: var(--bg); margin: 0; height: 100vh; display: flex; justify-content: center; color: var(--text); overflow: hidden; }
    .app-container { display: none; width: 100%; max-width: 1200px; height: 100%; background: var(--sidebar); box-shadow: 0 0 20px rgba(0,0,0,0.2); }
    @media(min-width: 800px){ .app-container{ height: 95vh; margin-top: 2.5vh; border-radius: 12px; overflow: hidden; display: flex;} }
    .sidebar { width: 320px; border-left: 1px solid var(--border); display: flex; flex-direction: column; background: var(--sidebar); z-index: 2; }
    .sidebar-header { padding: 15px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: var(--sidebar); }
    .group-list { flex: 1; overflow-y: auto; }
    .group-item { padding: 12px 15px; display: flex; align-items: center; cursor: pointer; transition: 0.2s; border-bottom: 1px solid var(--border); }
    .group-item:hover, .group-item.active { background: rgba(128,128,128,0.1); }
    .group-icon { width: 45px; height: 45px; border-radius: 50%; background: var(--accent); color: white; display: flex; justify-content: center; align-items: center; font-size: 20px; margin-left: 10px; }
    .saved-msgs .group-icon { background: #50bfe6; }
    .chat-area { flex: 1; display: flex; flex-direction: column; position: relative; background: var(--chat); background-image: url('https://web.telegram.org/img/bg_0.png'); background-size: cover; }
    .chat-header { padding: 10px; background: var(--sidebar); border-bottom: 1px solid var(--border); display: flex; align-items: center; z-index: 5; }
    .header-info { flex: 1; margin-right: 10px; }
    .member-count { font-size: 11px; color: #888; }
    #messages { flex: 1; overflow-y: scroll; padding: 10px; display: flex; flex-direction: column; gap: 5px; scroll-behavior: smooth; }
    .msg-row { display: flex; max-width: 85%; }
    .msg-row.mine { align-self: flex-end; flex-direction: row-reverse; }
    .msg-row.other { align-self: flex-start; }
    .bubble { background: var(--other); padding: 6px 10px; border-radius: 10px; position: relative; box-shadow: 0 1px 2px rgba(0,0,0,0.15); font-size: 14px; min-width: 120px; display: flex; flex-direction: column;}
    .mine .bubble { background: var(--mine); border-bottom-right-radius: 0; }
    .other .bubble { border-bottom-left-radius: 0; }
    .sender { font-size: 12px; color: var(--accent); font-weight: bold; margin-bottom: 3px; cursor: pointer; }
    .meta { font-size: 10px; color: #888; display: flex; justify-content: flex-end; align-items: center; margin-top: 3px; }
    .ticks { font-size: 14px; color: #4db358; margin-right: 3px; }
    .reply-preview { border-right: 3px solid var(--accent); background: rgba(0,0,0,0.05); padding: 4px; border-radius: 4px; font-size: 11px; margin-bottom: 4px; cursor: pointer;}
    .forward-tag { font-size: 11px; color: var(--accent); font-style: italic; margin-bottom: 3px; }
    .system-msg { align-self: center; background: rgba(0,0,0,0.3); color: white; padding: 3px 10px; border-radius: 10px; font-size: 11px; margin: 5px 0; }
    .chat-img { max-width: 100%; border-radius: 8px; cursor: pointer; }
    audio { width: 100%; height: 30px; margin-top: 5px; }
    .pin-bar { background: var(--sidebar); padding: 8px; border-bottom: 1px solid var(--border); display: none; align-items: center; cursor: pointer; font-size: 13px; }
    .input-wrapper { background: var(--sidebar); padding: 5px; }
    .input-box { display: flex; background: var(--bg); border: 1px solid var(--border); border-radius: 20px; align-items: center; padding: 2px 10px; }
    input { flex: 1; border: none; background: transparent; padding: 10px; outline: none; color: var(--text); }
    .btn-icon { font-size: 22px; color: #888; cursor: pointer; padding: 0 8px; background: none; border: none; }
    .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; justify-content: center; align-items: flex-end; }
    .modal-sheet { background: var(--sidebar); width: 100%; max-width: 500px; border-radius: 15px 15px 0 0; overflow: hidden; animation: slideUp 0.2s; }
    .modal-item { padding: 15px; border-bottom: 1px solid var(--border); cursor: pointer; display: flex; align-items: center; gap: 10px; font-size: 15px; }
    @keyframes slideUp { from { transform: translateY(100%); } to { transform: translateY(0); } }
    .lightbox { display: none; position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.9); z-index:2000; justify-content:center; align-items:center; }
    .lightbox img { max-width:95%; max-height:95%; border-radius:5px; }
    .login-box { width: 300px; background: var(--sidebar); padding: 30px; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.2); text-align: center; margin: auto; display: flex; flex-direction: column; gap: 10px;}
    .back-btn { display: none; font-size: 24px; cursor: pointer; margin-left: 10px; }
    .scroll-btn { position: absolute; bottom: 80px; right: 20px; background: rgba(0,0,0,0.4); color: white; width: 40px; height: 40px; border-radius: 50%; display: none; justify-content: center; align-items: center; cursor: pointer; z-index: 10; }
    @media(max-width: 800px) {
        .app-container { display: none; position: fixed; top:0; left:0; }
        .sidebar, .chat-area { width: 100%; height: 100%; }
        .show-chat .sidebar { display: none; } .show-chat .chat-area { display: flex; }
        .back-btn { display: block; }
    }
</style>
</head>
<body>
<div class="login-box" id="loginScreen">
    <h2 style="color:var(--accent)">Telegram Pro</h2>
    <input type="text" id="username" placeholder="نام کاربری...">
    <button onclick="login()" style="padding:12px; background:var(--accent); color:white; border:none; border-radius:8px; cursor:pointer;">شروع چت</button>
</div>
<div class="app-container" id="app">
    <div class="sidebar">
        <div class="sidebar-header">
            <b>پیام‌رسان</b>
            <div><button class="btn-icon" onclick="changeWallpaper()">🖼️</button><button class="btn-icon" onclick="toggleTheme()">🌙</button></div>
        </div>
        <div class="group-list">
            <div class="group-item saved-msgs" onclick="joinGroup('saved')" id="grp-saved"><div class="group-icon">🔖</div><div><b>پیام‌های ذخیره شده</b><br><small>شخصی</small></div></div>
            <div class="group-item active" onclick="joinGroup('general')" id="grp-general"><div class="group-icon">📢</div><div><b>گروه عمومی</b><br><small id="cnt-general">...</small></div></div>
            <div class="group-item" onclick="joinGroup('tech')" id="grp-tech"><div class="group-icon">💻</div><div><b>تکنولوژی</b><br><small id="cnt-tech">...</small></div></div>
        </div>
    </div>
    <div class="chat-area">
        <div class="chat-header">
            <div class="back-btn" onclick="goBack()">➔</div>
            <div class="header-info"><b id="chatTitle">گروه عمومی</b><br><span class="member-count" id="onlineCount">در حال اتصال...</span></div>
            <button class="btn-icon" onclick="toggleSearch()">🔍</button>
        </div>
        <div class="pin-bar" id="pinBanner" onclick="scrollToPin()">
            <div style="border-right: 3px solid var(--accent); height: 25px; margin-left: 10px;"></div>
            <div style="flex:1"><b style="color:var(--accent)">پین شده</b><br><span id="pinText" style="font-size:11px;">...</span></div><span onclick="unpin(event)" style="padding:5px;">✕</span>
        </div>
        <div id="searchBar" style="display:none; padding:10px; background:var(--sidebar);"><input type="text" id="searchInp" placeholder="جستجو..." onkeyup="doSearch()" style="width:100%; border:1px solid #ccc;"></div>
        <div id="messages" onscroll="checkScroll()"></div>
        <div class="scroll-btn" id="scrollBtn" onclick="scrollToBottom()">⬇</div>
        <div class="input-wrapper">
            <div id="actionInfo" style="display:none; background:rgba(0,0,0,0.05); padding:5px; border-radius:5px; margin-bottom:5px; font-size:12px; justify-content:space-between;"><span id="actionText"></span> <span onclick="cancelAction()" style="color:red; cursor:pointer;">✕</span></div>
            <div class="input-box">
                <input type="file" id="fileInp" hidden onchange="uploadFile('image')"><input type="file" id="wallInp" hidden onchange="uploadWall()">
                <button class="btn-icon" onclick="document.getElementById('fileInp').click()">📎</button>
                <input type="text" id="msgInp" placeholder="پیام..." autocomplete="off">
                <button class="btn-icon" id="micBtn" onclick="recordVoice()">🎤</button>
                <button class="btn-icon btn-send" onclick="sendMsg()">➤</button>
            </div>
        </div>
    </div>
</div>
<div class="modal-overlay" id="ctxMenu" onclick="closeMenu(event)"><div class="modal-sheet">
    <div class="modal-item" onclick="actReply()">↩️ پاسخ</div><div class="modal-item" onclick="actForward()">↪️ فوروارد</div><div class="modal-item" onclick="actCopy()">📋 کپی</div>
    <div class="modal-item" id="optPin" onclick="actPin()">📌 پین</div><div class="modal-item" id="optEdit" onclick="actEdit()">✏️ ویرایش</div><div class="modal-item" id="optDel" onclick="actDel()" style="color:red">🗑 حذف</div>
</div></div>
<div class="modal-overlay" id="fwdMenu" onclick="closeFwd(event)"><div class="modal-sheet">
    <div style="padding:15px; text-align:center; color:#888;">ارسال به...</div>
    <div class="modal-item" onclick="doForward('saved')">🔖 پیام‌های ذخیره شده</div><div class="modal-item" onclick="doForward('general')">📢 عمومی</div><div class="modal-item" onclick="doForward('tech')">💻 تکنولوژی</div>
</div></div>
<div class="lightbox" id="lightbox" onclick="this.style.display='none'"><img id="lbImg" src=""></div>
<script>
    var ws, user, curGroup="general", selMsg, actionData=null, editId=null;
    if(localStorage.getItem("user")) document.getElementById("username").value = localStorage.getItem("user");
    if(localStorage.getItem("theme")==="dark") document.body.setAttribute("data-theme", "dark");
    if(localStorage.getItem("wall")) document.querySelector('.chat-area').style.backgroundImage = `url(${localStorage.getItem("wall")})`;
    function login(){
        user = document.getElementById("username").value.trim();
        if(!user) return;
        localStorage.setItem("user", user);
        document.getElementById("loginScreen").style.display="none";
        document.getElementById("app").style.display= window.innerWidth<800 ? "block" : "flex";
        connect();
    }
    function connect(){
        // Dynamic IP detection
        var protocol = window.location.protocol==="https:"?"wss":"ws";
        ws = new WebSocket(`${protocol}://${window.location.host}/ws/${user}`);
        ws.onmessage = (e) => processData(JSON.parse(e.data));
        ws.onclose = () => setTimeout(connect, 3000);
    }
    function processData(d){
        if(d.action === "history") {
            document.getElementById("messages").innerHTML = "";
            document.getElementById("pinBanner").style.display="none";
            d.messages.forEach(m => addMsg(m));
        }
        else if(d.action === "new") addMsg(d.message);
        else if(d.action === "user_list") document.getElementById("onlineCount").innerText = d.count + " نفر آنلاین";
        else if(d.action === "delete") { var el=document.getElementById("row-"+d.id); if(el) el.remove(); }
        else if(d.action === "edit") { 
            var el=document.getElementById("txt-"+d.id); if(el) el.innerHTML=linkify(d.content); 
            document.getElementById("meta-"+d.id).innerHTML += " (Edited)";
        }
        else if(d.action === "pin") showPin(d.content, d.id);
        else if(d.action === "unpin") document.getElementById("pinBanner").style.display="none";
    }
    function addMsg(m){
        var box = document.getElementById("messages");
        if(m.msg_type === "system") { box.innerHTML += `<div class="system-msg">${m.content}</div>`; return; }
        if(m.is_pinned) showPin(m.content, m.id);
        var isMine = m.sender === user;
        var row = document.createElement("div"); row.className = `msg-row ${isMine?'mine':'other'}`; row.id = `row-${m.id}`;
        var content = "";
        if(m.msg_type==="image") content = `<img src="${m.content}" class="chat-img" onclick="viewImg('${m.content}')">`;
        else if(m.msg_type==="audio") content = `<audio controls src="${m.content}"></audio>`;
        else content = `<span id="txt-${m.id}">${linkify(m.content)}</span>`;
        var replyHtml = "";
        if(m.reply_to_sender) replyHtml = `<div class="reply-preview"><b>${m.reply_to_sender}</b><br>${short(m.reply_to_content)}</div>`;
        if(m.forward_from) replyHtml = `<div class="forward-tag">فوروارد از ${m.forward_from}</div>` + replyHtml;
        row.innerHTML = `<div class="bubble" onclick="openCtx(this, ${m.id}, '${m.sender}', '${m.msg_type}')" data-content="${m.content}">
            ${!isMine ? `<div class="sender">${m.sender}</div>` : ''} ${replyHtml} ${content}
            <div class="meta" id="meta-${m.id}">${isMine ? '<span class="ticks">✓✓</span>' : ''} ${m.time} ${m.is_edited ? '(Edited)' : ''}</div></div>`;
        box.appendChild(row); scrollToBottom();
    }
    function joinGroup(gid){
        curGroup = gid;
        document.querySelectorAll(".group-item").forEach(e=>e.classList.remove("active"));
        document.getElementById("grp-"+gid).classList.add("active");
        var titles = {'saved':'پیام‌های ذخیره شده', 'general':'گروه عمومی', 'tech':'تکنولوژی'};
        document.getElementById("chatTitle").innerText = titles[gid];
        ws.send(JSON.stringify({action:"join_group", group:gid}));
        if(window.innerWidth<800) document.getElementById("app").classList.add("show-chat");
    }
    function sendMsg(){
        var txt = document.getElementById("msgInp").value.trim();
        if(!txt) return;
        if(editId) { ws.send(JSON.stringify({action:"edit", id:editId, content:txt})); } 
        else {
            var pl = {action:"send", content:txt, msg_type:"text"};
            if(actionData && actionData.type==="reply") { pl.reply_to_sender = actionData.sender; pl.reply_to_content = actionData.content; }
            if(actionData && actionData.type==="forward") { pl.forward_from = actionData.from; pl.content = actionData.content; pl.msg_type = actionData.msg_type; }
            ws.send(JSON.stringify(pl));
        }
        resetInput();
    }
    async function uploadFile(type){
        var f = document.getElementById("fileInp").files[0]; if(!f) return;
        var fd = new FormData(); fd.append("file", f);
        var res = await fetch("/upload-file/", {method:"POST", body:fd});
        var j = await res.json();
        ws.send(JSON.stringify({action:"send", content:j.url, msg_type:type}));
    }
    function linkify(txt){ return txt.replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" style="color:var(--accent)">$1</a>'); }
    function short(t){ return t.length>30 ? t.substring(0,30)+"..." : t; }
    function scrollToBottom(){ var b=document.getElementById("messages"); b.scrollTop=b.scrollHeight; }
    function checkScroll(){ var b=document.getElementById("messages"); document.getElementById("scrollBtn").style.display = (b.scrollHeight - b.scrollTop > 500) ? "flex" : "none"; }
    function openCtx(el, id, sender, type){
        selMsg = {id:id, sender:sender, type:type, content:el.getAttribute("data-content")};
        var isMine = sender===user;
        document.getElementById("optDel").style.display = isMine ? "flex" : "none";
        document.getElementById("optEdit").style.display = (isMine && type==="text") ? "flex" : "none";
        document.getElementById("ctxMenu").style.display = "flex";
    }
    function closeMenu(e){ if(e.target.id==="ctxMenu") document.getElementById("ctxMenu").style.display="none"; }
    function actReply(){ setAction("پاسخ به: "+selMsg.sender, "reply"); document.getElementById("ctxMenu").style.display="none"; document.getElementById("msgInp").focus(); }
    function actCopy(){ navigator.clipboard.writeText(selMsg.content); document.getElementById("ctxMenu").style.display="none"; }
    function actDel(){ if(confirm("حذف؟")) ws.send(JSON.stringify({action:"delete", id:selMsg.id})); document.getElementById("ctxMenu").style.display="none"; }
    function actEdit(){ editId = selMsg.id; document.getElementById("msgInp").value = selMsg.content; setAction("ویرایش...", "edit"); document.getElementById("ctxMenu").style.display="none"; }
    function actPin(){ ws.send(JSON.stringify({action:"pin", id:selMsg.id, content:selMsg.content})); document.getElementById("ctxMenu").style.display="none"; }
    function unpin(e){ e.stopPropagation(); ws.send(JSON.stringify({action:"unpin"})); }
    function showPin(txt, id){ document.getElementById("pinBanner").style.display="flex"; document.getElementById("pinText").innerText = short(txt.startsWith("/uploads")?"[فایل]":txt); document.getElementById("pinBanner").onclick = () => document.getElementById("row-"+id).scrollIntoView({behavior:"smooth", block:"center"}); }
    function actForward(){ document.getElementById("ctxMenu").style.display="none"; document.getElementById("fwdMenu").style.display="flex"; }
    function closeFwd(e){ if(e.target.id==="fwdMenu") document.getElementById("fwdMenu").style.display="none"; }
    function doForward(grp){ joinGroup(grp); actionData = {type:"forward", from:selMsg.sender, content:selMsg.content, msg_type:selMsg.type}; sendMsg(); document.getElementById("fwdMenu").style.display="none"; }
    function setAction(txt, type){ document.getElementById("actionInfo").style.display="flex"; document.getElementById("actionText").innerText = txt; actionData = selMsg; actionData.type = type; }
    function resetInput() { actionData=null; editId=null; document.getElementById("actionInfo").style.display="none"; document.getElementById("msgInp").value=""; }
    function cancelAction(){ resetInput(); }
    function toggleTheme(){ var b=document.body; b.setAttribute("data-theme", b.getAttribute("data-theme")==="dark"?"light":"dark"); localStorage.setItem("theme", b.getAttribute("data-theme")); }
    function changeWallpaper(){ document.getElementById("wallInp").click(); }
    function uploadWall(){ var f = document.getElementById("wallInp").files[0]; var r = new FileReader(); r.onload=function(e){ document.querySelector('.chat-area').style.backgroundImage=`url(${e.target.result})`; localStorage.setItem("wall", e.target.result); }; r.readAsDataURL(f); }
    function toggleSearch(){ var b=document.getElementById("searchBar"); b.style.display = b.style.display==="none"?"block":"none"; if(b.style.display==="block") document.getElementById("searchInp").focus(); }
    function doSearch(){ var v = document.getElementById("searchInp").value.toLowerCase(); document.querySelectorAll(".bubble").forEach(e=>{ e.parentElement.style.display = e.innerText.toLowerCase().includes(v) ? "flex" : "none"; }); }
    function viewImg(src){ document.getElementById("lightbox").style.display="flex"; document.getElementById("lbImg").src = src; }
    function goBack(){ document.getElementById("app").classList.remove("show-chat"); }
    var mediaRec;
    async function recordVoice(){ var btn = document.getElementById("micBtn"); if(btn.style.color === "red") { mediaRec.stop(); btn.style.color = "#888"; } else { try { var s = await navigator.mediaDevices.getUserMedia({audio:true}); mediaRec = new MediaRecorder(s); var ch=[]; mediaRec.ondataavailable=e=>ch.push(e.data); mediaRec.onstop=async()=>{ var b=new Blob(ch,{type:'audio/webm'}); var fd=new FormData(); fd.append("file",b,"v.webm"); var r=await fetch("/upload-file/",{method:"POST",body:fd}); var j=await r.json(); ws.send(JSON.stringify({action:"send",content:j.url,msg_type:"audio"})); }; mediaRec.start(); btn.style.color="red"; } catch(e){ alert("نیاز به HTTPS دارد"); } } }
    document.getElementById("msgInp").onkeyup = (e) => { if(e.key==="Enter") sendMsg(); }
</script>
</body>
</html>
"""

@app.get("/")
async def get(): return HTMLResponse(html)

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await manager.connect(websocket, username)
    
    # Load history of general group
    db = SessionLocal()
    msgs = db.query(MessageModel).filter(MessageModel.group_id == "general").all()
    hist = []
    for m in msgs: hist.append(row_to_dict(m))
    await websocket.send_text(json.dumps({"action": "history", "messages": hist}))
    db.close()
    
    try:
        while True:
            data = json.loads(await websocket.receive_text())
            current_group = next((u['group'] for u in manager.active_connections if u['ws'] == websocket), "general")
            
            if data['action'] == 'join_group':
                await manager.switch_group(websocket, data['group'])
                db = SessionLocal()
                msgs = db.query(MessageModel).filter(MessageModel.group_id == data['group']).all()
                hist = [row_to_dict(m) for m in msgs]
                db.close()
                await websocket.send_text(json.dumps({"action": "history", "messages": hist}))

            elif data['action'] == 'send':
                curr_time = datetime.now().strftime("%H:%M")
                db = SessionLocal()
                new_msg = MessageModel(
                    sender=username, content=data['content'], msg_type=data['msg_type'], time=curr_time,
                    group_id=current_group, reply_to_sender=data.get('reply_to_sender'), 
                    reply_to_content=data.get('reply_to_content'), forward_from=data.get('forward_from')
                )
                db.add(new_msg); db.commit(); db.refresh(new_msg)
                db.close()
                await manager.broadcast_to_group({"action": "new", "message": row_to_dict(new_msg)}, current_group)
            
            elif data['action'] == 'edit':
                db = SessionLocal()
                msg = db.query(MessageModel).filter(MessageModel.id == data['id'], MessageModel.sender == username).first()
                if msg:
                    msg.content = data['content']; msg.is_edited = True; db.commit()
                    await manager.broadcast_to_group({"action": "edit", "id": data['id'], "content": data['content']}, current_group)
                db.close()

            elif data['action'] == 'delete':
                db = SessionLocal()
                msg = db.query(MessageModel).filter(MessageModel.id == data['id'], MessageModel.sender == username).first()
                if msg:
                    db.delete(msg); db.commit()
                    await manager.broadcast_to_group({"action": "delete", "id": data['id']}, current_group)
                db.close()

            elif data['action'] == 'pin':
                db = SessionLocal()
                db.query(MessageModel).filter(MessageModel.group_id == current_group).update({MessageModel.is_pinned: False})
                msg = db.query(MessageModel).filter(MessageModel.id == data['id']).first()
                if msg: msg.is_pinned = True; db.commit(); await manager.broadcast_to_group({"action": "pin", "id": msg.id, "content": msg.content}, current_group)
                db.close()

            elif data['action'] == 'unpin':
                db = SessionLocal(); db.query(MessageModel).filter(MessageModel.group_id == current_group).update({MessageModel.is_pinned: False}); db.commit(); db.close()
                await manager.broadcast_to_group({"action": "unpin"}, current_group)

    except WebSocketDisconnect:
        await manager.disconnect(websocket)

def row_to_dict(m):
    return {
        "id": m.id, "sender": m.sender, "content": m.content, "msg_type": m.msg_type,
        "time": m.time, "reply_to_sender": m.reply_to_sender, "reply_to_content": m.reply_to_content,
        "is_edited": m.is_edited, "is_pinned": m.is_pinned, "forward_from": m.forward_from
    }
