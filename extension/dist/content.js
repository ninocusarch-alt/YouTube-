const yt="rt-ai-video-companion-root",X="videoCompanionPanelLayouts";const Ct={showEnglish:!0,showChinese:!0,fontSize:22,opacity:.96};let L={...Ct},p="idle",y="",N="",f="",K="",Y=null,O=!0,C=!1,G=null,F=null,U=null,V=0;const Z=[],m=new Map,tt=new Map;function et(){const t=Math.max(480,Math.min(940,window.innerWidth-32)),e=Math.max(170,Math.min(290,window.innerHeight*.34)),i=Math.max(300,Math.min(380,window.innerWidth-32)),o=Math.max(360,Math.min(620,window.innerHeight-96));return{subtitle:{left:Math.max(12,(window.innerWidth-t)/2),top:Math.max(12,window.innerHeight-e-18),width:t,height:e,hidden:!1,collapsed:!1},chat:{left:Math.max(12,window.innerWidth-i-18),top:Math.min(72,Math.max(12,window.innerHeight-o-12)),width:i,height:o,hidden:!0}}}let n=et();const q=document.createElement("div");var ft;(ft=document.getElementById(yt))==null||ft.remove();q.id=yt;Object.assign(q.style,{position:"fixed",inset:"0",width:"100vw",height:"100vh",zIndex:"2147483647",pointerEvents:"none"});document.documentElement.appendChild(q);function pt(){return["n","e","s","w","ne","nw","se","sw"].map(t=>`<span class="resize-handle ${t}" data-direction="${t}"></span>`).join("")}const r=q.attachShadow({mode:"open"});r.innerHTML=`
  <style>
    :host { color-scheme: light; }
    * { box-sizing: border-box; letter-spacing: 0; }
    button, input, textarea { font: inherit; }
    button { cursor: pointer; }
    .floating-panel {
      --content-size: 17px; --surface-alpha: .96;
      position: absolute; display: none; flex-direction: column; min-width: 0; min-height: 0;
      overflow: hidden; color: #151716; background: rgba(255,255,255,var(--surface-alpha));
      border: 1px solid rgba(20,27,23,.12); border-radius: 14px;
      box-shadow: 0 18px 48px rgba(17,24,20,.18), 0 2px 8px rgba(17,24,20,.08);
      backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
      font-family: Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      pointer-events: auto; animation: panel-in .16s ease-out both;
    }
    .floating-panel.visible { display: flex; }
    .floating-panel.interacting { border-color: rgba(25,166,106,.48); box-shadow: 0 24px 58px rgba(17,24,20,.24), 0 3px 10px rgba(17,24,20,.1); user-select: none; }
    .panel-header {
      height: 48px; flex: 0 0 48px; display: flex; align-items: center; justify-content: space-between;
      gap: 12px; padding: 0 10px 0 16px; border-bottom: 1px solid #e7eae8;
      background: rgba(255,255,255,.72); cursor: grab; touch-action: none;
    }
    .panel-header.dragging { cursor: grabbing; }
    .title-row { display: flex; align-items: center; gap: 9px; min-width: 0; }
    .title-copy { min-width: 0; }
    .title { margin: 0; font-size: 14px; line-height: 1.15; font-weight: 680; }
    .status-text { margin: 2px 0 0; overflow: hidden; color: #8b918e; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
    .status-dot { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; background: #a4aaa7; }
    .status-dot.running { background: #19a66a; box-shadow: 0 0 0 4px rgba(25,166,106,.11); }
    .status-dot.paused { background: #d89b31; box-shadow: 0 0 0 4px rgba(216,155,49,.1); }
    .status-dot.error { background: #d94a4a; box-shadow: 0 0 0 4px rgba(217,74,74,.09); }
    .header-actions { display: flex; align-items: center; gap: 3px; }
    .text-button, .icon-button { border: 0; border-radius: 7px; color: #5e6561; background: transparent; transition: color .14s ease, background .14s ease, transform .12s ease; }
    .text-button { height: 30px; padding: 0 9px; font-size: 11px; font-weight: 650; }
    .icon-button { width: 30px; height: 30px; font-size: 17px; line-height: 1; }
    .text-button:hover, .icon-button:hover { color: #151716; background: #f0f3f1; }
    .text-button:active, .icon-button:active, .quick-action:active, .send:active { transform: scale(.97); }
    .chat-toggle.active { color: #087b4c; background: #eaf7f1; }
    .panel-body { min-height: 0; flex: 1; display: flex; flex-direction: column; }
    .global-error { display: none; margin: 9px 12px 0; padding: 8px 10px; border: 1px solid #f3cece; border-radius: 8px; color: #a93434; background: #fff4f4; font-size: 11px; }
    .global-error.visible { display: block; }
    .live { display: grid; grid-template-columns: auto minmax(0,1fr); align-items: start; gap: 10px; padding: 9px 15px; border-bottom: 1px solid #eef0ef; background: rgba(247,248,247,.86); }
    .section-label { margin: 2px 0 0; color: #16875a; font-size: 9px; font-weight: 750; text-transform: uppercase; }
    .live-text { margin: 0; min-height: 18px; overflow: hidden; color: #252a27; font-size: calc(var(--content-size) - 1px); line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
    .live-text.empty { color: #9ca19e; font-size: 11px; }
    .transcript-section { position: relative; min-height: 0; flex: 1; display: flex; flex-direction: column; }
    .section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 14px; }
    .section-head h2 { margin: 0; font-size: 12px; font-weight: 680; }
    .search { width: min(210px,30vw); height: 29px; padding: 0 10px; border: 1px solid #e0e4e1; border-radius: 8px; outline: none; color: #202522; background: #fafbfa; font-size: 11px; transition: border-color .14s ease, box-shadow .14s ease, background .14s ease; }
    .search:focus { border-color: #62bd94; background: #fff; box-shadow: 0 0 0 3px rgba(25,166,106,.09); }
    .transcript-list { min-height: 0; flex: 1; overflow: auto; overflow-anchor: none; padding: 0 8px 8px; scrollbar-width: thin; scrollbar-color: #cbd0cd transparent; }
    .jump-latest { position: absolute; right: 15px; bottom: 13px; display: none; align-items: center; height: 31px; padding: 0 11px; border: 1px solid #d3e8dd; border-radius: 9px; color: #087b4c; background: rgba(245,252,248,.96); box-shadow: 0 7px 22px rgba(18,85,55,.14); font-size: 11px; font-weight: 680; z-index: 2; transition: transform .14s ease, background .14s ease; }
    .jump-latest.visible { display: inline-flex; }
    .jump-latest:hover { background: #eaf7f1; transform: translateY(-1px); }
    .empty-state { padding: 26px 16px; color: #a0a5a2; text-align: center; font-size: 11px; }
    .transcript-item { position: relative; padding: 10px 12px 11px 14px; border: 1px solid transparent; border-radius: 10px; cursor: pointer; transition: background .14s ease, border-color .14s ease, transform .14s ease, box-shadow .14s ease; }
    .transcript-item + .transcript-item { margin-top: 2px; }
    .transcript-item:hover { border-color: #e7ebe8; background: rgba(248,250,249,.94); transform: translateY(-1px); }
    .transcript-item:hover::after { content: '点击提问'; position: absolute; right: 12px; top: 9px; color: #16875a; font-size: 9px; }
    .transcript-item.selected { border-color: #cbe9da; background: #f0f9f5; box-shadow: inset 3px 0 #19a66a; }
    .transcript-item.new-item { animation: item-in .2s ease-out both; }
    .record-meta { display: flex; justify-content: space-between; min-height: 14px; margin-bottom: 3px; color: #a1a6a3; font-size: 9px; }
    .record-time { margin: -3px 0 -2px -4px; padding: 3px 4px 2px; border: 0; border-radius: 5px; color: #8c938f; background: transparent; font-size: 9px; transition: color .14s ease, background .14s ease; }
    .record-time:hover { color: #087b4c; background: #e8f6ef; }
    .record-error { color: #b94545; }
    .record-en { margin: 0; padding-right: 58px; color: #191d1a; font-size: var(--content-size); line-height: 1.42; }
    .record-zh { margin: 4px 0 0; color: #68706b; font-size: calc(var(--content-size) - 1px); line-height: 1.48; animation: translation-in .3s ease-out both; }
    .hide-english .record-en, .hide-english .live { display: none; }
    .hide-chinese .record-zh { display: none; }
    .subtitle-panel.collapsed .panel-body, .subtitle-panel.collapsed .global-error { display: none; }
    .subtitle-panel.collapsed .panel-header { border-bottom: 0; }
    .chat-panel .panel-header { padding-left: 15px; }
    .chat-context { padding: 11px 13px 10px; border-bottom: 1px solid #ecefec; }
    .context-label { margin: 0 0 6px; color: #929894; font-size: 9px; font-weight: 700; text-transform: uppercase; }
    .selected-quote { display: none; margin: 0; padding: 9px 10px; border-radius: 9px; color: #39413c; background: #f4f7f5; font-size: 11px; line-height: 1.45; white-space: pre-wrap; }
    .selected-quote.visible { display: block; }
    .no-selection { margin: 0; color: #969c98; font-size: 11px; line-height: 1.5; }
    .quick-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
    .quick-action { min-height: 28px; padding: 5px 9px; border: 1px solid #e0e6e2; border-radius: 999px; color: #5c645f; background: #fff; font-size: 10px; transition: color .14s ease, border-color .14s ease, background .14s ease, transform .12s ease; }
    .quick-action:hover { border-color: #a8d6bf; color: #087b4c; background: #f4fbf7; }
    .chat-messages { min-height: 0; flex: 1; overflow: auto; padding: 8px 14px 12px; scrollbar-width: thin; scrollbar-color: #cbd0cd transparent; }
    .chat-empty { padding: 30px 12px; color: #a0a5a2; text-align: center; font-size: 11px; line-height: 1.6; }
    .message { margin: 10px 0; color: #333936; font-size: 12px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; animation: item-in .18s ease-out both; }
    .message.user { margin-left: 34px; padding: 8px 10px; border-radius: 10px 10px 3px 10px; color: #25513d; background: #edf8f2; }
    .message.assistant { padding-left: 11px; border-left: 2px solid #d8e9e0; }
    .message.pending { color: #959b97; }
    .message.error { padding: 8px 10px; border: 1px solid #f1d2d2; border-radius: 8px; color: #aa3b3b; background: #fff6f6; }
    .time-citation { margin: 0 2px; padding: 1px 5px; border: 0; border-radius: 5px; color: #087b4c; background: #eaf7f1; font-size: 10px; font-weight: 680; vertical-align: baseline; }
    .time-citation:hover { background: #d8f0e4; }
    .thinking-dots { display: inline-flex; gap: 3px; margin-left: 4px; vertical-align: middle; }
    .thinking-dots i { width: 4px; height: 4px; border-radius: 50%; background: #9ca29e; animation: dot-pulse 1.1s ease-in-out infinite; }
    .thinking-dots i:nth-child(2) { animation-delay: .14s; } .thinking-dots i:nth-child(3) { animation-delay: .28s; }
    .composer { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 8px; padding: 10px 12px 12px; border-top: 1px solid #e9ecea; background: rgba(255,255,255,.7); }
    .question { min-width: 0; height: 42px; max-height: 104px; resize: none; padding: 10px 11px; border: 1px solid #dde2df; border-radius: 10px; outline: none; color: #1f2421; background: #fafbfa; font-size: 11px; line-height: 1.45; transition: border-color .14s ease, box-shadow .14s ease, background .14s ease; }
    .question:focus { border-color: #62bd94; background: #fff; box-shadow: 0 0 0 3px rgba(25,166,106,.09); }
    .send { min-width: 56px; height: 42px; border: 0; border-radius: 10px; color: #fff; background: #171b18; font-size: 11px; font-weight: 680; transition: background .14s ease, transform .12s ease; }
    .send:hover { background: #087b4c; }
    .send:disabled, .question:disabled { cursor: not-allowed; opacity: .46; }
    .resize-handle { position: absolute; z-index: 8; }
    .resize-handle.n, .resize-handle.s { left: 10px; right: 10px; height: 7px; cursor: ns-resize; }
    .resize-handle.n { top: -2px; } .resize-handle.s { bottom: -2px; }
    .resize-handle.e, .resize-handle.w { top: 10px; bottom: 10px; width: 7px; cursor: ew-resize; }
    .resize-handle.e { right: -2px; } .resize-handle.w { left: -2px; }
    .resize-handle.ne, .resize-handle.nw, .resize-handle.se, .resize-handle.sw { width: 14px; height: 14px; }
    .resize-handle.ne { top: -3px; right: -3px; cursor: nesw-resize; } .resize-handle.nw { top: -3px; left: -3px; cursor: nwse-resize; }
    .resize-handle.se { right: -3px; bottom: -3px; cursor: nwse-resize; } .resize-handle.sw { left: -3px; bottom: -3px; cursor: nesw-resize; }
    .resize-handle.se::after { content: ''; position: absolute; right: 4px; bottom: 4px; width: 6px; height: 6px; border-right: 1px solid #aeb5b1; border-bottom: 1px solid #aeb5b1; opacity: .65; }
    .reopen-dock { position: absolute; right: 14px; bottom: 14px; display: none; align-items: center; gap: 6px; padding: 5px; border: 1px solid rgba(20,27,23,.12); border-radius: 12px; background: rgba(255,255,255,.96); box-shadow: 0 10px 30px rgba(17,24,20,.18); backdrop-filter: blur(12px); pointer-events: auto; animation: panel-in .16s ease-out both; }
    .reopen-dock.visible { display: flex; }
    .reopen-button { height: 32px; padding: 0 11px; border: 0; border-radius: 8px; color: #343a36; background: transparent; font-size: 11px; font-weight: 650; }
    .reopen-button:hover { color: #087b4c; background: #edf8f2; }
    @keyframes panel-in { from { opacity: 0; transform: scale(.985) translateY(3px); } to { opacity: 1; transform: scale(1) translateY(0); } }
    @keyframes item-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
    @keyframes translation-in { from { opacity: 0; color: #15945e; transform: translateY(2px); } to { opacity: 1; color: #68706b; transform: translateY(0); } }
    @keyframes dot-pulse { 0%,70%,100% { opacity: .28; transform: translateY(0); } 35% { opacity: 1; transform: translateY(-2px); } }
    @media (max-width: 720px) { .floating-panel { border-radius: 11px; } .subtitle-panel .title-copy { max-width: 116px; } .text-button { padding: 0 6px; } .search { width: 126px; } .record-en { padding-right: 0; } .transcript-item:hover::after { display: none; } }
    @media (prefers-reduced-motion: reduce) { *,*::before,*::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; scroll-behavior: auto !important; } }
  </style>

  <section class="floating-panel subtitle-panel" aria-label="双语字幕记录">
    <header class="panel-header subtitle-header">
      <div class="title-row"><span class="status-dot"></span><div class="title-copy"><h1 class="title">Video Companion</h1><p class="status-text">等待启动</p></div></div>
      <div class="header-actions">
        <button class="text-button chat-toggle" type="button" title="显示或隐藏 AI 问答">AI 问答</button>
        <button class="icon-button reset-layout" type="button" title="恢复默认布局">↺</button>
        <button class="icon-button collapse-subtitle" type="button" title="收起字幕">−</button>
        <button class="icon-button hide-subtitle" type="button" title="隐藏字幕">×</button>
      </div>
    </header>
    <div class="global-error"></div>
    <div class="panel-body">
      <section class="live"><p class="section-label">正在听</p><p class="live-text empty">等待语音…</p></section>
      <section class="transcript-section">
        <div class="section-head"><h2>双语记录</h2><input class="search" type="search" placeholder="搜索字幕" /></div>
        <div class="transcript-list"><div class="empty-state">双语内容将在这里持续累积</div></div>
        <button class="jump-latest" type="button" title="继续自动跟随最新记录">↓ 回到最新</button>
      </section>
    </div>
    ${pt()}
  </section>

  <aside class="floating-panel chat-panel" aria-label="AI 视频问答">
    <header class="panel-header chat-header">
      <div class="title-row"><span class="status-dot chat-status-dot"></span><div class="title-copy"><h2 class="title">AI 视频问答</h2><p class="status-text chat-status-text">选择字幕后开始提问</p></div></div>
      <div class="header-actions"><button class="icon-button hide-chat" type="button" title="隐藏 AI 问答">×</button></div>
    </header>
    <div class="panel-body">
      <section class="chat-context">
        <p class="context-label">已选择</p>
        <p class="selected-quote"></p>
        <p class="no-selection">点击字幕中的具体句子，AI 会结合视频上下文进行解释。</p>
        <div class="quick-actions">
          <button class="quick-action" data-question="请用简单中文解释我选中的英文句子。">解释句子</button>
          <button class="quick-action" data-question="请结合视频前后文解释我选中的句子。">结合前文</button>
          <button class="quick-action" data-question="请分析我选中句子的语法和重点词汇。">分析语法</button>
          <button class="quick-action" data-question="请解释我选中句子里的专业术语。">解释术语</button>
        </div>
      </section>
      <div class="chat-messages"><div class="chat-empty">选择一句字幕，或直接询问刚才的视频内容。</div></div>
      <div class="composer"><textarea class="question" placeholder="询问视频内容或英文表达"></textarea><button class="send" type="button">发送</button></div>
    </div>
    ${pt()}
  </aside>

  <nav class="reopen-dock" aria-label="恢复隐藏的窗口">
    <button class="reopen-button reopen-subtitle" type="button">打开字幕</button>
    <button class="reopen-button reopen-chat" type="button">打开问答</button>
  </nav>
`;const z=r.querySelector(".subtitle-panel"),it=r.querySelector(".chat-panel"),It=r.querySelector(".subtitle-header"),Dt=r.querySelector(".chat-header"),Ht=r.querySelectorAll(".status-dot"),$t=r.querySelector(".subtitle-panel .status-text"),vt=r.querySelector(".chat-status-text"),ut=r.querySelector(".live-text"),c=r.querySelector(".transcript-list"),Et=r.querySelector(".jump-latest"),S=r.querySelector(".chat-messages"),ht=r.querySelector(".selected-quote"),Nt=r.querySelector(".no-selection"),v=r.querySelector(".question"),kt=r.querySelector(".send"),ot=r.querySelector(".search"),bt=r.querySelector(".global-error"),Q=r.querySelector(".chat-toggle"),Yt=r.querySelector(".reopen-dock"),St=r.querySelector(".reopen-subtitle"),Lt=r.querySelector(".reopen-chat"),nt={subtitle:z,chat:it},zt={subtitle:{width:480,height:140},chat:{width:300,height:360}};function b(t,e,i){return Math.min(Math.max(t,e),Math.max(e,i))}function Rt(t,e){const i=zt[t],o=Math.max(280,window.innerWidth-12*2),s=Math.max(180,window.innerHeight-12*2),a=b(e.width,Math.min(i.width,o),o),l=b(e.height,Math.min(i.height,s),s);return{...e,width:a,height:l,left:b(e.left,12,window.innerWidth-a-12),top:b(e.top,12,window.innerHeight-l-12)}}function T(t){const e=nt[t],i=Rt(t,n[t]);t==="subtitle"&&n.subtitle.collapsed&&(i.top=b(n.subtitle.top,12,window.innerHeight-48-12)),t==="subtitle"?n.subtitle={...i,collapsed:n.subtitle.collapsed}:n.chat=i,e.style.left=`${i.left}px`,e.style.top=`${i.top}px`,e.style.width=`${i.width}px`,e.style.height=t==="subtitle"&&n.subtitle.collapsed?"48px":`${i.height}px`}function I(){T("subtitle"),T("chat")}function u(){chrome.storage.local.set({[X]:n})}function qt(){n=et(),I(),d(),u(),A()}function Tt(t,e){e.addEventListener("pointerdown",i=>{if(i.target.closest("button"))return;const o=n[t],s=i.clientX-o.left,a=i.clientY-o.top,l=nt[t];e.classList.add("dragging"),l.classList.add("interacting"),e.setPointerCapture(i.pointerId);const k=x=>{const h=t==="subtitle"&&n.subtitle.collapsed?48:o.height,_=b(x.clientX-s,12,window.innerWidth-o.width-12),w=b(x.clientY-a,12,window.innerHeight-h-12);t==="subtitle"?n.subtitle={...n.subtitle,left:_,top:w}:n.chat={...n.chat,left:_,top:w},T(t)},g=x=>{e.classList.remove("dragging"),l.classList.remove("interacting"),e.hasPointerCapture(x.pointerId)&&e.releasePointerCapture(x.pointerId),e.removeEventListener("pointermove",k),e.removeEventListener("pointerup",g),e.removeEventListener("pointercancel",g),u()};e.addEventListener("pointermove",k),e.addEventListener("pointerup",g),e.addEventListener("pointercancel",g)}),e.addEventListener("dblclick",()=>{const i=et();t==="subtitle"?n.subtitle=i.subtitle:n.chat=i.chat,T(t),d(),u()})}function At(t){const e=nt[t];e.querySelectorAll(".resize-handle").forEach(i=>{i.addEventListener("pointerdown",o=>{if(t==="subtitle"&&n.subtitle.collapsed)return;o.preventDefault(),o.stopPropagation();const s=i.dataset.direction,a={...n[t]},l=o.clientX,k=o.clientY,g=a.left+a.width,x=a.top+a.height,h=zt[t];e.classList.add("interacting"),i.setPointerCapture(o.pointerId);const _=P=>{const lt=P.clientX-l,ct=P.clientY-k;let H=a.left,$=a.top,W=g,j=x;s.includes("e")&&(W=b(g+lt,H+Math.min(h.width,window.innerWidth-12*2),window.innerWidth-12)),s.includes("w")&&(H=b(a.left+lt,12,W-Math.min(h.width,window.innerWidth-12*2))),s.includes("s")&&(j=b(x+ct,$+Math.min(h.height,window.innerHeight-12*2),window.innerHeight-12)),s.includes("n")&&($=b(a.top+ct,12,j-Math.min(h.height,window.innerHeight-12*2)));const dt={...a,left:H,top:$,width:W-H,height:j-$};t==="subtitle"?n.subtitle={...dt,collapsed:n.subtitle.collapsed}:n.chat=dt,T(t),t==="subtitle"&&D()},w=P=>{e.classList.remove("interacting"),i.hasPointerCapture(P.pointerId)&&i.releasePointerCapture(P.pointerId),i.removeEventListener("pointermove",_),i.removeEventListener("pointerup",w),i.removeEventListener("pointercancel",w),u(),t==="subtitle"&&A()};i.addEventListener("pointermove",_),i.addEventListener("pointerup",w),i.addEventListener("pointercancel",w)})})}function Ot(t){return new Date(t*1e3).toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}function Bt(t){const e=Math.max(0,Math.floor(t/1e3)),i=Math.floor(e/3600),o=Math.floor(e%3600/60),s=e%60;return i>0?`${String(i).padStart(2,"0")}:${String(o).padStart(2,"0")}:${String(s).padStart(2,"0")}`:`${String(o).padStart(2,"0")}:${String(s).padStart(2,"0")}`}function _t(t){const e=document.querySelector("video");e&&(e.currentTime=Math.max(0,t/1e3),e.play().catch(()=>{}))}function J(){Y!==null&&window.clearInterval(Y),Y=null}function Wt(){J(),Y=window.setInterval(()=>{const t=document.querySelector("video");!t||p!=="running"||chrome.runtime.sendMessage({type:"PLAYBACK_POSITION",seconds:t.currentTime}).catch(()=>{})},250)}function st(){return Math.max(0,c.scrollHeight-c.scrollTop-c.clientHeight)}function D(){const t=c.scrollHeight>c.clientHeight+4,e=st()>80;Et.classList.toggle("visible",!O&&t&&e)}function E(t){O=t,D()}function M(t=!1,e=100){!O||n.subtitle.collapsed||(cancelAnimationFrame(V),V=requestAnimationFrame(()=>{V=requestAnimationFrame(()=>{C=!0,t?c.scrollTo({top:c.scrollHeight,behavior:"smooth"}):c.scrollTop=c.scrollHeight,G!==null&&window.clearTimeout(G),G=window.setTimeout(()=>{C=!1,st()<=80&&(O=!0),D()},t?600:e)})}))}function A(){M(!1,1e3),F!==null&&window.clearTimeout(F),U!==null&&window.clearTimeout(U),F=window.setTimeout(()=>M(!1,750),250),U=window.setTimeout(()=>M(!1,150),1e3)}const B=new ResizeObserver(()=>{M(!1,500),D()});B.observe(c);function d(){const t=Z.length>0||tt.size>0,e=p!=="idle"||t||!!y;z.classList.toggle("visible",e&&!n.subtitle.hidden),it.classList.toggle("visible",e&&!n.chat.hidden),z.classList.toggle("collapsed",n.subtitle.collapsed),Q.classList.toggle("active",!n.chat.hidden),Q.textContent=n.chat.hidden?"AI 问答":"隐藏问答";const i=r.querySelector(".collapse-subtitle");i.textContent=n.subtitle.collapsed?"+":"−",i.title=n.subtitle.collapsed?"展开字幕":"收起字幕",T("subtitle"),St.style.display=n.subtitle.hidden?"":"none",Lt.style.display=n.chat.hidden?"":"none",Yt.classList.toggle("visible",e&&(n.subtitle.hidden||n.chat.hidden)),Ht.forEach(a=>{const l=a.classList.contains("chat-status-dot")?" chat-status-dot":"";a.className=`status-dot${l} ${p}`});const o=p==="running"?"实时理解中":p==="paused"?"已暂停":p==="starting"?"正在连接…":p==="error"?"连接异常":"本次会话已结束";$t.textContent=K&&p!=="idle"?`${K} · ${o}`:o,vt.textContent=f?"已关联所选字幕":o,bt.textContent=y,bt.classList.toggle("visible",!!y);const s=p==="running"||p==="paused";v.disabled=!s,kt.disabled=!s}function Pt(){const t=Math.max(14,Math.min(22,L.fontSize-4)),e=Math.max(.7,Math.min(1,L.opacity));[z,it].forEach(i=>{i.style.setProperty("--content-size",`${t}px`),i.style.setProperty("--surface-alpha",`${e}`)}),z.classList.toggle("hide-english",!L.showEnglish),z.classList.toggle("hide-chinese",!L.showChinese),A()}function Gt(t){N=t,ut.textContent=N||"等待下一段语音…",ut.classList.toggle("empty",!N)}function rt(){c.querySelectorAll(".transcript-item").forEach(e=>e.classList.toggle("selected",e.dataset.id===f));const t=m.get(f);ht.textContent=t?`${t.source_text}${t.target_text?`
${t.target_text}`:""}`:"",ht.classList.toggle("visible",!!t),Nt.style.display=t?"none":"",vt.textContent=t?"已关联所选字幕":p==="running"?"实时理解中":"选择字幕后开始提问"}function jt(t){f=f===t?"":t,f&&(E(!1),n.chat.hidden=!1,u(),d(),window.setTimeout(()=>v.focus(),180)),rt()}function Mt(){const t=ot.value.trim().toLowerCase();t&&E(!1),c.querySelectorAll(".transcript-item").forEach(e=>{const i=m.get(e.dataset.id||""),o=`${(i==null?void 0:i.source_text)||""} ${(i==null?void 0:i.target_text)||""}`.toLowerCase();e.style.display=!t||o.includes(t)?"":"none"}),D()}function Ft(t,e=""){var g;const i=m.get(t.id);m.set(t.id,{...i,...t});let o=c.querySelector(`[data-id="${CSS.escape(t.id)}"]`);o||((g=c.querySelector(".empty-state"))==null||g.remove(),Z.push(t.id),o=document.createElement("article"),o.className="transcript-item new-item",o.dataset.id=t.id,o.innerHTML='<div class="record-meta"><button class="record-time" type="button" title="跳转到视频位置"></button><span class="record-state"></span></div><p class="record-en"></p><p class="record-zh"></p>',o.addEventListener("click",()=>jt(t.id)),c.appendChild(o),B.observe(o),window.setTimeout(()=>o==null?void 0:o.classList.remove("new-item"),260),o.querySelector(".record-time").addEventListener("click",x=>{x.stopPropagation();const h=m.get(t.id);(h==null?void 0:h.start_ms)!==void 0&&_t(h.start_ms)}));const s=m.get(t.id);o.querySelector(".record-time").textContent=s.start_ms!==void 0?Bt(s.start_ms):Ot(s.timestamp);const a=o.querySelector(".record-state");a.textContent=s.status==="error"?e||"中文暂未生成":"",a.classList.toggle("record-error",s.status==="error"),o.querySelector(".record-en").textContent=s.source_text;const l=o.querySelector(".record-zh"),k=!!(s.target_text&&s.target_text!==(i==null?void 0:i.target_text));l.textContent=s.target_text,l.style.display=s.target_text?"":"none",k&&(l.style.animation="none",l.offsetHeight,l.style.animation=""),o.classList.toggle("selected",t.id===f),t.id===f&&rt(),Mt(),A()}function R(t){var i;tt.set(t.id,t),(i=S.querySelector(".chat-empty"))==null||i.remove();let e=S.querySelector(`[data-chat-id="${CSS.escape(t.id)}"]`);e||(e=document.createElement("div"),e.dataset.chatId=t.id,S.appendChild(e)),e.className=`message ${t.role}${t.pending?" pending":""}${t.error?" error":""}`,t.pending?e.innerHTML='AI 正在回答 <span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>':t.role==="assistant"&&!t.error?Vt(e,t.text):e.textContent=t.text,S.scrollTop=S.scrollHeight}function Ut(t){const e=t.split(":").map(Number);return e.some(Number.isNaN)?0:e.length===3?(e[0]*3600+e[1]*60+e[2])*1e3:(e[0]*60+e[1])*1e3}function Vt(t,e){t.replaceChildren();const i=/\[((?:\d{2}:)?\d{2}:\d{2})\]/g;let o=0;for(const s of e.matchAll(i)){const a=s.index??0;t.append(document.createTextNode(e.slice(o,a)));const l=document.createElement("button");l.className="time-citation",l.type="button",l.textContent=`[${s[1]}]`,l.title="跳转到视频位置",l.addEventListener("click",()=>_t(Ut(s[1]))),t.append(l),o=a+s[0].length}t.append(document.createTextNode(e.slice(o)))}async function at(t){const e=(t||v.value).trim();if(!e)return;n.chat.hidden=!1,d(),u();const i=crypto.randomUUID(),o=m.get(f);R({id:`${i}-user`,role:"user",text:e}),R({id:i,role:"assistant",text:"AI 正在回答",pending:!0}),v.value="";const s=await chrome.runtime.sendMessage({type:"CHAT_ASK",requestId:i,question:e,selectedSegmentId:f,selectedText:(o==null?void 0:o.source_text)||""});s.ok||R({id:i,role:"assistant",text:s.error||"发送失败",error:!0})}function Xt(){N="",f="",y="",Z.length=0,m.clear(),tt.clear(),E(!0),B.disconnect(),B.observe(c),c.innerHTML='<div class="empty-state">双语内容将在这里持续累积</div>',S.innerHTML='<div class="chat-empty">选择一句字幕，或直接询问刚才的视频内容。</div>',ot.value="",Gt(""),rt()}Tt("subtitle",It);Tt("chat",Dt);At("subtitle");At("chat");var gt;(gt=r.querySelector(".collapse-subtitle"))==null||gt.addEventListener("click",()=>{n.subtitle.collapsed=!n.subtitle.collapsed,d(),u(),n.subtitle.collapsed||A()});var xt;(xt=r.querySelector(".hide-subtitle"))==null||xt.addEventListener("click",()=>{n.subtitle.hidden=!0,d(),u()});var mt;(mt=r.querySelector(".hide-chat"))==null||mt.addEventListener("click",()=>{n.chat.hidden=!0,d(),u()});Q.addEventListener("click",()=>{n.chat.hidden=!n.chat.hidden,d(),u(),n.chat.hidden||window.setTimeout(()=>v.focus(),180)});var wt;(wt=r.querySelector(".reset-layout"))==null||wt.addEventListener("click",qt);St.addEventListener("click",()=>{n.subtitle.hidden=!1,d(),u(),A()});Lt.addEventListener("click",()=>{n.chat.hidden=!1,d(),u(),window.setTimeout(()=>v.focus(),180)});c.addEventListener("scroll",()=>{C||E(st()<=80)});c.addEventListener("pointerdown",()=>{C=!1,G!==null&&window.clearTimeout(G),E(!1)});c.addEventListener("wheel",t=>{t.deltaY<0&&(C=!1,E(!1))},{passive:!0});Et.addEventListener("click",()=>{E(!0),M()});ot.addEventListener("input",Mt);kt.addEventListener("click",()=>void at());v.addEventListener("keydown",t=>{t.key==="Enter"&&!t.shiftKey&&(t.preventDefault(),at())});r.querySelectorAll(".quick-action").forEach(t=>t.addEventListener("click",()=>void at(t.dataset.question)));chrome.runtime.onMessage.addListener((t,e,i)=>{var o;if(t.type==="CONTENT_PING")return i({ok:!0}),!1;if(t.type==="TRANSCRIPT_LIVE"&&Gt(((o=t.payload)==null?void 0:o.source_text)||""),t.type==="TRANSCRIPT_UPDATE"&&(Ft(t.payload,String(t.message||"")),y="",d()),t.type==="CHAT_RESPONSE"){const s=String(t.requestId||"");s&&R({id:s,role:"assistant",text:String(t.answer||t.error||"没有收到回答。"),error:!!t.error})}if(t.type==="SUBTITLE_SETTINGS"&&(L={...L,...t.settings},Pt()),t.type==="RESET_PANEL_LAYOUT"&&qt(),t.type==="CAPTURE_STATE"){const s=t.status,a=s==="running"&&(p==="idle"||p==="error");a&&Xt(),p=s,(t.inputMode==="audio"||t.inputMode==="captions")&&t.inputMode,typeof t.sourceLabel=="string"&&(K=t.sourceLabel),a&&Wt(),s==="idle"&&J(),n.subtitle.hidden=!1,d()}t.type==="CAPTURE_ERROR"&&(p="error",J(),y=String(t.error??"未知错误"),n.subtitle.hidden=!1,console.error("[Real-time AI Video Companion]",y),d())});Pt();I();d();chrome.storage.local.get([X]).then(t=>{const e=t[X];e!=null&&e.subtitle&&(n.subtitle={...n.subtitle,...e.subtitle}),e!=null&&e.chat&&(n.chat={...n.chat,...e.chat}),I(),d()});window.addEventListener("resize",()=>{I(),u()});function Kt(){const t=document.fullscreenElement||document.documentElement;q.parentElement!==t&&t.appendChild(q),window.setTimeout(()=>{I(),d()},80)}document.addEventListener("fullscreenchange",Kt);
