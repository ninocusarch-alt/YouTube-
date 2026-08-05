let stream: MediaStream | null = null;
let audioContext: AudioContext | null = null;
let source: MediaStreamAudioSourceNode | null = null;
let processor: ScriptProcessorNode | null = null;
let paused = false;
let sendQueue = Promise.resolve();

const ASR_SAMPLE_RATE = 16000;

function bufferToBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
}

function downsampleToPcm16(input: Float32Array, inputRate: number, outputRate: number) {
  const ratio = inputRate / outputRate;
  const outputLength = Math.max(1, Math.floor(input.length / ratio));
  const buffer = new ArrayBuffer(outputLength * 2);
  const view = new DataView(buffer);

  for (let outputIndex = 0; outputIndex < outputLength; outputIndex += 1) {
    const start = Math.floor(outputIndex * ratio);
    const end = Math.min(input.length, Math.max(start + 1, Math.floor((outputIndex + 1) * ratio)));
    let sum = 0;
    for (let inputIndex = start; inputIndex < end; inputIndex += 1) sum += input[inputIndex];
    const sample = Math.max(-1, Math.min(1, sum / (end - start)));
    const pcm = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    view.setInt16(outputIndex * 2, pcm, true);
  }
  return buffer;
}

function sendAudioFrame(input: Float32Array) {
  if (!audioContext || input.length === 0) return;
  const pcm = downsampleToPcm16(input, audioContext.sampleRate, ASR_SAMPLE_RATE);
  const base64Audio = bufferToBase64(pcm);
  sendQueue = sendQueue
    .then(() => chrome.runtime.sendMessage({ type: 'AUDIO_FRAME', base64Audio }))
    .catch(() => undefined);
}

function handleAudio(event: AudioProcessingEvent) {
  const input = event.inputBuffer.getChannelData(0);
  const output = event.outputBuffer.getChannelData(0);

  // tabCapture stops Chrome's normal audio output. Passing samples to this
  // AudioContext destination keeps the original YouTube sound audible.
  output.set(input);

  // Pause only stops ASR upload; it must never mute the video.
  if (!paused) sendAudioFrame(input);
}

async function startCapture(streamId: string) {
  if (audioContext) return;
  stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      ...({ mandatory: { chromeMediaSource: 'tab', chromeMediaSourceId: streamId } } as any),
    },
    video: false,
  });

  audioContext = new AudioContext();
  source = audioContext.createMediaStreamSource(stream);
  // At the usual 48 kHz input rate, 4096 samples produce an audio frame about every 85 ms.
  processor = audioContext.createScriptProcessor(4096, 1, 1);
  processor.onaudioprocess = handleAudio;
  source.connect(processor);
  processor.connect(audioContext.destination);
  await audioContext.resume();
  paused = false;
  sendQueue = Promise.resolve();
}

function stopCapture() {
  if (processor) processor.onaudioprocess = null;
  processor?.disconnect();
  processor = null;
  source?.disconnect();
  source = null;
  void audioContext?.close();
  audioContext = null;
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  paused = false;
  sendQueue = Promise.resolve();
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.target !== 'offscreen') return;
  if (message.type === 'START_CAPTURE') {
    startCapture(message.streamId as string).catch((error: Error) => {
      chrome.runtime.sendMessage({ type: 'OFFSCREEN_ERROR', error: error.message }).catch(() => undefined);
    });
  }
  if (message.type === 'STOP_CAPTURE') stopCapture();
  if (message.type === 'PAUSE_CAPTURE') paused = true;
  if (message.type === 'RESUME_CAPTURE' && audioContext) paused = false;
});
