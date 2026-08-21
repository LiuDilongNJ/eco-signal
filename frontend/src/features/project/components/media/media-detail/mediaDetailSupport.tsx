import { useLayoutEffect, useRef, useState, type ReactNode } from "react"
import { RECORDING_FFT_SIZES, type RecordingDetail } from "../../../../../api/endpoints/media"
import type { AnnotationListParams, AnnotationPublic } from "../../../../../api/endpoints/annotations"
import type { AnnotationReviewRead } from "../../../../../api/endpoints/reviews"
import type { LabelPublic } from "../../../../../api/endpoints/labels"
import type { SoundClassificationPublic } from "../../../../../api/endpoints/taxons"
import { COOKIE_RETENTION_DAYS, isFunctionalCookiesAllowed } from "../../../../home/cookieConsent"
import type { MenuProps } from "@/components/ui"
import type { ColumnDef } from "../../data/DataPageLayout"
import { viewportParamsKey, type MediaViewportParams } from "../mediaViewportParams"
import { annotationHasActiveAssignedTask, normalizeUserColorHex } from "../mediaAnnotationPresentation"

export type StudioRightPanel =
    | "info"
    | "new-annotation"
    | "assign-task"
    | "ai-models"
    | "acoustic-indices"
    | "acoustic-analysis"

/** 标注表 body 的 scroll.y 额外安全边距，实际高度按容器/表头/分页实时计算。 */
export const ANNOTATION_TABLE_SCROLL_BUFFER_PX = 12

export const CHANNEL_DROPDOWN_ITEMS = [
    { id: 1, label: "Left (L)" },
    { id: 2, label: "Right (R)" },
]

export const FFT_DROPDOWN_ITEMS = RECORDING_FFT_SIZES.map((n) => ({ id: String(n), label: String(n) }))

/** 播放速度滑块范围；部分浏览器对 playbackRate < 0.25 可能抛错，effect 内会回退 */
export const PLAYBACK_RATE_SLIDER_MIN = 0.1
export const PLAYBACK_RATE_SLIDER_MAX = 1

/** 声谱图横向缩放：0% = 全时长可见，100% = 最大放大；仅保留极小数学下限避免除零。 */
export const SPECTROGRAM_ZOOM_STEP = 10
export const SPECTROGRAM_ZOOM_MIN_WINDOW_EPSILON_S = 1e-6
export const SPECTROGRAM_FREQ_WINDOW_EPSILON_HZ = 1e-6
export const SPECTROGRAM_ANNOTATION_MIN_VISIBLE_PX = 6
export const SPECTROGRAM_DRAFT_MIN_SIZE_PX = 12
export const SPECTROGRAM_PX_PER_SEC_MIN = 0.01
export const SPECTROGRAM_DISPLAY_MAX_DECIMALS = 4
export const SPECTROGRAM_VISIBLE_RANGE_SNAP_EPSILON_S = 0.05
export const SPECTROGRAM_CONTROL_COOLDOWN_MS = 160
export const AUDIO_CONTROL_COOLDOWN_MS = 220
export const CONTINUOUS_PREFETCH_LEAD_S = 1.5
export const CONTINUOUS_SCHEDULE_AHEAD_S = 0.35
export const CONTINUOUS_ADVANCE_EPSILON_S = 0.005
export const CONTINUOUS_MIN_SCHEDULE_DELAY_S = 0.02
export const AUDIO_SIGNAL_ANALYSIS_TARGET_SAMPLES = 500_000
export const AUDIO_SIGNAL_MEASURABLE_RMS_FLOOR = 10 ** (-90 / 20)
export const AUDIO_SIGNAL_MEASURABLE_PEAK_FLOOR = 10 ** (-80 / 20)
export const AUDIO_SIGNAL_LIKELY_AUDIBLE_RMS_FLOOR = 10 ** (-60 / 20)
export const AUDIO_SIGNAL_LIKELY_AUDIBLE_PEAK_FLOOR = 10 ** (-50 / 20)
export const AUDIO_SIGNAL_NON_SILENT_SAMPLE_FLOOR = AUDIO_SIGNAL_MEASURABLE_PEAK_FLOOR
export const AUDIO_SIGNAL_HUMAN_UPPER_EDGE_HZ = 18_000

export function clamp(n: number, lo: number, hi: number) {
    return Math.min(hi, Math.max(lo, n))
}

export function amplitudeToDbFs(v: number): number {
    return v > 0 ? 20 * Math.log10(v) : -Infinity
}

export function formatDbFs(v: number): string {
    return Number.isFinite(v) ? `${v.toFixed(1)} dBFS` : "-Infinity dBFS"
}

export function analyzeAudioBufferSignal(buffer: AudioBuffer) {
    const totalSamples = buffer.length
    const channels = buffer.numberOfChannels
    const stride = Math.max(1, Math.floor(totalSamples / AUDIO_SIGNAL_ANALYSIS_TARGET_SAMPLES))
    let sumSquares = 0
    let peak = 0
    let nonSilentSamples = 0
    let analyzedSamples = 0

    for (let ch = 0; ch < channels; ch += 1) {
        const data = buffer.getChannelData(ch)
        for (let i = 0; i < totalSamples; i += stride) {
            const abs = Math.abs(data[i] ?? 0)
            sumSquares += abs * abs
            peak = Math.max(peak, abs)
            if (abs >= AUDIO_SIGNAL_NON_SILENT_SAMPLE_FLOOR) nonSilentSamples += 1
            analyzedSamples += 1
        }
    }

    const rms = analyzedSamples > 0 ? Math.sqrt(sumSquares / analyzedSamples) : 0
    const rmsDbFs = amplitudeToDbFs(rms)
    const peakDbFs = amplitudeToDbFs(peak)
    const nonSilentRatio = analyzedSamples > 0 ? nonSilentSamples / analyzedSamples : 0
    const hasMeasurableSignal =
        rms >= AUDIO_SIGNAL_MEASURABLE_RMS_FLOOR || peak >= AUDIO_SIGNAL_MEASURABLE_PEAK_FLOOR
    const likelyAudibleByLevel =
        rms >= AUDIO_SIGNAL_LIKELY_AUDIBLE_RMS_FLOOR && peak >= AUDIO_SIGNAL_LIKELY_AUDIBLE_PEAK_FLOOR

    return {
        durationS: buffer.duration,
        sampleRateHz: buffer.sampleRate,
        channels,
        totalSamples,
        analyzedSamples,
        stride,
        rms,
        rmsDbFs,
        peak,
        peakDbFs,
        nonSilentRatio,
        hasMeasurableSignal,
        likelyAudibleByLevel,
    }
}

export function logAudioBufferSignal(
    buffer: AudioBuffer,
    context: {
        mediaId: number
        source: string
        viewport: MediaViewportParams
        requestedBandFilter: boolean
        segment?: string
    },
) {
    const result = analyzeAudioBufferSignal(buffer)
    const bandNearHumanUpperEdge =
        context.viewport.filter && context.viewport.max_freq >= AUDIO_SIGNAL_HUMAN_UPPER_EDGE_HZ

    console.info("[AudioSignal] audio waveform check", {
        mediaId: context.mediaId,
        source: context.source,
        segment: context.segment,
        timeRangeS: [context.viewport.start_time, context.viewport.end_time],
        frequencyRangeHz: context.viewport.filter
            ? [context.viewport.min_freq, context.viewport.max_freq]
            : "full spectrum",
        channel: context.viewport.channel,
        filter: context.viewport.filter,
        requestedBandFilter: context.requestedBandFilter,
        decoded: {
            durationS: Number(result.durationS.toFixed(4)),
            sampleRateHz: result.sampleRateHz,
            channels: result.channels,
            totalSamples: result.totalSamples,
            analyzedSamples: result.analyzedSamples,
            stride: result.stride,
        },
        signal: {
            hasMeasurableSignal: result.hasMeasurableSignal,
            likelyAudibleByLevel: result.likelyAudibleByLevel,
            rms: Number(result.rms.toExponential(3)),
            rmsDbFs: formatDbFs(result.rmsDbFs),
            peak: Number(result.peak.toExponential(3)),
            peakDbFs: formatDbFs(result.peakDbFs),
            nonSilentRatio: `${(result.nonSilentRatio * 100).toFixed(2)}%`,
        },
        note: bandNearHumanUpperEdge
            ? "Selected band is near the upper edge of human hearing. A measurable signal here may still be hard or impossible to hear."
            : undefined,
    })
}

export function logAudioBlobSignal(blob: Blob, context: Parameters<typeof logAudioBufferSignal>[1]) {
    const AudioContextCtor =
        window.AudioContext ??
        (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AudioContextCtor) {
        console.warn("[AudioSignal] AudioContext is unavailable; cannot decode audio for signal check", context)
        return
    }

    void (async () => {
        const ctx = new AudioContextCtor()
        try {
            const data = await blob.arrayBuffer()
            const buffer = await ctx.decodeAudioData(data)
            logAudioBufferSignal(buffer, context)
        } catch (error) {
            console.warn("[AudioSignal] Could not decode audio blob for signal check", {
                ...context,
                error,
            })
        } finally {
            void ctx.close().catch(() => {
                /* ignore */
            })
        }
    })()
}

export function normalizeSpectrogramPxPerSec(v: number): number {
    if (!Number.isFinite(v)) return SPECTROGRAM_PX_PER_SEC_MIN
    return Math.max(SPECTROGRAM_PX_PER_SEC_MIN, v)
}

export function formatDisplayNumber(v: number, maxDecimals = SPECTROGRAM_DISPLAY_MAX_DECIMALS): string {
    if (!Number.isFinite(v)) return ""
    const s = v.toFixed(maxDecimals).replace(/\.?0+$/, "")
    if (s === "" || s === "-0") return "0"
    return s
}

export function formatSpectrogramPxPerSecDisplay(v: number): string {
    return formatDisplayNumber(normalizeSpectrogramPxPerSec(v))
}

export function roundAnnotationCoord(value: number): number {
    if (!Number.isFinite(value)) return value
    return Number(value.toFixed(4))
}

export function snapVisibleRangeEndSec(endSec: number, durationSec: number): number {
    if (!(durationSec > 0)) return Math.max(0, endSec)
    if (Math.abs(endSec - durationSec) <= SPECTROGRAM_VISIBLE_RANGE_SNAP_EPSILON_S) {
        return durationSec
    }
    return clamp(endSec, 0, durationSec)
}

/** 按时间起点排序后的下一条标注（用于连续播放） */
export function compareAnnotationByMinTimeAndFrequency(a: AnnotationPublic, b: AnnotationPublic): number {
    const ax = Math.min(a.min_x, a.max_x)
    const bx = Math.min(b.min_x, b.max_x)
    if (Math.abs(ax - bx) > 1e-9) return ax - bx

    const ay = Math.min(a.min_y, a.max_y)
    const by = Math.min(b.min_y, b.max_y)
    if (Math.abs(ay - by) > 1e-9) return ay - by

    return 0
}

export function nextAnnotationAfterByTime(currentId: number, list: AnnotationPublic[]): AnnotationPublic | null {
    const sorted = [...list].sort(compareAnnotationByMinTimeAndFrequency)
    const idx = sorted.findIndex((x) => x.annotation_id === currentId)
    if (idx < 0 || idx + 1 >= sorted.length) return null
    return sorted[idx + 1] ?? null
}

/** 与 SetLabelsDrawer 一致：系统内置标签不可删 */
export function isLabelSystemProtected(l: LabelPublic): boolean {
    return typeof l.label_id === "number" && (l.label_id <= 3 || l.creator_id == null)
}

export function spectrogramVisibleWindowSec(durationS: number, zoomPercent: number): number {
    const dur = durationS > 0 ? durationS : 1
    const z = clamp(zoomPercent, 0, 100) / 100
    const minWin = spectrogramMinWindowSec(dur)
    return Math.max(minWin, dur * (1 - z * (1 - minWin / dur)))
}

/** 最小可见时间窗（秒），与 `spectrogramVisibleWindowSec` 一致 */
export function spectrogramMinWindowSec(durationS: number): number {
    const dur = durationS > 0 ? durationS : 1
    return Math.min(dur, SPECTROGRAM_ZOOM_MIN_WINDOW_EPSILON_S)
}

export function resolveSpectrogramViewportWindow(durationS: number, viewStartRaw: number, zoomPercent: number) {
    const dur = durationS > 0 ? durationS : 1
    const nominalWin = spectrogramVisibleWindowSec(dur, zoomPercent)
    const maxS = Math.max(0, dur - nominalWin)
    const viewStart = snapTimeSec(clamp(viewStartRaw, 0, dur), dur)
    const clampedStart = viewStart > maxS && viewStart < dur ? viewStart : clamp(viewStart, 0, maxS)
    const windowSec = clamp(dur - clampedStart, spectrogramMinWindowSec(dur), nominalWin)
    return {
        nominalWindowSec: nominalWin,
        windowSec,
        viewStartClamped: snapTimeSec(clampedStart, dur),
    }
}

/** 视窗时长（秒）= 播放器宽度 / px/s，再夹在 [minWin, dur] */
export function windowSecFromPxPerSec(durationS: number, viewportW: number, pxPerSec: number): number {
    const dur = durationS > 0 ? durationS : 0
    if (!(dur > 0) || !(viewportW > 0) || !(pxPerSec >= SPECTROGRAM_PX_PER_SEC_MIN)) {
        return dur > 0 ? dur : 1
    }
    const minWin = spectrogramMinWindowSec(dur)
    const raw = viewportW / pxPerSec
    return clamp(raw, minWin, dur)
}

/** 由当前可见窗（秒）换算缩放滑块百分比（cookie / 兼容旧逻辑；窗宽仍由 px/s 决定） */
export function zoomPercentFromWindowSec(durationS: number, windowSec: number): number {
    const dur = durationS > 0 ? durationS : 1
    const minWin = spectrogramMinWindowSec(dur)
    const W = clamp(windowSec, minWin, dur)
    if (W >= dur - 1e-9) return 0
    const denom = 1 - minWin / dur
    if (denom < 1e-12) return 100
    const z = (1 - W / dur) / denom
    return clamp(z * 100, 0, 100)
}

export function snapTimeSec(value: number, durationS?: number): number {
    if (!Number.isFinite(value)) return 0
    const snapped = Math.round(value * 1e4) / 1e4
    if (durationS != null && durationS > 0) return clamp(snapped, 0, durationS)
    return Math.max(0, snapped)
}

/** 保证 zoom % 与可见时间窗互为精确反函数，避免高倍放大时的浮点漂移 */
export function resolveSpectrogramZoomWindow(
    durationS: number,
    windowSecDesired: number,
): { win: number; zp: number } {
    const dur = durationS > 0 ? durationS : 1
    const minWin = spectrogramMinWindowSec(dur)
    const desired = clamp(windowSecDesired, minWin, dur)
    const zp = zoomPercentFromWindowSec(dur, desired)
    const win = spectrogramVisibleWindowSec(dur, zp)
    return { win, zp }
}

export function resolveSpectrogramViewStart(durationS: number, centerSec: number, windowSec: number): number {
    const dur = durationS > 0 ? durationS : 1
    const win = windowSec > 0 ? windowSec : spectrogramMinWindowSec(dur)
    const maxS = Math.max(0, dur - win)
    return snapTimeSec(clamp(centerSec - win / 2, 0, maxS), dur)
}

export function hexColorToRgba(hex: string, alpha: number): string {
    const normalized = normalizeUserColorHex(hex) ?? "#3B82F6"
    const r = Number.parseInt(normalized.slice(1, 3), 16)
    const g = Number.parseInt(normalized.slice(3, 5), 16)
    const b = Number.parseInt(normalized.slice(5, 7), 16)
    return `rgba(${r}, ${g}, ${b}, ${clamp(alpha, 0, 1)})`
}

export const SOUNDSCAPE_LABELS: Record<string, string> = {
    "": "Other / Unspecified",
    biophony: "Biophony",
    anthropophony: "Anthropophony",
    geophony: "Geophony",
    other: "Other",
}

export function buildSoundscapeSelectOptions(rows: SoundClassificationPublic[]) {
    const keys = new Set<string>()
    for (const r of rows) {
        keys.add(r.soundscape_component ?? "")
    }
    const preferred = ["biophony", "anthropophony", "geophony", "other"]
    const first = preferred.filter((p) => keys.has(p))
    const rest = [...keys].filter((k) => !preferred.includes(k)).sort((a, b) => a.localeCompare(b))
    return [...first, ...rest].map((value) => ({
        value,
        label:
            SOUNDSCAPE_LABELS[value] ??
            (value === "" ? "Other / Unspecified" : value.replace(/_/g, " ")),
    }))
}

export const selectSearchFilter = (input: string, option?: { label?: string }) =>
    String(option?.label ?? "")
        .toLowerCase()
        .includes((input ?? "").toLowerCase())

export function buildAnimalSoundSelectOptions(rows: Array<{ name?: string | null }>) {
    const seen = new Set<string>()
    const options: Array<{ value: string; label: string }> = []
    for (const row of rows) {
        const name = String(row.name ?? "").trim()
        if (!name || seen.has(name)) continue
        seen.add(name)
        options.push({ value: name, label: name })
    }
    return options
}

export function renderStudioRequiredLabel(label: string) {
    return (
        <>
            {label}
            <span className="form-drawer-required-suffix">*</span>
        </>
    )
}

export function formatAnnotationTimeSec(v: number) {
    return formatDisplayNumber(v)
}

export function formatAnnotationHz(v: number) {
    return formatDisplayNumber(v)
}

export type MagnifierLayout = {
    vs: number
    zp: number
    win: number
    y0: number
    y1: number
    start_time: number
    end_time: number
    min_freq: number
    max_freq: number
}

export type ContinuousPlaybackSegment = {
    kind: "annotation" | "viewport"
    start: number
    end: number
    annotationId?: number
    viewStart: number
}

export type ContinuousDecodedSegment = ContinuousPlaybackSegment & {
    buffer: AudioBuffer
}

export type ContinuousPlaybackEngine = {
    ctx: AudioContext
    runId: number
    current: ContinuousDecodedSegment | null
    next: ContinuousDecodedSegment | null
    source: AudioBufferSourceNode | null
    nextSource: AudioBufferSourceNode | null
    startedAtCtx: number
    scheduledEndCtx: number
    currentCtxDuration: number
    nextStartedAtCtx: number | null
    nextScheduledEndCtx: number | null
    nextCtxDuration: number | null
    playbackRate: number
    prefetchingKey: string | null
    stopAfterCurrent: boolean
}

export type PrefetchedSpectrogram = {
    key: string
    url: string
    runId: number
}

export function continuousSegmentKey(segment: ContinuousPlaybackSegment): string {
    return [
        segment.kind,
        segment.annotationId ?? "",
        snapTimeSec(segment.start),
        snapTimeSec(segment.end),
        snapTimeSec(segment.viewStart),
    ].join(":")
}

export function physBoxFreqBandHz(
    box: { min_y: number; max_y: number },
    nyquistHz: number,
): { lo: number; hi: number } {
    const y0 = clamp(Math.min(box.min_y, box.max_y), 0, nyquistHz)
    const y1 = clamp(Math.max(box.min_y, box.max_y), y0, nyquistHz)
    return { lo: snapTimeSec(y0), hi: snapTimeSec(y1) }
}

export function computeMagnifierLayoutForAnnotation(
    a: AnnotationPublic,
    durationS: number,
    samplingRateHz: number,
): MagnifierLayout | null {
    const dur = durationS
    if (!(dur > 0)) return null
    const minT = snapTimeSec(Math.min(a.min_x, a.max_x), dur)
    const maxT = snapTimeSec(Math.max(a.min_x, a.max_x), dur)
    const span = Math.max(maxT - minT, spectrogramMinWindowSec(dur))
    const { win, zp } = resolveSpectrogramZoomWindow(dur, span)
    const sr = samplingRateHz
    const nyq = !Number.isNaN(sr) && sr > 0 ? Math.round(sr / 2) : 24000
    const y0 = clamp(Math.min(a.min_y, a.max_y), 0, nyq)
    const y1 = clamp(Math.max(a.min_y, a.max_y), y0, nyq)
    return {
        vs: minT,
        zp,
        win,
        y0,
        y1,
        start_time: minT,
        end_time: maxT,
        min_freq: snapTimeSec(y0),
        max_freq: snapTimeSec(y1),
    }
}

/** 与 audio.html 标注表列一致；列 key 即数据表字段名，与后端 list order_by / 筛选参数对齐（不设 width，由内容与表头撑开） */
export const STUDIO_ANNOTATION_COLUMNS: ColumnDef[] = [
    { key: "annotation_id", label: "ID", type: "number", sortable: true, filterable: true, width: 150 },
    { key: "uuid", label: "UUID", type: "text", sortable: true, filterable: true, width: 320 },
    { key: "min_x", label: "Min X", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "max_x", label: "Max X", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "min_y", label: "Min Y", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "max_y", label: "Max Y", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "creator_type", label: "Creator", type: "text", sortable: true, filterable: true, filterSearch: true, width: 140 },
    { key: "soundscape_component", label: "Soundscape", type: "text", sortable: true, filterable: true, width: 140 },
    { key: "sound_type", label: "Sound Type", type: "text", sortable: true, filterable: true, width: 140 },
    { key: "taxon_name", label: "Taxon", type: "number", sortable: true, filterable: true, width: 120 },
    { key: "uncertain", label: "Uncertain", type: "boolean", sortable: true, filterable: true, filterOptions: ["true", "false"], width: 120 },
    { key: "animal_sound_type", label: "Animal Sound", type: "select", sortable: true, filterable: true, filterSearch: true, width: 280 },
    { key: "confidence", label: "Confidence", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "sound_distance_m", label: "Distance (m)", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "distance_not_estimable", label: "Not Estimable", type: "badge", sortable: true, filterable: true, filterOptions: ["True", "False"], width: 140 },
    { key: "individual_num", label: "Indiv. Num", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "reference", label: "Reference", type: "badge", sortable: true, filterable: true, filterOptions: ["True", "False"], width: 120 },
    { key: "comments", label: "Comments", type: "text", sortable: true, filterable: true, width: 220 },
]

/** Photo annotations use object classification fields instead of audio soundscape fields. */
export const PHOTO_STUDIO_ANNOTATION_COLUMNS: ColumnDef[] = [
    { key: "annotation_id", label: "ID", type: "number", sortable: true, filterable: true, width: 150 },
    { key: "uuid", label: "UUID", type: "text", sortable: true, filterable: true, width: 320 },
    { key: "min_x", label: "Min X", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "max_x", label: "Max X", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "min_y", label: "Min Y", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "max_y", label: "Max Y", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 280 },
    { key: "object_type", label: "Object Type", type: "text", sortable: true, filterable: true, filterOptions: ["organism", "other"], width: 160 },
    { key: "creator_type", label: "Creator", type: "text", sortable: true, filterable: true, filterSearch: true, width: 140 },
    { key: "taxon_name", label: "Taxon", type: "text", sortable: true, filterable: true, width: 180 },
    { key: "uncertain", label: "Uncertain", type: "boolean", sortable: true, filterable: true, filterOptions: ["true", "false"], width: 120 },
    { key: "individual_num", label: "Indiv. Num", type: "number", sortable: true, filterable: true, filterType: "numberRange", width: 180 },
    { key: "reference", label: "Reference", type: "badge", sortable: true, filterable: true, filterOptions: ["True", "False"], width: 120 },
    { key: "comments", label: "Comments", type: "text", sortable: true, filterable: true, width: 220 },
]

export type StudioAnnotationRow = {
    annotation_id: number
    uuid: string
    min_x: number
    max_x: number
    min_y: number
    max_y: number
    sound_id: number | null
    object_type: "organism" | "other" | null
    creator_type: string
    soundscape_component: string
    sound_type: string
    taxon_id: number | null
    taxon_scientific_name: string
    taxon_common_name: string
    /** 学名优先的展示名，与列 key / 后端 taxon_name 参数对齐 */
    taxon_name: string
    uncertain: boolean | null
    animal_sound_type: string
    confidence: number | null
    sound_distance_m: number | null
    distance_not_estimable: boolean | null
    individual_num: number | null
    reference: boolean | null
    comments: string
    /** 后端在该标注上为当前用户返回了 task 摘要（AnnotationPublic.task） */
    hasTask: boolean
}

/**
 * 导航「仅任务」：与表格主题色 Task 徽章一致。当前用户已 review 的任务不再显示。
 */
export function annotationHasTaskTagForNav(a: AnnotationPublic, reviewerId: number | null): boolean {
    return annotationHasActiveAssignedTask(a, reviewerId)
}

export function annotationPublicToStudioRow(
    a: AnnotationPublic,
    reviewerId: number | null,
): StudioAnnotationRow {
    const hasTask = annotationHasActiveAssignedTask(a, reviewerId)
    return {
        annotation_id: a.annotation_id,
        uuid: String(a.uuid),
        min_x: a.min_x,
        max_x: a.max_x,
        min_y: a.min_y,
        max_y: a.max_y,
        sound_id: a.sound_id ?? null,
        object_type: a.object_type ?? null,
        creator_type: a.creator_type ?? "",
        soundscape_component: a.soundscape_component ?? "",
        sound_type: a.sound_type ?? "",
        taxon_id: a.taxon_id ?? null,
        taxon_scientific_name: a.taxon_scientific_name ?? "",
        taxon_common_name: a.taxon_common_name ?? "",
        taxon_name: a.taxon_scientific_name ?? a.taxon_common_name ?? "",
        uncertain: a.uncertain ?? null,
        animal_sound_type: a.animal_sound_type ?? "",
        confidence: a.confidence ?? null,
        sound_distance_m: a.sound_distance_m ?? null,
        distance_not_estimable: a.distance_not_estimable ?? null,
        individual_num: a.individual_num ?? null,
        reference: a.reference ?? null,
        comments: a.comments ?? "",
        hasTask,
    }
}

export function mergeStudioAnnotationQuery(
    mediaId: number,
    projectId: number | null,
    sortKey: string | null,
    sortDir: "asc" | "desc" | null,
    filters: Record<string, string>,
    viewportFilter?: {
        view_time_start: number
        view_time_end: number
        view_freq_min: number
        view_freq_max: number
    },
): AnnotationListParams {
    const params: AnnotationListParams = {
        media_id: mediaId,
        order_by: sortKey && sortDir ? sortKey : "annotation_id",
        order_dir: sortKey && sortDir ? sortDir : "asc",
    }
    if (projectId != null) {
        params.project_id = projectId
    }
    if (viewportFilter) {
        params.view_time_start = viewportFilter.view_time_start
        params.view_time_end = viewportFilter.view_time_end
        params.view_freq_min = viewportFilter.view_freq_min
        params.view_freq_max = viewportFilter.view_freq_max
    }
    for (const [k, raw] of Object.entries(filters)) {
        const v = String(raw ?? "").trim()
        if (v === "" || v === "all") continue
        if (k === "annotation_id") {
            const n = Number(v)
            if (Number.isFinite(n)) params.annotation_id = n
        } else if (k === "uncertain" || k === "reference" || k === "distance_not_estimable") {
            const lower = v.toLowerCase()
            if (lower === "true" || lower === "false") params[k] = lower === "true"
        } else {
            // 其余列 key 与后端筛选参数同名，直传（含区间列的 "min,max" 字符串）
            params[k] = v
        }
    }
    return params
}

/** 标注表布尔列：True/False 药丸标签（True 用主题色） */
export function annotationTableBoolBadge(
    v: boolean | null | undefined,
    opts?: { unknownAsFalse?: boolean },
): ReactNode {
    if (v === true) {
        return (
            <span className="studio-annot-bool-badge studio-annot-bool-badge--true">True</span>
        )
    }
    if (v === false || (opts?.unknownAsFalse && v == null)) {
        return (
            <span className="studio-annot-bool-badge studio-annot-bool-badge--false">False</span>
        )
    }
    return ""
}

/** 与 DataPageLayout badge 列一致（如 Projects public：True 绿 / False 红） */
export function dataModuleBoolBadge(
    v: boolean | null | undefined,
    opts?: { unknownAsFalse?: boolean },
): ReactNode {
    if (v === true) {
        return <span className="data-badge data-badge-success">True</span>
    }
    if (v === false || (opts?.unknownAsFalse && v == null)) {
        return <span className="data-badge data-badge-danger">False</span>
    }
    return ""
}

/** 编辑侧栏 Save 上方：来源徽章（与常见 creator_type 一致；无独立模型版本字段时用 V1.0 占位） */
export function annotationCreatorTypeBadgeLabel(creatorType: string | null | undefined): string {
    const raw = (creatorType ?? "user").trim()
    const t = raw.toLowerCase()
    const version = raw.match(/(?:^|[\s_-])v?(\d+(?:\.\d+){0,2})(?=$|[^\d.])/i)?.[1] ?? "1.0"
    const map: Record<string, string> = {
        auto_script: "AUTO SCRIPT",
        "auto-script": "AUTO SCRIPT",
        autoscript: "AUTO SCRIPT",
        birdnet: `BirdNET V${version}`,
        batdetect: `BatDetect V${version}`,
        batdetect2: `BatDetect V${version}`,
        insects: `Insects V${version}`,
        template_matching: "Template Matching",
        "template-matching": "Template Matching",
        templatematching: "Template Matching",
        user: "USER",
    }
    if (map[t]) return map[t]
    if (!t) return ""
    if (t.includes("birdnet")) return `BirdNET V${version}`
    if (t.includes("batdetect")) return `BatDetect V${version}`
    if (t.includes("insects")) return `Insects V${version}`
    if (t.includes("template") && t.includes("matching")) return "Template Matching"
    const compact = t.replace(/[^a-z0-9]+/gi, "").slice(0, 6)
    return `${(compact || t).toUpperCase()} V${version}`
}

/** CONF 徽章颜色档：低红 / 中橙 / 高绿（默认按 0–1；>1 且 ≤100 视为百分数） */
export function annotationConfidenceTier(confidence: number): "low" | "mid" | "high" {
    let c = Number(confidence)
    if (!Number.isFinite(c)) return "mid"
    if (c > 1 && c <= 100) c = c / 100
    c = Math.min(1, Math.max(0, c))
    if (c >= 0.75) return "high"
    if (c >= 0.4) return "mid"
    return "low"
}

export function AutoFitBadgeText({ label }: { label: string }) {
    const outerRef = useRef<HTMLSpanElement | null>(null)
    const textRef = useRef<HTMLSpanElement | null>(null)
    const [scale, setScale] = useState(1)

    useLayoutEffect(() => {
        const outer = outerRef.current
        const text = textRef.current
        if (!outer || !text) return

        const measure = () => {
            const style = window.getComputedStyle(outer)
            const horizontalPadding =
                (Number.parseFloat(style.paddingLeft) || 0) +
                (Number.parseFloat(style.paddingRight) || 0)
            const available = Math.max(0, outer.clientWidth - horizontalPadding)
            const natural = text.scrollWidth
            const nextScale = available > 0 && natural > available ? Math.max(0.55, available / natural) : 1
            setScale((current) => (Math.abs(current - nextScale) > 0.01 ? nextScale : current))
        }

        measure()
        const resizeObserver = new ResizeObserver(measure)
        resizeObserver.observe(outer)
        resizeObserver.observe(text)
        return () => resizeObserver.disconnect()
    }, [label])

    return (
        <span
            ref={outerRef}
            className="studio-annot-meta-badge studio-annot-meta-badge--source"
            title={label}
        >
            <span
                ref={textRef}
                className="studio-annot-meta-badge-fit-text"
                style={{ transform: `scaleX(${scale})` }}
            >
                {label}
            </span>
        </span>
    )
}

/** 与 seed `annotation_review_status` 一致：1 Accepted, 2 Corrected, 3 Rejected, 4 Uncertain */
export const REVIEW_STATUS_IDS = {
    accepted: 1,
    corrected: 2,
    rejected: 3,
    uncertain: 4,
} as const

export function reviewStatusRequiresTaxon(statusId: number): boolean {
    return statusId === REVIEW_STATUS_IDS.corrected
}

/** Accept / Reject / Uncertain 下不要求填写物种，Taxon 禁用 */
export function reviewStatusDisablesTaxon(statusId: number): boolean {
    return !reviewStatusRequiresTaxon(statusId)
}

export function normalizeAnnotationReviews(raw: unknown): AnnotationReviewRead[] {
    if (!Array.isArray(raw)) return []
    const out: AnnotationReviewRead[] = []
    for (const item of raw) {
        if (!item || typeof item !== "object") continue
        const r = item as Record<string, unknown>
        if (r.annotation_id == null || r.reviewer_id == null) continue
        out.push({
            annotation_id: Number(r.annotation_id),
            reviewer_id: Number(r.reviewer_id),
            annotation_review_status_id: Number(r.annotation_review_status_id ?? 0),
            taxon_id: r.taxon_id != null && r.taxon_id !== "" ? Number(r.taxon_id) : null,
            note: r.note != null ? String(r.note) : null,
            creation_date: String(r.creation_date ?? ""),
            reviewer_name: String(r.reviewer_name ?? ""),
            status_name: String(r.status_name ?? ""),
            taxon_name: r.taxon_name != null ? String(r.taxon_name) : null,
            media_name: r.media_name != null ? String(r.media_name) : null,
        })
    }
    return out
}

/** 详情/列表字段不一致时解析标注 ID（annotation_id / id 等） */
export function pickAnnotationIdFromPublic(a: AnnotationPublic | null | undefined): number | null {
    if (a == null) return null
    const r = a as unknown as Record<string, unknown>
    const candidates: unknown[] = [a.annotation_id, r.id, r.annotationId]
    for (const c of candidates) {
        if (c == null || c === "") continue
        const n = typeof c === "number" ? c : Number(String(c).trim())
        if (Number.isFinite(n) && n > 0) return Math.trunc(n)
    }
    return null
}

export async function copyTextToClipboard(text: string): Promise<void> {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text)
            return
        } catch {
            // Fall through to the legacy selection copy below.
        }
    }

    const textarea = document.createElement("textarea")
    textarea.value = text
    textarea.setAttribute("readonly", "")
    textarea.style.position = "fixed"
    textarea.style.top = "-1000px"
    textarea.style.left = "-1000px"
    textarea.style.opacity = "0"
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    textarea.setSelectionRange(0, text.length)

    try {
        const copied = document.execCommand("copy")
        if (!copied) throw new Error("Fallback copy failed")
    } finally {
        document.body.removeChild(textarea)
    }
}

export function setAnnotationShareParam(url: URL, key: string, value: unknown): void {
    if (value == null || value === "") return
    if (typeof value === "number") {
        if (!Number.isFinite(value)) return
        url.searchParams.set(key, String(Number(value.toFixed(4))))
        return
    }
    const text = String(value).trim()
    if (text) url.searchParams.set(key, text)
}

export function reviewStatusVisualKey(statusName: string): "accept" | "revise" | "reject" | "uncertain" {
    const s = statusName.toLowerCase()
    if (s.includes("accept")) return "accept"
    if (s.includes("correct") || s.includes("revis")) return "revise"
    if (s.includes("reject")) return "reject"
    return "uncertain"
}

export function formatReviewDateDisplay(iso: string): string {
    if (!iso) return ""
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso.trim() || ""
    const pad = (n: number) => String(n).padStart(2, "0")
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function formatReviewDateOnlyDisplay(iso: string): string {
    if (!iso) return ""
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso.trim().split(/\s+/)[0] || ""
    const pad = (n: number) => String(n).padStart(2, "0")
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function pickRecordingDetailSpectrogramUrl(d: RecordingDetail): string | undefined {
    if (typeof d.spectrogram === "string" && d.spectrogram.trim()) {
        return d.spectrogram
    }
    const previews = Array.isArray(d.previews) ? d.previews : []
    const spectrogramPreview = previews.find((preview) => {
        const type = typeof preview?.type === "string" ? preview.type.trim().toLowerCase() : ""
        return type === "spectrogram" && typeof preview.url === "string" && preview.url.trim()
    })
    if (spectrogramPreview?.url) {
        return spectrogramPreview.url
    }
    const firstPreview = previews.find(
        (preview) => typeof preview?.url === "string" && preview.url.trim(),
    )
    return firstPreview?.url
}

export function normalizeRecordingDetail(d: RecordingDetail): RecordingDetail {
    const as = d.audio_setting || {}
    const rawCh = as.channel_num != null ? as.channel_num : d.channels
    const channelsNorm =
        rawCh === null || rawCh === undefined || rawCh === "" ? undefined : String(rawCh)
    return {
        ...d,
        id: d.media_id ?? d.id,
        duration_s: as.duration_s ?? d.duration_s,
        sampling_rate_hz: as.sampling_rate_hz ?? d.sampling_rate_hz,
        bit_depth: as.bit_depth != null ? String(as.bit_depth) : d.bit_depth,
        gain: as.recording_gain_db != null ? `${as.recording_gain_db} dB` : d.gain,
        channels: channelsNorm,
        spectrogram: pickRecordingDetailSpectrogramUrl(d),
    }
}

export function resolveSpectrogramRequestSize(
    measuredWidth: number,
    measuredHeight: number,
): { width: number; height: number } | null {
    const width = Math.round(measuredWidth)
    const height = Math.round(measuredHeight)
    if (!(width > 0) || !(height > 0)) return null
    return { width, height }
}

export function spectrogramRequestParamsKey(viewport: MediaViewportParams): string {
    return viewportParamsKey(viewport)
}

export function pickRecordingDetailId(detail: RecordingDetail | null | undefined): number | null {
    if (detail == null) return null
    const candidates: unknown[] = [detail.media_id, detail.id]
    for (const c of candidates) {
        if (c == null || c === "") continue
        const n = typeof c === "number" ? c : Number(String(c).trim())
        if (Number.isFinite(n) && n > 0) return Math.trunc(n)
    }
    return null
}

export function trimThemeValue(value: unknown): string | null {
    if (typeof value !== "string") return null
    const next = value.trim()
    return next !== "" ? next : null
}

export function resolveDetailThemeValue(detail: RecordingDetail | null): string | null | undefined {
    if (!detail) return undefined

    const record = detail as Record<string, unknown>
    if (Object.prototype.hasOwnProperty.call(record, "theme_value")) {
        return trimThemeValue(record.theme_value)
    }

    return (
        trimThemeValue(record.site_realm_name) ??
        trimThemeValue(record.realm_name) ??
        trimThemeValue(record.sphere)
    )
}

/** 与后端标注一致：min_x/max_x 为秒，min_y/max_y 为 Hz；声谱图 y 轴自下而上 0 → Nyquist */
export type AnnotationPhysBox = {
    min_x: number
    max_x: number
    min_y: number
    max_y: number
}

export type PixelRect = {
    left: number
    top: number
    width: number
    height: number
}

export type DraftResizeHandle = "n" | "s" | "e" | "w" | "nw" | "ne" | "sw" | "se"

export const DRAFT_RESIZE_HANDLES: Array<{
    handle: DraftResizeHandle
    className: string
}> = [
    { handle: "nw", className: "media-selection-handle--nw" },
    { handle: "n", className: "media-selection-handle--n" },
    { handle: "ne", className: "media-selection-handle--ne" },
    { handle: "w", className: "media-selection-handle--w" },
    { handle: "e", className: "media-selection-handle--e" },
    { handle: "sw", className: "media-selection-handle--sw" },
    { handle: "s", className: "media-selection-handle--s" },
    { handle: "se", className: "media-selection-handle--se" },
]

export function normalizeDraftPixelRect(
    rect: PixelRect,
    viewportW: number,
    viewportH: number,
    minSizePx = SPECTROGRAM_DRAFT_MIN_SIZE_PX,
): PixelRect {
    const minW = Math.min(Math.max(1, minSizePx), Math.max(1, viewportW))
    const minH = Math.min(Math.max(1, minSizePx), Math.max(1, viewportH))
    const width = clamp(Math.max(rect.width, minW), minW, Math.max(minW, viewportW))
    const height = clamp(Math.max(rect.height, minH), minH, Math.max(minH, viewportH))
    const left = clamp(rect.left - (width - rect.width) / 2, 0, Math.max(0, viewportW - width))
    const top = clamp(rect.top - (height - rect.height) / 2, 0, Math.max(0, viewportH - height))
    const snappedLeft = Math.round(left)
    const snappedTop = Math.round(top)
    return {
        left: snappedLeft,
        top: snappedTop,
        width: Math.max(1, Math.round(left + width) - snappedLeft),
        height: Math.max(1, Math.round(top + height) - snappedTop),
    }
}

export function resizeDraftPixelRectFromHandle(
    startRect: PixelRect,
    handle: DraftResizeHandle,
    dx: number,
    dy: number,
    viewportW: number,
    viewportH: number,
    minSizePx = SPECTROGRAM_DRAFT_MIN_SIZE_PX,
): PixelRect {
    const startLeft = startRect.left
    const startTop = startRect.top
    const startWidth = Math.max(startRect.width, minSizePx)
    const startHeight = Math.max(startRect.height, minSizePx)
    const startRight = startLeft + startWidth
    const startBottom = startTop + startHeight

    if (handle === "n" || handle === "s" || handle === "e" || handle === "w") {
        let left = startLeft
        let top = startTop
        let right = startRight
        let bottom = startBottom
        if (handle === "n") {
            top = clamp(startTop + dy, 0, startBottom - minSizePx)
        } else if (handle === "s") {
            bottom = clamp(startBottom + dy, startTop + minSizePx, viewportH)
        } else if (handle === "w") {
            left = clamp(startLeft + dx, 0, startRight - minSizePx)
        } else if (handle === "e") {
            right = clamp(startRight + dx, startLeft + minSizePx, viewportW)
        }
        return {
            left,
            top,
            width: Math.max(minSizePx, right - left),
            height: Math.max(minSizePx, bottom - top),
        }
    }

    const scaleX =
        handle === "nw" || handle === "sw"
            ? (startWidth - dx) / startWidth
            : (startWidth + dx) / startWidth
    const scaleY =
        handle === "nw" || handle === "ne"
            ? (startHeight - dy) / startHeight
            : (startHeight + dy) / startHeight
    const dominantScale =
        Math.abs(scaleX - 1) >= Math.abs(scaleY - 1) ? scaleX : scaleY
    const minScale = Math.max(minSizePx / startWidth, minSizePx / startHeight)

    let maxScale = Number.POSITIVE_INFINITY
    if (handle === "nw") {
        maxScale = Math.min(startRight / startWidth, startBottom / startHeight)
    } else if (handle === "ne") {
        maxScale = Math.min((viewportW - startLeft) / startWidth, startBottom / startHeight)
    } else if (handle === "sw") {
        maxScale = Math.min(startRight / startWidth, (viewportH - startTop) / startHeight)
    } else if (handle === "se") {
        maxScale = Math.min((viewportW - startLeft) / startWidth, (viewportH - startTop) / startHeight)
    }

    const scale = clamp(dominantScale, minScale, maxScale)
    const width = startWidth * scale
    const height = startHeight * scale

    if (handle === "nw") {
        return { left: startRight - width, top: startBottom - height, width, height }
    }
    if (handle === "ne") {
        return { left: startLeft, top: startBottom - height, width, height }
    }
    if (handle === "sw") {
        return { left: startRight - width, top: startTop, width, height }
    }
    return { left: startLeft, top: startTop, width, height }
}

/** 按可见时间窗/频率窗映射到像素 */
export function physToPixelsWindow(
    p: AnnotationPhysBox,
    w: number,
    h: number,
    viewStart: number,
    windowSec: number,
    freqMinHz: number,
    freqMaxHz: number,
) {
    const win = windowSec > 0 ? windowSec : 1
    const left = ((p.min_x - viewStart) / win) * w
    const width = Math.max(0, ((p.max_x - p.min_x) / win) * w)
    const f0 = Number.isFinite(freqMinHz) ? freqMinHz : 0
    const f1 = Number.isFinite(freqMaxHz) ? freqMaxHz : f0
    const denom = Math.max(1e-6, f1 - f0)
    const top = (1 - (p.max_y - f0) / denom) * h
    const height = Math.max(0, ((p.max_y - p.min_y) / denom) * h)
    return { left, top, width, height }
}

export function pixelsToPhysWindow(
    x0: number,
    y0: number,
    x1: number,
    y1: number,
    w: number,
    h: number,
    viewStart: number,
    windowSec: number,
    freqMinHz: number,
    freqMaxHz: number,
): AnnotationPhysBox {
    const win = windowSec > 0 ? windowSec : 1
    const c = (v: number, max: number) => Math.max(0, Math.min(max, v))
    const ax0 = c(x0, w)
    const ax1 = c(x1, w)
    const ay0 = c(y0, h)
    const ay1 = c(y1, h)
    const t1 = viewStart + (ax0 / w) * win
    const t2 = viewStart + (ax1 / w) * win
    const min_x = Math.min(t1, t2)
    const max_x = Math.max(t1, t2)
    const f0 = Number.isFinite(freqMinHz) ? freqMinHz : 0
    const f1 = Number.isFinite(freqMaxHz) ? freqMaxHz : f0
    const denom = Math.max(1e-6, f1 - f0)
    const fTop = f0 + (1 - ay0 / h) * denom
    const fBottom = f0 + (1 - ay1 / h) * denom
    const min_y = Math.min(fTop, fBottom)
    const max_y = Math.max(fTop, fBottom)
    return { min_x, max_x, min_y, max_y }
}

export function normalizeAnnotationOverlayRect(
    rect: { left: number; top: number; width: number; height: number },
    viewportW: number,
    viewportH: number,
    minSizePx = SPECTROGRAM_ANNOTATION_MIN_VISIBLE_PX,
) {
    const width = Math.max(0, rect.width)
    const height = Math.max(0, rect.height)
    const visibleWidth = width > 0 && width < minSizePx ? minSizePx : width
    const visibleHeight = height > 0 && height < minSizePx ? minSizePx : height
    const left = clamp(rect.left - (visibleWidth - width) / 2, -visibleWidth, viewportW)
    const top = clamp(rect.top - (visibleHeight - height) / 2, -visibleHeight, viewportH)
    const snappedLeft = Math.round(left)
    const snappedTop = Math.round(top)
    return {
        left: snappedLeft,
        top: snappedTop,
        width: Math.max(1, Math.round(left + visibleWidth) - snappedLeft),
        height: Math.max(1, Math.round(top + visibleHeight) - snappedTop),
    }
}

export interface MediaDetailViewProps {
    mediaId: number
}

export const SPEC_ZOOM_COOKIE_KEY = "ecoSignal_spec_zoom_percent"
export const SPEC_ZOOM_DRAFT_IN_COOKIE_KEY = "ecoSignal_spec_zoom_percent_draft_in"
export const SPEC_ZOOM_DRAFT_OUT_COOKIE_KEY = "ecoSignal_spec_zoom_percent_draft_out"
export const SPEC_PXS_COOKIE_KEY = "ecoSignal_spec_px_per_sec"
export const DEFAULT_SPECTROGRAM_PX_PER_SEC = 15
export const ANNOT_SAVE_MODE_COOKIE_KEY = "ecoSignal_annot_save_mode"

export function parseSpectrogramZoomPercent(raw: string | null | undefined, fallback: number): number {
    const n = raw != null ? Number(raw) : NaN
    return Number.isFinite(n) ? clamp(Math.round(n * 1e4) / 1e4, 0, 100) : fallback
}

export function storeSpectrogramZoomPercentCookie(zp: number) {
    setCookieValue(SPEC_ZOOM_COOKIE_KEY, formatDisplayNumber(clamp(zp, 0, 100), 4))
}

export type AnnotationSaveMode = "save" | "save_close" | "save_next" | "save_prev"

export const ANNOTATION_SAVE_MODES: AnnotationSaveMode[] = ["save", "save_close", "save_next", "save_prev"]

export const ANNOTATION_SAVE_MODE_LABELS: Record<AnnotationSaveMode, string> = {
    save: "Save only",
    save_close: "Save & close",
    save_next: "Save & next",
    save_prev: "Save & previous",
}

export const ANNOTATION_SAVE_MODE_MENU_ITEMS: MenuProps["items"] = ANNOTATION_SAVE_MODES.map((mode) => ({
    key: mode,
    label: ANNOTATION_SAVE_MODE_LABELS[mode],
}))

export function parseAnnotationSaveModeCookie(raw: string | null): AnnotationSaveMode {
    if (raw != null && ANNOTATION_SAVE_MODES.includes(raw as AnnotationSaveMode)) {
        return raw as AnnotationSaveMode
    }
    return "save_close"
}

/** 新建保存后从全量列表中解析刚创建的 annotation_id（创建接口不返回 id） */
export function pickMatchingAnnotationIdFromList(
    items: AnnotationPublic[],
    soundId: number,
    physMinX: number,
    physMaxX: number,
    physMinY: number,
    physMaxY: number,
): number | null {
    const tolT = 0.06
    const tolY = 1
    let best: number | null = null
    for (const a of items) {
        if (Number(a.sound_id ?? 0) !== Number(soundId)) continue
        const ax0 = Math.min(a.min_x, a.max_x)
        const ax1 = Math.max(a.min_x, a.max_x)
        const ay0 = Math.min(a.min_y, a.max_y)
        const ay1 = Math.max(a.min_y, a.max_y)
        if (Math.abs(ax0 - physMinX) > tolT || Math.abs(ax1 - physMaxX) > tolT) continue
        if (Math.abs(ay0 - physMinY) > tolY || Math.abs(ay1 - physMaxY) > tolY) continue
        const id = a.annotation_id
        best = best == null || id > best ? id : best
    }
    return best
}

export function getCookieValue(name: string): string | null {
    if (typeof document === "undefined") return null
    if (!isFunctionalCookiesAllowed()) return null
    const prefix = `${encodeURIComponent(name)}=`
    const parts = document.cookie ? document.cookie.split("; ") : []
    for (const p of parts) {
        if (p.startsWith(prefix)) {
            return decodeURIComponent(p.slice(prefix.length))
        }
    }
    return null
}

export function setCookieValue(name: string, value: string, days = COOKIE_RETENTION_DAYS): void {
    if (typeof document === "undefined") return
    if (!isFunctionalCookiesAllowed()) return
    const d = new Date()
    d.setTime(d.getTime() + days * 24 * 60 * 60 * 1000)
    document.cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; expires=${d.toUTCString()}; path=/; samesite=lax`
}
