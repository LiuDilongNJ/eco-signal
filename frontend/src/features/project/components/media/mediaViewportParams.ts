import type { MediaAudioQueryParams, SpectrogramQueryParams } from "@/api/endpoints/media"

/** Detail viewport params shared by playback and spectrogram rendering. */
export type MediaViewportParams = {
    start_time: number
    end_time: number
    min_freq: number
    max_freq: number
    channel: number
    filter: boolean
    fft_size: number
}

function roundMediaTimeParam(value: number): number {
    if (!Number.isFinite(value)) return value
    return Number(value.toFixed(4))
}

export function viewportParamsKey(p: MediaViewportParams): string {
    return [
        p.start_time,
        p.end_time,
        p.min_freq,
        p.max_freq,
        p.channel,
        p.filter ? 1 : 0,
        p.fft_size,
    ].join("|")
}

export function audioViewportParamsKey(p: MediaViewportParams): string {
    return [
        p.start_time,
        p.end_time,
        p.min_freq,
        p.max_freq,
        p.filter ? 1 : 0,
        p.fft_size,
    ].join("|")
}

export type BuildMediaViewportParamsInput = {
    durationS: number
    samplingRateHz: number
    viewStart: number
    windowSec: number
    freqMinHz: number
    freqMaxHz: number
    fftSize: number
    stereo: boolean
    audioChannel: 1 | 2
    /** When true, audio is bandpass-filtered to [min_freq, max_freq]. */
    bandFilter: boolean
}

export function buildMediaViewportParams(input: BuildMediaViewportParamsInput): MediaViewportParams {
    const nyq =
        Number.isFinite(input.samplingRateHz) && input.samplingRateHz > 0
            ? Math.round(input.samplingRateHz / 2)
            : 24000
    // Match legacy detail default f_min=1 (svt.py / ImageService).
    const rawMinHz = input.freqMinHz <= 0 ? 1 : input.freqMinHz
    const min_freq = roundMediaTimeParam(Math.max(1, Math.min(rawMinHz, nyq)))
    const max_freq = roundMediaTimeParam(Math.max(min_freq, Math.min(input.freqMaxHz, nyq)))
    const start_time = roundMediaTimeParam(Math.max(0, input.viewStart))
    const end_time = roundMediaTimeParam(Math.max(start_time, input.viewStart + Math.max(input.windowSec, 0)))

    return {
        start_time,
        end_time,
        min_freq,
        max_freq,
        channel: input.stereo ? input.audioChannel : 1,
        filter: input.bandFilter,
        fft_size: input.fftSize,
    }
}

export function toSpectrogramQueryParams(
    p: MediaViewportParams,
    width: number,
    height: number,
): SpectrogramQueryParams {
    return {
        start_time: p.start_time,
        end_time: p.end_time,
        min_freq: p.min_freq,
        max_freq: p.max_freq,
        channel: p.channel,
        filter: p.filter,
        fft_size: p.fft_size,
        width,
        height,
    }
}

export function toAudioQueryParams(p: MediaViewportParams, reloadKey?: number): MediaAudioQueryParams {
    const params: MediaAudioQueryParams = {
        start_time: p.start_time,
        end_time: p.end_time,
        filter: p.filter,
    }
    if (p.filter) {
        params.min_freq = p.min_freq
        params.max_freq = p.max_freq
        params.fft_size = p.fft_size
    }
    if (reloadKey != null) params.reload_key = reloadKey
    return params
}
