import type { ExtensionStatus, SubtitlePayload, SubtitleSettings } from './types';

const ROOT_ID = 'rt-ai-video-companion-root';
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

let settings = { ...defaultSettings };
let status: ExtensionStatus = 'idle';
let lastError = '';
let liveText = '';
let selectedSegmentId = '';
let panelHidden = false;
let savedPanelPosition: { left: number; top: number } | null = null;
let autoFollowLatest = true;
let programmaticTranscriptScroll = false;
let transcriptScrollTimer: number | null = null;
let transcriptSettleTimer: number | null = null;
let transcriptLongSettleTimer: number | null = null;
let transcriptScrollFrame = 0;
const transcriptOrder: string[] = [];
const transcripts = new Map<string, SubtitlePayload>();
const chats = new Map<string, ChatMessage>();

const host = document.createElement('div');
document.getElementById(ROOT_ID)?.remove();
host.id = ROOT_ID;
host.style.position = 'fixed';
host.style.zIndex = '2147483647';
host.style.top = '68px';
host.style.right = '14px';
host.style.width = 'min(400px, calc(100vw - 24px))';
host.style.height = 'min(760px, calc(100vh - 84px))';
host.style.pointerEvents = 'none';
document.documentElement.appendChild(host);

const shadow = host.attachShadow({ mode: 'open' });
shadow.innerHTML = `
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
`;

const panel = shadow.querySelector<HTMLElement>('.panel')!;
const reopenButton = shadow.querySelector<HTMLButtonElement>('.reopen')!;
const panelHeader = shadow.querySelector<HTMLElement>('.header')!;
const statusDot = shadow.querySelector<HTMLElement>('.status-dot')!;
const statusText = shadow.querySelector<HTMLElement>('.status-text')!;
const liveElement = shadow.querySelector<HTMLElement>('.live-text')!;
const transcriptList = shadow.querySelector<HTMLElement>('.transcript-list')!;
const jumpLatestButton = shadow.querySelector<HTMLButtonElement>('.jump-latest')!;
const chatMessages = shadow.querySelector<HTMLElement>('.chat-messages')!;
const selectedQuote = shadow.querySelector<HTMLElement>('.selected-quote')!;
const questionInput = shadow.querySelector<HTMLTextAreaElement>('.question')!;
const sendButton = shadow.querySelector<HTMLButtonElement>('.send')!;
const searchInput = shadow.querySelector<HTMLInputElement>('.search')!;
const globalError = shadow.querySelector<HTMLElement>('.global-error')!;

function formatTime(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function movePanel(left: number, top: number, persist = false) {
  const panelWidth = Math.min(400, window.innerWidth - 24);
  const minPanelHeight = Math.min(460, window.innerHeight - 16);
  const boundedLeft = Math.max(8, Math.min(left, window.innerWidth - panelWidth - 8));
  const boundedTop = Math.max(8, Math.min(top, window.innerHeight - minPanelHeight - 8));
  savedPanelPosition = { left: boundedLeft, top: boundedTop };
  host.style.left = `${boundedLeft}px`;
  host.style.right = 'auto';
  host.style.top = `${boundedTop}px`;
  host.style.height = `min(760px, calc(100vh - ${boundedTop + 8}px))`;
  if (persist) void chrome.storage.local.set({ assistantPanelPosition: savedPanelPosition });
}

function transcriptDistanceFromBottom() {
  return Math.max(0, transcriptList.scrollHeight - transcriptList.scrollTop - transcriptList.clientHeight);
}

function updateJumpLatestButton() {
  const hasOverflow = transcriptList.scrollHeight > transcriptList.clientHeight + 4;
  const isAwayFromLatest = transcriptDistanceFromBottom() > 80;
  jumpLatestButton.classList.toggle('visible', !autoFollowLatest && hasOverflow && isAwayFromLatest);
}

function setAutoFollowLatest(enabled: boolean) {
  autoFollowLatest = enabled;
  updateJumpLatestButton();
}

function scrollToLatest(smooth = false, releaseDelay = 100) {
  if (!autoFollowLatest) return;
  cancelAnimationFrame(transcriptScrollFrame);
  transcriptScrollFrame = requestAnimationFrame(() => {
    transcriptScrollFrame = requestAnimationFrame(() => {
      programmaticTranscriptScroll = true;
      if (smooth) {
        transcriptList.scrollTo({ top: transcriptList.scrollHeight, behavior: 'smooth' });
      } else {
        transcriptList.scrollTop = transcriptList.scrollHeight;
      }
      if (transcriptScrollTimer !== null) window.clearTimeout(transcriptScrollTimer);
      transcriptScrollTimer = window.setTimeout(() => {
        programmaticTranscriptScroll = false;
        if (transcriptDistanceFromBottom() <= 80) autoFollowLatest = true;
        updateJumpLatestButton();
      }, smooth ? 600 : releaseDelay);
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

const transcriptResizeObserver = new ResizeObserver(() => {
  scrollToLatest(false, 500);
  updateJumpLatestButton();
});
transcriptResizeObserver.observe(transcriptList);

function updatePanelState() {
  const hasContent = transcriptOrder.length > 0 || chats.size > 0;
  panel.classList.toggle('visible', !panelHidden && (status !== 'idle' || hasContent || Boolean(lastError)));
  reopenButton.classList.toggle('visible', panelHidden && (status !== 'idle' || hasContent || Boolean(lastError)));
  host.style.pointerEvents = panel.classList.contains('visible') || reopenButton.classList.contains('visible') ? 'auto' : 'none';
  statusDot.className = `status-dot ${status}`;
  statusText.textContent = status === 'running'
    ? '实时理解中'
    : status === 'paused'
      ? '已暂停'
      : status === 'error'
        ? '连接异常'
        : '本次会话已结束';
  globalError.textContent = lastError;
  globalError.classList.toggle('visible', Boolean(lastError));
  const chatEnabled = status === 'running' || status === 'paused';
  questionInput.disabled = !chatEnabled;
  sendButton.disabled = !chatEnabled;
}

function applySettings() {
  const contentSize = Math.max(13, Math.min(20, settings.fontSize - 5));
  panel.style.setProperty('--content-size', `${contentSize}px`);
  panel.style.background = `rgba(17, 19, 21, ${Math.max(0.55, settings.opacity)})`;
  panel.classList.toggle('hide-english', !settings.showEnglish);
  panel.classList.toggle('hide-chinese', !settings.showChinese);
  scheduleTranscriptFollow();
}

function updateLiveText(text: string) {
  liveText = text;
  liveElement.textContent = liveText || '等待下一段语音…';
  liveElement.classList.toggle('empty', !liveText);
}

function selectTranscript(id: string) {
  selectedSegmentId = selectedSegmentId === id ? '' : id;
  if (selectedSegmentId) setAutoFollowLatest(false);
  transcriptList.querySelectorAll<HTMLElement>('.transcript-item').forEach((element) => {
    element.classList.toggle('selected', element.dataset.id === selectedSegmentId);
  });
  const selected = transcripts.get(selectedSegmentId);
  selectedQuote.textContent = selected ? `已选择：${selected.source_text}` : '';
  selectedQuote.classList.toggle('visible', Boolean(selected));
}

function applySearch() {
  const query = searchInput.value.trim().toLowerCase();
  if (query) setAutoFollowLatest(false);
  transcriptList.querySelectorAll<HTMLElement>('.transcript-item').forEach((element) => {
    const item = transcripts.get(element.dataset.id || '');
    const haystack = `${item?.source_text || ''} ${item?.target_text || ''}`.toLowerCase();
    element.style.display = !query || haystack.includes(query) ? '' : 'none';
  });
  updateJumpLatestButton();
}

function upsertTranscript(next: SubtitlePayload, errorMessage = '') {
  const previous = transcripts.get(next.id);
  transcripts.set(next.id, { ...previous, ...next });
  let element = transcriptList.querySelector<HTMLElement>(`[data-id="${CSS.escape(next.id)}"]`);

  if (!element) {
    transcriptList.querySelector('.empty-state')?.remove();
    transcriptOrder.push(next.id);
    element = document.createElement('article');
    element.className = 'transcript-item';
    element.dataset.id = next.id;
    element.innerHTML = '<div class="record-meta"><span class="record-time"></span><span class="record-state"></span></div><p class="record-en"></p><p class="record-zh"></p>';
    element.addEventListener('click', () => selectTranscript(next.id));
    transcriptList.appendChild(element);
    transcriptResizeObserver.observe(element);
  }

  const current = transcripts.get(next.id)!;
  element.querySelector<HTMLElement>('.record-time')!.textContent = formatTime(current.timestamp);
  const stateElement = element.querySelector<HTMLElement>('.record-state')!;
  stateElement.textContent = current.status === 'error' ? (errorMessage || '中文暂未生成') : '';
  stateElement.classList.toggle('record-error', current.status === 'error');
  element.querySelector<HTMLElement>('.record-en')!.textContent = current.source_text;
  const chinese = element.querySelector<HTMLElement>('.record-zh')!;
  chinese.textContent = current.target_text;
  chinese.style.display = current.target_text ? '' : 'none';
  element.classList.toggle('selected', next.id === selectedSegmentId);
  applySearch();
  scheduleTranscriptFollow();
}

function renderChatMessage(message: ChatMessage) {
  chats.set(message.id, message);
  let element = chatMessages.querySelector<HTMLElement>(`[data-chat-id="${CSS.escape(message.id)}"]`);
  if (!element) {
    element = document.createElement('div');
    element.dataset.chatId = message.id;
    chatMessages.appendChild(element);
  }
  element.className = `message ${message.role}${message.pending ? ' pending' : ''}${message.error ? ' error' : ''}`;
  element.textContent = message.text;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function askQuestion(prefilledQuestion?: string) {
  const question = (prefilledQuestion || questionInput.value).trim();
  if (!question) return;
  const requestId = crypto.randomUUID();
  const selected = transcripts.get(selectedSegmentId);
  renderChatMessage({ id: `${requestId}-user`, role: 'user', text: question });
  renderChatMessage({ id: requestId, role: 'assistant', text: '正在回答…', pending: true });
  questionInput.value = '';
  const response = await chrome.runtime.sendMessage({
    type: 'CHAT_ASK',
    requestId,
    question,
    selectedSegmentId,
    selectedText: selected?.source_text || '',
  }) as { ok: boolean; error?: string };
  if (!response.ok) {
    renderChatMessage({ id: requestId, role: 'assistant', text: response.error || '发送失败', error: true });
  }
}

function resetForNewSession() {
  liveText = '';
  selectedSegmentId = '';
  lastError = '';
  transcriptOrder.length = 0;
  transcripts.clear();
  chats.clear();
  setAutoFollowLatest(true);
  transcriptResizeObserver.disconnect();
  transcriptResizeObserver.observe(transcriptList);
  transcriptList.innerHTML = '<div class="empty-state">双语内容将在这里持续累积</div>';
  chatMessages.innerHTML = '';
  selectedQuote.textContent = '';
  selectedQuote.classList.remove('visible');
  searchInput.value = '';
  updateLiveText('');
}

shadow.querySelector('.collapse-button')?.addEventListener('click', () => {
  panel.classList.toggle('collapsed');
  const button = shadow.querySelector<HTMLButtonElement>('.collapse-button')!;
  button.textContent = panel.classList.contains('collapsed') ? '+' : '−';
  button.title = panel.classList.contains('collapsed') ? '展开面板' : '收起面板';
  if (!panel.classList.contains('collapsed')) scrollToLatest();
});
panelHeader.addEventListener('pointerdown', (event) => {
  if ((event.target as HTMLElement).closest('button')) return;
  const rect = host.getBoundingClientRect();
  const offsetX = event.clientX - rect.left;
  const offsetY = event.clientY - rect.top;
  panelHeader.classList.add('dragging');
  panelHeader.setPointerCapture(event.pointerId);

  const handleMove = (moveEvent: PointerEvent) => {
    movePanel(moveEvent.clientX - offsetX, moveEvent.clientY - offsetY);
  };
  const handleEnd = (endEvent: PointerEvent) => {
    panelHeader.classList.remove('dragging');
    panelHeader.releasePointerCapture(endEvent.pointerId);
    panelHeader.removeEventListener('pointermove', handleMove);
    panelHeader.removeEventListener('pointerup', handleEnd);
    panelHeader.removeEventListener('pointercancel', handleEnd);
    if (savedPanelPosition) void chrome.storage.local.set({ assistantPanelPosition: savedPanelPosition });
  };

  panelHeader.addEventListener('pointermove', handleMove);
  panelHeader.addEventListener('pointerup', handleEnd);
  panelHeader.addEventListener('pointercancel', handleEnd);
});
shadow.querySelector('.close-button')?.addEventListener('click', () => {
  panelHidden = true;
  updatePanelState();
});
reopenButton.addEventListener('click', () => {
  panelHidden = false;
  updatePanelState();
  scrollToLatest();
});
transcriptList.addEventListener('scroll', () => {
  if (programmaticTranscriptScroll) return;
  setAutoFollowLatest(transcriptDistanceFromBottom() <= 80);
});
transcriptList.addEventListener('pointerdown', () => {
  programmaticTranscriptScroll = false;
  if (transcriptScrollTimer !== null) window.clearTimeout(transcriptScrollTimer);
  setAutoFollowLatest(false);
});
transcriptList.addEventListener('wheel', (event) => {
  if (event.deltaY < 0) {
    programmaticTranscriptScroll = false;
    setAutoFollowLatest(false);
  }
}, { passive: true });
jumpLatestButton.addEventListener('click', () => {
  setAutoFollowLatest(true);
  scrollToLatest();
});
searchInput.addEventListener('input', applySearch);
sendButton.addEventListener('click', () => void askQuestion());
questionInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    void askQuestion();
  }
});
shadow.querySelectorAll<HTMLButtonElement>('.quick-action').forEach((button) => {
  button.addEventListener('click', () => void askQuestion(button.dataset.question));
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'CONTENT_PING') {
    sendResponse({ ok: true });
    return false;
  }
  if (message.type === 'TRANSCRIPT_LIVE') {
    updateLiveText((message.payload as SubtitlePayload | undefined)?.source_text || '');
  }
  if (message.type === 'TRANSCRIPT_UPDATE') {
    upsertTranscript(message.payload as SubtitlePayload, String(message.message || ''));
    lastError = '';
    updatePanelState();
  }
  if (message.type === 'CHAT_RESPONSE') {
    const requestId = String(message.requestId || '');
    if (requestId) {
      renderChatMessage({
        id: requestId,
        role: 'assistant',
        text: String(message.answer || message.error || '没有收到回答。'),
        error: Boolean(message.error),
      });
    }
  }
  if (message.type === 'SUBTITLE_SETTINGS') {
    settings = { ...settings, ...(message.settings as SubtitleSettings) };
    applySettings();
  }
  if (message.type === 'CAPTURE_STATE') {
    const nextStatus = message.status as ExtensionStatus;
    if (nextStatus === 'running' && (status === 'idle' || status === 'error')) resetForNewSession();
    status = nextStatus;
    panelHidden = false;
    updatePanelState();
  }
  if (message.type === 'CAPTURE_ERROR') {
    status = 'error';
    lastError = String(message.error ?? '未知错误');
    panelHidden = false;
    console.error('[Real-time AI Video Companion]', lastError);
    updatePanelState();
  }
  return undefined;
});

applySettings();
updatePanelState();
chrome.storage.local.get(['assistantPanelPosition']).then((stored) => {
  const position = stored.assistantPanelPosition as { left?: number; top?: number } | undefined;
  if (typeof position?.left === 'number' && typeof position.top === 'number') {
    movePanel(position.left, position.top);
  }
});
window.addEventListener('resize', () => {
  if (savedPanelPosition) movePanel(savedPanelPosition.left, savedPanelPosition.top);
});
