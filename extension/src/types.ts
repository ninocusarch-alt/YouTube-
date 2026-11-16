export type SubtitlePayload = {
  id: string;
  source_text: string;
  target_text: string;
  timestamp: number;
  start_ms?: number;
  end_ms?: number;
  source?: 'youtube-manual' | 'youtube-auto' | 'qwen-asr' | string;
  status?: 'partial' | 'translating' | 'final' | 'error';
};

export type CaptionCue = {
  id: string;
  text: string;
  startMs: number;
  endMs: number;
  source: 'youtube-manual' | 'youtube-auto';
};

export type SubtitleSettings = {
  showEnglish: boolean;
  showChinese: boolean;
  fontSize: number;
  opacity: number;
};

export type ExtensionStatus = 'idle' | 'starting' | 'running' | 'paused' | 'error';
