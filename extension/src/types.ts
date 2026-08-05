export type SubtitlePayload = {
  id: string;
  source_text: string;
  target_text: string;
  timestamp: number;
  status?: 'partial' | 'translating' | 'final' | 'error';
};

export type SubtitleSettings = {
  showEnglish: boolean;
  showChinese: boolean;
  fontSize: number;
  opacity: number;
};

export type ExtensionStatus = 'idle' | 'starting' | 'running' | 'paused' | 'error';
