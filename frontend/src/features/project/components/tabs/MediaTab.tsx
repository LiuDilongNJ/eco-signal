import { Input as ESInput, Button as ESButton } from "@/components/ui"
/**
 * MediaTab - 媒体管理页
 *
 * 包含: 搜索工具栏 + Gallery/List 视图切换 + 媒体卡片
 * 点击卡片跳转到 `/dashboard/:id/media/:mediaId` 统一媒体详情页。
 */

import { useState, useRef, useCallback, useEffect, useMemo } from "react"
import {
    FileAudio,
    Search,
    Grid,
    List,
    Calendar,
    Clock,
    Timer,
    HardDrive,
    Image as ImageIcon,
    MapPin,
    Mountain,
    Waves,
    ChevronRight,
} from "lucide-react"
import { CustomScrollArea } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { useDelayedFlag } from "@/hooks/useDelayedFlag"
import { UnifiedImage } from "@/components/ui"
import { useProjectStore } from "../../stores/useProjectStore"
import { getRealmAccentVars, getRealmTagPillStyle } from "../../sphereTheme"

import { mediaApi, MediaPublic, type BrowseMediaParams } from "../../../../api/endpoints/media"
import {
    MediaGalleryCard,
    ActionLink,
    formatDuration,
    formatMetadataProgress,
    hasCompleteMetadataDutyCycle,
    safeArray,
    getMediaLabelNames,
    isGalleryMetadataItem,
    getMetadataMediaKind,
    splitMediaDisplayDateTime,
    resolveMediaDetailTo,
    resolveMediaThemeValue,
    resolveMediaNumericId,
} from "../media/MediaGalleryCard"
import { useMediaSpectrogramUrl } from "../media/useMediaSpectrogramUrl"
import { MediaTypeSegment } from "./MediaTypeSegment"
import { mediaTypeFilterParam, type MediaTypeFilter } from "./mediaTypeFilter"


/** 列表行站点区：接口可能平铺 topography_m */
function formatTopographyMeters(item: MediaPublic): string | null {
    const raw = (item as Record<string, unknown>).topography_m ?? item.topography_m
    if (raw === undefined || raw === null || raw === "") return null
    const n = typeof raw === "number" ? raw : Number(String(raw).trim())
    if (!Number.isFinite(n)) return null
    return `${Math.round(n)}`
}

/** 列表行站点区：接口可能平铺 freshwater_depth_m */
function formatFreshwaterDepth(item: MediaPublic): string | null {
    const raw = (item as Record<string, unknown>).freshwater_depth_m ?? item.freshwater_depth_m
    if (raw === undefined || raw === null || raw === "") return null
    const n = typeof raw === "number" ? raw : Number(String(raw).trim())
    if (!Number.isFinite(n) || n <= 0) return null
    return `${Math.round(n)}`
}

/** browse 返回 gallery 用 preview_url、list 无预览图；统一 id / spectrogram 供组件使用 */
function normalizeBrowseRows(rows: MediaPublic[]): MediaPublic[] {
    return (rows || []).map((row) => {
        const r = row as Record<string, unknown>
        const idRaw = r.id ?? r.media_id
        const idNum = typeof idRaw === "number" ? idRaw : Number(String(idRaw ?? "").trim())
        const next: Record<string, unknown> = { ...r }
        if (Number.isFinite(idNum)) next.id = idNum
        const spec = r.spectrogram ?? r.preview_url
        if (spec !== undefined) next.spectrogram = spec
        return next as unknown as MediaPublic
    })
}

function browseResponseOk(res: unknown): res is { data: MediaPublic[]; page_info?: { total?: number } } {
    if (!res || typeof res !== "object") return false
    const r = res as { code?: number; data?: unknown }
    const codeOk = r.code === undefined || r.code === 0 || r.code === 200
    return codeOk && Array.isArray(r.data)
}

/** 避免接口重复 id / 缺 id 时 React key 冲突 */
function mediaItemListKey(item: MediaPublic, index: number): string {
    const idPart = item.id != null ? String(item.id) : "x"
    const u = typeof item.uuid === "string" ? item.uuid.trim() : ""
    if (u) return `m-${idPart}-${u}`
    const name = typeof item.name === "string" ? item.name.slice(0, 40) : ""
    return `m-${idPart}-i${index}-${name}`
}

function mediaMergeKey(item: MediaPublic): string | null {
    const id = resolveMediaNumericId(item)
    if (id != null) return `id:${id}`
    const uuid = typeof item.uuid === "string" ? item.uuid.trim() : ""
    if (uuid) return `uuid:${uuid}`
    const name = typeof item.name === "string" ? item.name.trim() : ""
    return name ? `name:${name}` : null
}

function mergeMediaLabelFields(target: MediaPublic, source?: MediaPublic): MediaPublic {
    if (!source || getMediaLabelNames(target).length > 0) return target
    const s = source as Record<string, unknown>
    return {
        ...target,
        label: target.label ?? (s.label as string | null | undefined),
        labels: target.labels ?? (s.labels as string[] | undefined),
        annotations: target.annotations ?? s.annotations,
        label_names: target.label_names ?? s.label_names,
        label_list: target.label_list ?? s.label_list,
        label_values: target.label_values ?? s.label_values,
    } as MediaPublic
}

function mergeListItemsWithGalleryLabels(listItems: MediaPublic[], galleryItems: MediaPublic[]): MediaPublic[] {
    const galleryByKey = new Map<string, MediaPublic>()
    galleryItems.forEach((item) => {
        const key = mediaMergeKey(item)
        if (key) galleryByKey.set(key, item)
    })
    return listItems.map((item, index) => {
        const key = mediaMergeKey(item)
        const matchingGallery = key ? galleryByKey.get(key) : undefined
        return mergeMediaLabelFields(item, matchingGallery ?? galleryItems[index])
    })
}

export function MediaTab() {
    const project = useProjectStore((s) => {
        if (!s.currentProjectId) return undefined
        return s.projects.find(p => p.id === s.currentProjectId)
    })
    const collection = useProjectStore((s) => {
        if (!s.currentCollectionId) return undefined
        return s.collectionOptions.find(c => c.id === s.currentCollectionId)
    })
    const isCollectionMode = !!collection && collection.id !== ""

    const [searchQuery, setSearchQuery] = useState("")
    const [mediaTypeFilter, setMediaTypeFilter] = useState<MediaTypeFilter>("all")
    const [viewMode, setViewMode] = useState<"gallery" | "list">("gallery")
    const pillRef = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const timeoutRef = useRef<NodeJS.Timeout | null>(null)
    const fetchGenRef = useRef(0)
    // 记录上一次搜索词，用于区分“搜索输入”与其他触发源
    const prevSearchRef = useRef(searchQuery)

    /** 与 view 解耦：切换 Gallery/List 只换展示，不重新请求 */
    const [galleryItems, setGalleryItems] = useState<MediaPublic[]>([])
    const [listItems, setListItems] = useState<MediaPublic[]>([])
    const [totalItems, setTotalItems] = useState(0)
    const [loading, setLoading] = useState(false)
    // 遮罩延迟显示：快速请求（<250ms）不闪 loading，避免刷新时的视觉卡顿感
    const delayedLoading = useDelayedFlag(loading, 250)

    const [page, setPage] = useState(1)
    const [hasMore, setHasMore] = useState({ gallery: true, list: true })
    const [loadingMore, setLoadingMore] = useState(false)
    const loadingMoreRef = useRef(false)

    const displayItems = useMemo(
        () => (viewMode === "gallery" ? galleryItems : listItems),
        [viewMode, galleryItems, listItems],
    )
    const hasVisibleItems = displayItems.length > 0
    const showLoadingOverlay = delayedLoading && hasVisibleItems
    const showInitialLoading = delayedLoading && !hasVisibleItems
    const showCenteredState = showInitialLoading || displayItems.length === 0

    // 项目 / 集合 / 搜索 变化时并行拉取两种 view（后端字段不同），避免切换视图时再闪 loading；
    // 仅搜索输入需要防抖，项目/集合/类型切换立即请求
    useEffect(() => {
        if (!project) {
            setGalleryItems([])
            setListItems([])
            setTotalItems(0)
            setLoading(false)
            setPage(1)
            setHasMore({ gallery: true, list: true })
            return
        }

        const projectId = project.id

        if (timeoutRef.current) clearTimeout(timeoutRef.current)

        const searchChanged = prevSearchRef.current !== searchQuery
        prevSearchRef.current = searchQuery

        const gen = ++fetchGenRef.current
        let mounted = true
        timeoutRef.current = setTimeout(async () => {
            setLoading(true)
            setPage(1)
            setHasMore({ gallery: true, list: true })
            const baseParams: Record<string, unknown> = {
                project_id: projectId,
                page: 1,
                page_size: 100,
            }
            if (isCollectionMode && collection) {
                baseParams.collection_id = collection.id
            }
            if (searchQuery) {
                baseParams.name = searchQuery
            }
            const mediaType = mediaTypeFilterParam(mediaTypeFilter)
            if (mediaType) {
                baseParams.media_type = mediaType
            }

            try {
                const [gRes, lRes] = await Promise.all([
                    mediaApi.browseMedia({ ...baseParams, view_type: "gallery" } as BrowseMediaParams, true),
                    mediaApi.browseMedia({ ...baseParams, view_type: "list" } as BrowseMediaParams, true),
                ])
                if (!mounted || fetchGenRef.current !== gen) return

                const gOk = browseResponseOk(gRes)
                const lOk = browseResponseOk(lRes)
                const gItems = gOk ? normalizeBrowseRows(gRes.data) : []
                const lItems = lOk ? normalizeBrowseRows(lRes.data) : []
                const mergedListItems = mergeListItemsWithGalleryLabels(lItems, gItems)
                if (gOk) setGalleryItems(gItems)
                if (lOk) setListItems(mergedListItems)
                setHasMore({
                    gallery: gItems.length >= 100,
                    list: lItems.length >= 100
                })
                const total =
                    (gOk && gRes.page_info?.total != null ? gRes.page_info.total : undefined) ??
                    (lOk && lRes.page_info?.total != null ? lRes.page_info.total : undefined) ??
                    (gOk ? gRes.data.length : 0) ??
                    (lOk ? lRes.data.length : 0)
                setTotalItems(total)
            } catch (error) {
                console.error("Failed to fetch media:", error)
            } finally {
                if (mounted && fetchGenRef.current === gen) setLoading(false)
            }
        }, searchChanged ? 400 : 0)

        return () => {
            mounted = false
        }
    }, [project?.id, collection?.id, isCollectionMode, searchQuery, mediaTypeFilter])

    const loadMore = useCallback(async () => {
        if (!project || loadingMoreRef.current || (!hasMore.gallery && !hasMore.list)) return

        loadingMoreRef.current = true
        setLoadingMore(true)

        const nextPage = page + 1
        const baseParams: Record<string, unknown> = {
            project_id: project.id,
            page: nextPage,
            page_size: 100,
        }
        if (isCollectionMode && collection) {
            baseParams.collection_id = collection.id
        }
        if (searchQuery) {
            baseParams.name = searchQuery
        }
        const mediaType = mediaTypeFilterParam(mediaTypeFilter)
        if (mediaType) {
            baseParams.media_type = mediaType
        }

        try {
            const promises = []
            let gRes: any, lRes: any;
            if (hasMore.gallery) {
                promises.push(mediaApi.browseMedia({ ...baseParams, view_type: "gallery" } as BrowseMediaParams, true).then(res => gRes = res))
            }
            if (hasMore.list) {
                promises.push(mediaApi.browseMedia({ ...baseParams, view_type: "list" } as BrowseMediaParams, true).then(res => lRes = res))
            }

            await Promise.all(promises)

            const newGalleryItems = gRes && browseResponseOk(gRes)
                ? normalizeBrowseRows(gRes.data)
                : []
            if (gRes && browseResponseOk(gRes)) {
                setGalleryItems(prev => [...prev, ...newGalleryItems])
                setHasMore(prev => ({ ...prev, gallery: newGalleryItems.length >= 100 }))
            }
            if (lRes && browseResponseOk(lRes)) {
                const newItems = normalizeBrowseRows(lRes.data)
                const galleryLabelSource = newGalleryItems.length > 0
                    ? newGalleryItems
                    : galleryItems
                const mergedNewItems = mergeListItemsWithGalleryLabels(newItems, galleryLabelSource)
                setListItems(prev => [...prev, ...mergedNewItems])
                setHasMore(prev => ({ ...prev, list: newItems.length >= 100 }))
            }
            setPage(nextPage)
        } catch (error) {
            console.error("Failed to fetch more media:", error)
        } finally {
            loadingMoreRef.current = false
            setLoadingMore(false)
        }
    }, [project, isCollectionMode, collection, searchQuery, mediaTypeFilter, page, hasMore, galleryItems])

    const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
        const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
        if (scrollHeight - scrollTop - clientHeight < 50) {
            loadMore()
        }
    }, [loadMore])

    // 视图切换动画
    const movePill = useCallback((btn: HTMLElement) => {
        if (!pillRef.current || !containerRef.current) return
        pillRef.current.style.width = `${btn.offsetWidth}px`
        pillRef.current.style.left = `${btn.offsetLeft}px`
    }, [])

    useEffect(() => {
        const activeBtn = containerRef.current?.querySelector(".view-btn.active") as HTMLElement | null
        if (activeBtn) {
            if (pillRef.current) pillRef.current.style.transition = "none"
            movePill(activeBtn)
            requestAnimationFrame(() => {
                if (pillRef.current) pillRef.current.style.transition = ""
            })
        }
    }, [movePill])

    const handleViewSwitch = (mode: "gallery" | "list", e: React.MouseEvent<HTMLButtonElement>) => {
        setViewMode(mode)
        movePill(e.currentTarget)
    }

    if (!project) return null

    return (
        <div className="dashboard-card" style={{ height: "100%" }}>
            {/* Header */}
            <div className="card-header media-header">
                <div className="media-title">
                    <FileAudio size={24} />
                    Media
                    <MediaTypeSegment value={mediaTypeFilter} onChange={setMediaTypeFilter} />
                    <span className="media-count-badge">{totalItems} Items</span>
                </div>
                <div className="media-controls">
                    <div className="media-search-box">
                        <Search className="media-search-icon" size={16} />
                        <ESInput appearance="unstyled"
                            className="media-search-input"
                            type="text"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>
                    <div className="view-switcher-container" ref={containerRef}>
                        <div className="view-pill" ref={pillRef} />
                        <ESButton appearance="unstyled"
                            className={`view-btn ${viewMode === "gallery" ? "active" : ""}`}
                            title="Show media as preview cards"
                            onClick={(e) => handleViewSwitch("gallery", e)}
                        >
                            <Grid size={14} />
                            Gallery
                        </ESButton>
                        <ESButton appearance="unstyled"
                            className={`view-btn ${viewMode === "list" ? "active" : ""}`}
                            title="Show media in a compact list"
                            onClick={(e) => handleViewSwitch("list", e)}
                        >
                            <List size={14} />
                            List
                        </ESButton>
                    </div>
                </div>
            </div>

            {/* Body */}
            <CustomScrollArea
                variant="fill"
                className="card-body media-scroll-area flex-1 min-h-0"
                bodyClassName="h-full"
                onScroll={handleScroll}
            >
                <div
                    className={`media-container ${viewMode === "gallery" ? "view-gallery" : "view-list"} block-anim${showLoadingOverlay ? " media-container--loading" : ""}${showCenteredState ? " media-container--state" : ""}`}
                >
                    {showInitialLoading ? (
                        <LoadingState label="Loading media..." variant="page" size="lg" className="media-state media-state--loading" />
                    ) : displayItems.length === 0 ? (
                        // 加载中的空列表保持空白，避免切换集合/类型时闪 "No Data"
                        loading ? null : (
                            <EmptyState className="ui-state--page media-state" title="No Data" />
                        )
                    ) : viewMode === "gallery" ? (
                        displayItems.map((item, index) => (
                            <MediaGalleryCard
                                key={mediaItemListKey(item, index)}
                                item={item}
                                detailTo={resolveMediaDetailTo(item, project.id)}
                                projectId={Number(project.id)}
                                sphere={resolveMediaThemeValue(item)}
                            />
                        ))
                    ) : (
                        displayItems.map((item, index) => (
                            <ListRow
                                key={mediaItemListKey(item, index)}
                                item={item}
                                detailTo={resolveMediaDetailTo(item, project.id)}
                                projectId={Number(project.id)}
                            />
                        ))
                    )}
                </div>
                {showLoadingOverlay || loadingMore ? (
                    <LoadingState
                        label={loadingMore ? "Loading more..." : "Updating media..."}
                        variant="overlay"
                        size="lg"
                        className="media-loading-overlay"
                    />
                ) : null}
            </CustomScrollArea>
        </div>
    )
}

/** List 行 */
function ListRow({
    item,
    onDetail,
    detailTo,
    projectId,
}: {
    item: MediaPublic
    onDetail?: () => void
    detailTo?: string
    projectId?: number | null
}) {
    const isMetadata = isGalleryMetadataItem(item)
    const isPhoto = String(item.media_type ?? "").toLowerCase() === "photo"
    const metadataMediaKind = isMetadata ? getMetadataMediaKind(item) : null
    const isNonNavigable = !detailTo && !onDetail

    const srHz = Number(item.sampling_rate_hz);
    const displaySr = !isNaN(srHz) && srHz > 0
        ? `${srHz / 1000}kHz`
        : undefined;

    const sizeB = Number(item.size_b);
    const displaySize = !isNaN(sizeB) && sizeB > 0
        ? `${(sizeB / (1024 * 1024)).toFixed(2)} MB`
        : undefined;

    const durS = Number(item.duration_s);
    const displayDuration = !isNaN(durS) && durS > 0
        ? formatDuration(durS)
        : undefined;

    const { displayDate, displayTime } = splitMediaDisplayDateTime(item)
    const metadataProgress = isNonNavigable ? formatMetadataProgress(item) : "-"
    const showMetadataProgress = isMetadata && hasCompleteMetadataDutyCycle(item)

    const labelNames = getMediaLabelNames(item);
    const hierarchy = safeArray(item.hierarchy, '>');
    const topographyM = formatTopographyMeters(item)
    const freshwaterDepthM = formatFreshwaterDepth(item)

    const rawListSpectrogram = !isMetadata
        ? (item.spectrogram ??
            (item as Record<string, unknown>).preview_url ??
            undefined)
        : undefined
    const listMediaNumericId = !isMetadata ? resolveMediaNumericId(item) : null
    const listSpectrogramUrl = useMediaSpectrogramUrl(
        typeof rawListSpectrogram === "string" ? rawListSpectrogram : undefined,
        listMediaNumericId,
        projectId,
    )

    const rowClass = `media-item-row${isMetadata ? " media-item-row--metadata" : ""}`

    const themeValue = resolveMediaThemeValue(item)
    const tagPillStyle = getRealmTagPillStyle(themeValue)
    const accentStyle = getRealmAccentVars(themeValue)

    const annotationsRow = (
        <div className="annotations-row">
            {labelNames.length > 0
                ? labelNames.map((l: string, idx: number) => (
                    <span key={`lab-${idx}`} className="media-annotation" style={tagPillStyle}>
                        {l}
                    </span>
                ))
                : null}
        </div>
    )

    return (
        <div className={rowClass} style={accentStyle}>
            <ActionLink detailTo={detailTo} onDetail={onDetail} className={`list-spec-container${isMetadata ? " list-spec-container--metadata" : ""}`}>
                {isMetadata ? (
                    <div className="metadata-cover">
                        {metadataMediaKind === "photo" ? (
                            <ImageIcon className="metadata-icon" aria-hidden />
                        ) : (
                            <FileAudio className="metadata-icon" aria-hidden />
                        )}
                        <span className="metadata-text">
                            {metadataMediaKind === "photo" ? "PHOTO METADATA" : "AUDIO METADATA"}
                        </span>
                    </div>
                ) : (
                    <UnifiedImage
                        src={listSpectrogramUrl}
                        className="list-spec-img"
                        alt={isPhoto ? item.name || item.filename || "Photo" : "Spectrogram"}
                    />
                )}
                {!isMetadata && isPhoto && Number(item.image_width) > 0 && Number(item.image_height) > 0 ? (
                    <div className="sr-badge">{Number(item.image_width)} × {Number(item.image_height)}</div>
                ) : null}
                {!isMetadata && !isPhoto && displaySr && <div className="sr-badge">{displaySr}</div>}
                {!isMetadata && !isPhoto && displayDuration && <div className="duration-badge">{displayDuration}</div>}
            </ActionLink>
            {isMetadata ? (
                <div className="row-basic-info list-row-metadata-main">
                    <ActionLink detailTo={detailTo} onDetail={onDetail} className="row-name" title={item.name ?? undefined}>
                        {item.name}
                    </ActionLink>
                    {annotationsRow}
                    <div className="row-meta-list">
                        <div className="row-meta-item">
                            <Calendar size={18} /> {displayDate || "-"}
                        </div>
                        <div className="row-meta-item">
                            <Clock size={18} /> {displayTime || "-"}
                        </div>
                        {showMetadataProgress ? (
                            <div className="row-meta-item meta-icon-text">
                                <Timer size={18} /> {metadataProgress}
                            </div>
                        ) : null}
                    </div>
                </div>
            ) : (
                <div className="row-basic-info">
                    <ActionLink detailTo={detailTo} onDetail={onDetail} className="row-name" title={item.name ?? undefined}>
                        {item.name}
                    </ActionLink>
                    {annotationsRow}
                    <div className="row-meta-list">
                        <div className="row-meta-item">
                            <Calendar size={18} /> {displayDate || "-"}
                        </div>
                        <div className="row-meta-item">
                            <Clock size={18} /> {displayTime || "-"}
                        </div>
                        <div className="row-meta-item">
                            {isNonNavigable ? (
                                <>
                                    <Timer size={18} /> {metadataProgress}
                                </>
                            ) : (
                                <>
                                    <HardDrive size={18} /> {displaySize}
                                </>
                            )}
                        </div>
                    </div>
                </div>
            )}

            <div className="row-details-col">
                <div className="rd-header-row">
                    <div className="rd-site-group">
                        <div className="rd-site-name">
                            <MapPin size={24} className="rd-site-pin" style={{ color: "var(--media-accent)" }} />
                            <span className="rd-site-title-text">
                                {item.site_name || "Unknown Site"}
                            </span>
                            {topographyM != null && (
                                <>
                                    <span className="rd-site-title-sep" aria-hidden />
                                    {/* 小于0时，不显示  */}
                                    {Number(topographyM) > 0 && (
                                        <span className="rd-site-topography">
                                            <Mountain size={22} className="rd-topography-icon" style={{ color: "var(--media-accent)" }} aria-hidden />
                                            <span>{topographyM}m</span>
                                        </span>
                                    )}
                                </>
                            )}
                            {freshwaterDepthM != null && (
                                <>
                                    <span className="rd-site-title-sep" aria-hidden />
                                    <span className="rd-site-topography">
                                        <Waves size={22} className="rd-topography-icon" style={{ color: "var(--media-accent)" }} aria-hidden />
                                        <span>{freshwaterDepthM}m</span>
                                    </span>
                                </>
                            )}
                        </div>
                        {item.elevation && (
                            <div className="rd-site-metrics">
                                <span><Mountain size={22} />{item.elevation}</span>
                            </div>
                        )}
                    </div>
                    {hierarchy.length > 0 && (
                        <div className="rd-hierarchy">
                            {hierarchy.map((h: string, i: number) => (
                                <span
                                    key={i}
                                    className={`rd-hierarchy-item${i === 0 ? " rd-hierarchy-item--accent" : ""}`}
                                >
                                    {h}
                                    {i < hierarchy.length - 1 && <ChevronRight size={12} className="rd-bread-sep" />}
                                </span>
                            ))}
                        </div>
                    )}
                </div>

                <div className="rd-grid">
                    <div className="rd-item">
                        <span className="rd-label">MEDIUM</span>
                        <span className="rd-val">{item.medium || "-"}</span>
                    </div>
                    <div className="rd-item">
                        <span className="rd-label">SENSOR</span>
                        <span className="rd-val">{item.sensor_name || "-"}</span>
                    </div>
                    <div className="rd-item">
                        <span className="rd-label">LICENSE</span>
                        <span className="rd-val">{item.license_name || "-"}</span>
                    </div>

                    <div className="rd-item span-v">
                        <span className="rd-label">NOTE</span>
                        <span className="rd-val" title={item.note || "-"}>{item.note || "-"}</span>
                    </div>

                    <div className="rd-item">
                        <span className="rd-label">UPLOADER</span>
                        <span className="rd-val">{item.uploader_name || item.uploader_id || "-"}</span>
                    </div>
                    <div className="rd-item">
                        <span className="rd-label">CREATOR</span>
                        <span className="rd-val">{item.creator_name || item.creator_id || "-"}</span>
                    </div>
                    <div className="rd-item">
                        <span className="rd-label">DOI</span>
                        <span className="rd-val">{item.doi || "-"}</span>
                    </div>
                </div>

            </div>
        </div>
    )
}
