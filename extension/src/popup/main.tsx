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

function sendMessage<T = { ok: boolean; error?: string }>(message: unknown) {
  return chrome.runtime.sendMessage(message) as Promise<T>;
}

function App() {
  const [status, setStatus] = useState<ExtensionStatus>('idle');
  const [error, setError] = useState('');
  const [settings, setSettings] = useState(initialSettings);

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

  return (
    <main className="panel">
      <div className="brand">
        <div className="eyebrow">REAL-TIME AI</div>
        <h1>Video Companion</h1>
        <p>实时双语记录与视频问答</p>
      </div>

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
          <span>透明度 <b>{Math.round(settings.opacity * 100)}%</b></span>
          <input type="range" min="40" max="100" value={Math.round(settings.opacity * 100)} onChange={(e) => updateSettings({ ...settings, opacity: Number(e.target.value) / 100 })} />
        </label>
      </section>

      {error && <p className="error">{error}</p>}
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
