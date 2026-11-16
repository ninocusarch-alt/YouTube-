import type { ExtensionStatus, SubtitlePayload, SubtitleSettings } from './types';

const ROOT_ID = 'rt-ai-video-companion-root';
const LAYOUT_STORAGE_KEY = 'videoCompanionPanelLayouts';
const EDGE_GAP = 12;

const defaultSettings: SubtitleSettings = {
  showEnglish: true,
  showChinese: true,
  fontSize: 22,
  opacity: 0.96,
};

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  pending?: boolean;
  error?: boolean;
};

type PanelName = 'subtitle' | 'chat';
type ResizeDirection = 'n' | 'e' | 's' | 'w' | 'ne' | 'nw' | 'se' | 'sw';

type PanelLayout = {
  left: number;
  top: number;
  width: number;
  height: number;
  hidden: boolean;
};

type StoredPanelLayouts = {
  subtitle: PanelLayout & { collapsed: boolean };
  chat: PanelLayout;
};

let settings = { ...defaultSettings };
let status: ExtensionStatus = 'idle';
let lastError = '';
let liveText = '';
let selectedSegmentId = '';
let inputMode: 'audio' | 'captions' = 'audio';
let inputSourceLabel = '';
let playbackTimer: number | null = null;
let autoFollowLatest = true;
let programmaticTranscriptScroll = false;
let transcriptScrollTimer: number | null = null;
let transcriptSettleTimer: number | null = null;
let transcriptLongSettleTimer: number | null = null;
let transcriptScrollFrame = 0;
const transcriptOrder: string[] = [];
const transcripts = new Map<string, SubtitlePayload>();
const chats = new Map<string, ChatMessage>();

function createDefaultLayouts(): StoredPanelLayouts {
  const subtitleWidth = Math.max(480, Math.min(940, window.innerWidth - 32));
  const subtitleHeight = Math.max(170, Math.min(290, window.innerHeight * 0.34));
  const chatWidth = Math.max(300, Math.min(380, window.innerWidth - 32));
  const chatHeight = Math.max(360, Math.min(620, window.innerHeight - 96));
  return {
    subtitle: {
      left: Math.max(EDGE_GAP, (window.innerWidth - subtitleWidth) / 2),
      top: Math.max(EDGE_GAP, window.innerHeight - subtitleHeight - 18),
      width: subtitleWidth,
      height: subtitleHeight,
      hidden: false,
      collapsed: false,
    },
    chat: {
      left: Math.max(EDGE_GAP, window.innerWidth - chatWidth - 18),
      top: Math.min(72, Math.max(EDGE_GAP, window.innerHeight - chatHeight - EDGE_GAP)),
      width: chatWidth,
      height: chatHeight,
      hidden: true,
    },
  };
}

let layouts = createDefaultLayouts();

const host = document.createElement('div');
document.getElementById(ROOT_ID)?.remove();
host.id = ROOT_ID;
Object.assign(host.style, {
  position: 'fixed',
  inset: '0',
  width: '100vw',
  height: '100vh',
  zIndex: '2147483647',
  pointerEvents: 'none',
});
document.documentElement.appendChild(host);

function resizeHandles() {
  return (['n', 'e', 's', 'w', 'ne', 'nw', 'se', 'sw'] as ResizeDirection[])
    .map((direction) => `<span class="resize-handle ${direction}" data-direction="${direction}"></span>`)
    .join('');
}

const shadow = host.attachShadow({ mode: 'open' });
shadow.innerHTML = `
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
    ${resizeHandles()}
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
    ${resizeHandles()}
  </aside>

  <nav class="reopen-dock" aria-label="恢复隐藏的窗口">
    <button class="reopen-button reopen-subtitle" type="button">打开字幕</button>
    <button class="reopen-button reopen-chat" type="button">打开问答</button>
  </nav>
`;

const subtitlePanel = shadow.querySelector<HTMLElement>('.subtitle-panel')!;
const chatPanel = shadow.querySelector<HTMLElement>('.chat-panel')!;
const subtitleHeader = shadow.querySelector<HTMLElement>('.subtitle-header')!;
const chatHeader = shadow.querySelector<HTMLElement>('.chat-header')!;
const statusDots = shadow.querySelectorAll<HTMLElement>('.status-dot');
const statusText = shadow.querySelector<HTMLElement>('.subtitle-panel .status-text')!;
const chatStatusText = shadow.querySelector<HTMLElement>('.chat-status-text')!;
const liveElement = shadow.querySelector<HTMLElement>('.live-text')!;
const transcriptList = shadow.querySelector<HTMLElement>('.transcript-list')!;
const jumpLatestButton = shadow.querySelector<HTMLButtonElement>('.jump-latest')!;
const chatMessages = shadow.querySelector<HTMLElement>('.chat-messages')!;
const selectedQuote = shadow.querySelector<HTMLElement>('.selected-quote')!;
const noSelection = shadow.querySelector<HTMLElement>('.no-selection')!;
const questionInput = shadow.querySelector<HTMLTextAreaElement>('.question')!;
const sendButton = shadow.querySelector<HTMLButtonElement>('.send')!;
const searchInput = shadow.querySelector<HTMLInputElement>('.search')!;
const globalError = shadow.querySelector<HTMLElement>('.global-error')!;
const chatToggle = shadow.querySelector<HTMLButtonElement>('.chat-toggle')!;
const reopenDock = shadow.querySelector<HTMLElement>('.reopen-dock')!;
const reopenSubtitle = shadow.querySelector<HTMLButtonElement>('.reopen-subtitle')!;
const reopenChat = shadow.querySelector<HTMLButtonElement>('.reopen-chat')!;

const panelElements: Record<PanelName, HTMLElement> = { subtitle: subtitlePanel, chat: chatPanel };
const panelMinimums: Record<PanelName, { width: number; height: number }> = { subtitle: { width: 480, height: 140 }, chat: { width: 300, height: 360 } };

function clamp(value: number, min: number, max: number) { return Math.min(Math.max(value, min), Math.max(min, max)); }

function clampLayout(name: PanelName, input: PanelLayout): PanelLayout {
  const minimum = panelMinimums[name];
  const availableWidth = Math.max(280, window.innerWidth - EDGE_GAP * 2);
  const availableHeight = Math.max(180, window.innerHeight - EDGE_GAP * 2);
  const width = clamp(input.width, Math.min(minimum.width, availableWidth), availableWidth);
  const height = clamp(input.height, Math.min(minimum.height, availableHeight), availableHeight);
  return { ...input, width, height, left: clamp(input.left, EDGE_GAP, window.innerWidth - width - EDGE_GAP), top: clamp(input.top, EDGE_GAP, window.innerHeight - height - EDGE_GAP) };
}

function applyPanelLayout(name: PanelName) {
  const element = panelElements[name];
  const next = clampLayout(name, layouts[name]);
  if (name === 'subtitle' && layouts.subtitle.collapsed) {
    next.top = clamp(layouts.subtitle.top, EDGE_GAP, window.innerHeight - 48 - EDGE_GAP);
  }
  if (name === 'subtitle') layouts.subtitle = { ...next, collapsed: layouts.subtitle.collapsed };
  else layouts.chat = next;
  element.style.left = `${next.left}px`;
  element.style.top = `${next.top}px`;
  element.style.width = `${next.width}px`;
  element.style.height = name === 'subtitle' && layouts.subtitle.collapsed ? '48px' : `${next.height}px`;
}

function applyAllLayouts() { applyPanelLayout('subtitle'); applyPanelLayout('chat'); }
function persistLayouts() { void chrome.storage.local.set({ [LAYOUT_STORAGE_KEY]: layouts }); }

function resetLayouts() {
  layouts = createDefaultLayouts();
  applyAllLayouts();
  updatePanelState();
  persistLayouts();
  scheduleTranscriptFollow();
}

function bindPanelDrag(name: PanelName, handle: HTMLElement) {
  handle.addEventListener('pointerdown', (event) => {
    if ((event.target as HTMLElement).closest('button')) return;
    const current = layouts[name];
    const offsetX = event.clientX - current.left;
    const offsetY = event.clientY - current.top;
    const panel = panelElements[name];
    handle.classList.add('dragging'); panel.classList.add('interacting'); handle.setPointerCapture(event.pointerId);
    const handleMove = (moveEvent: PointerEvent) => {
      const visibleHeight = name === 'subtitle' && layouts.subtitle.collapsed ? 48 : current.height;
      const nextLeft = clamp(moveEvent.clientX - offsetX, EDGE_GAP, window.innerWidth - current.width - EDGE_GAP);
      const nextTop = clamp(moveEvent.clientY - offsetY, EDGE_GAP, window.innerHeight - visibleHeight - EDGE_GAP);
      if (name === 'subtitle') layouts.subtitle = { ...layouts.subtitle, left: nextLeft, top: nextTop };
      else layouts.chat = { ...layouts.chat, left: nextLeft, top: nextTop };
      applyPanelLayout(name);
    };
    const handleEnd = (endEvent: PointerEvent) => {
      handle.classList.remove('dragging'); panel.classList.remove('interacting');
      if (handle.hasPointerCapture(endEvent.pointerId)) handle.releasePointerCapture(endEvent.pointerId);
      handle.removeEventListener('pointermove', handleMove); handle.removeEventListener('pointerup', handleEnd); handle.removeEventListener('pointercancel', handleEnd);
      persistLayouts();
    };
    handle.addEventListener('pointermove', handleMove); handle.addEventListener('pointerup', handleEnd); handle.addEventListener('pointercancel', handleEnd);
  });
  handle.addEventListener('dblclick', () => {
    const defaults = createDefaultLayouts();
    if (name === 'subtitle') layouts.subtitle = defaults.subtitle; else layouts.chat = defaults.chat;
    applyPanelLayout(name); updatePanelState(); persistLayouts();
  });
}

function bindPanelResize(name: PanelName) {
  const panel = panelElements[name];
  panel.querySelectorAll<HTMLElement>('.resize-handle').forEach((handle) => {
    handle.addEventListener('pointerdown', (event) => {
      if (name === 'subtitle' && layouts.subtitle.collapsed) return;
      event.preventDefault(); event.stopPropagation();
      const direction = handle.dataset.direction as ResizeDirection;
      const start = { ...layouts[name] };
      const startX = event.clientX; const startY = event.clientY;
      const startRight = start.left + start.width; const startBottom = start.top + start.height;
      const minimum = panelMinimums[name];
      panel.classList.add('interacting'); handle.setPointerCapture(event.pointerId);
      const handleMove = (moveEvent: PointerEvent) => {
        const dx = moveEvent.clientX - startX; const dy = moveEvent.clientY - startY;
        let left = start.left; let top = start.top; let right = startRight; let bottom = startBottom;
        if (direction.includes('e')) right = clamp(startRight + dx, left + Math.min(minimum.width, window.innerWidth - EDGE_GAP * 2), window.innerWidth - EDGE_GAP);
        if (direction.includes('w')) left = clamp(start.left + dx, EDGE_GAP, right - Math.min(minimum.width, window.innerWidth - EDGE_GAP * 2));
        if (direction.includes('s')) bottom = clamp(startBottom + dy, top + Math.min(minimum.height, window.innerHeight - EDGE_GAP * 2), window.innerHeight - EDGE_GAP);
        if (direction.includes('n')) top = clamp(start.top + dy, EDGE_GAP, bottom - Math.min(minimum.height, window.innerHeight - EDGE_GAP * 2));
        const next = { ...start, left, top, width: right - left, height: bottom - top };
        if (name === 'subtitle') layouts.subtitle = { ...next, collapsed: layouts.subtitle.collapsed }; else layouts.chat = next;
        applyPanelLayout(name); if (name === 'subtitle') updateJumpLatestButton();
      };
      const handleEnd = (endEvent: PointerEvent) => {
        panel.classList.remove('interacting'); if (handle.hasPointerCapture(endEvent.pointerId)) handle.releasePointerCapture(endEvent.pointerId);
        handle.removeEventListener('pointermove', handleMove); handle.removeEventListener('pointerup', handleEnd); handle.removeEventListener('pointercancel', handleEnd);
        persistLayouts(); if (name === 'subtitle') scheduleTranscriptFollow();
      };
      handle.addEventListener('pointermove', handleMove); handle.addEventListener('pointerup', handleEnd); handle.addEventListener('pointercancel', handleEnd);
    });
  });
}

function formatTime(timestamp: number) { return new Date(timestamp * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
function formatVideoTime(milliseconds: number) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function seekVideo(milliseconds: number) {
  const video = document.querySelector<HTMLVideoElement>('video');
  if (!video) return;
  video.currentTime = Math.max(0, milliseconds / 1000);
  void video.play().catch(() => undefined);
}

function stopPlaybackTracking() {
  if (playbackTimer !== null) window.clearInterval(playbackTimer);
  playbackTimer = null;
}

function startPlaybackTracking() {
  stopPlaybackTracking();
  playbackTimer = window.setInterval(() => {
    const currentVideo = document.querySelector<HTMLVideoElement>('video');
    if (!currentVideo || status !== 'running') return;
    void chrome.runtime.sendMessage({ type: 'PLAYBACK_POSITION', seconds: currentVideo.currentTime }).catch(() => undefined);
  }, 250);
}
function transcriptDistanceFromBottom() { return Math.max(0, transcriptList.scrollHeight - transcriptList.scrollTop - transcriptList.clientHeight); }
function updateJumpLatestButton() { const hasOverflow = transcriptList.scrollHeight > transcriptList.clientHeight + 4; const isAway = transcriptDistanceFromBottom() > 80; jumpLatestButton.classList.toggle('visible', !autoFollowLatest && hasOverflow && isAway); }
function setAutoFollowLatest(enabled: boolean) { autoFollowLatest = enabled; updateJumpLatestButton(); }

function scrollToLatest(smooth = false, releaseDelay = 100) {
  if (!autoFollowLatest || layouts.subtitle.collapsed) return;
  cancelAnimationFrame(transcriptScrollFrame);
  transcriptScrollFrame = requestAnimationFrame(() => {
    transcriptScrollFrame = requestAnimationFrame(() => {
      programmaticTranscriptScroll = true;
      if (smooth) transcriptList.scrollTo({ top: transcriptList.scrollHeight, behavior: 'smooth' }); else transcriptList.scrollTop = transcriptList.scrollHeight;
      if (transcriptScrollTimer !== null) window.clearTimeout(transcriptScrollTimer);
      transcriptScrollTimer = window.setTimeout(() => { programmaticTranscriptScroll = false; if (transcriptDistanceFromBottom() <= 80) autoFollowLatest = true; updateJumpLatestButton(); }, smooth ? 600 : releaseDelay);
    });
  });
}

function scheduleTranscriptFollow() {
  scrollToLatest(false, 1000);
  if (transcriptSettleTimer !== null) window.clearTimeout(transcriptSettleTimer);
  if (transcriptLongSettleTimer !== null) window.clearTimeout(transcriptLongSettleTimer);
  transcriptSettleTimer = window.setTimeout(() => scrollToLatest(false, 750), 250);
  transcriptLongSettleTimer = window.setTimeout(() => scrollToLatest(false, 150), 1000);
}

const transcriptResizeObserver = new ResizeObserver(() => { scrollToLatest(false, 500); updateJumpLatestButton(); });
transcriptResizeObserver.observe(transcriptList);

function updatePanelState() {
  const hasContent = transcriptOrder.length > 0 || chats.size > 0;
  const hasSession = status !== 'idle' || hasContent || Boolean(lastError);
  subtitlePanel.classList.toggle('visible', hasSession && !layouts.subtitle.hidden);
  chatPanel.classList.toggle('visible', hasSession && !layouts.chat.hidden);
  subtitlePanel.classList.toggle('collapsed', layouts.subtitle.collapsed);
  chatToggle.classList.toggle('active', !layouts.chat.hidden);
  chatToggle.textContent = layouts.chat.hidden ? 'AI 问答' : '隐藏问答';
  const collapseButton = shadow.querySelector<HTMLButtonElement>('.collapse-subtitle')!;
  collapseButton.textContent = layouts.subtitle.collapsed ? '+' : '−';
  collapseButton.title = layouts.subtitle.collapsed ? '展开字幕' : '收起字幕';
  applyPanelLayout('subtitle');
  reopenSubtitle.style.display = layouts.subtitle.hidden ? '' : 'none';
  reopenChat.style.display = layouts.chat.hidden ? '' : 'none';
  reopenDock.classList.toggle('visible', hasSession && (layouts.subtitle.hidden || layouts.chat.hidden));
  statusDots.forEach((dot) => { const chatClass = dot.classList.contains('chat-status-dot') ? ' chat-status-dot' : ''; dot.className = `status-dot${chatClass} ${status}`; });
  const currentStatusText = status === 'running' ? '实时理解中' : status === 'paused' ? '已暂停' : status === 'starting' ? '正在连接…' : status === 'error' ? '连接异常' : '本次会话已结束';
  statusText.textContent = inputSourceLabel && status !== 'idle' ? `${inputSourceLabel} · ${currentStatusText}` : currentStatusText;
  chatStatusText.textContent = selectedSegmentId ? '已关联所选字幕' : currentStatusText;
  globalError.textContent = lastError; globalError.classList.toggle('visible', Boolean(lastError));
  const chatEnabled = status === 'running' || status === 'paused'; questionInput.disabled = !chatEnabled; sendButton.disabled = !chatEnabled;
}

function applySettings() {
  const contentSize = Math.max(14, Math.min(22, settings.fontSize - 4));
  const alpha = Math.max(.7, Math.min(1, settings.opacity));
  [subtitlePanel, chatPanel].forEach((panel) => { panel.style.setProperty('--content-size', `${contentSize}px`); panel.style.setProperty('--surface-alpha', `${alpha}`); });
  subtitlePanel.classList.toggle('hide-english', !settings.showEnglish); subtitlePanel.classList.toggle('hide-chinese', !settings.showChinese); scheduleTranscriptFollow();
}

function updateLiveText(text: string) { liveText = text; liveElement.textContent = liveText || '等待下一段语音…'; liveElement.classList.toggle('empty', !liveText); }

function updateSelectedTranscript() {
  transcriptList.querySelectorAll<HTMLElement>('.transcript-item').forEach((element) => element.classList.toggle('selected', element.dataset.id === selectedSegmentId));
  const selected = transcripts.get(selectedSegmentId);
  selectedQuote.textContent = selected ? `${selected.source_text}${selected.target_text ? `\n${selected.target_text}` : ''}` : '';
  selectedQuote.classList.toggle('visible', Boolean(selected)); noSelection.style.display = selected ? 'none' : '';
  chatStatusText.textContent = selected ? '已关联所选字幕' : (status === 'running' ? '实时理解中' : '选择字幕后开始提问');
}

function selectTranscript(id: string) {
  selectedSegmentId = selectedSegmentId === id ? '' : id;
  if (selectedSegmentId) { setAutoFollowLatest(false); layouts.chat.hidden = false; persistLayouts(); updatePanelState(); window.setTimeout(() => questionInput.focus(), 180); }
  updateSelectedTranscript();
}

function applySearch() {
  const query = searchInput.value.trim().toLowerCase(); if (query) setAutoFollowLatest(false);
  transcriptList.querySelectorAll<HTMLElement>('.transcript-item').forEach((element) => { const item = transcripts.get(element.dataset.id || ''); const haystack = `${item?.source_text || ''} ${item?.target_text || ''}`.toLowerCase(); element.style.display = !query || haystack.includes(query) ? '' : 'none'; });
  updateJumpLatestButton();
}

function upsertTranscript(next: SubtitlePayload, errorMessage = '') {
  const previous = transcripts.get(next.id); transcripts.set(next.id, { ...previous, ...next });
  let element = transcriptList.querySelector<HTMLElement>(`[data-id="${CSS.escape(next.id)}"]`);
  if (!element) {
    transcriptList.querySelector('.empty-state')?.remove(); transcriptOrder.push(next.id); element = document.createElement('article');
    element.className = 'transcript-item new-item'; element.dataset.id = next.id;
    element.innerHTML = '<div class="record-meta"><button class="record-time" type="button" title="跳转到视频位置"></button><span class="record-state"></span></div><p class="record-en"></p><p class="record-zh"></p>';
    element.addEventListener('click', () => selectTranscript(next.id)); transcriptList.appendChild(element); transcriptResizeObserver.observe(element); window.setTimeout(() => element?.classList.remove('new-item'), 260);
    element.querySelector<HTMLButtonElement>('.record-time')!.addEventListener('click', (event) => {
      event.stopPropagation();
      const segment = transcripts.get(next.id);
      if (segment?.start_ms !== undefined) seekVideo(segment.start_ms);
    });
  }
  const current = transcripts.get(next.id)!;
  element.querySelector<HTMLElement>('.record-time')!.textContent = current.start_ms !== undefined
    ? formatVideoTime(current.start_ms)
    : formatTime(current.timestamp);
  const stateElement = element.querySelector<HTMLElement>('.record-state')!; stateElement.textContent = current.status === 'error' ? (errorMessage || '中文暂未生成') : ''; stateElement.classList.toggle('record-error', current.status === 'error');
  element.querySelector<HTMLElement>('.record-en')!.textContent = current.source_text;
  const chinese = element.querySelector<HTMLElement>('.record-zh')!; const targetChanged = Boolean(current.target_text && current.target_text !== previous?.target_text); chinese.textContent = current.target_text; chinese.style.display = current.target_text ? '' : 'none';
  if (targetChanged) { chinese.style.animation = 'none'; void chinese.offsetHeight; chinese.style.animation = ''; }
  element.classList.toggle('selected', next.id === selectedSegmentId); if (next.id === selectedSegmentId) updateSelectedTranscript(); applySearch(); scheduleTranscriptFollow();
}

function renderChatMessage(message: ChatMessage) {
  chats.set(message.id, message); chatMessages.querySelector('.chat-empty')?.remove();
  let element = chatMessages.querySelector<HTMLElement>(`[data-chat-id="${CSS.escape(message.id)}"]`);
  if (!element) { element = document.createElement('div'); element.dataset.chatId = message.id; chatMessages.appendChild(element); }
  element.className = `message ${message.role}${message.pending ? ' pending' : ''}${message.error ? ' error' : ''}`;
  if (message.pending) {
    element.innerHTML = 'AI 正在回答 <span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>';
  } else if (message.role === 'assistant' && !message.error) {
    renderAnswerWithTimestamps(element, message.text);
  } else {
    element.textContent = message.text;
  }
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function timestampToMilliseconds(timestamp: string) {
  const parts = timestamp.split(':').map(Number);
  if (parts.some(Number.isNaN)) return 0;
  if (parts.length === 3) return ((parts[0] * 3600) + (parts[1] * 60) + parts[2]) * 1000;
  return ((parts[0] * 60) + parts[1]) * 1000;
}

function renderAnswerWithTimestamps(container: HTMLElement, answer: string) {
  container.replaceChildren();
  const pattern = /\[((?:\d{2}:)?\d{2}:\d{2})\]/g;
  let cursor = 0;
  for (const match of answer.matchAll(pattern)) {
    const index = match.index ?? 0;
    container.append(document.createTextNode(answer.slice(cursor, index)));
    const button = document.createElement('button');
    button.className = 'time-citation';
    button.type = 'button';
    button.textContent = `[${match[1]}]`;
    button.title = '跳转到视频位置';
    button.addEventListener('click', () => seekVideo(timestampToMilliseconds(match[1])));
    container.append(button);
    cursor = index + match[0].length;
  }
  container.append(document.createTextNode(answer.slice(cursor)));
}

async function askQuestion(prefilledQuestion?: string) {
  const question = (prefilledQuestion || questionInput.value).trim(); if (!question) return;
  layouts.chat.hidden = false; updatePanelState(); persistLayouts();
  const requestId = crypto.randomUUID(); const selected = transcripts.get(selectedSegmentId);
  renderChatMessage({ id: `${requestId}-user`, role: 'user', text: question }); renderChatMessage({ id: requestId, role: 'assistant', text: 'AI 正在回答', pending: true }); questionInput.value = '';
  const response = await chrome.runtime.sendMessage({ type: 'CHAT_ASK', requestId, question, selectedSegmentId, selectedText: selected?.source_text || '' }) as { ok: boolean; error?: string };
  if (!response.ok) renderChatMessage({ id: requestId, role: 'assistant', text: response.error || '发送失败', error: true });
}

function resetForNewSession() {
  liveText = ''; selectedSegmentId = ''; lastError = ''; transcriptOrder.length = 0; transcripts.clear(); chats.clear(); setAutoFollowLatest(true);
  transcriptResizeObserver.disconnect(); transcriptResizeObserver.observe(transcriptList); transcriptList.innerHTML = '<div class="empty-state">双语内容将在这里持续累积</div>';
  chatMessages.innerHTML = '<div class="chat-empty">选择一句字幕，或直接询问刚才的视频内容。</div>'; searchInput.value = ''; updateLiveText(''); updateSelectedTranscript();
}

bindPanelDrag('subtitle', subtitleHeader); bindPanelDrag('chat', chatHeader); bindPanelResize('subtitle'); bindPanelResize('chat');
shadow.querySelector('.collapse-subtitle')?.addEventListener('click', () => { layouts.subtitle.collapsed = !layouts.subtitle.collapsed; updatePanelState(); persistLayouts(); if (!layouts.subtitle.collapsed) scheduleTranscriptFollow(); });
shadow.querySelector('.hide-subtitle')?.addEventListener('click', () => { layouts.subtitle.hidden = true; updatePanelState(); persistLayouts(); });
shadow.querySelector('.hide-chat')?.addEventListener('click', () => { layouts.chat.hidden = true; updatePanelState(); persistLayouts(); });
chatToggle.addEventListener('click', () => { layouts.chat.hidden = !layouts.chat.hidden; updatePanelState(); persistLayouts(); if (!layouts.chat.hidden) window.setTimeout(() => questionInput.focus(), 180); });
shadow.querySelector('.reset-layout')?.addEventListener('click', resetLayouts);
reopenSubtitle.addEventListener('click', () => { layouts.subtitle.hidden = false; updatePanelState(); persistLayouts(); scheduleTranscriptFollow(); });
reopenChat.addEventListener('click', () => { layouts.chat.hidden = false; updatePanelState(); persistLayouts(); window.setTimeout(() => questionInput.focus(), 180); });
transcriptList.addEventListener('scroll', () => { if (!programmaticTranscriptScroll) setAutoFollowLatest(transcriptDistanceFromBottom() <= 80); });
transcriptList.addEventListener('pointerdown', () => { programmaticTranscriptScroll = false; if (transcriptScrollTimer !== null) window.clearTimeout(transcriptScrollTimer); setAutoFollowLatest(false); });
transcriptList.addEventListener('wheel', (event) => { if (event.deltaY < 0) { programmaticTranscriptScroll = false; setAutoFollowLatest(false); } }, { passive: true });
jumpLatestButton.addEventListener('click', () => { setAutoFollowLatest(true); scrollToLatest(); });
searchInput.addEventListener('input', applySearch); sendButton.addEventListener('click', () => void askQuestion());
questionInput.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void askQuestion(); } });
shadow.querySelectorAll<HTMLButtonElement>('.quick-action').forEach((button) => button.addEventListener('click', () => void askQuestion(button.dataset.question)));

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'CONTENT_PING') { sendResponse({ ok: true }); return false; }
  if (message.type === 'TRANSCRIPT_LIVE') updateLiveText((message.payload as SubtitlePayload | undefined)?.source_text || '');
  if (message.type === 'TRANSCRIPT_UPDATE') { upsertTranscript(message.payload as SubtitlePayload, String(message.message || '')); lastError = ''; updatePanelState(); }
  if (message.type === 'CHAT_RESPONSE') { const requestId = String(message.requestId || ''); if (requestId) renderChatMessage({ id: requestId, role: 'assistant', text: String(message.answer || message.error || '没有收到回答。'), error: Boolean(message.error) }); }
  if (message.type === 'SUBTITLE_SETTINGS') { settings = { ...settings, ...(message.settings as SubtitleSettings) }; applySettings(); }
  if (message.type === 'RESET_PANEL_LAYOUT') resetLayouts();
  if (message.type === 'CAPTURE_STATE') {
    const nextStatus = message.status as ExtensionStatus;
    const startingNewSession = nextStatus === 'running' && (status === 'idle' || status === 'error');
    if (startingNewSession) resetForNewSession();
    status = nextStatus;
    if (message.inputMode === 'audio' || message.inputMode === 'captions') inputMode = message.inputMode;
    if (typeof message.sourceLabel === 'string') inputSourceLabel = message.sourceLabel;
    if (startingNewSession) startPlaybackTracking();
    if (nextStatus === 'idle') stopPlaybackTracking();
    layouts.subtitle.hidden = false;
    updatePanelState();
  }
  if (message.type === 'CAPTURE_ERROR') { status = 'error'; stopPlaybackTracking(); lastError = String(message.error ?? '未知错误'); layouts.subtitle.hidden = false; console.error('[Real-time AI Video Companion]', lastError); updatePanelState(); }
  return undefined;
});

applySettings(); applyAllLayouts(); updatePanelState();
chrome.storage.local.get([LAYOUT_STORAGE_KEY]).then((stored) => {
  const saved = stored[LAYOUT_STORAGE_KEY] as Partial<StoredPanelLayouts> | undefined;
  if (saved?.subtitle) layouts.subtitle = { ...layouts.subtitle, ...saved.subtitle };
  if (saved?.chat) layouts.chat = { ...layouts.chat, ...saved.chat };
  applyAllLayouts(); updatePanelState();
});
window.addEventListener('resize', () => { applyAllLayouts(); persistLayouts(); });

function syncFullscreenHost() {
  const target = document.fullscreenElement || document.documentElement;
  if (host.parentElement !== target) target.appendChild(host);
  window.setTimeout(() => {
    applyAllLayouts();
    updatePanelState();
  }, 80);
}

document.addEventListener('fullscreenchange', syncFullscreenHost);
