import { Button as ESButton } from "@/components/ui"
/**
 * TimelineTab - 项目媒体时间线（站点 × 时间 Gantt 风格）
 *
 * 数据: GET /v1/media-timeline-items
 * time_range 为绝对边界；可视窗口可滚轮缩放。ats-bar 与时间刻度均按 (t−vMin)/(vMax−vMin) 百分比定位，保证对齐。
 */

import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
    type CSSProperties,
} from "react"
import { useNavigate } from "react-router-dom"
import { CalendarRange, ChevronRight, ChevronLeft, Maximize } from "lucide-react"
import { CustomScrollArea } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { useProjectStore } from "../../stores/useProjectStore"
import { getRealmTheme, getRealmAccentVars } from "../../sphereTheme"
import {
    collectionsApi,
    type CollectionTimelineItem,
    type CollectionTimelineResponse,
} from "../../../../api/endpoints/collections"
import { MediaTypeSegment } from "./MediaTypeSegment"
import { mediaTypeFilterParam, type MediaTypeFilter } from "./mediaTypeFilter"

const ROW_COLLAPSED_PX = 40
const BAR_HEIGHT = 22
const BAR_GAP = 4
const SIDEBAR_W = 200
const VIRTUAL_ROW_OVERSCAN = 8
const DETAIL_DEBOUNCE_MS = 250
const WHEEL_ZOOM_STEP = 1.14
const MIN_VIEW_SPAN_MS = 60_000
const TIMELINE_EDGE_PADDING_RATIO = 0.25
const MS = 1
const SECOND = 1000 * MS
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
/** Calendar-year approximation for axis tick spacing (matches existing 365-day step in pickTickStep). */
const YEAR_MS = 365 * DAY
function parsePositiveFinite(raw: unknown): number | null {
    const value = typeof raw === "number" ? raw : Number(raw)
    return Number.isFinite(value) && value > 0 ? value : null
}

function buildMetadataBarStyle(
    item: CollectionTimelineItem,
    barWidthPx: number,
    fillColor: string,
    borderColor: string,
): Pick<CSSProperties, "backgroundColor" | "backgroundImage" | "borderColor"> {
    const dutyCyclePeriod = parsePositiveFinite(item.duty_cycle_period)
    const dutyCycleRecording = parsePositiveFinite(item.duty_cycle_recording)

    const baseStyle: Pick<CSSProperties, "backgroundColor" | "borderColor"> = {
        backgroundColor: fillColor,
        borderColor,
    }

    if (!dutyCyclePeriod || !dutyCycleRecording || !(barWidthPx > 0)) {
        return baseStyle
    }

    const activeRatio = dutyCycleRecording / dutyCyclePeriod
    if (!(activeRatio > 0)) return baseStyle
    if (activeRatio >= 1) {
        return {
            backgroundColor: fillColor,
            borderColor,
        }
    }

    const segmentCount = 10
    const segmentWidthPx = Math.max(barWidthPx / segmentCount, 1)
    const activeWidthPx = Math.max(segmentWidthPx * activeRatio, 1)

    return {
        backgroundColor: "var(--bg-surface)",
        borderColor,
        backgroundImage: `repeating-linear-gradient(to right, ${fillColor} 0px, ${fillColor} ${activeWidthPx}px, var(--bg-surface) ${activeWidthPx}px, var(--bg-surface) ${segmentWidthPx}px)`,
    }
}

function parseTimelineDate(s: string): number {
    const normalized = s.includes("T") ? s : s.replace(" ", "T")
    const t = new Date(normalized).getTime()
    return Number.isNaN(t) ? NaN : t
}

function formatTimelineParam(ms: number): string {
    const d = new Date(ms)
    const pad = (n: number) => String(n).padStart(2, "0")
    return [
        d.getFullYear(),
        pad(d.getMonth() + 1),
        pad(d.getDate()),
    ].join("-") + ` ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function timelineSiteKey(it: CollectionTimelineItem): string {
    return it.site_key ?? (it.site_id != null ? `site:${it.site_id}` : "nogeo")
}

function pickTickStep(spanMs: number, maxTicks = 11): number {
    const raw = spanMs / maxTicks
    const candidates = [
        15 * SECOND,
        30 * SECOND,
        1 * MINUTE,
        2 * MINUTE,
        5 * MINUTE,
        10 * MINUTE,
        15 * MINUTE,
        30 * MINUTE,
        1 * HOUR,
        2 * HOUR,
        3 * HOUR,
        6 * HOUR,
        12 * HOUR,
        1 * DAY,
        2 * DAY,
        3 * DAY,
        7 * DAY,
        14 * DAY,
        30 * DAY,
        90 * DAY,
        YEAR_MS,
        2 * YEAR_MS,
        5 * YEAR_MS,
        10 * YEAR_MS,
        25 * YEAR_MS,
        50 * YEAR_MS,
        100 * YEAR_MS,
    ]
    for (const c of candidates) {
        if (c >= raw) return c
    }
    // Spans longer than ~1100 years: double until step covers target density
    let step = candidates[candidates.length - 1]!
    while (step < raw) step *= 2
    return step
}

function formatAxisLabel(t: number, stepMs: number): string {
    const d = new Date(t)
    const Y = d.getFullYear()
    const M = String(d.getMonth() + 1).padStart(2, "0")
    const D = String(d.getDate()).padStart(2, "0")
    const h = String(d.getHours()).padStart(2, "0")
    const m = String(d.getMinutes()).padStart(2, "0")
    const s = String(d.getSeconds()).padStart(2, "0")

    const dateStr = `${M}-${D}`
    const fullDate = `${Y}-${M}-${D}`

    // Multi-year ticks: show year only so labels stay readable at wide spans (e.g. 1970–2025).
    if (stepMs >= 2 * YEAR_MS) {
        return String(Y)
    }

    if (stepMs < MINUTE) {
        return `${dateStr} ${h}:${m}:${s}`
    }
    if (stepMs < DAY) {
        return `${dateStr} ${h}:${m}`
    }
    if (stepMs < 120 * DAY) {
        return fullDate
    }
    return `${Y}-${M}`
}

/** 自适应主刻度（短区间不再出现「季度刻度为空」；跨年区间按日历年对齐） */
function buildAdaptiveTicks(tMin: number, tMax: number): { pct: number; label: string }[] {
    const span = tMax - tMin
    if (span <= 0) return []
    const step = pickTickStep(span, 11)
    const out: { t: number; label: string }[] = []

    if (step >= YEAR_MS) {
        const yearStep = Math.max(1, Math.round(step / YEAR_MS))
        const startYear = new Date(tMin).getFullYear()
        const endYear = new Date(tMax).getFullYear()
        let y = Math.floor(startYear / yearStep) * yearStep
        if (y < startYear) y += yearStep
        for (; y <= endYear + yearStep; y += yearStep) {
            const t = new Date(y, 0, 1).getTime()
            if (t >= tMin - step * 0.001 && t <= tMax + step * 0.001) {
                out.push({ t, label: formatAxisLabel(t, step) })
            }
        }
    } else {
        let t = Math.ceil(tMin / step) * step
        let guard = 0
        while (t <= tMax + step * 0.0001 && guard++ < 600) {
            out.push({ t, label: formatAxisLabel(t, step) })
            t += step
        }
    }

    if (out.length === 0) {
        out.push({ t: tMin, label: formatAxisLabel(tMin, step) })
        if (tMax > tMin) out.push({ t: tMax, label: formatAxisLabel(tMax, step) })
    }
    return out.map((x) => ({ pct: ((x.t - tMin) / span) * 100, label: x.label }))
}

type SiteBucket = {
    key: string
    tAnchor: number
    count: number
    items: CollectionTimelineItem[]
    metaOnly: boolean
    realm?: string | null
}

function bucketItemsForSite(
    items: CollectionTimelineItem[],
    vMin: number,
    vSpan: number,
    chartTrackPx: number
): SiteBucket[] {
    if (chartTrackPx <= 0) return []
    const thresholdMs = (24 / chartTrackPx) * vSpan

    const sorted = [...items].sort((a, b) => parseTimelineDate(a.start_date) - parseTimelineDate(b.start_date))

    const buckets: SiteBucket[] = []
    for (const it of sorted) {
        const itemCount = it.item_count ?? 1
        const start = parseTimelineDate(it.start_date)
        const end = parseTimelineDate(it.end_date)
        const t = Number.isNaN(start) ? NaN : start
        if (Number.isNaN(t)) continue

        if (t > vMin + vSpan) break
        if ((Number.isNaN(end) ? t : end) < vMin) continue

        const lastB = buckets[buckets.length - 1]
        if (!lastB || (t - lastB.tAnchor) > thresholdMs) {
            buckets.push({
                key: `b-${t}-${it.media_id}`,
                tAnchor: t,
                count: itemCount,
                items: [it],
                metaOnly: it.is_metadata,
                realm: it.realm,
            })
        } else {
            lastB.items.push(it)
            lastB.count += itemCount
            if (!it.is_metadata) lastB.metaOnly = false
        }
    }
    return buckets
}

function timelineItemsBounds(items: CollectionTimelineItem[]) {
    let min = Infinity
    let max = -Infinity
    for (const it of items) {
        const start = parseTimelineDate(it.start_date)
        if (Number.isNaN(start)) continue
        const rawEnd = parseTimelineDate(it.end_date)
        const end = Number.isNaN(rawEnd) ? start : Math.max(start, rawEnd)
        min = Math.min(min, start)
        max = Math.max(max, end)
    }
    if (min === Infinity || max === -Infinity) return null
    return { min, max, span: Math.max(max - min, 1) }
}

function buildCenteredTimeWindow(
    rangeMin: number,
    rangeMax: number,
    paddingRatio = 0.12,
    minPaddingMs = 30 * SECOND,
) {
    if (!Number.isFinite(rangeMin) || !Number.isFinite(rangeMax)) return null
    const safeMin = Math.min(rangeMin, rangeMax)
    const safeMax = Math.max(rangeMin, rangeMax)
    const duration = safeMax - safeMin
    const padding = Math.max(duration * paddingRatio, minPaddingMs)
    return {
        start: safeMin - padding,
        end: safeMax + padding,
    }
}

function buildWindowFromResponseRange(
    timeRange: CollectionTimelineResponse["time_range"] | null | undefined,
    fallbackItems?: CollectionTimelineItem[],
) {
    const rangeMin = timeRange?.min ? parseTimelineDate(timeRange.min) : NaN
    const rangeMax = timeRange?.max ? parseTimelineDate(timeRange.max) : NaN
    if (!Number.isNaN(rangeMin) && !Number.isNaN(rangeMax) && rangeMax >= rangeMin) {
        return buildCenteredTimeWindow(rangeMin, rangeMax)
    }

    const bounds = fallbackItems?.length ? timelineItemsBounds(fallbackItems) : null
    if (bounds) {
        return buildCenteredTimeWindow(bounds.min, bounds.max)
    }
    return null
}

function TimelineAxis({ ticks }: { ticks: { pct: number; label: string }[] }) {
    return (
        <div className="ats-axis ats-axis--top">
            <div className="ats-axis-track">
                {ticks.map((tk, i) => (
                    <div key={i} className="ats-time-tick" style={{ left: `${tk.pct}%` }}>
                        <span className="ats-time-tick-line" />
                        <span className="ats-time-tick-label">{tk.label}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}

function VerticalGrid({ ticks }: { ticks: { pct: number }[] }) {
    return (
        <div className="ats-vgrid" aria-hidden>
            {ticks.map((tk, i) => (
                <div key={i} className="ats-vline" style={{ left: `${tk.pct}%` }} />
            ))}
        </div>
    )
}

export function TimelineTab() {
    const project = useProjectStore((s) => {
        if (!s.currentProjectId) return undefined
        return s.projects.find((p) => p.id === s.currentProjectId)
    })
    const collection = useProjectStore((s) => {
        if (!s.currentCollectionId) return undefined
        return s.collectionOptions.find((c) => c.id === s.currentCollectionId)
    })
    const navigate = useNavigate()

    const projectIdNum = project?.id != null ? Number(project.id) : NaN
    const collectionIdNum =
        collection?.id !== undefined && collection.id !== "" ? Number(collection.id) : NaN

    const [data, setData] = useState<CollectionTimelineResponse | null>(null)
    const [mediaTypeFilter, setMediaTypeFilter] = useState<MediaTypeFilter>("all")
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [activeSite, setActiveSite] = useState<string | null>(null)
    const [detailDataByKey, setDetailDataByKey] = useState<Map<string, CollectionTimelineResponse>>(new Map())
    const detailDataByKeyRef = useRef(detailDataByKey)
    detailDataByKeyRef.current = detailDataByKey
    const [detailLoadingKey, setDetailLoadingKey] = useState<string | null>(null)
    const [detailError, setDetailError] = useState<string | null>(null)
    const [scrollTop, setScrollTop] = useState(0)
    const [viewportHeight, setViewportHeight] = useState(0)
    const [detailScrollTop, setDetailScrollTop] = useState(0)
    const [renderPending, setRenderPending] = useState(false)
    const [expandPending, setExpandPending] = useState(false)
    /** null = 显示完整 time_range */
    const [viewWindow, setViewWindow] = useState<{ start: number; end: number } | null>(null)
    const scrollBodyRef = useRef<HTMLElement | null>(null)
    const expandedScrollAreaRef = useRef<HTMLDivElement | null>(null)
    const allowDetailAutoWindowRef = useRef(false)

    useEffect(() => {
        if (Number.isNaN(projectIdNum)) {
            setData(null)
            setError(null)
            setRenderPending(false)
            return
        }
        let cancelled = false
        const requestedActiveSite = activeSite
        const requestedDetailKey = requestedActiveSite
            ? `${requestedActiveSite}|${Number.isNaN(collectionIdNum) ? "all" : collectionIdNum}|${mediaTypeFilter}`
            : null
        setLoading(true)
        setError(null)
        setRenderPending(true)
        setDetailError(null)
        setDetailLoadingKey(requestedDetailKey)
        setExpandPending(Boolean(requestedActiveSite))
        if (requestedActiveSite) {
            // Re-fit the expanded site after the new media type is loaded.
            allowDetailAutoWindowRef.current = true
        }
            ; (async () => {
                try {
                    const params: Parameters<typeof collectionsApi.getTimeline>[0] = {
                        project_id: projectIdNum,
                        include_metadata: true,
                        response_mode: "overview",
                        order_dir: "asc",
                    }
                    if (!Number.isNaN(collectionIdNum)) {
                        params.collection_id = collectionIdNum
                    }
                    const mediaType = mediaTypeFilterParam(mediaTypeFilter)
                    if (mediaType) {
                        params.media_type = mediaType
                    }
                    const res = await collectionsApi.getTimeline(params, true)
                    if (cancelled) return
                    if (res.code !== 0 && res.code !== 200) {
                        setError(res.message || "Failed to load timeline")
                        setData(null)
                        return
                    }
                    const nextData = res.data ?? null
                    setData(nextData)
                    setDetailDataByKey(new Map())
                    if (
                        requestedActiveSite &&
                        !nextData?.items?.some((item) => timelineSiteKey(item) === requestedActiveSite)
                    ) {
                        setActiveSite(null)
                        setExpandPending(false)
                        setViewWindow(null)
                    }
                } catch (e: unknown) {
                    if (!cancelled) {
                        setError(e instanceof Error ? e.message : "Failed to load timeline")
                        setData(null)
                    }
                } finally {
                    if (!cancelled) setLoading(false)
                }
            })()
        return () => {
            cancelled = true
        }
    }, [projectIdNum, collectionIdNum, mediaTypeFilter])

    const { boundsMin, boundsMax, boundsSpan, dataMin, dataMax, dataSpan, siteOrder, bySite, siteNames } = useMemo(() => {
        const empty = {
            boundsMin: 0,
            boundsMax: 0,
            boundsSpan: 0,
            dataMin: 0,
            dataMax: 0,
            dataSpan: 0,
            siteOrder: [] as string[],
            bySite: new Map<string, CollectionTimelineItem[]>(),
            siteNames: new Map<string, string>(),
        }
        if (!data?.items?.length || !data.time_range?.min || !data.time_range?.max) {
            return empty
        }
        const t0_raw = parseTimelineDate(data.time_range.min)
        const t1_raw = parseTimelineDate(data.time_range.max)
        if (Number.isNaN(t0_raw) || Number.isNaN(t1_raw) || t1_raw <= t0_raw) {
            return empty
        }
        const rawSpan = t1_raw - t0_raw
        // Keep the initial viewport symmetric so dragging has the same room at both ends.
        const edgePadding = rawSpan * TIMELINE_EDGE_PADDING_RATIO
        const t0 = t0_raw - edgePadding
        const t1 = t1_raw + edgePadding

        const map = new Map<string, CollectionTimelineItem[]>()
        const names = new Map<string, string>()
        for (const it of data.items) {
            const key = timelineSiteKey(it)
            if (!map.has(key)) map.set(key, [])
            map.get(key)!.push(it)
            if (!names.has(key)) names.set(key, it.site_name?.trim() || "not geo-referenced")
        }
        for (const items of map.values()) {
            items.sort((a, b) => parseTimelineDate(a.start_date) - parseTimelineDate(b.start_date))
        }
        const order = Array.from(map.keys()).sort((a, b) => {
            const minA = parseTimelineDate(map.get(a)?.[0]?.start_date ?? "")
            const minB = parseTimelineDate(map.get(b)?.[0]?.start_date ?? "")
            return minA - minB
        })
        return {
            boundsMin: t0,
            boundsMax: t1,
            boundsSpan: t1 - t0,
            dataMin: t0_raw,
            dataMax: t1_raw,
            dataSpan: t1_raw - t0_raw,
            siteOrder: order,
            bySite: map,
            siteNames: names,
        }
    }, [data])

    useEffect(() => {
        setViewWindow(null)
        allowDetailAutoWindowRef.current = false
        setActiveSite(null)
        setDetailDataByKey(new Map())
        setDetailLoadingKey(null)
        setDetailError(null)
        setExpandPending(false)
        setScrollTop(0)
        setDetailScrollTop(0)
    }, [projectIdNum, collectionIdNum])

    useEffect(() => {
        if (loading) return
        if (error || !data?.items?.length) {
            setRenderPending(false)
            return
        }

        let raf1 = 0
        let raf2 = 0
        raf1 = window.requestAnimationFrame(() => {
            raf2 = window.requestAnimationFrame(() => {
                setRenderPending(false)
            })
        })

        return () => {
            window.cancelAnimationFrame(raf1)
            window.cancelAnimationFrame(raf2)
        }
    }, [loading, error, data])

    const vMin = viewWindow?.start ?? boundsMin
    const vMax = viewWindow?.end ?? boundsMax
    const vSpan = Math.max(vMax - vMin, 1)
    /** One detail payload per site; do not refetch on scroll/zoom (client filters by vMin/vMax). */
    const detailSiteKey = activeSite
        ? `${activeSite}|${Number.isNaN(collectionIdNum) ? "all" : collectionIdNum}|${mediaTypeFilter}`
        : null

    useEffect(() => {
        if (Number.isNaN(projectIdNum) || !activeSite || !detailSiteKey || boundsSpan <= 0) {
            return
        }
        if (detailDataByKeyRef.current.has(detailSiteKey)) return

        let cancelled = false
        const timer = window.setTimeout(async () => {
            if (detailDataByKeyRef.current.has(detailSiteKey)) return
            setDetailLoadingKey(detailSiteKey)
            setDetailError(null)

            const overviewItems = bySite.get(activeSite) ?? []
            let rangeMin = Infinity
            let rangeMax = -Infinity
            for (const it of overviewItems) {
                const s = parseTimelineDate(it.start_date)
                const e = parseTimelineDate(it.end_date)
                const t1 = Number.isNaN(e) ? s : Math.max(s, e)
                if (!Number.isNaN(s)) {
                    rangeMin = Math.min(rangeMin, s)
                    rangeMax = Math.max(rangeMax, t1)
                }
            }
            if (rangeMin === Infinity) {
                rangeMin = boundsMin
                rangeMax = boundsMax
            } else {
                const detailWindow = buildCenteredTimeWindow(rangeMin, rangeMax, 0.12, 120 * SECOND)
                if (detailWindow) {
                    rangeMin = detailWindow.start
                    rangeMax = detailWindow.end
                }
            }

            try {
                const params: Parameters<typeof collectionsApi.getTimeline>[0] = {
                    project_id: projectIdNum,
                    include_metadata: true,
                    response_mode: "detail",
                    site_key: activeSite,
                    start_date: formatTimelineParam(rangeMin),
                    end_date: formatTimelineParam(rangeMax),
                }
                if (!Number.isNaN(collectionIdNum)) {
                    params.collection_id = collectionIdNum
                }
                const mediaType = mediaTypeFilterParam(mediaTypeFilter)
                if (mediaType) {
                    params.media_type = mediaType
                }
                const res = await collectionsApi.getTimeline(params, true)
                if (cancelled) return
                if (res.code !== 0 && res.code !== 200) {
                    setDetailError(res.message || "Failed to load timeline detail")
                    return
                }
                const responseData =
                    res.data ?? { project_id: projectIdNum, items: [], time_range: { min: null, max: null } }
                const responseWindow = buildWindowFromResponseRange(
                    responseData.time_range,
                    responseData.items,
                )
                if (responseWindow && allowDetailAutoWindowRef.current) {
                    setViewWindow(responseWindow)
                }
                allowDetailAutoWindowRef.current = false
                setDetailDataByKey((prev) => {
                    const next = new Map(prev)
                    next.set(detailSiteKey, responseData)
                    return next
                })
            } catch (e: unknown) {
                if (!cancelled) {
                    setDetailError(e instanceof Error ? e.message : "Failed to load timeline detail")
                }
            } finally {
                if (!cancelled) setDetailLoadingKey(null)
            }
        }, DETAIL_DEBOUNCE_MS)

        return () => {
            cancelled = true
            window.clearTimeout(timer)
        }
    }, [activeSite, boundsMax, boundsMin, boundsSpan, bySite, collectionIdNum, detailSiteKey, mediaTypeFilter, projectIdNum, siteNames])

    const headerChartRef = useRef<HTMLDivElement>(null)
    const [chartTrackPx, setChartTrackPx] = useState(0)

    const timelineGridReady =
        !loading && !error && Boolean(data?.items?.length) && boundsSpan > 0

    const wheelZoomRef = useRef({
        vMin,
        vMax,
        vSpan,
        chartTrackPx,
        boundsMin,
        boundsMax,
        boundsSpan,
        dataMin,
        dataMax,
        dataSpan,
    })
    wheelZoomRef.current = {
        vMin,
        vMax,
        vSpan,
        chartTrackPx,
        boundsMin,
        boundsMax,
        boundsSpan,
        dataMin,
        dataMax,
        dataSpan,
    }

    useLayoutEffect(() => {
        const el = headerChartRef.current
        if (!el || !timelineGridReady) {
            setChartTrackPx(0)
            return
        }
        const measure = () => setChartTrackPx(el.getBoundingClientRect().width)
        measure()
        const ro = new ResizeObserver(measure)
        ro.observe(el)
        return () => ro.disconnect()
    }, [timelineGridReady])

    useEffect(() => {
        // Bind interactions to the main scroll body (avoid nested row scroll areas).
        const root = headerChartRef.current?.closest(".acoustic-timeline-body") as HTMLElement | null
        const chartArea =
            (root?.querySelector(".ats-main-scroll-body") as HTMLElement | null) ??
            (headerChartRef.current?.closest(".custom-scroll-area__body") as HTMLElement | null) ??
            (headerChartRef.current?.closest(".custom-scroll-area") as HTMLElement | null)
        if (!chartArea || !timelineGridReady) return
        scrollBodyRef.current = chartArea
        const updateScrollMetrics = () => {
            setScrollTop(chartArea.scrollTop)
            setViewportHeight(chartArea.clientHeight)
        }
        updateScrollMetrics()
        const ro = new ResizeObserver(updateScrollMetrics)
        ro.observe(chartArea)

        let isDragging = false
        let dragStartX = 0
        let dragStartY = 0
        let dragStartVMin = 0
        let dragStartVMax = 0
        let dragStartScrollTop = 0
        let dragScrollEl: HTMLElement = chartArea
        let dragCanScrollY = false
        let dragActivated = false

        const clampWindowToDataBounds = (
            start: number,
            end: number,
            s: typeof wheelZoomRef.current,
        ) => {
            const span = Math.max(end - start, MIN_VIEW_SPAN_MS)
            const baseMin = s.dataMin
            const baseMax = s.dataMax
            const baseSpan = s.dataSpan
            if (!(baseSpan > 0)) return { start, end: start + span }

            if (span >= baseSpan) {
                const minStart = baseMax - span
                const maxStart = baseMin
                const nextStart = Math.max(minStart, Math.min(start, maxStart))
                return {
                    start: nextStart,
                    end: nextStart + span,
                }
            }

            const minStart = baseMin
            const maxStart = baseMax - span
            const nextStart = Math.max(minStart, Math.min(start, maxStart))
            const nextEnd = nextStart + span

            return {
                start: nextStart,
                end: nextEnd,
            }
        }

        const wheelOpts: AddEventListenerOptions = { passive: false, capture: true }
        const onWheel = (e: WheelEvent) => {
            const el = e.target as Element
            // If hovering over custom scroll area track, allow native scroll
            if (el && el.closest && el.closest('.custom-scroll-area__track')) return

            const s = wheelZoomRef.current
            if (s.chartTrackPx <= 0) return

            const modifierZoom = e.ctrlKey || e.metaKey || e.altKey

            // Left column: only vertical scroll (do not intercept).
            if (el && el.closest && el.closest(".ats-site-name")) return

            // Expanded detail: normal wheel scroll should never fall through into timeline zoom.
            const expandedRoot = el?.closest?.(".ats-expanded-scroll-area") as HTMLElement | null
            if (expandedRoot && !modifierZoom && Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
                const innerBody = expandedRoot.querySelector(
                    ".custom-scroll-area__body",
                ) as HTMLElement | null
                if (innerBody) {
                    return
                }
            }

            // Right column: modifier wheel zooms; horizontal wheel/trackpad pans. Plain vertical wheel scrolls normally.
            const paneEl =
                (el as HTMLElement | null)?.closest?.(
                    ".ats-chart-pane--header, .ats-chart-pane, .ats-vgrid-container, .ats-expanded-scroll-area, .ats-row-collapsed, .ats-row-expanded",
                ) ?? null
            if (!paneEl) return // not on chart column -> allow normal vertical scroll
            const paneRect = paneEl.getBoundingClientRect()
            if (paneRect.width <= 0) return

            const xInside = e.clientX - paneRect.left

            if (!modifierZoom && Math.abs(e.deltaY) > Math.abs(e.deltaX)) return

            e.stopPropagation()
            e.preventDefault()

            const ratio = Math.max(0, Math.min(1, xInside / paneRect.width))

            if (modifierZoom) {
                // Zoom
                const tAnchor = s.vMin + ratio * s.vSpan
                const zoomIn = e.deltaY < 0
                const factor = zoomIn ? 1 / WHEEL_ZOOM_STEP : WHEEL_ZOOM_STEP
                let newSpan = s.vSpan * factor
                newSpan = Math.min(s.boundsSpan * 5, Math.max(MIN_VIEW_SPAN_MS, newSpan))

                allowDetailAutoWindowRef.current = false
                setViewWindow(clampWindowToDataBounds(
                    tAnchor - ratio * newSpan,
                    tAnchor + (1 - ratio) * newSpan,
                    s,
                ))
            } else {
                // Pan horizontally with trackpad
                const msShift = (e.deltaX / paneRect.width) * s.vSpan
                allowDetailAutoWindowRef.current = false
                setViewWindow(clampWindowToDataBounds(s.vMin + msShift, s.vMax + msShift, s))
            }
        }

        const onPointerDown = (e: PointerEvent) => {
            const s = wheelZoomRef.current
            if (s.chartTrackPx <= 0) return

            const target = e.target as HTMLElement
            // block dragging if clicking interactive elements
            if (target.closest('button')) return
            // Left column: allow native interactions (including vertical scroll)
            if (target.closest(".ats-site-name")) return
            // Only enable dragging when pointer is on the chart column.
            if (
                !target.closest(
                    ".ats-chart-pane--header, .ats-chart-pane, .ats-vgrid-container, .ats-expanded-scroll-area, .ats-row-collapsed, .ats-row-expanded",
                )
            ) {
                return
            }

            isDragging = true
            dragActivated = false
            dragStartX = e.clientX
            dragStartY = e.clientY
            dragStartVMin = s.vMin
            dragStartVMax = s.vMax
            chartArea.setPointerCapture(e.pointerId)
            chartArea.style.cursor = 'grabbing'
            // When expanded, allow vertical drag to scroll the inner row scroll area.
            const rowScrollBody = target
                .closest(".ats-expanded-scroll-area")
                ?.querySelector(".custom-scroll-area__body") as HTMLElement | null
            dragScrollEl = rowScrollBody ?? chartArea
            dragCanScrollY = Boolean(rowScrollBody)
            dragStartScrollTop = dragScrollEl.scrollTop
        }

        const onPointerMove = (e: PointerEvent) => {
            if (!isDragging) return
            const s = wheelZoomRef.current
            const deltaX = e.clientX - dragStartX
            const deltaY = e.clientY - dragStartY
            if (!dragActivated) {
                if (Math.hypot(deltaX, deltaY) < 6) return
                dragActivated = true
            }
            const msShift = (deltaX / s.chartTrackPx) * s.vSpan

            allowDetailAutoWindowRef.current = false
            setViewWindow(clampWindowToDataBounds(dragStartVMin - msShift, dragStartVMax - msShift, s))

            // Only expanded detail rows support vertical drag-scroll. Header/overview drags are horizontal pan only.
            if (dragCanScrollY) {
                dragScrollEl.scrollTop = dragStartScrollTop - deltaY
            }
        }

        const onPointerUp = (e: PointerEvent) => {
            isDragging = false
            try {
                chartArea.releasePointerCapture(e.pointerId)
            } catch {
                // Pointer capture may already be released.
            }
            chartArea.style.cursor = ''
            dragCanScrollY = false
            dragActivated = false
        }

        chartArea.addEventListener("wheel", onWheel, wheelOpts)
        chartArea.addEventListener("pointerdown", onPointerDown)
        chartArea.addEventListener("pointermove", onPointerMove)
        chartArea.addEventListener("pointerup", onPointerUp)
        chartArea.addEventListener("pointercancel", onPointerUp)
        chartArea.addEventListener("scroll", updateScrollMetrics, { passive: true })

        return () => {
            ro.disconnect()
            chartArea.removeEventListener("wheel", onWheel, wheelOpts)
            chartArea.removeEventListener("pointerdown", onPointerDown)
            chartArea.removeEventListener("pointermove", onPointerMove)
            chartArea.removeEventListener("pointerup", onPointerUp)
            chartArea.removeEventListener("pointercancel", onPointerUp)
            chartArea.removeEventListener("scroll", updateScrollMetrics)
        }
    }, [timelineGridReady, activeSite, bySite])

    const barTimeLayout = useCallback(
        (startMs: number, endMs: number): Pick<CSSProperties, "left" | "width"> => {
            const safeSpan = vSpan > 0 ? vSpan : 1
            const dur = Math.max(endMs - startMs, 0)
            const leftPct = ((startMs - vMin) / safeSpan) * 100
            const widthPct = (dur / safeSpan) * 100
            return {
                left: `${leftPct}%`,
                ...(dur > 0 ? { width: `${widthPct}%` } : {}),
            }
        },
        [vMin, vSpan],
    )

    const estimateBarWidthPx = useCallback(
        (startMs: number, endMs: number) => {
            const safeSpan = vSpan > 0 ? vSpan : 1
            const dur = Math.max(endMs - startMs, 0)
            return (dur / safeSpan) * Math.max(chartTrackPx, 1)
        },
        [vSpan, chartTrackPx],
    )

    const toggleSite = useCallback((site: string) => {
        setActiveSite((prev) => {
            const next = prev === site ? null : site
            if (next) {
                allowDetailAutoWindowRef.current = true
                const nextDetailKey = `${next}|${Number.isNaN(collectionIdNum) ? "all" : collectionIdNum}|${mediaTypeFilter}`
                const cachedDetail = detailDataByKeyRef.current.get(nextDetailKey)
                const hasCachedDetail = Boolean(cachedDetail)
                setExpandPending(true)
                setDetailError(null)
                setDetailLoadingKey(hasCachedDetail ? null : nextDetailKey)
                const items = bySite.get(next) ?? []
                if (items.length > 0) {
                    let min = Infinity
                    let max = -Infinity
                    for (const it of items) {
                        const s = parseTimelineDate(it.start_date)
                        const e = parseTimelineDate(it.end_date)
                        const t1 = Number.isNaN(e) ? s : Math.max(s, e)
                        if (!Number.isNaN(s)) {
                            min = Math.min(min, s)
                            max = Math.max(max, t1)
                        }
                    }
                    if (min !== Infinity) {
                        const expandedWindow = buildCenteredTimeWindow(min, max)
                        const cachedWindow = cachedDetail
                            ? buildWindowFromResponseRange(cachedDetail.time_range, cachedDetail.items)
                            : null
                        const nextWindow = cachedWindow ?? expandedWindow
                        if (nextWindow) {
                            setViewWindow(nextWindow)
                        }
                    }
                }
            } else {
                // Optional: reset to bounds when collapsing
                allowDetailAutoWindowRef.current = false
                setExpandPending(false)
                setDetailLoadingKey(null)
                setViewWindow(null)
            }
            return next
        })
    }, [bySite, collectionIdNum, mediaTypeFilter, setViewWindow])

    const openAudioDetail = useCallback(
        (mediaId: number) => {
            const pid = project?.id ?? "1"
            navigate(`/dashboard/${pid}/media/${mediaId}`)
        },
        [navigate, project?.id],
    )

    const focusWindowOnItem = useCallback((it: CollectionTimelineItem) => {
        const start = parseTimelineDate(it.start_date)
        if (Number.isNaN(start)) return
        const end = parseTimelineDate(it.end_date)
        const t1 = Number.isNaN(end) ? start : Math.max(start, end)
        const itemDur = t1 - start

        const spanNeeded = Math.max(itemDur * 1.5, MIN_VIEW_SPAN_MS * 2)
        const center = start + itemDur / 2
        allowDetailAutoWindowRef.current = false
        setViewWindow({ start: center - spanNeeded / 2, end: center + spanNeeded / 2 })
    }, [])

    const scrollDetailListToItem = useCallback((rowIndex: number) => {
        window.requestAnimationFrame(() => {
            const root = expandedScrollAreaRef.current
            const body = root?.querySelector(".ats-expanded-scroll-body") as HTMLElement | null
            if (!body) return
            const rowTop = 6 + rowIndex * (BAR_HEIGHT + BAR_GAP)
            const target = Math.max(0, rowTop - (body.clientHeight - BAR_HEIGHT) / 2)
            const maxScroll = Math.max(0, body.scrollHeight - body.clientHeight)
            body.scrollTo({ top: Math.min(target, maxScroll), behavior: "smooth" })
        })
    }, [])

    const panWindowToItem = useCallback((it: CollectionTimelineItem, rowIndex: number) => {
        const start = parseTimelineDate(it.start_date)
        if (Number.isNaN(start)) return
        const end = parseTimelineDate(it.end_date)
        const safeEnd = Number.isNaN(end) ? start : Math.max(start, end)
        const currentSpan = Math.max(vSpan, MIN_VIEW_SPAN_MS)
        const itemCenter = start + (safeEnd - start) / 2
        const nextStart = itemCenter - currentSpan / 2

        allowDetailAutoWindowRef.current = false
        setViewWindow({ start: nextStart, end: nextStart + currentSpan })
        scrollDetailListToItem(rowIndex)
    }, [scrollDetailListToItem, vSpan])

    const onBucketClick = useCallback((site: string) => {
        toggleSite(site)
    }, [toggleSite])

    const zoomToItem = useCallback((it: CollectionTimelineItem) => {
        focusWindowOnItem(it)
    }, [focusWindowOnItem])

    const activeDetail = detailSiteKey ? detailDataByKey.get(detailSiteKey) : undefined
    const activeDetailItems = useMemo(() => {
        if (!activeDetail?.items?.length) return null
        return [...activeDetail.items].sort(
            (a, b) => parseTimelineDate(a.start_date) - parseTimelineDate(b.start_date),
        )
    }, [activeDetail])

    const getSiteItems = useCallback(
        (site: string) => {
            if (site === activeSite && activeDetailItems) return activeDetailItems
            return bySite.get(site) ?? []
        },
        [activeDetailItems, activeSite, bySite],
    )
    const ticks = useMemo(() => buildAdaptiveTicks(vMin, vMax), [vMin, vMax])

    useEffect(() => {
        if (!activeSite) {
            setDetailScrollTop(0)
            return
        }
        const root = expandedScrollAreaRef.current
        const body = root?.querySelector(".ats-expanded-scroll-body") as HTMLElement | null
        if (!body) return

        const sync = () => setDetailScrollTop(body.scrollTop)
        sync()
        body.addEventListener("scroll", sync, { passive: true })
        return () => body.removeEventListener("scroll", sync)
    }, [activeSite, activeDetailItems])

    useEffect(() => {
        if (!expandPending) return
        if (!activeSite || !detailSiteKey) {
            setExpandPending(false)
            return
        }

        const detailReady =
            detailError != null ||
            (detailLoadingKey !== detailSiteKey &&
                (detailDataByKeyRef.current.has(detailSiteKey) || Boolean(activeDetail)))

        if (!detailReady) return

        let raf1 = 0
        let raf2 = 0
        raf1 = window.requestAnimationFrame(() => {
            raf2 = window.requestAnimationFrame(() => {
                setExpandPending(false)
            })
        })

        return () => {
            window.cancelAnimationFrame(raf1)
            window.cancelAnimationFrame(raf2)
        }
    }, [activeDetail, activeSite, detailError, detailLoadingKey, detailSiteKey, expandPending])

    const resetView = useCallback(() => {
        allowDetailAutoWindowRef.current = false
        if (activeSite) {
            const items = getSiteItems(activeSite)
            if (items.length > 0) {
                let min = Infinity
                let max = -Infinity
                for (const it of items) {
                    const s = parseTimelineDate(it.start_date)
                    const e = parseTimelineDate(it.end_date)
                    const t1 = Number.isNaN(e) ? s : Math.max(s, e)
                    if (!Number.isNaN(s)) {
                        min = Math.min(min, s)
                        max = Math.max(max, t1)
                    }
                }
                if (min !== Infinity) {
                    const resetWindow = buildCenteredTimeWindow(min, max)
                    if (resetWindow) setViewWindow(resetWindow)
                }
            }
        } else {
            setViewWindow(null)
            setActiveSite(null)
        }
    }, [activeSite, getSiteItems])

    if (!project) return null

    const allVisibleSites = activeSite ? siteOrder.filter((s) => s === activeSite) : siteOrder
    const activeSiteName = activeSite ? (siteNames.get(activeSite) ?? activeSite) : null
    const virtualStart = activeSite
        ? 0
        : Math.max(0, Math.floor(scrollTop / ROW_COLLAPSED_PX) - VIRTUAL_ROW_OVERSCAN)
    const virtualCount = activeSite
        ? allVisibleSites.length
        : Math.ceil(Math.max(viewportHeight, ROW_COLLAPSED_PX) / ROW_COLLAPSED_PX) + VIRTUAL_ROW_OVERSCAN * 2
    const virtualEnd = activeSite
        ? allVisibleSites.length
        : Math.min(allVisibleSites.length, virtualStart + virtualCount)
    const visibleSites = allVisibleSites.slice(virtualStart, virtualEnd)
    const topSpacerPx = activeSite ? 0 : virtualStart * ROW_COLLAPSED_PX
    const bottomSpacerPx = activeSite ? 0 : Math.max(0, (allVisibleSites.length - virtualEnd) * ROW_COLLAPSED_PX)
    const activeCount = activeSite
        ? getSiteItems(activeSite).reduce((sum, it) => sum + (it.item_count ?? 1), 0)
        : 0
    const overviewCount = data?.items?.reduce((sum, it) => sum + (it.item_count ?? 1), 0)
    const activeSiteAccentVars = activeSite
        ? getRealmAccentVars(getSiteItems(activeSite)[0]?.realm ?? bySite.get(activeSite)?.[0]?.realm)
        : undefined

    const timelineLayoutVars = {
        "--ats-sidebar-w": `${SIDEBAR_W}px`,
        "--ats-corner-w": `${SIDEBAR_W}px`,
    } as CSSProperties

    const gridStyle = {
        ...timelineLayoutVars,
        width: "100%",
        display: "grid",
        gridTemplateColumns: `${SIDEBAR_W}px 1fr`,
        // 不需要 filler 行，避免底部出现空白仍可滚动
        gridTemplateRows: activeSite
            ? `minmax(0, 1fr)`
            : `${topSpacerPx}px repeat(${visibleSites.length}, ${ROW_COLLAPSED_PX}px) ${bottomSpacerPx}px`,
        userSelect: "none" // Prevent text selection while panning
    } as CSSProperties

    const showTimelineLoadingOverlay = loading || renderPending || expandPending

    return (
        <div className="acoustic-timeline dashboard-card" style={activeSiteAccentVars}>
            <div className="card-header media-header">
                <div className="media-title">
                    <CalendarRange size={24} />
                    Timeline
                    <MediaTypeSegment value={mediaTypeFilter} onChange={setMediaTypeFilter} />
                    {activeSite ? (
                        <span className="media-count-badge">
                            {activeCount} Items
                        </span>
                    ) : overviewCount != null ? (
                        <span className="media-count-badge">{overviewCount} Items</span>
                    ) : null}
                </div>
                <div className="media-controls">
                    <ESButton appearance="unstyled" type="button" className="timeline-show-all-btn" title="Fit the timeline to all sites and media" onClick={resetView}>
                        <Maximize size={14} />
                        Show All
                    </ESButton>
                </div>
            </div>

            <div className="acoustic-timeline-body">
                {loading && !data ? (
                    <div className="acoustic-timeline-state acoustic-timeline-state--loading">
                        <div className="acoustic-timeline-state__card">
                            <LoadingState label="Loading timeline..." variant="inline" size="lg" />
                        </div>
                    </div>
                ) : error ? (
                    <div className="acoustic-timeline-error">{error}</div>
                ) : !data?.items?.length || boundsSpan <= 0 ? (
                    <div className="acoustic-timeline-state">
                        <EmptyState className="acoustic-timeline-state__card" title="No Data" />
                    </div>
                ) : (
                    <div className="acoustic-timeline-stage">
                        {showTimelineLoadingOverlay ? (
                            <div className="acoustic-timeline-state acoustic-timeline-state--loading acoustic-timeline-state--overlay">
                                <div className="acoustic-timeline-state__card">
                                    <LoadingState label="Loading timeline..." variant="inline" size="lg" />
                                </div>
                            </div>
                        ) : null}
                        <div
                            className="acoustic-timeline-stage__content"
                            style={{
                                visibility: showTimelineLoadingOverlay ? "hidden" : "visible",
                                ...timelineLayoutVars,
                            }}
                        >
                            <CustomScrollArea
                                className="flex-1 min-h-0 ats-main-scroll"
                                variant="fill"
                                bodyClassName="ats-main-scroll-body"
                                bodyStyle={{
                                    overflowX: "hidden",
                                    overflowY: activeSite ? "hidden" : "auto",
                                    display: "flex",
                                    flexDirection: "column",
                                }}
                            >
                                <div className="ats-sticky-header">
                                    <div className="ats-corner ats-corner--header">
                                        {activeSite ? (
                                            <div className="ats-corner-site-head">
                                                <ESButton appearance="unstyled"
                                                    type="button"
                                                    className="ats-corner-site-back"
                                                    onClick={() => toggleSite(activeSite)}
                                                    title="Collapse and show back all rows"
                                                    aria-label="Back to site list"
                                                >
                                                    <ChevronLeft size={14} />
                                                </ESButton>
                                                <span className="ats-corner-site-title">{activeSiteName}</span>
                                            </div>
                                        ) : null}
                                    </div>
                                    <div className="ats-chart-pane ats-chart-pane--header" ref={headerChartRef}>
                                        <TimelineAxis ticks={ticks} />
                                    </div>
                                </div>
                                <div className="acoustic-timeline-matrix" style={{ ...gridStyle, flex: 1 }}>
                                    {!activeSite && topSpacerPx > 0 ? (
                                        <div style={{ gridColumn: "1 / 3", gridRow: "1 / 2", height: topSpacerPx }} />
                                    ) : null}
                                    {visibleSites.map((site, gridIdx) => {
                                const overviewItems = bySite.get(site) ?? []
                                const items = getSiteItems(site)
                                const realm = items[0]?.realm ?? overviewItems[0]?.realm
                                const accentVars = getRealmAccentVars(realm)
                                const expanded = activeSite === site
                                const buckets = bucketItemsForSite(overviewItems, vMin, vSpan, chartTrackPx)
                                const sorted = items
                                const rowH = expanded
                                    ? 12 + sorted.length * (BAR_HEIGHT + BAR_GAP)
                                    : ROW_COLLAPSED_PX

                                const rowNumber = activeSite ? gridIdx + 1 : gridIdx + 2
                                const rowPos = `${rowNumber} / ${rowNumber + 1}`

                                return (
                                    <div key={site} className="ats-matrix-row" data-site-row={site} style={accentVars}>
                                        {expanded ? (
                                            <div
                                                className="ats-site-detail ats-site-name--sticky"
                                                style={{ height: "100%", gridColumn: "1 / 2", gridRow: rowPos }}
                                            >
                                                <div className="ats-site-detail-viewport">
                                                    <div
                                                        className="ats-site-detail-list"
                                                        style={{
                                                            height: rowH,
                                                            transform: `translateY(-${detailScrollTop}px)`,
                                                        }}
                                                    >
                                                        {sorted.map((it, idx) => {
                                                            const top = 6 + idx * (BAR_HEIGHT + BAR_GAP)
                                                            return (
                                                                <ESButton appearance="unstyled"
                                                                    key={`label-${it.media_id}`}
                                                                    type="button"
                                                                    className="ats-sublabel-item"
                                                                    style={{ top, height: BAR_HEIGHT }}
                                                                    onClick={(e) => {
                                                                        e.stopPropagation()
                                                                        panWindowToItem(it, idx)
                                                                    }}
                                                                    title={`${it.name || "Media"}\n${it.start_date} - ${it.end_date}`}
                                                                >
                                                                    <span className="ats-sublabel-text">{it.name || "Media"}</span>
                                                                </ESButton>
                                                            )
                                                        })}
                                                    </div>
                                                </div>
                                            </div>
                                        ) : (
                                            <ESButton appearance="unstyled"
                                                type="button"
                                                className="ats-site-name ats-site-name--sticky"
                                                style={{ height: rowH, gridColumn: "1 / 2", gridRow: rowPos }}
                                                    onClick={() => toggleSite(site)}
                                                title="Expand this site row to show its media timeline"
                                            >
                                                <ChevronRight size={16} className="ats-site-chevron" />
                                                <span className="ats-site-name-text">{siteNames.get(site) ?? site}</span>
                                            </ESButton>
                                        )}

                                        {!expanded ? (
                                            <div
                                                className="ats-chart-pane"
                                                style={{ height: rowH, gridColumn: "2 / 3", gridRow: rowPos, position: "relative" }}
                                            >
                                                <VerticalGrid ticks={ticks} />
                                                <div
                                                    className="ats-row-collapsed"
                                                    style={{ height: ROW_COLLAPSED_PX }}
                                                >
                                                    {buckets.map((b) => {
                                                        const isPhotoCluster = b.items.length > 0 && b.items.every((it) => String(it.media_type ?? "").toLowerCase() === "photo")
                                                        return (
                                                            <ESButton appearance="unstyled"
                                                                key={b.key}
                                                                type="button"
                                                                className="ats-cluster"
                                                                style={barTimeLayout(b.tAnchor, b.tAnchor)}
                                                                onClick={() => onBucketClick(site)}
                                                                title={b.count > 1 ? `Open ${b.count} media items for this site` : "Open media for this site"}
                                                                aria-label={
                                                                    b.count > 1
                                                                        ? `${b.count} items`
                                                                        : (b.items[0]?.name ?? "Media")
                                                                }
                                                            >
                                                                <span
                                                                    className={`ats-cluster-bar${isPhotoCluster ? " ats-cluster-bar--photo" : ""}`}
                                                                    style={{
                                                                        background: getRealmTheme(b.realm).brand,
                                                                        borderColor: getRealmTheme(b.realm).brandHover,
                                                                    }}
                                                                >
                                                                    {b.count > 1 ? (
                                                                        <span className="ats-cluster-count">{b.count}</span>
                                                                    ) : null}
                                                                    <span
                                                                        className="ats-cluster-hover-name"
                                                                        style={{ borderColor: getRealmTheme(b.realm).brand }}
                                                                    >
                                                                        {b.count > 1 ? `${b.count} items` : b.items[0]?.name}
                                                                    </span>
                                                                </span>
                                                            </ESButton>
                                                        )
                                                    })}
                                                </div>
                                            </div>
                                        ) : (
                                            <>
                                                {/* Vertical grid separated out so it stays put during vertical scroll */}
                                                <div
                                                    className="ats-vgrid-container"
                                                    style={{ gridColumn: "2 / 3", gridRow: rowPos, position: "relative", overflow: "hidden", pointerEvents: "none" }}
                                                >
                                                    <VerticalGrid ticks={ticks} />
                                                </div>

                                                <div
                                                    ref={expanded ? expandedScrollAreaRef : null}
                                                    className="ats-expanded-scroll-area"
                                                    style={{ gridColumn: "2 / 3", gridRow: rowPos, position: "relative", height: "100%" }}
                                                >
                                                    <CustomScrollArea
                                                        className="absolute inset-0 w-full h-full"
                                                        bodyClassName="ats-expanded-scroll-body"
                                                    >
                                                        <div style={{ display: "flex", height: rowH }}>
                                                            {/* Bars Column */}
                                                            <div className="ats-row-expanded" style={{ flex: 1, position: "relative", overflow: "hidden" }}>
                                                                {expanded && detailLoadingKey === detailSiteKey ? (
                                                                    <div className="acoustic-timeline-detail-state acoustic-timeline-detail-state--loading">
                                                                        <div className="acoustic-timeline-detail-state__card">
                                                                            <LoadingState label="Loading detail..." variant="inline" size="sm" />
                                                                        </div>
                                                                    </div>
                                                                ) : null}
                                                                {expanded && detailError ? (
                                                                    <div className="acoustic-timeline-error" style={{ position: "absolute", left: 12, top: 8, zIndex: 2 }}>
                                                                        {detailError}
                                                                    </div>
                                                                ) : null}
                                                                {sorted.map((it, idx) => {
                                                                    const x0 = parseTimelineDate(it.start_date)
                                                                    const x1 = parseTimelineDate(it.end_date)
                                                                    if (Number.isNaN(x0)) return null
                                                                    const end = Number.isNaN(x1) ? x0 : x1
                                                                    if (end < vMin || x0 > vMax) return null
                                                                    const top = 6 + idx * (BAR_HEIGHT + BAR_GAP)
                                                                    const isMeta = it.is_metadata
                                                                    const isPhoto = String(it.media_type ?? "").toLowerCase() === "photo"
                                                                    const canOpen = !isMeta
                                                                    const realmTheme = getRealmTheme(it.realm)

                                                                    const barWidthPx = estimateBarWidthPx(x0, end)
                                                                    const metadataBarStyle = isMeta
                                                                        ? buildMetadataBarStyle(
                                                                            it,
                                                                            barWidthPx,
                                                                            realmTheme.brand,
                                                                            realmTheme.brandHover,
                                                                        )
                                                                        : null
                                                                    const estimatedNameWidth = (it.name?.length || 0) * 7.5 + 20
                                                                    const canFitInside = barWidthPx > estimatedNameWidth

                                                                    return (
                                                                        <ESButton appearance="unstyled"
                                                                            key={it.media_id}
                                                                            type="button"
                                                                            className={`ats-bar${isMeta ? " ats-bar--metadata" : ""}${isPhoto ? " ats-bar--photo" : ""}`}
                                                                            style={{
                                                                                top: isPhoto ? top + (BAR_HEIGHT - 8) / 2 : top,
                                                                                height: isPhoto ? 8 : BAR_HEIGHT,
                                                                                ...barTimeLayout(x0, isPhoto ? x0 : end),
                                                                                ...(isMeta
                                                                                    ? metadataBarStyle ?? undefined
                                                                                    : {
                                                                                        background: realmTheme.brand,
                                                                                        borderColor: realmTheme.brandHover,
                                                                                    }),
                                                                                cursor: canOpen ? "pointer" : "default",
                                                                            }}
                                                                            onClick={() => {
                                                                                if (canOpen) openAudioDetail(it.media_id)
                                                                            }}
                                                                            title={canOpen ? `Open ${it.name || "this media"} in the media viewer` : "Metadata-only item; no media viewer available"}
                                                                        >
                                                                            <span
                                                                                className={`ats-bar-label ${canFitInside ? "ats-bar-label--inside" : ""}`}
                                                                                style={{ borderColor: canFitInside ? "transparent" : getRealmTheme(it.realm).brand }}
                                                                                onClick={(e) => {
                                                                                    e.stopPropagation()
                                                                                    zoomToItem(it)
                                                                                }}
                                                                            >
                                                                                {it.name}
                                                                            </span>
                                                                        </ESButton>
                                                                    )
                                                                })}
                                                            </div>
                                                        </div>
                                                    </CustomScrollArea>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                )
                                    })}
                                    {!activeSite && bottomSpacerPx > 0 ? (
                                        <div
                                            style={{
                                                gridColumn: "1 / 3",
                                                gridRow: `${visibleSites.length + 2} / ${visibleSites.length + 3}`,
                                                height: bottomSpacerPx,
                                            }}
                                        />
                                    ) : null}

                                </div>
                            </CustomScrollArea>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
