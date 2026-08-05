const G="rt-ai-video-companion-root",te={showEnglish:!0,showChinese:!0,fontSize:22,opacity:.96};let v={...te},l="idle",g="",k="",h="",w=!1,x=null,T=!0,q=!1,L=null,M=null,A=null,H=0;const R=[],f=new Map,$=new Map,a=document.createElement("div");var Y;(Y=document.getElementById(G))==null||Y.remove();a.id=G;a.style.position="fixed";a.style.zIndex="2147483647";a.style.top="68px";a.style.right="14px";a.style.width="min(400px, calc(100vw - 24px))";a.style.height="min(760px, calc(100vh - 84px))";a.style.pointerEvents="none";document.documentElement.appendChild(a);const r=a.attachShadow({mode:"open"});r.innerHTML=`
  <style>
    :host { color-scheme: dark; }
    * { box-sizing: border-box; letter-spacing: 0; }
    button, input, textarea { font: inherit; }
    button { cursor: pointer; }
    .panel {
      --content-size: 16px;
      width: 100%; height: 100%; display: none; flex-direction: column;
      overflow: hidden; color: #f7f8f8; background: rgba(17, 19, 21, .96);
      border: 1px solid rgba(255,255,255,.14); border-radius: 8px;
      box-shadow: 0 16px 42px rgba(0,0,0,.38);
      font-family: Inter, "Microsoft YaHei", system-ui, sans-serif;
      pointer-events: auto;
    }
    .panel.visible { display: flex; }
    .reopen {
      display: none; width: 44px; height: 38px; margin-left: auto; border: 1px solid rgba(255,255,255,.16);
      border-radius: 6px; color: #07140d; background: #56d294; font-size: 12px; font-weight: 800;
      box-shadow: 0 8px 24px rgba(0,0,0,.3); pointer-events: auto;
    }
    .reopen.visible { display: block; }
    .panel.collapsed { height: 52px; }
    .panel.collapsed .body { display: none; }
    .header {
      height: 52px; flex: 0 0 52px; display: flex; align-items: center;
      justify-content: space-between; padding: 0 10px 0 14px;
      border-bottom: 1px solid rgba(255,255,255,.1); background: #171a1c;
      cursor: grab; touch-action: none;
    }
    .header.dragging { cursor: grabbing; user-select: none; }
    .title-row { display: flex; align-items: center; gap: 9px; min-width: 0; }
    .status-dot { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; background: #73787c; }
    .status-dot.running { background: #36c982; box-shadow: 0 0 0 3px rgba(54,201,130,.14); }
    .status-dot.paused { background: #f1bd55; }
    .status-dot.error { background: #ef6a65; }
    .title { margin: 0; font-size: 14px; line-height: 1.2; font-weight: 700; }
    .status-text { margin: 2px 0 0; color: #9ea5a9; font-size: 11px; }
    .header-actions { display: flex; gap: 3px; }
    .icon-button {
      width: 30px; height: 30px; border: 0; border-radius: 5px;
      color: #c9cdcf; background: transparent; font-size: 18px;
    }
    .icon-button:hover { background: #292d2f; color: #fff; }
    .body { min-height: 0; flex: 1; display: grid; grid-template-rows: auto minmax(150px, 1fr) minmax(220px, .72fr); }
    .live {
      padding: 11px 14px 12px; border-bottom: 1px solid rgba(255,255,255,.1);
      background: #202426;
    }
    .section-label { margin: 0 0 5px; color: #74d9a7; font-size: 10px; font-weight: 800; text-transform: uppercase; }
    .live-text { margin: 0; min-height: 20px; color: #f3f5f4; font-size: var(--content-size); line-height: 1.45; }
    .live-text.empty { color: #7d8589; font-size: 12px; }
    .transcript-section { position: relative; min-height: 0; display: flex; flex-direction: column; border-bottom: 1px solid rgba(255,255,255,.12); }
    .section-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 9px 12px; }
    .section-head h2 { margin: 0; font-size: 12px; font-weight: 700; }
    .search {
      width: 138px; height: 28px; padding: 0 9px; border: 1px solid #373d40;
      border-radius: 5px; outline: none; color: #f4f5f5; background: #212527; font-size: 11px;
    }
    .search:focus { border-color: #43b982; }
    .transcript-list { min-height: 0; flex: 1; overflow: auto; overflow-anchor: none; scrollbar-width: thin; }
    .jump-latest {
      position: absolute; right: 13px; bottom: 11px; display: none; align-items: center;
      height: 30px; padding: 0 10px; border: 1px solid #4b725f; border-radius: 5px;
      color: #e9f6ee; background: #28543e; box-shadow: 0 5px 15px rgba(0,0,0,.32);
      font-size: 11px; font-weight: 700; z-index: 2;
    }
    .jump-latest.visible { display: inline-flex; }
    .jump-latest:hover { background: #32694d; }
    .empty-state { padding: 32px 16px; color: #777f83; text-align: center; font-size: 12px; }
    .transcript-item {
      padding: 10px 14px 11px; border-top: 1px solid rgba(255,255,255,.075);
      cursor: pointer; transition: background .12s ease;
    }
    .transcript-item:hover { background: #202527; }
    .transcript-item.selected { background: #26312b; box-shadow: inset 3px 0 #42c486; }
    .record-meta { display: flex; justify-content: space-between; margin-bottom: 4px; color: #7f878b; font-size: 10px; }
    .record-error { color: #cf928d; }
    .record-en { margin: 0; color: #f2f4f3; font-size: var(--content-size); line-height: 1.42; }
    .record-zh { margin: 5px 0 0; color: #bde8ce; font-size: calc(var(--content-size) - 1px); line-height: 1.5; }
    .hide-english .record-en, .hide-english .live { display: none; }
    .hide-chinese .record-zh { display: none; }
    .chat-section { min-height: 0; display: flex; flex-direction: column; background: #151819; }
    .chat-head { padding: 9px 12px 7px; }
    .chat-title-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .chat-title-row h2 { margin: 0; font-size: 12px; }
    .selected-quote {
      display: none; max-width: 240px; overflow: hidden; color: #d8e9df;
      font-size: 10px; text-overflow: ellipsis; white-space: nowrap;
    }
    .selected-quote.visible { display: block; }
    .quick-actions { display: flex; gap: 6px; margin-top: 7px; }
    .quick-action {
      padding: 5px 8px; border: 1px solid #343a3d; border-radius: 5px;
      color: #bcc2c4; background: #202426; font-size: 10px;
    }
    .quick-action:hover { border-color: #4e8067; color: #e8f5ed; }
    .chat-messages { min-height: 0; flex: 1; overflow: auto; padding: 2px 12px 8px; scrollbar-width: thin; }
    .message { margin: 7px 0; font-size: 12px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
    .message.user { margin-left: 34px; padding: 7px 9px; border-radius: 6px; color: #eff8f2; background: #28553e; }
    .message.assistant { color: #d7dcde; }
    .message.pending { color: #8c9497; }
    .message.error { color: #e09a94; }
    .composer { display: grid; grid-template-columns: 1fr auto; gap: 7px; padding: 8px 10px 10px; border-top: 1px solid rgba(255,255,255,.08); }
    .question {
      min-width: 0; height: 38px; max-height: 86px; resize: none; padding: 9px 10px;
      border: 1px solid #393f42; border-radius: 6px; outline: none;
      color: #f4f6f5; background: #202426; font-size: 12px; line-height: 1.45;
    }
    .question:focus { border-color: #43b982; }
    .send {
      width: 52px; height: 38px; border: 0; border-radius: 6px;
      color: #07140d; background: #56d294; font-size: 12px; font-weight: 800;
    }
    .send:hover { background: #74dda8; }
    .send:disabled, .question:disabled { cursor: not-allowed; opacity: .45; }
    .global-error { display: none; padding: 7px 12px; color: #ffd0cb; background: #642f2c; font-size: 11px; }
    .global-error.visible { display: block; }
    @media (max-width: 650px) {
      .panel { border-radius: 6px; }
      .body { grid-template-rows: auto minmax(130px, 1fr) minmax(200px, .8fr); }
    }
  </style>
  <button class="reopen" type="button" title="打开视频双语助手">AI</button>
  <aside class="panel" aria-label="视频双语助手">
    <header class="header">
      <div class="title-row">
        <span class="status-dot"></span>
        <div><h1 class="title">视频双语助手</h1><p class="status-text">等待启动</p></div>
      </div>
      <div class="header-actions">
        <button class="icon-button collapse-button" type="button" title="收起面板">−</button>
        <button class="icon-button close-button" type="button" title="关闭面板">×</button>
      </div>
    </header>
    <div class="global-error"></div>
    <div class="body">
      <section class="live"><p class="section-label">正在听</p><p class="live-text empty">等待语音…</p></section>
      <section class="transcript-section">
        <div class="section-head"><h2>双语记录</h2><input class="search" type="search" placeholder="搜索记录" /></div>
        <div class="transcript-list"><div class="empty-state">双语内容将在这里持续累积</div></div>
        <button class="jump-latest" type="button" title="继续自动跟随最新记录">↓ 回到最新</button>
      </section>
      <section class="chat-section">
        <div class="chat-head">
          <div class="chat-title-row"><h2>视频问答</h2><span class="selected-quote"></span></div>
          <div class="quick-actions">
            <button class="quick-action" data-question="请解释我选中的英文句子。">解释句子</button>
            <button class="quick-action" data-question="请分析我选中句子的语法和重点词汇。">分析语法</button>
            <button class="quick-action" data-question="请总结刚才的视频内容。">总结内容</button>
          </div>
        </div>
        <div class="chat-messages"></div>
        <div class="composer">
          <textarea class="question" placeholder="询问视频内容或英文表达"></textarea>
          <button class="send" type="button">发送</button>
        </div>
      </section>
    </div>
  </aside>
`;const u=r.querySelector(".panel"),_=r.querySelector(".reopen"),d=r.querySelector(".header"),oe=r.querySelector(".status-dot"),ne=r.querySelector(".status-text"),D=r.querySelector(".live-text"),s=r.querySelector(".transcript-list"),K=r.querySelector(".jump-latest"),S=r.querySelector(".chat-messages"),z=r.querySelector(".selected-quote"),C=r.querySelector(".question"),Q=r.querySelector(".send"),B=r.querySelector(".search"),U=r.querySelector(".global-error");function ie(e){return new Date(e*1e3).toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}function N(e,t,n=!1){const o=Math.min(400,window.innerWidth-24),i=Math.min(460,window.innerHeight-16),p=Math.max(8,Math.min(e,window.innerWidth-o-8)),c=Math.max(8,Math.min(t,window.innerHeight-i-8));x={left:p,top:c},a.style.left=`${p}px`,a.style.right="auto",a.style.top=`${c}px`,a.style.height=`min(760px, calc(100vh - ${c+8}px))`,n&&chrome.storage.local.set({assistantPanelPosition:x})}function j(){return Math.max(0,s.scrollHeight-s.scrollTop-s.clientHeight)}function I(){const e=s.scrollHeight>s.clientHeight+4,t=j()>80;K.classList.toggle("visible",!T&&e&&t)}function m(e){T=e,I()}function b(e=!1,t=100){T&&(cancelAnimationFrame(H),H=requestAnimationFrame(()=>{H=requestAnimationFrame(()=>{q=!0,e?s.scrollTo({top:s.scrollHeight,behavior:"smooth"}):s.scrollTop=s.scrollHeight,L!==null&&window.clearTimeout(L),L=window.setTimeout(()=>{q=!1,j()<=80&&(T=!0),I()},e?600:t)})}))}function V(){b(!1,1e3),M!==null&&window.clearTimeout(M),A!==null&&window.clearTimeout(A),M=window.setTimeout(()=>b(!1,750),250),A=window.setTimeout(()=>b(!1,150),1e3)}const P=new ResizeObserver(()=>{b(!1,500),I()});P.observe(s);function y(){const e=R.length>0||$.size>0;u.classList.toggle("visible",!w&&(l!=="idle"||e||!!g)),_.classList.toggle("visible",w&&(l!=="idle"||e||!!g)),a.style.pointerEvents=u.classList.contains("visible")||_.classList.contains("visible")?"auto":"none",oe.className=`status-dot ${l}`,ne.textContent=l==="running"?"实时理解中":l==="paused"?"已暂停":l==="error"?"连接异常":"本次会话已结束",U.textContent=g,U.classList.toggle("visible",!!g);const t=l==="running"||l==="paused";C.disabled=!t,Q.disabled=!t}function J(){const e=Math.max(13,Math.min(20,v.fontSize-5));u.style.setProperty("--content-size",`${e}px`),u.style.background=`rgba(17, 19, 21, ${Math.max(.55,v.opacity)})`,u.classList.toggle("hide-english",!v.showEnglish),u.classList.toggle("hide-chinese",!v.showChinese),V()}function Z(e){k=e,D.textContent=k||"等待下一段语音…",D.classList.toggle("empty",!k)}function se(e){h=h===e?"":e,h&&m(!1),s.querySelectorAll(".transcript-item").forEach(n=>{n.classList.toggle("selected",n.dataset.id===h)});const t=f.get(h);z.textContent=t?`已选择：${t.source_text}`:"",z.classList.toggle("visible",!!t)}function ee(){const e=B.value.trim().toLowerCase();e&&m(!1),s.querySelectorAll(".transcript-item").forEach(t=>{const n=f.get(t.dataset.id||""),o=`${(n==null?void 0:n.source_text)||""} ${(n==null?void 0:n.target_text)||""}`.toLowerCase();t.style.display=!e||o.includes(e)?"":"none"}),I()}function re(e,t=""){var O;const n=f.get(e.id);f.set(e.id,{...n,...e});let o=s.querySelector(`[data-id="${CSS.escape(e.id)}"]`);o||((O=s.querySelector(".empty-state"))==null||O.remove(),R.push(e.id),o=document.createElement("article"),o.className="transcript-item",o.dataset.id=e.id,o.innerHTML='<div class="record-meta"><span class="record-time"></span><span class="record-state"></span></div><p class="record-en"></p><p class="record-zh"></p>',o.addEventListener("click",()=>se(e.id)),s.appendChild(o),P.observe(o));const i=f.get(e.id);o.querySelector(".record-time").textContent=ie(i.timestamp);const p=o.querySelector(".record-state");p.textContent=i.status==="error"?t||"中文暂未生成":"",p.classList.toggle("record-error",i.status==="error"),o.querySelector(".record-en").textContent=i.source_text;const c=o.querySelector(".record-zh");c.textContent=i.target_text,c.style.display=i.target_text?"":"none",o.classList.toggle("selected",e.id===h),ee(),V()}function E(e){$.set(e.id,e);let t=S.querySelector(`[data-chat-id="${CSS.escape(e.id)}"]`);t||(t=document.createElement("div"),t.dataset.chatId=e.id,S.appendChild(t)),t.className=`message ${e.role}${e.pending?" pending":""}${e.error?" error":""}`,t.textContent=e.text,S.scrollTop=S.scrollHeight}async function F(e){const t=(e||C.value).trim();if(!t)return;const n=crypto.randomUUID(),o=f.get(h);E({id:`${n}-user`,role:"user",text:t}),E({id:n,role:"assistant",text:"正在回答…",pending:!0}),C.value="";const i=await chrome.runtime.sendMessage({type:"CHAT_ASK",requestId:n,question:t,selectedSegmentId:h,selectedText:(o==null?void 0:o.source_text)||""});i.ok||E({id:n,role:"assistant",text:i.error||"发送失败",error:!0})}function ae(){k="",h="",g="",R.length=0,f.clear(),$.clear(),m(!0),P.disconnect(),P.observe(s),s.innerHTML='<div class="empty-state">双语内容将在这里持续累积</div>',S.innerHTML="",z.textContent="",z.classList.remove("visible"),B.value="",Z("")}var W;(W=r.querySelector(".collapse-button"))==null||W.addEventListener("click",()=>{u.classList.toggle("collapsed");const e=r.querySelector(".collapse-button");e.textContent=u.classList.contains("collapsed")?"+":"−",e.title=u.classList.contains("collapsed")?"展开面板":"收起面板",u.classList.contains("collapsed")||b()});d.addEventListener("pointerdown",e=>{if(e.target.closest("button"))return;const t=a.getBoundingClientRect(),n=e.clientX-t.left,o=e.clientY-t.top;d.classList.add("dragging"),d.setPointerCapture(e.pointerId);const i=c=>{N(c.clientX-n,c.clientY-o)},p=c=>{d.classList.remove("dragging"),d.releasePointerCapture(c.pointerId),d.removeEventListener("pointermove",i),d.removeEventListener("pointerup",p),d.removeEventListener("pointercancel",p),x&&chrome.storage.local.set({assistantPanelPosition:x})};d.addEventListener("pointermove",i),d.addEventListener("pointerup",p),d.addEventListener("pointercancel",p)});var X;(X=r.querySelector(".close-button"))==null||X.addEventListener("click",()=>{w=!0,y()});_.addEventListener("click",()=>{w=!1,y(),b()});s.addEventListener("scroll",()=>{q||m(j()<=80)});s.addEventListener("pointerdown",()=>{q=!1,L!==null&&window.clearTimeout(L),m(!1)});s.addEventListener("wheel",e=>{e.deltaY<0&&(q=!1,m(!1))},{passive:!0});K.addEventListener("click",()=>{m(!0),b()});B.addEventListener("input",ee);Q.addEventListener("click",()=>void F());C.addEventListener("keydown",e=>{e.key==="Enter"&&!e.shiftKey&&(e.preventDefault(),F())});r.querySelectorAll(".quick-action").forEach(e=>{e.addEventListener("click",()=>void F(e.dataset.question))});chrome.runtime.onMessage.addListener((e,t,n)=>{var o;if(e.type==="CONTENT_PING")return n({ok:!0}),!1;if(e.type==="TRANSCRIPT_LIVE"&&Z(((o=e.payload)==null?void 0:o.source_text)||""),e.type==="TRANSCRIPT_UPDATE"&&(re(e.payload,String(e.message||"")),g="",y()),e.type==="CHAT_RESPONSE"){const i=String(e.requestId||"");i&&E({id:i,role:"assistant",text:String(e.answer||e.error||"没有收到回答。"),error:!!e.error})}if(e.type==="SUBTITLE_SETTINGS"&&(v={...v,...e.settings},J()),e.type==="CAPTURE_STATE"){const i=e.status;i==="running"&&(l==="idle"||l==="error")&&ae(),l=i,w=!1,y()}e.type==="CAPTURE_ERROR"&&(l="error",g=String(e.error??"未知错误"),w=!1,console.error("[Real-time AI Video Companion]",g),y())});J();y();chrome.storage.local.get(["assistantPanelPosition"]).then(e=>{const t=e.assistantPanelPosition;typeof(t==null?void 0:t.left)=="number"&&typeof t.top=="number"&&N(t.left,t.top)});window.addEventListener("resize",()=>{x&&N(x.left,x.top)});
