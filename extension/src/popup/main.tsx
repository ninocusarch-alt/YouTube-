import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { ExtensionStatus, SubtitleSettings } from '../types';
import './styles.css';

const initialSettings: SubtitleSettings = {
  showEnglish: true,
  showChinese: true,
  fontSize: 22,
  opacity: 0.96,
};

type HistoryItem = {
  session_id: string;
  video_url: string;
  video_title: string;
  created_at: string;
  segment_count: number;
  question_count: number;
  last_position_ms: number;
};

type HistoryDetail = HistoryItem & {
  segments: Array<{ id: string; source_text: string; target_text: string; start_ms: number }>;
  questions: Array<{ id: string; question: string; answer: string }>;
};

const BACKEND_URL = 'http://127.0.0.1:8000';

function sendMessage<T = { ok: boolean; error?: string }>(message: unknown) {
  return chrome.runtime.sendMessage(message) as Promise<T>;
}

function App() {
  const [status, setStatus] = useState<ExtensionStatus>('idle');
  const [error, setError] = useState('');
  const [settings, setSettings] = useState(initialSettings);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [historyDetail, setHistoryDetail] = useState<HistoryDetail | null>(null);

  useEffect(() => {
    chrome.storage.local.get(['subtitleSettings']).then((value) => {
      if (value.subtitleSettings) setSettings({ ...initialSettings, ...value.subtitleSettings });
    });
    sendMessage<{ status: ExtensionStatus }>({ type: 'GET_STATUS' }).then((result) => setStatus(result.status));
  }, []);

  async function updateSettings(next: SubtitleSettings) {
    setSettings(next);
    await chrome.storage.local.set({ subtitleSettings: next });
    await sendMessage({ type: 'UI_SETTINGS', settings: next });
  }

  async function start() {
    setStatus('starting');
    setError('');
    const result = await sendMessage<{ ok: boolean; error?: string }>({ type: 'START_CAPTURE' });
    if (!result.ok) {
      setStatus('error');
      setError(result.error ?? '启动失败');
      return;
    }
    setStatus('running');
  }

  async function togglePause() {
    const nextStatus = status === 'running' ? 'paused' : 'running';
    const result = await sendMessage<{ ok: boolean; error?: string }>({ type: nextStatus === 'paused' ? 'PAUSE_CAPTURE' : 'RESUME_CAPTURE' });
    if (result.ok) setStatus(nextStatus);
    else setError(result.error ?? '操作失败');
  }

  async function stop() {
    await sendMessage({ type: 'STOP_CAPTURE' });
    setStatus('idle');
  }

  async function resetLayout() {
    await sendMessage({ type: 'RESET_PANEL_LAYOUT' });
  }

  async function openHistory() {
    setHistoryOpen(true);
    setHistoryDetail(null);
    setHistoryLoading(true);
    setError('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/history?limit=20`);
      if (!response.ok) throw new Error('暂时无法读取历史记录');
      setHistoryItems(await response.json() as HistoryItem[]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '暂时无法读取历史记录');
    } finally {
      setHistoryLoading(false);
    }
  }

  async function openHistoryDetail(sessionId: string) {
    setHistoryLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/history/${sessionId}`);
      if (!response.ok) throw new Error('这条记录暂时无法打开');
      setHistoryDetail(await response.json() as HistoryDetail);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '这条记录暂时无法打开');
    } finally {
      setHistoryLoading(false);
    }
  }

  function continueWatching(item: HistoryItem) {
    try {
      const url = new URL(item.video_url);
      url.searchParams.set('t', String(Math.max(0, Math.floor(item.last_position_ms / 1000))));
      void chrome.tabs.create({ url: url.toString() });
    } catch {
      void chrome.tabs.create({ url: item.video_url });
    }
  }

  if (historyOpen) {
    return (
      <main className="panel history-panel">
        <div className="history-heading">
          <button className="back-button" onClick={() => historyDetail ? setHistoryDetail(null) : setHistoryOpen(false)}>←</button>
          <div><div className="eyebrow">WATCH HISTORY</div><h1>{historyDetail ? '本次观看记录' : '历史记录'}</h1></div>
        </div>
        {historyLoading && <div className="history-empty">正在读取…</div>}
        {!historyLoading && historyDetail && (
          <div className="history-detail">
            <h2>{historyDetail.video_title || '未命名视频'}</h2>
            <button className="secondary continue-button" onClick={() => continueWatching(historyDetail)}>从上次位置继续观看</button>
            <h3>双语记录</h3>
            {historyDetail.segments.length === 0 ? <p className="history-empty">本次没有生成字幕</p> : historyDetail.segments.slice(-40).map((segment) => (
              <div className="history-segment" key={segment.id}>
                <time>{Math.floor(segment.start_ms / 60000).toString().padStart(2, '0')}:{Math.floor(segment.start_ms / 1000 % 60).toString().padStart(2, '0')}</time>
                <p>{segment.source_text}</p><p className="history-zh">{segment.target_text}</p>
              </div>
            ))}
            {historyDetail.questions.length > 0 && <><h3>AI 问答</h3>{historyDetail.questions.map((question) => (
              <div className="history-question" key={question.id}><b>问：{question.question}</b><p>{question.answer}</p></div>
            ))}</>}
          </div>
        )}
        {!historyLoading && !historyDetail && (
          <div className="history-list">
            {historyItems.length === 0 && <div className="history-empty">还没有历史记录，先打开一个视频试试吧。</div>}
            {historyItems.map((item) => (
              <button className="history-item" key={item.session_id} onClick={() => void openHistoryDetail(item.session_id)}>
                <strong>{item.video_title || '未命名视频'}</strong>
                <span>{new Date(item.created_at).toLocaleString('zh-CN')} · {item.segment_count} 段字幕 · {item.question_count} 次问答</span>
              </button>
            ))}
          </div>
        )}
        {error && <div className="error"><strong>读取失败</strong><span>{error}</span></div>}
      </main>
    );
  }

  return (
    <main className="panel">
      <div className="brand">
        <div>
          <div className="eyebrow">REAL-TIME AI</div>
          <h1>Video Companion</h1>
        </div>
        <span className="brand-mark">VC</span>
      </div>

      <p className="description">实时双语记录与视频问答</p>

      <div className={`status status-${status}`}>
        <span className="dot" />
        {status === 'running' ? '实时理解中' : status === 'paused' ? '已暂停' : status === 'starting' ? '启动中…' : status === 'error' ? '出现问题' : '待启动'}
      </div>

      {status === 'running' || status === 'paused' || status === 'starting' ? (
        <>
          <button className="primary stop" onClick={togglePause} disabled={status === 'starting'}>
            {status === 'paused' ? '恢复实时理解' : '暂停实时理解'}
          </button>
          <button className="secondary" onClick={stop}>结束本次会话</button>
        </>
      ) : (
        <button className="primary" onClick={start}>打开视频双语助手</button>
      )}

      <section className="settings">
        <label className="setting-row">
          <span>显示英文原文</span>
          <input type="checkbox" checked={settings.showEnglish} onChange={(e) => updateSettings({ ...settings, showEnglish: e.target.checked })} />
        </label>
        <label className="setting-row">
          <span>显示中文翻译</span>
          <input type="checkbox" checked={settings.showChinese} onChange={(e) => updateSettings({ ...settings, showChinese: e.target.checked })} />
        </label>
        <label className="range-row">
          <span>字体大小 <b>{settings.fontSize}px</b></span>
          <input type="range" min="18" max="25" value={settings.fontSize} onChange={(e) => updateSettings({ ...settings, fontSize: Number(e.target.value) })} />
        </label>
        <label className="range-row">
          <span>背景透明度 <b>{Math.round(settings.opacity * 100)}%</b></span>
          <input type="range" min="70" max="100" value={Math.max(70, Math.round(settings.opacity * 100))} onChange={(e) => updateSettings({ ...settings, opacity: Number(e.target.value) / 100 })} />
        </label>
      </section>

      <button className="layout-reset" onClick={resetLayout}>恢复默认布局</button>
      <button className="history-entry" onClick={() => void openHistory()}>查看历史记录 →</button>

      {error && <div className="error"><strong>暂时无法启动</strong><span>{error}</span></div>}
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
