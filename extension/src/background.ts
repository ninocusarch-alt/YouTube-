import type { SubtitlePayload, SubtitleSettings } from './types';

const BACKEND_URL = 'http://127.0.0.1:8000';
const BACKEND_WS_URL = 'ws://127.0.0.1:8000';

type CaptureState = {
  tabId: number;
  sessionId: string;
  status: 'running' | 'paused';
  socket: WebSocket;
};

let captureState: CaptureState | null = null;
let offscreenCreating: Promise<void> | null = null;
let handlingFailure = false;
const contentScriptPreparing = new Map<number, Promise<void>>();

function isYouTubeUrl(url?: string) {
  return Boolean(url && /^https:\/\/(www\.)?youtube\.com\//i.test(url));
}

async function prepareContentScript(tabId: number) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, { type: 'CONTENT_PING' }) as { ok?: boolean } | undefined;
    if (response?.ok) return;
  } catch {
    // A freshly reloaded extension has no receiver in an already-open tab.
  }

  const tab = await chrome.tabs.get(tabId);
  if (!isYouTubeUrl(tab.url)) throw new Error('请先打开 YouTube 视频页面。');
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
    const response = await chrome.tabs.sendMessage(tabId, { type: 'CONTENT_PING' }) as { ok?: boolean } | undefined;
    if (!response?.ok) throw new Error('内容脚本没有响应。');
  } catch (error) {
    console.error('[Video Companion] Failed to prepare content script', error);
    throw new Error('无法加载 YouTube 页面助手，请刷新视频页面后重试。');
  }
}

async function ensureContentScript(tabId: number) {
  let preparing = contentScriptPreparing.get(tabId);
  if (!preparing) {
    preparing = prepareContentScript(tabId).finally(() => contentScriptPreparing.delete(tabId));
    contentScriptPreparing.set(tabId, preparing);
  }
  await preparing;
}

async function sendToContent(tabId: number, message: Record<string, unknown>) {
  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch {
    await ensureContentScript(tabId);
    return chrome.tabs.sendMessage(tabId, message);
  }
}

async function ensureOffscreenDocument() {
  const offscreenUrl = chrome.runtime.getURL('offscreen.html');
  const contexts = await (chrome.runtime.getContexts as any)({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
    documentUrls: [offscreenUrl],
  }) as unknown[];
  if (contexts.length > 0) return;
  if (!offscreenCreating) {
    offscreenCreating = (chrome.offscreen.createDocument as any)({
      url: 'offscreen.html',
      reasons: ['USER_MEDIA'],
      justification: 'Capture the current tab audio for continuous speech recognition.',
    }).finally(() => { offscreenCreating = null; });
  }
  await offscreenCreating;
}

async function sendToOffscreen(message: Record<string, unknown>) {
  await ensureOffscreenDocument();
  return chrome.runtime.sendMessage({ ...message, target: 'offscreen' });
}

async function createSession(tab: chrome.tabs.Tab) {
  const response = await fetch(`${BACKEND_URL}/api/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_url: tab.url ?? '' }),
  });
  if (!response.ok) throw new Error(`创建字幕会话失败：${response.status}`);
  return response.json() as Promise<{ session_id: string }>;
}

async function forwardBackendMessage(tabId: number, message: unknown) {
  if (!message || typeof message !== 'object') return;
  const event = message as {
    type?: string;
    payload?: SubtitlePayload;
    message?: string;
    request_id?: string;
    answer?: string;
  };
  if (event.type === 'transcript.live') {
    await sendToContent(tabId, { type: 'TRANSCRIPT_LIVE', payload: event.payload }).catch(() => undefined);
  }
  if (event.type === 'transcript.segment' || event.type === 'transcript.translation' || event.type === 'transcript.translation_error') {
    if (event.payload?.source_text) {
      await sendToContent(tabId, {
        type: 'TRANSCRIPT_UPDATE',
        payload: event.payload,
        message: event.message,
      }).catch(() => undefined);
    }
  }
  if (event.type === 'chat.answer' || event.type === 'chat.error') {
    await sendToContent(tabId, {
      type: 'CHAT_RESPONSE',
      requestId: event.request_id,
      answer: event.answer,
      error: event.message,
    }).catch(() => undefined);
  }
}

function openBackendSocket(sessionId: string, tabId: number) {
  return new Promise<WebSocket>((resolve, reject) => {
    const socket = new WebSocket(`${BACKEND_WS_URL}/ws/sessions/${sessionId}`);
    let ready = false;
    let failureMessage = '';
    const timeout = globalThis.setTimeout(() => {
      if (!ready) {
        failureMessage = '连接千问实时语音服务超时，请检查后端窗口中的错误。';
        socket.close();
        reject(new Error(failureMessage));
      }
    }, 20000);

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data)) as { type?: string; message?: string };
        if (message.type === 'session.ready' && !ready) {
          ready = true;
          globalThis.clearTimeout(timeout);
          resolve(socket);
          return;
        }
        if (message.type === 'error') {
          failureMessage = message.message || '千问实时语音服务返回错误。';
          if (!ready) {
            globalThis.clearTimeout(timeout);
            reject(new Error(failureMessage));
          }
          return;
        }
        void forwardBackendMessage(tabId, message);
      } catch {
        failureMessage = '后端返回了无法识别的数据。';
      }
    };

    socket.onerror = () => {
      failureMessage ||= '无法连接本地后端，请确认 PowerShell 中的后端正在运行。';
      if (!ready) {
        globalThis.clearTimeout(timeout);
        reject(new Error(failureMessage));
      }
    };

    socket.onclose = () => {
      globalThis.clearTimeout(timeout);
      if (!ready) {
        reject(new Error(failureMessage || '实时字幕连接已关闭。'));
      } else if (captureState?.sessionId === sessionId) {
        void failActiveCapture(failureMessage || '实时字幕连接意外断开，请重新开始。');
      }
    };
  });
}

async function failActiveCapture(message: string) {
  if (handlingFailure) return;
  const current = captureState;
  if (!current) return;
  handlingFailure = true;
  captureState = null;
  try {
    await sendToOffscreen({ type: 'STOP_CAPTURE' }).catch(() => undefined);
    await fetch(`${BACKEND_URL}/api/sessions/${current.sessionId}`, { method: 'DELETE' }).catch(() => undefined);
    await sendToContent(current.tabId, { type: 'CAPTURE_ERROR', error: message }).catch(() => undefined);
  } finally {
    handlingFailure = false;
  }
}

async function startCapture(tab: chrome.tabs.Tab) {
  if (!tab.id) throw new Error('找不到当前标签页。');
  if (!isYouTubeUrl(tab.url)) throw new Error('请先打开 YouTube 视频页面。');
  if (captureState) return { session_id: captureState.sessionId };

  // tabCapture must be requested while the popup click is still active.
  const streamId = await new Promise<string>((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id! }, (id) => {
      const error = chrome.runtime.lastError;
      if (error) reject(new Error(error.message));
      else resolve(id);
    });
  });

  await ensureContentScript(tab.id);

  const session = await createSession(tab);
  let socket: WebSocket | null = null;
  try {
    socket = await openBackendSocket(session.session_id, tab.id);
    await ensureOffscreenDocument();
    captureState = {
      tabId: tab.id,
      sessionId: session.session_id,
      status: 'running',
      socket,
    };
    await sendToOffscreen({ type: 'START_CAPTURE', streamId });
    await sendToContent(tab.id, { type: 'CAPTURE_STATE', status: 'running' });
    const stored = await chrome.storage.local.get(['subtitleSettings']);
    if (stored.subtitleSettings) {
      await sendToContent(tab.id, {
        type: 'SUBTITLE_SETTINGS',
        settings: stored.subtitleSettings,
      }).catch(() => undefined);
    }
    return { session_id: session.session_id };
  } catch (error) {
    await sendToOffscreen({ type: 'STOP_CAPTURE' }).catch(() => undefined);
    socket?.close();
    captureState = null;
    await fetch(`${BACKEND_URL}/api/sessions/${session.session_id}`, { method: 'DELETE' }).catch(() => undefined);
    throw error;
  }
}

async function pauseCapture() {
  if (!captureState) return;
  await sendToOffscreen({ type: 'PAUSE_CAPTURE' });
  captureState.status = 'paused';
  await sendToContent(captureState.tabId, { type: 'CAPTURE_STATE', status: 'paused' }).catch(() => undefined);
}

async function resumeCapture() {
  if (!captureState) return;
  if (captureState.socket.readyState !== WebSocket.OPEN) {
    throw new Error('实时字幕连接已断开，请结束后重新开始。');
  }
  await sendToOffscreen({ type: 'RESUME_CAPTURE' });
  captureState.status = 'running';
  await sendToContent(captureState.tabId, { type: 'CAPTURE_STATE', status: 'running' }).catch(() => undefined);
}

async function stopCapture() {
  const current = captureState;
  if (!current) return;
  captureState = null;
  await sendToOffscreen({ type: 'STOP_CAPTURE' });
  if (current.socket.readyState === WebSocket.OPEN) {
    current.socket.send(JSON.stringify({ type: 'session.close' }));
  }
  current.socket.close();
  await fetch(`${BACKEND_URL}/api/sessions/${current.sessionId}`, { method: 'DELETE' }).catch(() => undefined);
  await sendToContent(current.tabId, { type: 'CAPTURE_STATE', status: 'idle' }).catch(() => undefined);
}

async function sendSettings(settings: SubtitleSettings) {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (tab?.id && isYouTubeUrl(tab.url)) {
    await sendToContent(tab.id, { type: 'SUBTITLE_SETTINGS', settings }).catch(() => undefined);
  }
}

function sendAudioFrame(base64Audio: string) {
  const current = captureState;
  if (!current || current.status !== 'running' || current.socket.readyState !== WebSocket.OPEN) return;
  current.socket.send(JSON.stringify({ type: 'audio.append', audio: base64Audio }));
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target === 'offscreen') return undefined;

  if (message.type === 'START_CAPTURE') {
    chrome.tabs.query({ active: true, currentWindow: true })
      .then(([tab]) => startCapture(tab))
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error: Error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === 'STOP_CAPTURE') {
    stopCapture().then(() => sendResponse({ ok: true })).catch((error: Error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === 'PAUSE_CAPTURE') {
    pauseCapture().then(() => sendResponse({ ok: true })).catch((error: Error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === 'RESUME_CAPTURE') {
    resumeCapture().then(() => sendResponse({ ok: true })).catch((error: Error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === 'GET_STATUS') {
    sendResponse({ status: captureState?.status ?? 'idle' });
    return false;
  }
  if (message.type === 'AUDIO_FRAME') {
    sendAudioFrame(message.base64Audio as string);
    return false;
  }
  if (message.type === 'CHAT_ASK') {
    const current = captureState;
    if (!current || current.socket.readyState !== WebSocket.OPEN) {
      sendResponse({ ok: false, error: '请先开始实时理解。' });
      return false;
    }
    current.socket.send(JSON.stringify({
      type: 'chat.ask',
      request_id: message.requestId,
      question: message.question,
      selected_segment_id: message.selectedSegmentId,
      selected_text: message.selectedText,
    }));
    sendResponse({ ok: true });
    return false;
  }
  if (message.type === 'OFFSCREEN_ERROR') {
    void failActiveCapture(String(message.error || '无法捕获标签页声音。'));
    return false;
  }
  if (message.type === 'UI_SETTINGS') {
    sendSettings(message.settings as SubtitleSettings).then(() => sendResponse({ ok: true }));
    return true;
  }
  return undefined;
});
