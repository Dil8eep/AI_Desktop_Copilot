type PcmListener = (pcmS16le: Uint8Array) => void;
type LevelListener = (level: number) => void;

const TARGET_SAMPLE_RATE_HZ = 16_000;
const CHUNK_BYTES = (TARGET_SAMPLE_RATE_HZ * 2) / 4;

const resampleTo16Khz = (
  samples: Float32Array,
  inputSampleRate: number,
): Int16Array => {
  if (inputSampleRate === TARGET_SAMPLE_RATE_HZ) {
    return Int16Array.from(
      samples,
      (sample) => Math.max(-1, Math.min(1, sample)) * 0x7fff,
    );
  }
  const ratio = inputSampleRate / TARGET_SAMPLE_RATE_HZ;
  const output = new Int16Array(Math.round(samples.length / ratio));
  for (let index = 0; index < output.length; index += 1) {
    const sourceIndex = Math.min(Math.round(index * ratio), samples.length - 1);
    output[index] = Math.max(-1, Math.min(1, samples[sourceIndex])) * 0x7fff;
  }
  return output;
};

/** Captures microphone audio locally and emits bounded 16 kHz PCM chunks. */
export class MicrophoneCapture {
  private audioContext: AudioContext | undefined;
  private processor: ScriptProcessorNode | undefined;
  private source: MediaStreamAudioSourceNode | undefined;
  private stream: MediaStream | undefined;
  private mutedGain: GainNode | undefined;
  private buffered = new Uint8Array();

  public async start(onPcm: PcmListener, onLevel?: LevelListener): Promise<void> {
    if (this.stream) {
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      video: false,
    });
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    const mutedGain = audioContext.createGain();
    mutedGain.gain.value = 0;
    processor.onaudioprocess = (event): void => {
      const level = Math.min(
        1,
        Math.sqrt(
          event.inputBuffer
            .getChannelData(0)
            .reduce((sum, sample) => sum + sample * sample, 0) /
            event.inputBuffer.length,
        ) * 3,
      );
      onLevel?.(level);
      const pcm = resampleTo16Khz(
        event.inputBuffer.getChannelData(0),
        audioContext.sampleRate,
      );
      this.append(new Uint8Array(pcm.buffer), onPcm);
    };
    source.connect(processor);
    processor.connect(mutedGain);
    mutedGain.connect(audioContext.destination);
    await audioContext.resume();
    this.stream = stream;
    this.audioContext = audioContext;
    this.source = source;
    this.processor = processor;
    this.mutedGain = mutedGain;
  }

  public async stop(onPcm: PcmListener): Promise<void> {
    if (!this.stream) {
      return;
    }
    if (this.buffered.byteLength > 0) {
      onPcm(this.buffered);
      this.buffered = new Uint8Array();
    }
    this.processor?.disconnect();
    this.source?.disconnect();
    this.mutedGain?.disconnect();
    this.stream.getTracks().forEach((track) => track.stop());
    await this.audioContext?.close();
    this.audioContext = undefined;
    this.processor = undefined;
    this.source = undefined;
    this.stream = undefined;
    this.mutedGain = undefined;
  }

  private append(pcm: Uint8Array, onPcm: PcmListener): void {
    const next = new Uint8Array(this.buffered.byteLength + pcm.byteLength);
    next.set(this.buffered);
    next.set(pcm, this.buffered.byteLength);
    this.buffered = next;
    while (this.buffered.byteLength >= CHUNK_BYTES) {
      onPcm(this.buffered.slice(0, CHUNK_BYTES));
      this.buffered = this.buffered.slice(CHUNK_BYTES);
    }
  }
}

export const microphoneSampleRateHz = TARGET_SAMPLE_RATE_HZ;
