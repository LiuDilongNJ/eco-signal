import { Button as ESButton, Input as ESInput } from "@/components/ui"
/**
 * MediaDetailView - 统一媒体详情页
 *
 * 音频与图片共用详情工作台、标注表格和信息面板，仅替换主查看器。
 * 顶栏项目/集合切换由 ProjectNavBar 处理。
 */

import {
    useState,
    useEffect,
    useRef,
    useCallback,
    useLayoutEffect,
    useMemo,
    type Key,
    type PointerEvent,
    type ReactNode,
} from "react"
import { useLocation, useParams } from "react-router-dom"
import { message } from "@/components/ui"
import { downloadFile } from "@/utils/download"
import { NoDataIcon } from "@/components/ui"
import { UnifiedImage } from "@/components/ui"
import {
    Info,
    Tag,
    X,
    Headphones,
    SquareActivity,
    Eye,
    EyeOff,
    ChevronLeft,
    ChevronRight,
    ChevronUp,
    ChevronDown,
    ChevronsUpDown,
    ZoomIn,
    ZoomOut,
    StretchHorizontal,
    Play,
    Pause,
    Square,
    ArrowRightFromLine,
    Filter,
    Download,
    RotateCcw,
    ClipboardList,
    Trash2,
    MapPin,
    Cpu,
    BarChart2,
    AudioLines,
    ArrowLeft,
    Scan,
    Search,
    Volume2,
    Move,
    Share2,
} from "lucide-react"
import {
    mediaApi,
    RECORDING_FFT_SIZES,
    type RecordingDetail,
} from "../../../../api/endpoints/media"
import {
    audioViewportParamsKey,
    buildMediaViewportParams,
    toAudioQueryParams,
    toSpectrogramQueryParams,
    viewportParamsKey,
    type MediaViewportParams,
} from "./mediaViewportParams"
import { apiClient } from "../../../../api/client"
import { getApiData } from "../../../../api/utils"
import {
    annotationsApi,
    type AnnotationListParams,
    type AnnotationPublic,
    type AnnotationWithReviews,
    type CreateAnnotationPayload,
    type UpdateAnnotationPayload,
} from "../../../../api/endpoints/annotations"
import { tasksApi, type AssignableUserPublic } from "../../../../api/endpoints/tasks"
import {
    reviewsApi,
    type AnnotationReviewRead,
} from "../../../../api/endpoints/reviews"
import { labelsApi, fetchLabelsCatalog, type LabelPublic } from "../../../../api/endpoints/labels"
import type { UserPublic } from "../../../../api/endpoints/users"
import { taxonsApi, type SoundClassificationPublic } from "../../../../api/endpoints/taxons"
import { isSelectScrollNearBottom } from "@/hooks/usePagedSelectOptions"
import { useTaxonSearchOptions } from "@/hooks/useTaxonSearchOptions"
import { userPreferenceApi, type UserPreference } from "../../../../api/endpoints/users"
import { isFunctionalCookiesAllowed } from "../../../home/cookieConsent"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { applySphereTheme } from "../../sphereTheme"

function openLoadingMessage(content: string): string {
    const key = `msg-${Date.now()}-${Math.random().toString(16).slice(2)}`
    message.open({ type: "loading", content, duration: 0, key })
    return key
}

function closeLoadingMessage(key: string) {
    message.destroy(key)
}

function updateMessageSuccess(key: string, content: string) {
    message.open({ type: "success", content, key, duration: 2 })
}

function updateMessageError(key: string, content: string) {
    message.open({ type: "error", content, key, duration: 2 })
}
import { useProjectStore } from "../../stores/useProjectStore"
import { usePermissions } from "@/hooks/usePermissions"
import { StudioCrumbDropdown } from "../nav/StudioCrumbDropdown"
import {
    Button,
    Checkbox,
    Col,
    ConfigProvider,
    DataTable,
    Divider,
    DropdownMenuButton,
    Form,
    Input,
    InputNumber,
    Popconfirm,
    Popover,
    Row,
    Select,
    Space,
    Switch,
} from "@/components/ui"
import type { MenuProps } from "@/components/ui"
import type { ColumnDef } from "../data/DataPageLayout"
import "../data/styles/DataPageLayout.css"
import "../modals/styles/RunAIModelsDrawer.css"
import "../modals/styles/AssignTasksDrawer.css"
import { formatDuration, splitMediaDisplayDateTime } from "./MediaGalleryCard"
import { RunAIModelsDrawer } from "../modals/RunAIModelsDrawer"
import { AcousticIndicesDrawer } from "../modals/AcousticIndicesDrawer"
import { AcousticAnalysisStudioPanel } from "./AcousticAnalysisStudioPanel"
import { PhotoImageViewer, type PhotoAnnotationBox, type PhotoZoomRequest } from "./PhotoImageViewer"
import { MediaViewerToolbarButton } from "./MediaViewerToolbarButton"
import {
    getMediaAnnotationPresentation,
    mediaAnnotationClassName,
    normalizeUserColorHex,
} from "./mediaAnnotationPresentation"
import { ConfirmDialog } from "../modals/ConfirmDialog"
import { CustomScrollArea } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { authUtils } from "@/utils/auth"
import "../modals/styles/SetLabelsDrawer.css"

import {
    type StudioRightPanel,
    ANNOTATION_TABLE_SCROLL_BUFFER_PX,
    CHANNEL_DROPDOWN_ITEMS,
    FFT_DROPDOWN_ITEMS,
    PLAYBACK_RATE_SLIDER_MIN,
    PLAYBACK_RATE_SLIDER_MAX,
    SPECTROGRAM_ZOOM_STEP,
    SPECTROGRAM_FREQ_WINDOW_EPSILON_HZ,
    SPECTROGRAM_DRAFT_MIN_SIZE_PX,
    SPECTROGRAM_PX_PER_SEC_MIN,
    SPECTROGRAM_CONTROL_COOLDOWN_MS,
    AUDIO_CONTROL_COOLDOWN_MS,
    CONTINUOUS_PREFETCH_LEAD_S,
    CONTINUOUS_SCHEDULE_AHEAD_S,
    CONTINUOUS_ADVANCE_EPSILON_S,
    CONTINUOUS_MIN_SCHEDULE_DELAY_S,
    clamp,
    logAudioBufferSignal,
    logAudioBlobSignal,
    normalizeSpectrogramPxPerSec,
    formatDisplayNumber,
    formatSpectrogramPxPerSecDisplay,
    roundAnnotationCoord,
    snapVisibleRangeEndSec,
    compareAnnotationByMinTimeAndFrequency,
    nextAnnotationAfterByTime,
    isLabelSystemProtected,
    spectrogramVisibleWindowSec,
    spectrogramMinWindowSec,
    resolveSpectrogramViewportWindow,
    windowSecFromPxPerSec,
    snapTimeSec,
    resolveSpectrogramZoomWindow,
    resolveSpectrogramViewStart,
    hexColorToRgba,
    SOUNDSCAPE_LABELS,
    buildSoundscapeSelectOptions,
    selectSearchFilter,
    buildAnimalSoundSelectOptions,
    renderStudioRequiredLabel,
    formatAnnotationTimeSec,
    formatAnnotationHz,
    type MagnifierLayout,
    type ContinuousPlaybackSegment,
    type ContinuousDecodedSegment,
    type ContinuousPlaybackEngine,
    type PrefetchedSpectrogram,
    continuousSegmentKey,
    physBoxFreqBandHz,
    computeMagnifierLayoutForAnnotation,
    STUDIO_ANNOTATION_COLUMNS,
    PHOTO_STUDIO_ANNOTATION_COLUMNS,
    type StudioAnnotationRow,
    annotationHasTaskTagForNav,
    annotationPublicToStudioRow,
    mergeStudioAnnotationQuery,
    annotationTableBoolBadge,
    dataModuleBoolBadge,
    annotationCreatorTypeBadgeLabel,
    annotationConfidenceTier,
    AutoFitBadgeText,
    REVIEW_STATUS_IDS,
    reviewStatusRequiresTaxon,
    reviewStatusDisablesTaxon,
    normalizeAnnotationReviews,
    pickAnnotationIdFromPublic,
    copyTextToClipboard,
    setAnnotationShareParam,
    reviewStatusVisualKey,
    formatReviewDateDisplay,
    formatReviewDateOnlyDisplay,
    normalizeRecordingDetail,
    resolveSpectrogramRequestSize,
    spectrogramRequestParamsKey,
    pickRecordingDetailId,
    resolveDetailThemeValue,
    type AnnotationPhysBox,
    type PixelRect,
    type DraftResizeHandle,
    DRAFT_RESIZE_HANDLES,
    normalizeDraftPixelRect,
    resizeDraftPixelRectFromHandle,
    physToPixelsWindow,
    pixelsToPhysWindow,
    normalizeAnnotationOverlayRect,
    type MediaDetailViewProps,
    SPEC_ZOOM_COOKIE_KEY,
    SPEC_ZOOM_DRAFT_IN_COOKIE_KEY,
    SPEC_ZOOM_DRAFT_OUT_COOKIE_KEY,
    SPEC_PXS_COOKIE_KEY,
    DEFAULT_SPECTROGRAM_PX_PER_SEC,
    ANNOT_SAVE_MODE_COOKIE_KEY,
    parseSpectrogramZoomPercent,
    storeSpectrogramZoomPercentCookie,
    type AnnotationSaveMode,
    ANNOTATION_SAVE_MODE_LABELS,
    ANNOTATION_SAVE_MODE_MENU_ITEMS,
    parseAnnotationSaveModeCookie,
    pickMatchingAnnotationIdFromList,
    getCookieValue,
    setCookieValue,
} from "./media-detail/mediaDetailSupport"

export function MediaDetailView({ mediaId }: MediaDetailViewProps) {
    const { id: projectRouteId } = useParams<{ id?: string }>()
    const location = useLocation()
    const storeProjectId = useProjectStore((s) => s.currentProjectId)
    const currentProjectId = useMemo(() => {
        const routeId = projectRouteId != null && String(projectRouteId).trim() !== "" ? Number(projectRouteId) : NaN
        if (Number.isFinite(routeId) && routeId > 0) return Math.trunc(routeId)
        const storeId = storeProjectId != null && String(storeProjectId).trim() !== "" ? Number(storeProjectId) : NaN
        return Number.isFinite(storeId) && storeId > 0 ? Math.trunc(storeId) : null
    }, [projectRouteId, storeProjectId])
    const routeAnnotationId = useMemo(() => {
        const raw = new URLSearchParams(location.search).get("annotation_id")
        if (raw == null || raw.trim() === "") return null
        const parsed = Number(raw)
        return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : null
    }, [location.search])

    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const isThemeTransitioning = useAppStore((s) => s.isThemeTransitioning)
    const [media, setMedia] = useState<RecordingDetail | null>(null)
    const isPhoto = String(media?.media_type ?? "").toLowerCase() === "photo"
    const [photoContentUrl, setPhotoContentUrl] = useState<string | null>(null)
    const [photoZoomRequest, setPhotoZoomRequest] = useState<PhotoZoomRequest | null>(null)
    const handlePhotoContentReady = useCallback((url: string | null) => {
        setPhotoContentUrl(url)
    }, [])
    const detailThemeValue = useMemo(() => resolveDetailThemeValue(media), [media])
    const antdAppTheme = useAntdBrandConfig(isDark, detailThemeValue)
    const [loading, setLoading] = useState(true)
    const [analysisBlocking, setAnalysisBlocking] = useState(false)
    const [detailError, setDetailError] = useState<string | null>(null)
    const [spectrogramBlobUrl, setSpectrogramBlobUrl] = useState<string | null>(null)
    const [spectrogramLoading, setSpectrogramLoading] = useState(false)
    const [spectrogramInitialReady, setSpectrogramInitialReady] = useState(false)
    const [spectrogramRetryToken, setSpectrogramRetryToken] = useState(0)
    const spectrogramBlobUrlRef = useRef<string | null>(null)
    const spectrogramRequestIdRef = useRef(0)
    const [audioBlobUrl, setAudioBlobUrl] = useState<string | null>(null)
    const [audioLoading, setAudioLoading] = useState(false)
    const [audioReady, setAudioReady] = useState(false)
    const audioRequestIdRef = useRef(0)
    const activeAudioRequestIdRef = useRef(0)
    const audioElementRequestIdRef = useRef(0)

    const restoreThemeFromStore = useCallback(() => {
        const { currentCollectionId: cid, collectionOptions } = useProjectStore.getState()
        const col = collectionOptions.find(
            (c: { id?: number | string; sphere?: unknown }) => String(c.id) === String(cid ?? ""),
        )
        applySphereTheme(col?.sphere ?? null)
    }, [])

    const [isPlaying, setIsPlaying] = useState(false)
    const [currentTime, setCurrentTime] = useState(0)
    const [playbackSpeed, setPlaybackSpeed] = useState(1)
    const [annotationsVisible, setAnnotationsVisible] = useState(true)
    const [fftValue, setFftValue] = useState("1024")
    const [continuousSegmentPlayback, setContinuousSegmentPlayback] = useState(false)
    /** 声谱图横向缩放 0–100：越大放大越多（可见时间窗越短） */
    const [spectrogramZoomPercent, setSpectrogramZoomPercent] = useState(() =>
        parseSpectrogramZoomPercent(getCookieValue(SPEC_ZOOM_COOKIE_KEY), 50),
    )
    // 两个输入框互不联动：输入只是草稿值，不会立刻影响频谱图；点击按钮才应用
    const [spectrogramZoomDraftIn, setSpectrogramZoomDraftIn] = useState(() => {
        const raw = getCookieValue(SPEC_ZOOM_DRAFT_IN_COOKIE_KEY)
        const n = raw != null ? Number(raw) : NaN
        return Number.isFinite(n) ? String(clamp(Math.round(n), 0, 100)) : String(spectrogramZoomPercent)
    })
    const [spectrogramZoomDraftOut, setSpectrogramZoomDraftOut] = useState(() => {
        const raw = getCookieValue(SPEC_ZOOM_DRAFT_OUT_COOKIE_KEY)
        const n = raw != null ? Number(raw) : NaN
        return Number.isFinite(n) ? String(clamp(Math.round(n), 0, 100)) : String(spectrogramZoomPercent)
    })
    /** 可见窗左边缘对应时间（秒） */
    const [spectrogramViewStart, setSpectrogramViewStart] = useState(0)
    /** 放大镜已把声谱图缩到选区/标注时高亮按钮，便于再次点击恢复 */
    const [spectrogramMagnifierZoomed, setSpectrogramMagnifierZoomed] = useState(false)
    const spectrogramMagnifierZoomedRef = useRef(false)
    /** 全部音频共用的 px/s 偏好；从全局 cookie 读取，无值时默认 15 px/s */
    const [spectrogramPxPerSec, setSpectrogramPxPerSec] = useState(() => {
        const raw = getCookieValue(SPEC_PXS_COOKIE_KEY)
        const n = raw != null ? Number(raw) : NaN
        return Number.isFinite(n) ? normalizeSpectrogramPxPerSec(n) : DEFAULT_SPECTROGRAM_PX_PER_SEC
    })
    const [spectrogramPxPerSecDraft, setSpectrogramPxPerSecDraft] = useState(() =>
        formatSpectrogramPxPerSecDisplay(spectrogramPxPerSec),
    )
    /** 正在拖拽声谱图红线 scrub */
    const [spectrogramProgressScrubbing, setSpectrogramProgressScrubbing] = useState(false)
    /** 立体声：只影响 spectrogram channel；audio keeps the original channels. */
    const [audioChannel, setAudioChannel] = useState<1 | 2>(1)
    /**
     * 频段过滤播放：true = 按当前可见频段请求窄带音频（filter=true）；false = 全频段（filter=false）
     */
    const [audioBandFilter, setAudioBandFilter] = useState(false)
    /** 声谱图纵轴可见频段（Hz）；与后续频率缩放联动，默认同录音 Nyquist */
    const [specFreqMinHz, setSpecFreqMinHz] = useState(1)
    const [specFreqMaxHz, setSpecFreqMaxHz] = useState(24_000)
    const audioRef = useRef<HTMLAudioElement | null>(null)
    const audioPreserveTimeRef = useRef<number | null>(null)
    const continuousSegmentPlaybackRef = useRef(false)
    const continuousEngineRef = useRef<ContinuousPlaybackEngine | null>(null)
    const continuousRunIdRef = useRef(0)
    const continuousUiTickRef = useRef<number | null>(null)
    const continuousPlayingAnnotationRef = useRef<AnnotationPublic | null>(null)
    const stopContinuousPlaybackRef = useRef<(opts?: { keepToggle?: boolean }) => void>(() => {})
    const startContinuousPlaybackRef = useRef<(opts?: { startAt?: number; forceViewport?: boolean }) => void>(() => {})
    /** 当前 audio blob 对应的视口 start_time（秒）；element.currentTime 为相对该起点的偏移 */
    const audioWindowStartRef = useRef(0)
    /** 当前 audio blob 对应的视口 end_time（秒）；普通播放边界以实际 blob 为准 */
    const audioWindowEndRef = useRef(0)
    /** 当前 spectrogram 请求使用的视口参数 key */
    const activeViewportParamsKeyRef = useRef<string | null>(null)
    const prefetchedSpectrogramsRef = useRef(new Map<string, PrefetchedSpectrogram>())
    const prefetchingSpectrogramKeysRef = useRef(new Set<string>())
    const pendingDisplayPrefetchedSpectrogramKeyRef = useRef<string | null>(null)
    /** 当前 audio 请求使用的视口参数 key */
    const activeAudioViewportParamsKeyRef = useRef<string | null>(null)
    /** 与 lastAudioBandpassKeyRef 配套的 reload token，用于区分「仅纵轴缩放」与「强制重载」 */
    const lastFetchedAudioReloadTokenRef = useRef(-1)
    /** 放大镜/标注放大：下一次音频请求须使用的频段（避免 state 批处理滞后） */
    const pendingAudioBandpassHzRef = useRef<{ lo: number; hi: number } | null>(null)
    const [audioReloadToken, setAudioReloadToken] = useState(0)
    const pendingZoomSeekTimeRef = useRef<number | null>(null)
    const currentTimeRef = useRef(0)
    const userScrubbedPlaybackTimeRef = useRef<number | null>(null)
    const playbackSpeedRef = useRef(playbackSpeed)
    const spectrogramViewStartRef = useRef(0)
    const spectrogramZoomPercentRef = useRef(0)
    const spectrogramPxPerSecRef = useRef(spectrogramPxPerSec)
    /** 进入新录音后待按整段时长适配声谱图视窗（viewport 就绪后执行一次） */
    const spectrogramFitPendingMediaIdRef = useRef<number | null>(null)
    const spectrogramCursorTimeRef = useRef<number | null>(null)
    const spectrogramCursorFracRef = useRef<number | null>(null)
    /** 点击放大镜缩放声谱图前保存的视窗，再次点击恢复（含频率轴范围） */
    const spectrogramMagnifierBackupRef = useRef<{
        zoomPercent: number
        viewStart: number
        freqMinHz: number
        freqMaxHz: number
    } | null>(
        null,
    )
    const mediaDurationForPlaybackRef = useRef(0)
    const viewportRef = useRef<HTMLDivElement | null>(null)
    const seekSpectrogramToClientXRef = useRef<((clientX: number) => void) | null>(null)
    const spectrogramShortcutHandlersRef = useRef<{
        playToggle: (() => void) | null
        panLeft: (() => void) | null
        panRight: (() => void) | null
    }>({
        playToggle: null,
        panLeft: null,
        panRight: null,
    })
    const draftInteractionRef = useRef<
        | {
            mode: "create"
            pointerId: number
            x0: number
            y0: number
            x1: number
            y1: number
            panelOpened: boolean
        }
        | {
            mode: "move"
            pointerId: number
            startClientX: number
            startClientY: number
            startRect: PixelRect
            viewportW: number
            viewportH: number
        }
        | {
            mode: "resize"
            pointerId: number
            handle: DraftResizeHandle
            startClientX: number
            startClientY: number
            startRect: PixelRect
            viewportW: number
            viewportH: number
        }
        | null
    >(null)

    const [rightPanel, setRightPanel] = useState<StudioRightPanel>("info")
    useEffect(() => {
        if (isPhoto && rightPanel === "ai-models") {
            setRightPanel("info")
        }
    }, [isPhoto, rightPanel])
    const handleAnalysisProcessingChange = useCallback((processing: boolean) => {
        setAnalysisBlocking(processing)
    }, [])
    const [viewportSize, setViewportSize] = useState({ w: 0, h: 0 })
    const viewportSizeRef = useRef(viewportSize)
    const syncIsPlayingFromAudio = useCallback(() => {
        if (continuousEngineRef.current) {
            setIsPlaying(true)
            return
        }
        const el = audioRef.current
        setIsPlaying(Boolean(el && !el.paused && !el.ended))
    }, [])
    const readViewportLayoutSize = useCallback((el: HTMLDivElement) => {
        const rect = el.getBoundingClientRect()
        return {
            rect,
            w: el.offsetWidth || rect.width,
            h: el.offsetHeight || rect.height,
        }
    }, [])
    const clientToViewportLayoutPoint = useCallback((el: HTMLDivElement, clientX: number, clientY: number) => {
        const { rect, w, h } = readViewportLayoutSize(el)
        const scaleX = rect.width > 0 ? w / rect.width : 1
        const scaleY = rect.height > 0 ? h / rect.height : 1
        return {
            x: clamp((clientX - rect.left) * scaleX, 0, w),
            y: clamp((clientY - rect.top) * scaleY, 0, h),
            w,
            h,
        }
    }, [readViewportLayoutSize])
    const clearPrefetchedSpectrogram = useCallback(() => {
        const prefetched = Array.from(prefetchedSpectrogramsRef.current.values())
        prefetchedSpectrogramsRef.current.clear()
        prefetchingSpectrogramKeysRef.current.clear()
        pendingDisplayPrefetchedSpectrogramKeyRef.current = null
        prefetched.forEach((item) => URL.revokeObjectURL(item.url))
    }, [])
    const setPlaybackTime = useCallback((time: number) => {
        currentTimeRef.current = time
        setCurrentTime(time)
    }, [])
    const [annotationDraft, setAnnotationDraft] = useState<AnnotationPhysBox | null>(null)
    const annotationDraftRef = useRef<AnnotationPhysBox | null>(null)
    const audioBandFilterRef = useRef(false)
    const [annotationDraftOverlayVisible, setAnnotationDraftOverlayVisible] = useState(true)
    const [marqueePx, setMarqueePx] = useState<{ left: number; top: number; width: number; height: number } | null>(
        null,
    )
    const [marqueeCreating, setMarqueeCreating] = useState(false)
    const [annotationDraftHasSize, setAnnotationDraftHasSize] = useState(false)
    const [deleteAnnotationsConfirmOpen, setDeleteAnnotationsConfirmOpen] = useState(false)
    const [deleteEditingAnnotationConfirmOpen, setDeleteEditingAnnotationConfirmOpen] = useState(false)
    const [annotationExportConfirmOpen, setAnnotationExportConfirmOpen] = useState(false)
    const [annotationExportConfirmCount, setAnnotationExportConfirmCount] = useState(0)
    const annotationExportActionRef = useRef<(() => Promise<void>) | null>(null)
    const commitSpectrogramPxPerSec = useCallback(
        (nextRaw: number, opts?: { syncDraft?: boolean }) => {
            const next = normalizeSpectrogramPxPerSec(nextRaw)
            setSpectrogramPxPerSec(next)
            setCookieValue(SPEC_PXS_COOKIE_KEY, String(next))
            spectrogramPxPerSecRef.current = next
            if (opts?.syncDraft !== false) {
                setSpectrogramPxPerSecDraft(formatSpectrogramPxPerSecDisplay(next))
            }
            return next
        },
        [],
    )

    useEffect(() => {
        const isEditableTarget = (target: EventTarget | null): boolean => {
            if (!(target instanceof HTMLElement)) return false
            const tag = target.tagName.toLowerCase()
            return (
                tag === "input" ||
                tag === "textarea" ||
                tag === "select" ||
                target.isContentEditable ||
                target.closest("[contenteditable='true']") != null
            )
        }

        const handleKeyDown = (event: KeyboardEvent) => {
            if (isEditableTarget(event.target)) return
            const isPanModifier = event.ctrlKey || event.metaKey
            const key = event.key === "Left" ? "ArrowLeft" : event.key === "Right" ? "ArrowRight" : event.key
            if (isPanModifier && !event.altKey && key === "ArrowLeft") {
                event.preventDefault()
                event.stopPropagation()
                event.stopImmediatePropagation()
                spectrogramShortcutHandlersRef.current.panLeft?.()
                return
            }
            if (isPanModifier && !event.altKey && key === "ArrowRight") {
                event.preventDefault()
                event.stopPropagation()
                event.stopImmediatePropagation()
                spectrogramShortcutHandlersRef.current.panRight?.()
                return
            }
            if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key === " ") {
                event.preventDefault()
                spectrogramShortcutHandlersRef.current.playToggle?.()
            }
        }

        window.addEventListener("keydown", handleKeyDown, true)
        document.addEventListener("keydown", handleKeyDown, true)
        return () => {
            window.removeEventListener("keydown", handleKeyDown, true)
            document.removeEventListener("keydown", handleKeyDown, true)
        }
    }, [])

    useEffect(() => {
        const raw = getCookieValue(SPEC_PXS_COOKIE_KEY)
        const parsed = raw != null ? Number(raw) : NaN
        const normalized = Number.isFinite(parsed)
            ? normalizeSpectrogramPxPerSec(parsed)
            : DEFAULT_SPECTROGRAM_PX_PER_SEC
        if (raw == null || !Number.isFinite(parsed) || String(normalized) !== raw) {
            setCookieValue(SPEC_PXS_COOKIE_KEY, String(normalized))
        }
    }, [])
    /** null = 未选声景；"" 表示 API 中 soundscape_component 为 null 的分组 */
    const [formSoundscape, setFormSoundscape] = useState<string | null>(null)
    const [formObjectType, setFormObjectType] = useState<"organism" | "other" | null>(null)
    /** 第二级下拉对应行的 sound_id，提交 AnnotationCreate.sound_id */
    const [formSoundTypeSoundId, setFormSoundTypeSoundId] = useState<number | null>(null)
    const [soundClassifications, setSoundClassifications] = useState<SoundClassificationPublic[]>([])
    const [animalSoundTypes, setAnimalSoundTypes] = useState<{ taxon_sound_type_id: number; name: string }[]>([])
    const [animalSoundTypesLoading, setAnimalSoundTypesLoading] = useState(false)
    const [formTaxonId, setFormTaxonId] = useState<number | null>(null)
    /** Biophony：选中分类的展示文案（外链 Images / Xeno-canto 检索用） */
    const [formTaxonSearch, setFormTaxonSearch] = useState("")
    const taxonOptionsState = useTaxonSearchOptions()
    const [formUncertain, setFormUncertain] = useState("")
    const [formAnimalSound, setFormAnimalSound] = useState("")
    const [formDistanceM, setFormDistanceM] = useState<number | null>(null)
    const [formDistanceNotEstimable, setFormDistanceNotEstimable] = useState(false)
    /** Biophony：须完整播放选区一次后才可输入距离（新建与编辑相同） */
    const [distanceFieldUnlocked, setDistanceFieldUnlocked] = useState(false)
    const previewSelectionActiveRef = useRef(false)
    const previewSelectionEndSecRef = useRef(0)
    /** 带通音频重载完成后继续标注选区试听 */
    const previewPlayAfterLoadRef = useRef<{ startAt: number; end: number } | null>(null)
    /** 切换过滤/连续播放后，如果原本在播放，标准 audio 重载完成后从该时间继续播放 */
    const standardPlayAfterLoadRef = useRef<number | null>(null)
    const previewWatchIntervalRef = useRef<number | null>(null)
    const previewSafetyTimerRef = useRef<number | null>(null)

    const clearPreviewWatchInterval = useCallback(() => {
        if (previewWatchIntervalRef.current != null) {
            window.clearInterval(previewWatchIntervalRef.current)
            previewWatchIntervalRef.current = null
        }
        if (previewSafetyTimerRef.current != null) {
            window.clearTimeout(previewSafetyTimerRef.current)
            previewSafetyTimerRef.current = null
        }
    }, [])

    /** 仅在有「任务」标记的标注间跳转（见 `annotationHasTaskTagForNav`）；可与 navAutoZoomToAnnotation 同时开启 */
    const [navOnlyTaskTagged, setNavOnlyTaskTagged] = useState(false)
    /** 上一条/下一条时是否自动将声谱图缩放到目标标注时间范围 */
    const [navAutoZoomToAnnotation, setNavAutoZoomToAnnotation] = useState(false)
    const [formIndividualNum, setFormIndividualNum] = useState(1)
    const [formReference, setFormReference] = useState("")
    const [formComments, setFormComments] = useState("")
    const [savePending, setSavePending] = useState(false)
    const [annotationSaveMode, setAnnotationSaveMode] = useState<AnnotationSaveMode>(() =>
        parseAnnotationSaveModeCookie(getCookieValue(ANNOT_SAVE_MODE_COOKIE_KEY)),
    )

    const persistAnnotationSaveMode = useCallback((mode: AnnotationSaveMode) => {
        setAnnotationSaveMode(mode)
        setCookieValue(ANNOT_SAVE_MODE_COOKIE_KEY, mode)
    }, [])

    const [annotationListItems, setAnnotationListItems] = useState<AnnotationPublic[]>([])
    const [annotationListLoading, setAnnotationListLoading] = useState(false)
    const [annotationListInitialReady, setAnnotationListInitialReady] = useState(false)
    const [annotationColumnFilters, setAnnotationColumnFilters] = useState<Record<string, string>>({})
    const [annotationSortKey, setAnnotationSortKey] = useState<string | null>(null)
    const [annotationSortDir, setAnnotationSortDir] = useState<"asc" | "desc" | null>(null)

    const toggleAnnotationSort = useCallback(
        (key: string) => {
            if (annotationSortKey === key) {
                setAnnotationSortDir(annotationSortDir === "asc" ? "desc" : "asc")
            } else {
                setAnnotationSortKey(key)
                setAnnotationSortDir("asc")
            }
        },
        [annotationSortKey, annotationSortDir],
    )

    const [annotationListTick, setAnnotationListTick] = useState(0)
    const [selectedAnnotationKeys, setSelectedAnnotationKeys] = useState<Key[]>([])
    /** 与表格勾选同步；在 setState updater 内更新，避免「勾选后立刻点分配任务」时 state 尚未提交读到旧值 */
    const annotationTableSelectedIdsRef = useRef<number[]>([])
    /** 避免表格勾选状态未变时重复 seek */
    const prevSelectionSeekKeyRef = useRef<string>("")
    /** 顶栏集合同步：每个 mediaId 只按详情里的 collection_id 对齐一次，避免列表刷新反复覆盖用户手选 */
    const navSyncedCollectionForMediaRef = useRef<number | null>(null)
    /** 声谱图 ↔ 表格：悬停联动高亮（annotation_id） */
    const [annotationLinkedHighlightId, setAnnotationLinkedHighlightId] = useState<number | null>(null)
    /** 声谱图叠加：当前媒体下全部标注（分页拉全），与表格分页无关 */
    const [spectrogramAnnotations, setSpectrogramAnnotations] = useState<AnnotationPublic[]>([])
    const spectrogramAnnotationsRef = useRef<AnnotationPublic[]>([])
    const routeAutoOpenedAnnotationKeyRef = useRef<string>("")
    useEffect(() => {
        spectrogramAnnotationsRef.current = spectrogramAnnotations
    }, [spectrogramAnnotations])

    /** 侧栏「分配任务」：§7.1 / §7.2（右栏全高面板） */
    const [assignableUsers, setAssignableUsers] = useState<AssignableUserPublic[]>([])
    const [assignableLoading, setAssignableLoading] = useState(false)
    const [assignSubmitPending, setAssignSubmitPending] = useState(false)
    const [assignSelectedUserIds, setAssignSelectedUserIds] = useState<number[]>([])
    /** 打开「分配任务」时快照的 annotation id，避免侧栏打开后表格重渲染清空 rowSelection 导致提交时误用全量 */
    const assignTaskAnnotationIdsRef = useRef<number[]>([])

    const annotationTableViewportRef = useRef<HTMLDivElement>(null)
    const annotationTableHTrackRef = useRef<HTMLDivElement>(null)
    const [annotationTableBodyScrollY, setAnnotationTableBodyScrollY] = useState(320)
    const [annotationTableHThumb, setAnnotationTableHThumb] = useState({
        show: false,
        size: 0,
        offset: 0,
    })
    const [annotationTableHDragging, setAnnotationTableHDragging] = useState(false)
    /** 侧栏：折叠 / 展开底部标注表 */
    const [annotationTableVisible, setAnnotationTableVisible] = useState(true)
    const annotationTableHDragRef = useRef<{
        pointerId: number
        startClient: number
        startScroll: number
        maxScroll: number
        maxOffset: number
    } | null>(null)
    /** 非 null 表示侧栏在编辑已有标注；null 表示新建（框选后） */
    const [editingAnnotationId, setEditingAnnotationId] = useState<number | null>(null)
    /** 编辑时 Save 上方展示的元信息（与 §4.5 详情一致） */
    const [editingAnnotationMeta, setEditingAnnotationMeta] = useState<AnnotationPublic | null>(null)
    /** 编辑时 GET 详情内嵌的 reviews */
    const [editingAnnotationReviews, setEditingAnnotationReviews] = useState<AnnotationReviewRead[]>([])
    /**
     * 连续播放时「当前标注」：优先侧栏正在编辑的标注；否则仅表格单选时取该条。
     */
    const playingAnnotationResolved = useMemo(() => {
        if (editingAnnotationMeta != null && editingAnnotationId != null && editingAnnotationId > 0) {
            return editingAnnotationMeta
        }
        if (selectedAnnotationKeys.length === 1) {
            const id = Number(selectedAnnotationKeys[0])
            if (Number.isFinite(id) && id > 0) {
                return spectrogramAnnotations.find((a) => a.annotation_id === id) ?? null
            }
        }
        return null
    }, [editingAnnotationId, editingAnnotationMeta, selectedAnnotationKeys, spectrogramAnnotations])

    const playingAnnotationRef = useRef<AnnotationPublic | null>(null)
    useEffect(() => {
        playingAnnotationRef.current = playingAnnotationResolved
    }, [playingAnnotationResolved])

    const annotationPanelActiveRef = useRef(false)
    annotationPanelActiveRef.current = rightPanel === "new-annotation"

    /** 有历史记录时：false 仅展示列表 + Edit（图2）；true 展示右侧表单（图1/图3） */
    const [reviewPanelExpanded, setReviewPanelExpanded] = useState(true)
    const [reviewStatusId, setReviewStatusId] = useState<number>(REVIEW_STATUS_IDS.accepted)
    const [reviewNote, setReviewNote] = useState("")
    const [reviewTaxonId, setReviewTaxonId] = useState<number | null>(null)
    const [reviewTaxonSearch, setReviewTaxonSearch] = useState("")
    const [reviewTaxonError, setReviewTaxonError] = useState<string | null>(null)
    const reviewTaxonOptionsState = useTaxonSearchOptions()
    const [reviewSubmitPending, setReviewSubmitPending] = useState(false)
    /** Edit：按 reviewer_id 拉取本人评审时的 loading */
    const [reviewEditLoading, setReviewEditLoading] = useState(false)
    const [meUserId, setMeUserId] = useState<number | null>(null)
    const [meIsProjectAdmin, setMeIsProjectAdmin] = useState(false)
    // Scoped to the project: the detail page may be reached with no single
    // collection selected, and per-collection denial still comes back as 403.
    const { can: canInProject } = usePermissions(currentProjectId)
    const canWriteReview = canInProject("review:write")
    const [userAnnotationColor, setUserAnnotationColor] = useState("#3B82F6")
    const [meUserReady, setMeUserReady] = useState(false)
    const pendingReviewInitRef = useRef(false)

    const annotationTableRows = useMemo(
        () => annotationListItems.map((annotation) => annotationPublicToStudioRow(annotation, meUserId)),
        [annotationListItems, meUserId],
    )
    /** GET /v1/labels，用于工具栏标签文案与接口定义对齐 */
    const [toolbarLabelsCatalog, setToolbarLabelsCatalog] = useState<LabelPublic[]>([])
    const [labelPopoverOpen, setLabelPopoverOpen] = useState(false)
    const [labelPopoverLoading, setLabelPopoverLoading] = useState(false)
    const [labelPopoverSaving, setLabelPopoverSaving] = useState(false)
    const [labelPopoverAdding, setLabelPopoverAdding] = useState(false)
    const [labelPopoverDeletingId, setLabelPopoverDeletingId] = useState<number | null>(null)
    const [labelPopoverList, setLabelPopoverList] = useState<LabelPublic[]>([])
    const [labelPopoverSelectedId, setLabelPopoverSelectedId] = useState<number | null>(null)
    const [labelPopoverNewName, setLabelPopoverNewName] = useState("")
    const spectrogramControlCooldownUntilRef = useRef(0)
    const audioControlCooldownUntilRef = useRef(0)

    const isSpectrogramBusy = spectrogramLoading
    const isAudioBusy = audioLoading || (audioBlobUrl != null && !audioReady)

    const runSpectrogramControl = useCallback((action: () => void): boolean => {
        const now = Date.now()
        if (spectrogramLoading || now < spectrogramControlCooldownUntilRef.current) return false
        spectrogramControlCooldownUntilRef.current = now + SPECTROGRAM_CONTROL_COOLDOWN_MS
        action()
        return true
    }, [spectrogramLoading])

    const soundscapeSelectOptions = useMemo(
        () => buildSoundscapeSelectOptions(soundClassifications),
        [soundClassifications],
    )

    const soundTypeSelectOptions = useMemo(() => {
        if (formSoundscape === null) return []
        const key = formSoundscape
        return soundClassifications
            .filter((r) => (r.soundscape_component ?? "") === key)
            .map((r) => ({
                value: r.sound_id,
                label: r.sound_type?.trim() ? r.sound_type : "General",
            }))
    }, [soundClassifications, formSoundscape])

    const animalSoundSelectOptions = useMemo(
        () => buildAnimalSoundSelectOptions(animalSoundTypes),
        [animalSoundTypes],
    )

    const annotationColumnsMeta = useMemo(() => {
        const creatorOpts = Array.from(
            new Set(annotationTableRows.map((r) => r.creator_type).filter(Boolean)),
        ) as string[]
        const soundTypeOpts = soundClassifications.map((r) => ({
            label: r.sound_type?.trim() ? r.sound_type : "General",
            value: String(r.sound_id),
        }))
        const seen = new Set<string>()
        const soundTypeDeduped = soundTypeOpts.filter((o) => {
            if (seen.has(o.value)) return false
            seen.add(o.value)
            return true
        })
        const soundscapeOpts = soundscapeSelectOptions.map((o) => ({
            label: o.label,
            value: o.value,
        }))
        return {
            creatorOptions: creatorOpts,
            soundTypeOptions: soundTypeDeduped,
            animalOptions: animalSoundSelectOptions,
            soundscapeOptions: soundscapeOpts,
        }
    }, [animalSoundSelectOptions, annotationTableRows, soundClassifications, soundscapeSelectOptions])

    const taxonSelectMergedOptions = useMemo(() => {
        const m = new Map<number, { value: number; label: string }>()
        for (const o of taxonOptionsState.options) m.set(o.value, o)
        if (formTaxonId != null && formTaxonId > 0 && formTaxonSearch.trim()) {
            if (!m.has(formTaxonId)) {
                m.set(formTaxonId, { value: formTaxonId, label: formTaxonSearch.trim() })
            }
        }
        return [...m.values()]
    }, [formTaxonId, formTaxonSearch, taxonOptionsState.options])

    const reviewTaxonSelectMergedOptions = useMemo(() => {
        const m = new Map<number, { value: number; label: string }>()
        for (const o of reviewTaxonOptionsState.options) m.set(o.value, o)
        if (reviewTaxonId != null && reviewTaxonId > 0 && reviewTaxonSearch.trim()) {
            if (!m.has(reviewTaxonId)) {
                m.set(reviewTaxonId, { value: reviewTaxonId, label: reviewTaxonSearch.trim() })
            }
        }
        return [...m.values()]
    }, [reviewTaxonId, reviewTaxonSearch, reviewTaxonOptionsState.options])

    useEffect(() => {
        let cancelled = false
        taxonsApi
            .getSoundClassifications(true)
            .then((rows) => {
                if (!cancelled) setSoundClassifications(rows)
            })
            .catch(() => {
                if (!cancelled) {
                    setSoundClassifications([])
                    message.error("Failed to load sound classifications")
                }
            })
        return () => {
            cancelled = true
        }
    }, [])

    useEffect(() => {
        let cancelled = false
            ; (async () => {
                try {
                    const res = await apiClient.get<{ code: number; message: string; data: UserPublic }>(
                        "/v1/current-user",
                        { ignoreUnauthorized: true }
                    )
                    const data = getApiData(res)
                    if (!cancelled) {
                        setMeUserId(typeof data.user_id === "number" ? data.user_id : null)
                        setMeIsProjectAdmin(Boolean(data.is_project_admin || data.is_admin))
                        const nextColor = normalizeUserColorHex(data.color) ?? "#3B82F6"
                        setUserAnnotationColor(nextColor)
                    }
                } catch {
                    if (!cancelled) {
                        setMeUserId(null)
                        setMeIsProjectAdmin(false)
                    }
                } finally {
                    if (!cancelled) setMeUserReady(true)
                }
            })()
        return () => {
            cancelled = true
        }
    }, [])

    useEffect(() => {
        const bio = formSoundscape !== null && formSoundscape.toLowerCase() === "biophony"
        if (!bio) {
            setAnimalSoundTypes([])
            setFormAnimalSound("")
            return
        }
        let cancelled = false
        setAnimalSoundTypesLoading(true)
        taxonsApi
            .getAnimalSoundTypes(undefined, true)
            .then((rows) => {
                if (!cancelled) setAnimalSoundTypes(rows)
            })
            .catch(() => {
                if (!cancelled) setAnimalSoundTypes([])
            })
            .finally(() => {
                if (!cancelled) setAnimalSoundTypesLoading(false)
            })
        return () => {
            cancelled = true
        }
    }, [formSoundscape])

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        setDetailError(null)
        setMedia(null)
        setSpectrogramBlobUrl(null)
        clearPrefetchedSpectrogram()
        const prevSpectrogramUrl = spectrogramBlobUrlRef.current
        spectrogramBlobUrlRef.current = null
        activeViewportParamsKeyRef.current = null
        if (prevSpectrogramUrl) URL.revokeObjectURL(prevSpectrogramUrl)
        setSpectrogramInitialReady(false)
        setAudioBlobUrl(null)
        standardPlayAfterLoadRef.current = null
        audioWindowEndRef.current = 0
        setPlaybackTime(0)
        setIsPlaying(false)
        userScrubbedPlaybackTimeRef.current = null
        setRightPanel("info")
        setAnnotationDraft(null)
        setMarqueePx(null)
        setMarqueeCreating(false)
        setAnnotationDraftHasSize(false)
        draftInteractionRef.current = null
        spectrogramMagnifierBackupRef.current = null
        setSpectrogramMagnifierZoomed(false)
        setNavOnlyTaskTagged(false)
        setNavAutoZoomToAnnotation(false)
        setFormSoundscape(null)
        setFormSoundTypeSoundId(null)
        setFormTaxonId(null)
        setFormTaxonSearch("")
        setFormUncertain("")
        setFormAnimalSound("")
        setFormDistanceM(null)
        setFormDistanceNotEstimable(false)
        setFormIndividualNum(1)
        setFormReference("")
        setFormComments("")
        setAnnotationListItems([])
        setAnnotationListInitialReady(false)
        setAnnotationColumnFilters({})
        setAnnotationSortKey(null)
        setAnnotationSortDir(null)
        setAnnotationListTick(0)
        setSelectedAnnotationKeys([])
        setAnnotationLinkedHighlightId(null)
        setSpectrogramAnnotations([])
        setEditingAnnotationId(null)
        setEditingAnnotationMeta(null)
        setEditingAnnotationReviews([])
        setReviewPanelExpanded(true)
        pendingReviewInitRef.current = false
        if (currentProjectId == null) {
            setDetailError("Missing project context")
            setLoading(false)
            return
        }
        setAssignableUsers([])
        setAssignSelectedUserIds([])
            ; (async () => {
                try {
                    const [raw, pref] = await Promise.all([
                        mediaApi.getRecordingDetail(mediaId, currentProjectId, true),
                        userPreferenceApi.get({ ignoreUnauthorized: true }).catch((): UserPreference => ({})),
                    ])
                    if (cancelled) return
                    setMedia(normalizeRecordingDetail(raw))
                    const pFft = pref.fft
                    if (
                        typeof pFft === "number" &&
                        (RECORDING_FFT_SIZES as readonly number[]).includes(pFft)
                    ) {
                        setFftValue(String(pFft))
                    }
                } catch (e: unknown) {
                    if (!cancelled) {
                        setDetailError(e instanceof Error ? e.message : "Failed to load media")
                        setMedia(null)
                    }
                } finally {
                    if (!cancelled) setLoading(false)
                }
            })()
        return () => {
            cancelled = true
        }
    }, [clearPrefetchedSpectrogram, mediaId, currentProjectId, setPlaybackTime])

    useEffect(() => {
        navSyncedCollectionForMediaRef.current = null
    }, [mediaId])

    useLayoutEffect(() => {
        if (detailThemeValue === undefined) return
        applySphereTheme(detailThemeValue)
    }, [detailThemeValue])

    useEffect(() => {
        return () => {
            restoreThemeFromStore()
        }
    }, [restoreThemeFromStore])

    useEffect(() => {
        if (loading || !media) return
        if (navSyncedCollectionForMediaRef.current === mediaId) return

        const cidRaw = media.collection_id
        const projectFromMedia = media.project_id
        const routePid =
            projectRouteId != null && String(projectRouteId).trim() !== ""
                ? Number(projectRouteId)
                : NaN
        const projectIdNum = (() => {
            if (projectFromMedia != null && Number.isFinite(Number(projectFromMedia))) {
                return Number(projectFromMedia)
            }
            if (Number.isFinite(routePid)) return routePid
            const cp = useProjectStore.getState().currentProjectId
            if (cp != null && cp !== "" && Number.isFinite(Number(cp))) return Number(cp)
            return NaN
        })()

        if (!Number.isFinite(projectIdNum)) {
            navSyncedCollectionForMediaRef.current = mediaId
            return
        }

        const run = async () => {
            try {
                const store = useProjectStore.getState()
                await store.fetchCollectionOptions(projectIdNum)
                // 如果用户已在顶栏明确选择了某个 collection（非 ""），不要用 media.detail 的 collection_id 覆写，
                // 否则会出现「切换集合 -> 自动又切回去」的竞态/回跳。
                const userSelectedCid = store.currentCollectionId
                const userHasExplicitCollection =
                    userSelectedCid != null && String(userSelectedCid) !== "" && String(userSelectedCid).trim() !== ""

                if (!userHasExplicitCollection && cidRaw != null && cidRaw !== undefined && Number.isFinite(Number(cidRaw))) {
                    const nCid = Number(cidRaw)
                    const opts = useProjectStore.getState().collectionOptions
                    const found = opts.find(
                        (c: { id?: unknown }) => c.id !== "" && String(c.id) === String(nCid),
                    )
                    if (found) store.selectCollection(found.id)
                }
            } catch {
                /* ignore */
            } finally {
                navSyncedCollectionForMediaRef.current = mediaId
            }
        }
        void run()
    }, [loading, media, mediaId, projectRouteId])

    useEffect(() => {
        if (!media) return
        const sr = Number(media.sampling_rate_hz)
        const nyq = !Number.isNaN(sr) && sr > 0 ? Math.round(sr / 2) : 24000
        setSpecFreqMinHz(1)
        setSpecFreqMaxHz(nyq)
    }, [media?.sampling_rate_hz, mediaId])

    useEffect(() => {
        spectrogramViewStartRef.current = spectrogramViewStart
    }, [spectrogramViewStart])

    useEffect(() => {
        spectrogramZoomPercentRef.current = spectrogramZoomPercent
    }, [spectrogramZoomPercent])

    useEffect(() => {
        spectrogramPxPerSecRef.current = spectrogramPxPerSec
    }, [spectrogramPxPerSec])

    useEffect(() => {
        viewportSizeRef.current = viewportSize
    }, [viewportSize])

    useEffect(() => {
        playbackSpeedRef.current = playbackSpeed
    }, [playbackSpeed])

    useEffect(() => {
        mediaDurationForPlaybackRef.current = Number(media?.duration_s) || 0
    }, [media?.duration_s])

    // 播放时用 rAF 提升进度条刷新频率。
    // 这里采用“常驻 rAF + paused 时不更新”的方式，避免暂停/恢复后因事件/重挂时序导致不刷新。
    useEffect(() => {
        let raf = 0
        let disposed = false
        const tick = () => {
            if (disposed) return
            const el = audioRef.current
            if (el && !el.paused) {
                const t = el.currentTime
                if (Number.isFinite(t)) {
                    const absT = audioWindowStartRef.current + t
                    setPlaybackTime(absT)
                }
            }
            raf = requestAnimationFrame(tick)
        }
        raf = requestAnimationFrame(tick)
        return () => {
            disposed = true
            cancelAnimationFrame(raf)
        }
    }, [audioBlobUrl, setPlaybackTime])

    useEffect(() => {
        annotationDraftRef.current = annotationDraft
    }, [annotationDraft])

    useEffect(() => {
        return () => {
            clearPreviewWatchInterval()
        }
    }, [clearPreviewWatchInterval])

    useEffect(() => {
        if (previewPlayAfterLoadRef.current) return
        clearPreviewWatchInterval()
        previewSelectionActiveRef.current = false
    }, [audioBlobUrl, clearPreviewWatchInterval])

    useEffect(() => {
        audioBandFilterRef.current = audioBandFilter
    }, [audioBandFilter])

    const buildDetailViewportParams = useCallback(
        (viewStartOverride?: number): MediaViewportParams | null => {
            if (!media) return null
            const dur = Number(media.duration_s) || 0
            if (dur <= 0) return null
            const { windowSec, viewStartClamped: vs } = resolveSpectrogramViewportWindow(
                dur,
                viewStartOverride ?? spectrogramViewStartRef.current,
                spectrogramZoomPercentRef.current,
            )
            const stereo = Number(media.channels) === 2
            const sr = Number(media.sampling_rate_hz)
            const nyq = !Number.isNaN(sr) && sr > 0 ? Math.round(sr / 2) : 24000
            let freqMinHz = specFreqMinHz
            let freqMaxHz = specFreqMaxHz
            const pendingBand = pendingAudioBandpassHzRef.current
            if (audioBandFilterRef.current) {
                if (pendingBand) {
                    freqMinHz = pendingBand.lo
                    freqMaxHz = pendingBand.hi
                } else {
                    const draft = annotationDraftRef.current
                    if (annotationPanelActiveRef.current && draft && !spectrogramMagnifierZoomedRef.current) {
                        const annotBand = physBoxFreqBandHz(draft, nyq)
                        freqMinHz = annotBand.lo
                        freqMaxHz = annotBand.hi
                    }
                }
            }
            return buildMediaViewportParams({
                durationS: dur,
                samplingRateHz: sr || 0,
                viewStart: vs,
                windowSec,
                freqMinHz,
                freqMaxHz,
                fftSize: Number(fftValue),
                stereo,
                audioChannel,
                bandFilter: audioBandFilterRef.current,
            })
        },
        [media, audioChannel, specFreqMinHz, specFreqMaxHz, fftValue],
    )

    useEffect(() => {
        if (!media || currentProjectId == null) {
            setSpectrogramLoading(false)
            return
        }
        if (String(media.media_type ?? "").toLowerCase() === "photo") {
            setSpectrogramLoading(false)
            setSpectrogramInitialReady(true)
            return
        }
        const viewport = buildDetailViewportParams(spectrogramViewStart)
        if (!viewport) {
            setSpectrogramLoading(false)
            return
        }

        const vp = viewportRef.current
        const { w: measuredWidth = 0, h: measuredHeight = 0 } = vp ? readViewportLayoutSize(vp) : {}
        const requestSize = resolveSpectrogramRequestSize(measuredWidth, measuredHeight)
        if (!requestSize) {
            setSpectrogramLoading(false)
            return
        }
        const paramsKey = spectrogramRequestParamsKey(viewport)
        if (paramsKey === activeViewportParamsKeyRef.current && spectrogramBlobUrlRef.current) {
            setSpectrogramInitialReady(true)
            return
        }

        const prefetched = prefetchedSpectrogramsRef.current.get(paramsKey)
        if (prefetched) {
            prefetchedSpectrogramsRef.current.delete(paramsKey)
            prefetchingSpectrogramKeysRef.current.delete(paramsKey)
            pendingDisplayPrefetchedSpectrogramKeyRef.current = null
            const prev = spectrogramBlobUrlRef.current
            spectrogramBlobUrlRef.current = prefetched.url
            setSpectrogramBlobUrl(prefetched.url)
            activeViewportParamsKeyRef.current = paramsKey
            setSpectrogramInitialReady(true)
            setSpectrogramLoading(false)
            if (prev) URL.revokeObjectURL(prev)
            return
        }

        if (continuousEngineRef.current && prefetchingSpectrogramKeysRef.current.has(paramsKey)) {
            pendingDisplayPrefetchedSpectrogramKeyRef.current = paramsKey
            setSpectrogramInitialReady(true)
            setSpectrogramLoading(false)
            return
        }

        let cancelled = false
        let url: string | null = null
        const requestId = ++spectrogramRequestIdRef.current
        pendingDisplayPrefetchedSpectrogramKeyRef.current = null
        setSpectrogramLoading(true)
        mediaApi
            .fetchSpectrogramBlob(
                mediaId,
                currentProjectId,
                toSpectrogramQueryParams(viewport, requestSize.width, requestSize.height),
                true,
            )
            .then(({ blob }) => {
                if (cancelled || requestId !== spectrogramRequestIdRef.current) return
                url = URL.createObjectURL(blob)
                const prev = spectrogramBlobUrlRef.current
                spectrogramBlobUrlRef.current = url
                setSpectrogramBlobUrl(url)
                activeViewportParamsKeyRef.current = paramsKey
                if (prev) URL.revokeObjectURL(prev)
            })
            .catch(() => {
                if (!cancelled && requestId === spectrogramRequestIdRef.current) {
                    setSpectrogramBlobUrl(null)
                }
            })
            .finally(() => {
                if (!cancelled && requestId === spectrogramRequestIdRef.current) {
                    setSpectrogramInitialReady(true)
                    setSpectrogramLoading(false)
                }
            })
        return () => {
            cancelled = true
            if (url) URL.revokeObjectURL(url)
        }
    }, [
        media,
        mediaId,
        currentProjectId,
        fftValue,
        audioChannel,
        audioBandFilter,
        specFreqMinHz,
        specFreqMaxHz,
        spectrogramZoomPercent,
        spectrogramViewStart,
        spectrogramRetryToken,
        buildDetailViewportParams,
        readViewportLayoutSize,
        clearPrefetchedSpectrogram,
    ])

    useEffect(() => {
        // 确保卸载时回收最后一个 spectrogram blob url（避免频繁切 FFT 时泄漏）
        return () => {
            const prev = spectrogramBlobUrlRef.current
            spectrogramBlobUrlRef.current = null
            if (prev) URL.revokeObjectURL(prev)
            const prefetched = Array.from(prefetchedSpectrogramsRef.current.values())
            prefetchedSpectrogramsRef.current.clear()
            prefetchingSpectrogramKeysRef.current.clear()
            pendingDisplayPrefetchedSpectrogramKeyRef.current = null
            prefetched.forEach((item) => URL.revokeObjectURL(item.url))
        }
    }, [])

    useEffect(() => {
        if (!media) {
            stopContinuousPlaybackRef.current()
            const el = audioRef.current
            if (el) {
                try {
                    el.pause()
                } catch {
                    /* ignore */
                }
            }
            setIsPlaying(false)
            setAudioLoading(false)
            setAudioReady(false)
            return
        }
        if (String(media.media_type ?? "").toLowerCase() === "photo") {
            stopContinuousPlaybackRef.current()
            setIsPlaying(false)
            setAudioLoading(false)
            setAudioReady(false)
            setAudioBlobUrl(null)
            return
        }

        const viewport = buildDetailViewportParams()
        if (!viewport) return
        if (continuousSegmentPlaybackRef.current) return
        const paramsKey = audioViewportParamsKey(viewport)

        const el = audioRef.current
        if (
            paramsKey === activeAudioViewportParamsKeyRef.current &&
            pendingAudioBandpassHzRef.current == null &&
            audioReloadToken === lastFetchedAudioReloadTokenRef.current
        ) {
            return
        }

        if (audioPreserveTimeRef.current == null && el && Number.isFinite(el.currentTime)) {
            audioPreserveTimeRef.current = audioWindowStartRef.current + el.currentTime
        }

        let cancelled = false
        let url: string | null = null
        const requestId = ++audioRequestIdRef.current
        activeAudioRequestIdRef.current = requestId
        if (el) {
            try {
                el.pause()
            } catch {
                /* ignore */
            }
        }
        setIsPlaying(false)
        setAudioLoading(true)
        setAudioReady(false)
        setAudioBlobUrl(null)
        audioWindowEndRef.current = 0
        if (currentProjectId == null) {
            setIsPlaying(false)
            setAudioLoading(false)
            setAudioReady(false)
            return
        }
        mediaApi
            .fetchAudioBlob(mediaId, currentProjectId, toAudioQueryParams(viewport, audioReloadToken), true)
            .then(({ blob }) => {
                if (cancelled || requestId !== audioRequestIdRef.current) return
                logAudioBlobSignal(blob, {
                    mediaId,
                    source: "standard-playback",
                    viewport,
                    requestedBandFilter: audioBandFilter,
                })
                url = URL.createObjectURL(blob)
                activeAudioViewportParamsKeyRef.current = paramsKey
                lastFetchedAudioReloadTokenRef.current = audioReloadToken
                audioWindowStartRef.current = viewport.start_time
                audioWindowEndRef.current = viewport.end_time
                audioElementRequestIdRef.current = requestId
                setAudioLoading(false)
                if (audioBandFilter && pendingAudioBandpassHzRef.current != null) {
                    const sr = Number(media.sampling_rate_hz)
                    const nyq = sr > 0 ? Math.round(sr / 2) : 24000
                    const pendingLo = snapTimeSec(clamp(pendingAudioBandpassHzRef.current.lo, 0, nyq))
                    const pendingHi = snapTimeSec(
                        clamp(pendingAudioBandpassHzRef.current.hi, pendingLo, nyq),
                    )
                    if (
                        Math.abs(pendingLo - viewport.min_freq) < 1e-4 &&
                        Math.abs(pendingHi - viewport.max_freq) < 1e-4
                    ) {
                        pendingAudioBandpassHzRef.current = null
                    }
                }
                setAudioBlobUrl(url)
            })
            .catch(() => {
                if (!cancelled && requestId === audioRequestIdRef.current) {
                    setAudioBlobUrl(null)
                    audioWindowEndRef.current = 0
                    setAudioLoading(false)
                    setAudioReady(false)
                }
            })
        return () => {
            cancelled = true
            if (url) URL.revokeObjectURL(url)
        }
    }, [
        media,
        mediaId,
        currentProjectId,
        audioBandFilter,
        specFreqMinHz,
        specFreqMaxHz,
        spectrogramZoomPercent,
        spectrogramViewStart,
        buildDetailViewportParams,
        audioReloadToken,
        syncIsPlayingFromAudio,
    ])

    /** 切换声道后新 blob 加载完成，尽量恢复播放进度 */
    useEffect(() => {
        if (!audioBlobUrl) return
        const el = audioRef.current
        if (!el) return
        const targetAbs = audioPreserveTimeRef.current
        if (targetAbs == null || !Number.isFinite(targetAbs)) return
        audioPreserveTimeRef.current = null
        const apply = () => {
            const dur = el.duration
            const relative = targetAbs - audioWindowStartRef.current
            let appliedRelative = relative
            if (Number.isFinite(dur) && dur > 0) {
                appliedRelative = Math.min(Math.max(0, relative), dur)
                el.currentTime = appliedRelative
            } else {
                try {
                    el.currentTime = relative
                } catch {
                    /* ignore */
                }
            }
            if (Number.isFinite(appliedRelative)) {
                const windowEnd =
                    audioWindowEndRef.current > audioWindowStartRef.current
                        ? audioWindowEndRef.current
                        : audioWindowStartRef.current + appliedRelative
                setPlaybackTime(clamp(targetAbs, audioWindowStartRef.current, windowEnd))
            }
        }
        if (el.readyState >= 1) {
            apply()
            return
        }
        el.addEventListener("loadedmetadata", apply, { once: true })
        return () => el.removeEventListener("loadedmetadata", apply)
    }, [audioBlobUrl])

    const seekAudioElementToAbsoluteTime = useCallback((targetAbs: number) => {
        const a = audioRef.current
        if (!a || !Number.isFinite(targetAbs)) return false
        const relative = targetAbs - audioWindowStartRef.current
        try {
            const duration = Number(a.duration)
            a.currentTime =
                Number.isFinite(duration) && duration > 0
                    ? clamp(relative, 0, duration)
                    : Math.max(0, relative)
            return true
        } catch {
            return false
        }
    }, [])

    const spectrogramLayout = useMemo(() => {
        const dur = media ? Number(media.duration_s) || 0 : 0
        const w = viewportSize.w
        if (!media || dur <= 0 || w <= 0) {
            return { windowSec: 1, viewStartClamped: 0, innerW: 0, offsetX: 0 }
        }
        const { windowSec, viewStartClamped: vs } = resolveSpectrogramViewportWindow(
            dur,
            spectrogramViewStart,
            spectrogramZoomPercent,
        )
        // 后端按 start_time/end_time 生成当前窗口 PNG，前端不再用 transform 平移整张大图
        return { windowSec, viewStartClamped: vs, innerW: w, offsetX: 0 }
    }, [media, spectrogramViewStart, spectrogramZoomPercent, viewportSize.w])

    const spectrogramViewportFilter = useMemo(() => {
        if (!media) return null
        const dur = Number(media.duration_s) || 0
        const sr = Number(media.sampling_rate_hz) || 0
        if (!(dur > 0) || !(sr > 0)) return null
        const nyq = Math.round(sr / 2)
        const viewTimeStart = spectrogramLayout.viewStartClamped
        const viewTimeEnd = Math.min(viewTimeStart + spectrogramLayout.windowSec, dur)
        const viewFreqMin = clamp(specFreqMinHz, 0, nyq)
        const viewFreqMax = clamp(specFreqMaxHz, viewFreqMin, nyq)
        return {
            view_time_start: viewTimeStart,
            view_time_end: viewTimeEnd,
            view_freq_min: viewFreqMin,
            view_freq_max: viewFreqMax,
        }
    }, [media, spectrogramLayout.viewStartClamped, spectrogramLayout.windowSec, specFreqMaxHz, specFreqMinHz])

    const fetchAnnotationsForNavigation = useCallback(
        async (useFullAudio: boolean): Promise<AnnotationPublic[]> => {
            if (currentProjectId == null) return []
            return annotationsApi.listAll(
                {
                    media_id: mediaId,
                    project_id: currentProjectId,
                    order_by: "annotation_id",
                    order_dir: "asc",
                    ...(useFullAudio ? {} : (spectrogramViewportFilter ?? {})),
                },
                true,
            )
        },
        [currentProjectId, mediaId, spectrogramViewportFilter],
    )

    useEffect(() => {
        if (loading || !media) return
        let cancelled = false
        setAnnotationListLoading(true)
        const t = window.setTimeout(() => {
            ; (async () => {
                try {
                    const params = mergeStudioAnnotationQuery(
                        mediaId,
                        currentProjectId,
                        annotationSortKey,
                        annotationSortDir,
                        annotationColumnFilters,
                        spectrogramViewportFilter ?? undefined,
                    )
                    const items = await annotationsApi.listAll(params, true)
                    if (cancelled) return
                    setAnnotationListItems(items)
                } catch (e: unknown) {
                    if (!cancelled) {
                        message.error(e instanceof Error ? e.message : "Failed to load annotations")
                        setAnnotationListItems([])
                    }
                } finally {
                    if (!cancelled) {
                        setAnnotationListInitialReady(true)
                        setAnnotationListLoading(false)
                    }
                }
            })()
        }, 320)
        return () => {
            cancelled = true
            window.clearTimeout(t)
        }
    }, [
        loading,
        media,
        mediaId,
        annotationSortKey,
        annotationSortDir,
        annotationColumnFilters,
        annotationListTick,
        currentProjectId,
        spectrogramViewportFilter,
    ])

    useEffect(() => {
        if (loading || !media || !annotationsVisible) return
        if (currentProjectId == null) {
            setSpectrogramAnnotations([])
            return
        }
        let cancelled = false
            ; (async () => {
                try {
                    const items = await annotationsApi.listAll({
                            media_id: mediaId,
                            project_id: currentProjectId,
                            order_by: "annotation_id",
                            order_dir: "asc",
                            ...(spectrogramViewportFilter ?? {}),
                        }, true)
                    if (!cancelled) setSpectrogramAnnotations(items)
                } catch {
                    if (!cancelled) setSpectrogramAnnotations([])
                }
            })()
        return () => {
            cancelled = true
        }
    }, [loading, media, mediaId, currentProjectId, annotationsVisible, annotationListTick, spectrogramViewportFilter])

    const fetchSpectrogramAnnotationsForMedia = useCallback(async (): Promise<AnnotationPublic[]> => {
        if (currentProjectId == null) return []
        return annotationsApi.listAll(
            {
                media_id: mediaId,
                project_id: currentProjectId,
                order_by: "annotation_id",
                order_dir: "asc",
                ...(spectrogramViewportFilter ?? {}),
            },
            true,
        )
    }, [currentProjectId, mediaId, spectrogramViewportFilter])

    const handleDownloadViewportAudio = useCallback(async () => {
        if (!media || currentProjectId == null) return
        const viewport = buildDetailViewportParams()
        if (!viewport) return
        try {
            const download = await mediaApi.fetchAudioBlob(
                mediaId,
                currentProjectId,
                toAudioQueryParams(viewport),
            )
            downloadFile(download)
        } catch {
            message.error("Audio download failed")
        }
    }, [buildDetailViewportParams, currentProjectId, media, mediaId])

    const handleDownloadViewportSpectrogram = useCallback(async () => {
        if (!media || currentProjectId == null) return
        const viewport = buildDetailViewportParams()
        if (!viewport) return
        const measuredWidth =
            viewportSize.w > 0
                ? Math.round(viewportSize.w)
                : (() => {
                    const vp = viewportRef.current
                    if (!vp) return 0
                    const { w } = readViewportLayoutSize(vp)
                    return w > 0 ? Math.round(w) : 0
                })()
        const measuredHeight =
            viewportSize.h > 0
                ? Math.round(viewportSize.h)
                : (() => {
                    const vp = viewportRef.current
                    if (!vp) return 0
                    const { h } = readViewportLayoutSize(vp)
                    return h > 0 ? Math.round(h) : 0
                })()
        const requestSize = resolveSpectrogramRequestSize(measuredWidth, measuredHeight)
        if (!requestSize) {
            message.warning("Spectrogram size is not ready yet")
            return
        }
        try {
            const download = await mediaApi.fetchSpectrogramBlob(
                mediaId,
                currentProjectId,
                toSpectrogramQueryParams(viewport, requestSize.width, requestSize.height),
            )
            downloadFile(download)
        } catch {
            message.error("Spectrogram download failed")
        }
    }, [
        buildDetailViewportParams,
        currentProjectId,
        media,
        mediaId,
        readViewportLayoutSize,
        viewportSize.h,
        viewportSize.w,
    ])

    const acousticIndexSelection = useMemo(() => {
        if (!media) return null
        const dur = Number(media.duration_s) || 0
        if (dur <= 0) return null
        const sr = Number(media.sampling_rate_hz)
        const nyq = !Number.isNaN(sr) && sr > 0 ? Math.round(sr / 2) : 24000
        const minTime = clamp(spectrogramLayout.viewStartClamped, 0, dur)
        const maxTime = clamp(minTime + spectrogramLayout.windowSec, minTime, dur)
        const minFrequency = clamp(specFreqMinHz, 0, nyq)
        const maxFrequency = clamp(specFreqMaxHz, minFrequency, nyq)
        if (maxTime <= minTime || maxFrequency <= minFrequency) return null
        return {
            min_time: minTime,
            max_time: maxTime,
            min_frequency: Math.max(1, minFrequency),
            max_frequency: maxFrequency,
            filter_enabled: audioBandFilter,
        }
    }, [audioBandFilter, media, spectrogramLayout, specFreqMinHz, specFreqMaxHz])
    const acousticAnalysisIsFullTimeWindow = useMemo(() => {
        if (!media || !acousticIndexSelection) return false
        const dur = Number(media.duration_s) || 0
        return acousticIndexSelection.min_time <= 0.001 && Math.abs(acousticIndexSelection.max_time - dur) <= 0.001
    }, [acousticIndexSelection, media])

    useEffect(() => {
        if (!media) return
        const dur = Number(media.duration_s) || 0
        if (dur <= 0) return
        const { viewStartClamped: vs } = resolveSpectrogramViewportWindow(
            dur,
            spectrogramViewStart,
            spectrogramZoomPercent,
        )
        if (Math.abs(vs - spectrogramViewStart) > 1e-6) setSpectrogramViewStart(vs)
    }, [media, media?.duration_s, spectrogramViewStart, spectrogramZoomPercent])

    // px/s 仅作为用户手动输入并持久化的偏好值；当前视窗缩放由 zoomPercent 驱动。

    const renderedAnnotations = useMemo(() => {
        if (editingAnnotationId == null || editingAnnotationMeta == null) {
            return spectrogramAnnotations
        }
        const hasEditingAnnotation = spectrogramAnnotations.some(
            (annotation) => annotation.annotation_id === editingAnnotationId,
        )
        const currentAnnotation = {
            ...editingAnnotationMeta,
            annotation_id: editingAnnotationId,
        }
        return hasEditingAnnotation
            ? spectrogramAnnotations.map((annotation) =>
                annotation.annotation_id === editingAnnotationId ? currentAnnotation : annotation,
            )
            : [...spectrogramAnnotations, currentAnnotation]
    }, [editingAnnotationId, editingAnnotationMeta, spectrogramAnnotations])

    const annotationOverlayPx = useMemo(() => {
        if (!media || !annotationsVisible) return []
        const w = viewportSize.w
        const h = viewportSize.h
        if (w <= 0 || h <= 0) return []
        const sr = Number(media.sampling_rate_hz)
        const nyq = !Number.isNaN(sr) && sr > 0 ? Math.round(sr / 2) : 24000
        const f0 = clamp(specFreqMinHz, 0, nyq)
        const f1 = clamp(specFreqMaxHz, f0, nyq)
        const { windowSec, viewStartClamped } = spectrogramLayout
        const t0 = viewStartClamped
        const t1 = viewStartClamped + windowSec
        return renderedAnnotations
            .map((a) => {
                const phys: AnnotationPhysBox = {
                    min_x: Math.min(a.min_x, a.max_x),
                    max_x: Math.max(a.min_x, a.max_x),
                    min_y: Math.min(a.min_y, a.max_y),
                    max_y: Math.max(a.min_y, a.max_y),
                }
                if (phys.max_x < t0 || phys.min_x > t1) return null
                const pxRaw = physToPixelsWindow(phys, w, h, viewStartClamped, windowSec, f0, f1)
                const px = normalizeAnnotationOverlayRect(pxRaw, w, h)
                const sc = (a.soundscape_component ?? "").trim()
                const presentation = getMediaAnnotationPresentation(a, userAnnotationColor, meUserId)
                return {
                    id: a.annotation_id,
                    soundscape: a.soundscape_component,
                    presentation,
                    ...px,
                    title: `ID ${a.annotation_id} · ${sc || "-"} · Min X ${formatAnnotationTimeSec(phys.min_x)}s · Max X ${formatAnnotationTimeSec(phys.max_x)}s · Min Y ${formatAnnotationHz(phys.min_y)} Hz · Max Y ${formatAnnotationHz(phys.max_y)} Hz`,
                }
            })
            .filter((x): x is NonNullable<typeof x> => x != null)
    }, [
        annotationsVisible,
        media,
        renderedAnnotations,
        spectrogramLayout,
        meUserId,
        userAnnotationColor,
        viewportSize.h,
        viewportSize.w,
    ])

    /** 不使用 Table rowSelection：antd/rc-table 在 scroll.y 下 onChange 的 keys 可能整页错位；改为自定义列 + 显式 state */
    const toggleAnnotationRowSelected = useCallback((recordId: number, selected: boolean) => {
        setSelectedAnnotationKeys((prev) => {
            const s = new Set(prev.map((k) => Number(k)))
            if (selected) s.add(recordId)
            else s.delete(recordId)
            const next = Array.from(s)
            annotationTableSelectedIdsRef.current = next
                .map((k) => Number(k))
                .filter((n) => Number.isFinite(n) && n > 0)
            return next
        })
    }, [])

    const toggleAnnotationSelectAllCurrentPage = useCallback(() => {
        const pageIds = annotationTableRows.map((r) => r.annotation_id)
        if (pageIds.length === 0) return
        setSelectedAnnotationKeys((prev) => {
            const s = new Set(prev.map((k) => Number(k)))
            const allOnPageSelected = pageIds.every((id) => s.has(id))
            if (allOnPageSelected) {
                for (const id of pageIds) s.delete(id)
            } else {
                for (const id of pageIds) s.add(id)
            }
            const next = Array.from(s)
            annotationTableSelectedIdsRef.current = next
                .map((k) => Number(k))
                .filter((n) => Number.isFinite(n) && n > 0)
            return next
        })
    }, [annotationTableRows])

    const annotationAntdColumns = useMemo(() => {
        const pageIds = annotationTableRows.map((r) => r.annotation_id)
        const selectedSet = new Set(selectedAnnotationKeys.map((k) => Number(k)))
        const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedSet.has(id))
        const somePageSelected = pageIds.some((id) => selectedSet.has(id))
        const headerIndeterminate = somePageSelected && !allPageSelected

        const selectionColumn = {
            key: "__selection",
            columnKey: "__selection",
            width: 48,
            fixed: "left" as const,
            align: "center" as const,
            onHeaderCell: () => ({ className: "studio-annot-th-selection" }),
            onCell: () => ({ className: "studio-annot-td-selection" }),
            title: (
                <div
                    className="studio-annot-select-head"
                    onClick={(e) => e.stopPropagation()}
                >
                    <Checkbox
                        indeterminate={headerIndeterminate}
                        checked={allPageSelected && pageIds.length > 0}
                        onChange={() => toggleAnnotationSelectAllCurrentPage()}
                    />
                </div>
            ),
            render: (_t: unknown, record: StudioAnnotationRow) => (
                <div className="studio-annot-select-cell" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                        checked={selectedSet.has(record.annotation_id)}
                        onChange={(e) => toggleAnnotationRowSelected(record.annotation_id, e.target.checked)}
                    />
                </div>
            ),
        }

        const columnsForMedia = isPhoto ? PHOTO_STUDIO_ANNOTATION_COLUMNS : STUDIO_ANNOTATION_COLUMNS
        const cols = columnsForMedia.map((col) => {
            const useTextFilter = col.key === "creator_type" || col.key === "soundscape_component" || col.key === "sound_type"
            const filterOptionsResolved =
                useTextFilter
                    ? undefined
                    : col.key === "creator_type"
                    ? annotationColumnsMeta.creatorOptions
                    : col.key === "sound_type"
                        ? annotationColumnsMeta.soundTypeOptions
                        : col.key === "animal_sound_type"
                            ? annotationColumnsMeta.animalOptions
                            : col.key === "soundscape_component"
                                ? annotationColumnsMeta.soundscapeOptions
                                : col.filterOptions

            return {
                key: col.key,
                columnKey: col.key,
                ...(col.width ? { width: col.width } : {}),
                ellipsis: true,
                dataIndex: col.key,
                title: (
                    <div className="dpl-th-layout">
                        <div
                            className={`dpl-th-title-container ${col.sortable ? "sortable" : ""}`}
                            onClick={() => col.sortable && toggleAnnotationSort(col.key)}
                        >
                            <div
                                className="dpl-th-title"
                                style={{
                                    color: annotationSortKey === col.key ? "var(--brand)" : "inherit",
                                    fontWeight: annotationSortKey === col.key ? "bold" : "normal",
                                }}
                            >
                                {col.label}
                            </div>
                            {col.sortable && (
                                <div className={`dpl-th-sort-icon ${annotationSortKey === col.key ? "active" : ""}`}>
                                    {annotationSortKey === col.key ? (
                                        annotationSortDir === "asc" ? (
                                            <ChevronUp size={18} />
                                        ) : (
                                            <ChevronDown size={18} />
                                        )
                                    ) : (
                                        <ChevronsUpDown size={18} />
                                    )}
                                </div>
                            )}
                        </div>
                        {col.filterable ? (
                            <div className="th-filter" onClick={(e) => e.stopPropagation()}>
                                {col.filterType === "numberRange" ? (
                                    <div className="dpl-filter-number-group">
                                        <Input
                                            size="small"
                                            type="number"
                                            className="dpl-filter-number-input"
                                            value={(() => {
                                                const v = String(annotationColumnFilters[col.key] || "")
                                                return v.split(",")[0] || ""
                                            })()}
                                            onChange={(e) => {
                                                const parts = String(
                                                    annotationColumnFilters[col.key] || "",
                                                ).split(",")
                                                parts[0] = e.target.value
                                                setAnnotationColumnFilters((prev) => ({
                                                    ...prev,
                                                    [col.key]: parts.join(","),
                                                }))
                                            }}
                                        />
                                        <span className="dpl-filter-dash">-</span>
                                        <Input
                                            size="small"
                                            type="number"
                                            className="dpl-filter-number-input"
                                            value={(() => {
                                                const v = String(annotationColumnFilters[col.key] || "")
                                                return v.split(",")[1] || ""
                                            })()}
                                            onChange={(e) => {
                                                const parts = String(
                                                    annotationColumnFilters[col.key] || "",
                                                ).split(",")
                                                parts[1] = e.target.value
                                                setAnnotationColumnFilters((prev) => ({
                                                    ...prev,
                                                    [col.key]: parts.join(","),
                                                }))
                                            }}
                                        />
                                    </div>
                                ) : filterOptionsResolved && filterOptionsResolved.length > 0 ? (
                                    <Select
                                        showSearch={col.filterSearch}
                                        size="small"
                                        className="dpl-filter-select"
                                        classNames={{
                                            popup: {
                                                root: "eco-select-popup data-dpl-select-popup",
                                            },
                                        }}
                                        value={annotationColumnFilters[col.key] || "all"}
                                        onChange={(val) => {
                                            const newVal = val === "all" ? "" : String(val)
                                            setAnnotationColumnFilters((prev) => ({
                                                ...prev,
                                                [col.key]: newVal,
                                            }))
                                        }}
                                        options={[
                                            { value: "all", label: "All" },
                                            ...filterOptionsResolved.map((opt) =>
                                                typeof opt === "string"
                                                    ? { value: opt, label: opt }
                                                    : { value: String(opt.value), label: opt.label },
                                            ),
                                        ]}
                                        filterOption={(input, option) => {
                                            if (option?.value === "all") return true
                                            return String(option?.label ?? "")
                                                .toLowerCase()
                                                .includes(input.toLowerCase())
                                        }}
                                    />
                                ) : (
                                    <Input
                                        size="small"
                                        className="dpl-filter-input"
                                        value={annotationColumnFilters[col.key] || ""}
                                        onChange={(e) => {
                                            setAnnotationColumnFilters((prev) => ({
                                                ...prev,
                                                [col.key]: e.target.value,
                                            }))
                                        }}
                                    />
                                )}
                            </div>
                        ) : null}
                    </div>
                ),

                ...(col.key === "comments"
                    ? {
                        onCell: () => ({ className: "studio-annot-td-comments" }),
                        onHeaderCell: () => ({ className: "studio-annot-th-comments" }),
                    }
                    : {}),
                render: (text: unknown, record: StudioAnnotationRow) => {
                    if (col.key === "annotation_id") {
                        return (
                            <span className="data-cell-with-current">
                                <span className="num-cell">{text as ReactNode}</span>
                                {record.hasTask ? (
                                    <span className="data-task-pill">Task</span>
                                ) : null}
                            </span>
                        )
                    }
                    if (col.key === "min_x" || col.key === "max_x") {
                        return <span className="num-cell">{formatAnnotationTimeSec(Number(text))}</span>
                    }
                    if (col.key === "min_y" || col.key === "max_y") {
                        return <span className="num-cell">{formatAnnotationHz(Number(text))}</span>
                    }
                    if (col.key === "soundscape_component") {
                        const sc = String(record.soundscape_component ?? "")
                            .trim()
                            .toLowerCase()
                        if (!sc) return ""
                        const label = String(SOUNDSCAPE_LABELS[sc] ?? (record.soundscape_component || "")).trim()
                        return label ? (
                            <span className="studio-annot-cell-ellipsis" title={label}>
                                {label}
                            </span>
                        ) : (
                            ""
                        )
                    }
                    if (col.key === "object_type") {
                        const objectType = String(record.object_type ?? "").trim().toLowerCase()
                        return objectType === "organism" ? "Organism" : objectType === "other" ? "Other" : ""
                    }
                    if (col.key === "taxon_name") {
                        const label = String(
                            record.taxon_scientific_name || record.taxon_common_name || "",
                        ).trim()
                        return label ? (
                            <span className="studio-annot-cell-ellipsis" title={label}>
                                {label}
                            </span>
                        ) : (
                            ""
                        )
                    }
                    if (col.key === "distance_not_estimable") {
                        return dataModuleBoolBadge(record.distance_not_estimable)
                    }
                    if (col.key === "uncertain") {
                        return annotationTableBoolBadge(record.uncertain)
                    }
                    if (col.key === "reference") {
                        return dataModuleBoolBadge(record.reference)
                    }
                    if (col.type === "number" && col.key === "confidence") {
                        return record.confidence != null && Number.isFinite(record.confidence) ? (
                            <span className="num-cell">{record.confidence}</span>
                        ) : (
                            ""
                        )
                    }
                    if (col.type === "number" && col.key === "individual_num") {
                        return record.individual_num != null ? (
                            <span className="num-cell">{record.individual_num}</span>
                        ) : (
                            ""
                        )
                    }
                    if (col.key === "sound_distance_m") {
                        return record.sound_distance_m != null ? (
                            <span className="num-cell">{record.sound_distance_m}</span>
                        ) : (
                            ""
                        )
                    }
                    if (col.type === "number") {
                        return <span className="num-cell">{text as ReactNode}</span>
                    }
                    if (col.key === "comments" || col.key === "sound_type" || col.key === "animal_sound_type") {
                        const s = String(text ?? "").trim()
                        return s ? (
                            <span className="studio-annot-cell-ellipsis" title={s}>
                                {s}
                            </span>
                        ) : (
                            ""
                        )
                    }
                    const s = String(text ?? "").trim()
                    return s ? (
                        <span className="studio-annot-cell-ellipsis" title={s}>
                            {s}
                        </span>
                    ) : (
                        ""
                    )
                },
            }
        })

        return [selectionColumn, ...cols]
    }, [
        annotationColumnFilters,
        annotationColumnsMeta,
        annotationSortDir,
        annotationSortKey,
        annotationTableRows,
        isPhoto,
        isDark,
        selectedAnnotationKeys,
        toggleAnnotationRowSelected,
        toggleAnnotationSelectAllCurrentPage,
        toggleAnnotationSort,
    ])

    const handleAnnotationTableChange = useCallback(
        (_pagination: unknown, _filters: unknown, sorter: unknown) => {
            const s = sorter as {
                columnKey?: string
                order?: "ascend" | "descend" | null
            }
            if (!Array.isArray(s) && s.columnKey) {
                setAnnotationSortKey(s.columnKey)
                setAnnotationSortDir(s.order === "ascend" ? "asc" : s.order === "descend" ? "desc" : null)
            } else {
                setAnnotationSortKey(null)
                setAnnotationSortDir(null)
            }
        },
        [],
    )

    useEffect(() => {
        const valid = new Set(annotationTableRows.map((r) => r.annotation_id))
        setSelectedAnnotationKeys((prev) => {
            const next = prev.filter((k) => valid.has(Number(k)))
            return next.length === prev.length ? prev : next
        })
    }, [annotationTableRows])

    useEffect(() => {
        annotationTableSelectedIdsRef.current = selectedAnnotationKeys
            .map((k) => Number(k))
            .filter((n) => Number.isFinite(n) && n > 0)
    }, [selectedAnnotationKeys])

    const resetAnnotationTableState = useCallback(() => {
        setAnnotationColumnFilters({})
        setAnnotationSortKey(null)
        setAnnotationSortDir(null)
        setSelectedAnnotationKeys([])
        setAnnotationListTick((n) => n + 1)
    }, [])

    const handleAnnotationTableResetToolbar = useCallback(() => {
        resetAnnotationTableState()
    }, [resetAnnotationTableState])

    const closeAssignTaskPanel = useCallback(() => {
        assignTaskAnnotationIdsRef.current = []
        setRightPanel("info")
    }, [])

    const openAssignTaskPanel = useCallback(async () => {
        const fromState = [...new Set(selectedAnnotationKeys.map((k) => Number(k)))].filter(
            (n) => Number.isFinite(n) && n > 0,
        )
        const fromRef = [...new Set(annotationTableSelectedIdsRef.current)].filter(
            (n) => Number.isFinite(n) && n > 0,
        )
        /** 按钮 disabled 与 state 绑定；state 优先。ref 兜底「勾选后极快点击」时 state 尚未提交的一帧 */
        const annotation_ids = fromState.length > 0 ? fromState : fromRef
        if (annotation_ids.length === 0) {
            message.error("Select at least one annotation in the table first.")
            return
        }
        assignTaskAnnotationIdsRef.current = [...annotation_ids]

        setRightPanel("assign-task")
        setAssignableLoading(true)
        try {
            if (currentProjectId == null) throw new Error("Project context is required")
            const users = await tasksApi.listAssignableUsers(currentProjectId, mediaId, true)
            setAssignableUsers(users)
            setAssignSelectedUserIds(users.filter((u) => u.task_count > 0).map((u) => u.user_id))
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Failed to load assignable users")
            setAssignableUsers([])
            setAssignSelectedUserIds([])
        } finally {
            setAssignableLoading(false)
        }
    }, [mediaId, selectedAnnotationKeys])

    const toggleAssignUser = useCallback((userId: number, checked: boolean) => {
        setAssignSelectedUserIds((prev) => {
            if (checked) return prev.includes(userId) ? prev : [...prev, userId]
            return prev.filter((id) => id !== userId)
        })
    }, [])

    const submitAssignTask = useCallback(async () => {
        if (assignSelectedUserIds.length === 0) {
            message.error("Select at least one user.")
            return
        }
        const annotation_ids = assignTaskAnnotationIdsRef.current.filter((n) => Number.isFinite(n) && n > 0)
        if (annotation_ids.length === 0) {
            return
        }
        setAssignSubmitPending(true)
        try {
            if (currentProjectId == null) throw new Error("Project context is required")
            await tasksApi.assignTasks(currentProjectId, mediaId, {
                type: "annotation",
                annotation_ids,
                assignments: assignSelectedUserIds.map((user_id) => ({
                    user_id,
                    comment: "",
                })),
            })
            message.success("Tasks assigned.")
            closeAssignTaskPanel()
            setAnnotationListTick((n) => n + 1)
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Assignment failed")
        } finally {
            setAssignSubmitPending(false)
        }
    }, [assignSelectedUserIds, closeAssignTaskPanel, currentProjectId, mediaId])

    const handleDeleteSelectedAnnotations = useCallback(async () => {
        if (selectedAnnotationKeys.length === 0) {
            return
        }
        const ids = selectedAnnotationKeys
            .map((k) => Number(k))
            .filter((n) => Number.isFinite(n) && n > 0)
        if (ids.length === 0) return
        const loadingId = openLoadingMessage(`Deleting ${ids.length} annotation(s)…`)
        try {
            if (currentProjectId == null) {
                message.error("Missing project context.")
                return
            }
            await Promise.all(ids.map((id) => annotationsApi.delete(id, currentProjectId)))
            updateMessageSuccess(loadingId, `Deleted ${ids.length} annotation(s).`)
            setSelectedAnnotationKeys([])
            setAnnotationListTick((n) => n + 1)
        } catch (e: unknown) {
            updateMessageError(loadingId, e instanceof Error ? e.message : "Delete failed")
        } finally {
            closeLoadingMessage(loadingId)
        }
    }, [selectedAnnotationKeys, currentProjectId])

    const handleExportViewportAnnotationsCsv = useCallback(async () => {
        if (!media || currentProjectId == null) return
        const dur = Number(media.duration_s) || 0
        const { windowSec, viewStartClamped } = spectrogramLayout
        const t0 = viewStartClamped
        const t1 = dur > 0 ? Math.min(t0 + windowSec, dur) : t0 + windowSec
        const f0 = specFreqMinHz
        const f1 = specFreqMaxHz
        try {
            const countResponse = await annotationsApi.listPaged(
                isPhoto
                    ? {
                        media_id: mediaId,
                        project_id: currentProjectId,
                        page: 1,
                        page_size: 1,
                        order_by: "annotation_id",
                        order_dir: "asc",
                    }
                    : {
                        media_id: mediaId,
                        project_id: currentProjectId,
                        page: 1,
                        page_size: 1,
                        order_by: "annotation_id",
                        order_dir: "asc",
                        view_time_start: t0,
                        view_time_end: t1,
                        view_freq_min: f0,
                        view_freq_max: f1,
                    },
                true,
            )
            const recordCount = countResponse.pageInfo.total
            annotationExportActionRef.current = async () => {
                const loadingId = openLoadingMessage("Exporting CSV…")
                try {
                    const download = isPhoto
                        ? await annotationsApi.exportCsv({
                            media_id: mediaId,
                            project_id: currentProjectId,
                        })
                        : await annotationsApi.exportViewportCsv({
                            media_id: mediaId,
                            project_id: currentProjectId,
                            view_time_start: t0,
                            view_time_end: t1,
                            view_freq_min: f0,
                            view_freq_max: f1,
                        })
                    downloadFile(download)
                    updateMessageSuccess(loadingId, "CSV downloaded.")
                } catch (e: unknown) {
                    updateMessageError(loadingId, e instanceof Error ? e.message : "Export failed")
                } finally {
                    closeLoadingMessage(loadingId)
                }
            }
            setAnnotationExportConfirmCount(recordCount)
            setAnnotationExportConfirmOpen(true)
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Unable to count records for export")
        }
    }, [media, mediaId, currentProjectId, spectrogramLayout, specFreqMinHz, specFreqMaxHz, isPhoto])

    const scrollAnnotationTableRowIntoView = useCallback((annotationId: number) => {
        const wrap = annotationTableViewportRef.current
        if (!wrap) return
        const row = wrap.querySelector(`tr[data-row-key="${annotationId}"]`)
        if (row instanceof HTMLElement) {
            row.scrollIntoView({ block: "nearest", behavior: "smooth", inline: "nearest" })
        }
    }, [])

    useEffect(() => {
        if (editingAnnotationId == null) return
        if (!annotationTableRows.some((row) => row.annotation_id === editingAnnotationId)) return
        scrollAnnotationTableRowIntoView(editingAnnotationId)
    }, [annotationTableRows, editingAnnotationId, scrollAnnotationTableRowIntoView])

    const resetAnnotationFormFields = useCallback(() => {
        setFormSoundscape(null)
        setFormSoundTypeSoundId(null)
        setFormTaxonId(null)
        setFormTaxonSearch("")
        setFormUncertain("")
        setFormAnimalSound("")
        setFormDistanceM(null)
        setFormDistanceNotEstimable(false)
        setFormIndividualNum(1)
        setFormReference("")
        setFormComments("")
        taxonOptionsState.reset()
    }, [taxonOptionsState.reset])

    const initReviewFormFromReviews = useCallback((reviews: AnnotationReviewRead[], myId: number | null) => {
        const mine = myId != null ? reviews.find((r) => r.reviewer_id === myId) : undefined
        if (mine) {
            const sid =
                mine.annotation_review_status_id > 0
                    ? mine.annotation_review_status_id
                    : REVIEW_STATUS_IDS.accepted
            setReviewStatusId(sid)
            setReviewNote((mine.note ?? "").trim())
            if (reviewStatusDisablesTaxon(sid)) {
                setReviewTaxonId(null)
                setReviewTaxonSearch("")
            } else {
                const tid = mine.taxon_id != null && mine.taxon_id > 0 ? mine.taxon_id : null
                setReviewTaxonId(tid)
                setReviewTaxonSearch((mine.taxon_name ?? "").trim() || (tid != null ? String(tid) : ""))
            }
        } else {
            setReviewStatusId(REVIEW_STATUS_IDS.accepted)
            setReviewNote("")
            setReviewTaxonId(null)
            setReviewTaxonSearch("")
        }
        setReviewTaxonError(null)
        reviewTaxonOptionsState.reset()
    }, [reviewTaxonOptionsState.reset])

    const populateAnnotationFormFromPublic = useCallback((a: AnnotationPublic) => {
        setDistanceFieldUnlocked(false)
        setAnnotationDraft({
            min_x: a.min_x,
            max_x: a.max_x,
            min_y: a.min_y,
            max_y: a.max_y,
        })
        const sc = (a.soundscape_component ?? "").trim()
        setFormSoundscape(sc === "" ? null : a.soundscape_component ?? null)
        setFormSoundTypeSoundId(
            typeof a.sound_id === "number" && !Number.isNaN(a.sound_id) ? a.sound_id : null,
        )
        setFormObjectType(a.object_type ?? null)
        const sci = (a.taxon_scientific_name ?? "").trim()
        const com = (a.taxon_common_name ?? "").trim()
        if (sci && com) {
            setFormTaxonSearch(`${com} - ${sci}`)
        } else if (sci || com) {
            setFormTaxonSearch(sci || com)
        } else if (a.taxon_id != null && a.taxon_id > 0) {
            setFormTaxonSearch(String(a.taxon_id))
        } else {
            setFormTaxonSearch("")
        }
        setFormTaxonId(a.taxon_id != null && a.taxon_id > 0 ? a.taxon_id : null)
        if (a.uncertain === true) setFormUncertain("true")
        else if (a.uncertain === false) setFormUncertain("false")
        else setFormUncertain("")
        if (a.reference === true) setFormReference("true")
        else if (a.reference === false) setFormReference("false")
        else setFormReference("")
        setFormIndividualNum(Math.max(1, a.individual_num ?? 1))
        setFormDistanceM(
            a.sound_distance_m != null && Number.isFinite(a.sound_distance_m)
                ? a.sound_distance_m
                : null,
        )
        setFormDistanceNotEstimable(Boolean(a.distance_not_estimable))
        setFormAnimalSound((a.animal_sound_type ?? "").trim())
        setFormComments((a.comments ?? "").trim())
        taxonOptionsState.reset()
    }, [taxonOptionsState.reset])

    /** 编辑已有标注：Review 提交用（state 与 meta 多字段兜底） */
    const reviewContextAnnotationId = useMemo(() => {
        if (editingAnnotationId != null && Number.isFinite(editingAnnotationId) && editingAnnotationId > 0) {
            return Math.trunc(editingAnnotationId)
        }
        return pickAnnotationIdFromPublic(editingAnnotationMeta ?? undefined)
    }, [editingAnnotationId, editingAnnotationMeta])

    const handleShareEditingAnnotation = useCallback(async () => {
        const id = reviewContextAnnotationId
        if (id == null) {
            message.error("Missing annotation id.")
            return
        }
        const projectIdForUrl =
            projectRouteId != null && String(projectRouteId).trim() !== ""
                ? String(projectRouteId).trim()
                : currentProjectId != null
                    ? String(currentProjectId)
                    : ""
        if (!projectIdForUrl) {
            message.error("Missing project context.")
            return
        }
        const currentAnnotation =
            editingAnnotationMeta ??
            spectrogramAnnotationsRef.current.find((a) => a.annotation_id === id) ??
            null
        const url = new URL(`/dashboard/${projectIdForUrl}/media/${mediaId}`, window.location.origin)
        url.searchParams.set("annotation_id", String(id))
        if (currentAnnotation) {
            setAnnotationShareParam(url, "annotation_min_x", currentAnnotation.min_x)
            setAnnotationShareParam(url, "annotation_max_x", currentAnnotation.max_x)
            setAnnotationShareParam(url, "annotation_min_y", currentAnnotation.min_y)
            setAnnotationShareParam(url, "annotation_max_y", currentAnnotation.max_y)
            setAnnotationShareParam(url, "annotation_sound_id", currentAnnotation.sound_id)
            setAnnotationShareParam(url, "annotation_taxon_id", currentAnnotation.taxon_id)
            setAnnotationShareParam(
                url,
                "annotation_taxon",
                currentAnnotation.taxon_common_name || currentAnnotation.taxon_scientific_name,
            )
        }
        try {
            await copyTextToClipboard(url.toString())
            message.success("Annotation link copied.")
        } catch {
            message.error("Failed to copy annotation link.")
        }
    }, [currentProjectId, editingAnnotationMeta, mediaId, projectRouteId, reviewContextAnnotationId])

    useEffect(() => {
        if (!pendingReviewInitRef.current || reviewContextAnnotationId == null || !meUserReady) return
        pendingReviewInitRef.current = false
        /** 打开标注时不预填「我的评审」；点 Edit 再用 reviewer_id 请求列表后填充 */
        initReviewFormFromReviews([], null)
    }, [reviewContextAnnotationId, meUserReady, initReviewFormFromReviews])

    /** 展开评审表单：GET /reviews ?annotation_id & reviewer_id=当前用户，有则修改无则添加 */
    const handleReviewEditClick = useCallback(async () => {
        setReviewPanelExpanded(true)
        const annId = reviewContextAnnotationId
        if (annId == null || meUserId == null) {
            initReviewFormFromReviews([], null)
            if (meUserId == null) message.error("Sign in to review.")
            return
        }
        setReviewEditLoading(true)
        try {
            const { items } = await reviewsApi.listPaged({
                annotation_id: annId,
                reviewer_id: meUserId,
                page: 1,
                page_size: 20,
                order_by: "creation_date",
                order_dir: "desc",
            }, true)
            const rows = normalizeAnnotationReviews(items)
            const row = rows[0]
            if (row != null) {
                setEditingAnnotationReviews((prev) => {
                    const next = [...prev]
                    const i = next.findIndex(
                        (r) => r.annotation_id === row.annotation_id && r.reviewer_id === row.reviewer_id,
                    )
                    if (i >= 0) next[i] = row
                    else next.push(row)
                    return next.sort((a, b) =>
                        String(b.creation_date).localeCompare(String(a.creation_date)),
                    )
                })
                initReviewFormFromReviews([row], meUserId)
            } else {
                initReviewFormFromReviews([], null)
            }
        } catch {
            initReviewFormFromReviews(editingAnnotationReviews, meUserId)
        } finally {
            setReviewEditLoading(false)
        }
    }, [
        editingAnnotationReviews,
        initReviewFormFromReviews,
        meUserId,
        reviewContextAnnotationId,
    ])

    const handleDeleteReview = useCallback(async (review: AnnotationReviewRead) => {
        if (currentProjectId == null) {
            message.error("Missing project context.")
            return
        }
        if (!authUtils.getToken() || meUserId == null) {
            message.error("Sign in to delete a review.")
            return
        }
        const canDelete = meIsProjectAdmin || review.reviewer_id === meUserId
        if (!canDelete) {
            message.error("You can only delete your own review.")
            return
        }
        const annId = Number(review.annotation_id)
        const reviewerId = Number(review.reviewer_id)
        if (!Number.isFinite(annId) || !Number.isFinite(reviewerId)) return
        const loadingId = openLoadingMessage("Deleting review...")
        try {
            await reviewsApi.delete(annId, reviewerId, currentProjectId)
            const fresh = editingAnnotationReviews.filter(
                (r) => !(r.annotation_id === annId && r.reviewer_id === reviewerId),
            )
            setEditingAnnotationReviews(fresh)
            setEditingAnnotationMeta((annotation) =>
                annotation?.annotation_id === annId
                    ? { ...annotation, reviews: fresh }
                    : annotation,
            )
            setSpectrogramAnnotations((annotations) =>
                annotations.map((annotation) =>
                    annotation.annotation_id === annId
                        ? { ...annotation, reviews: fresh }
                        : annotation,
                ),
            )
            setAnnotationListItems((annotations) =>
                annotations.map((annotation) =>
                    annotation.annotation_id === annId
                        ? { ...annotation, reviews: fresh }
                        : annotation,
                ),
            )
            if (reviewerId === meUserId) {
                initReviewFormFromReviews([], null)
            }
            setReviewPanelExpanded((expanded) => expanded && reviewerId !== meUserId)
            setAnnotationListTick((n) => n + 1)
            updateMessageSuccess(loadingId, "Review deleted.")
        } catch (e: unknown) {
            updateMessageError(loadingId, e instanceof Error ? e.message : "Delete failed")
        } finally {
            closeLoadingMessage(loadingId)
        }
    }, [currentProjectId, editingAnnotationReviews, initReviewFormFromReviews, meIsProjectAdmin, meUserId])

    const sortedEditingAnnotationReviews = useMemo(() => {
        return [...editingAnnotationReviews].sort((a, b) =>
            String(b.creation_date).localeCompare(String(a.creation_date)),
        )
    }, [editingAnnotationReviews])

    const myAnnotationReviewRow = useMemo(() => {
        if (meUserId == null) return undefined
        return editingAnnotationReviews.find((r) => r.reviewer_id === meUserId)
    }, [editingAnnotationReviews, meUserId])

    /** 点 Revise 且 Review 侧 Taxon 为空时，用当前标注表单 / 详情里的物种预填 */
    const seedReviewTaxonForReviseFromAnnotation = useCallback(() => {
        setReviewTaxonId((prevTid) => {
            if (prevTid != null && prevTid > 0) return prevTid
            if (formTaxonId != null && formTaxonId > 0) return formTaxonId
            const m = editingAnnotationMeta?.taxon_id
            return m != null && m > 0 ? m : prevTid
        })
        setReviewTaxonSearch((prevLab) => {
            if (prevLab.trim()) return prevLab
            if (formTaxonSearch.trim()) return formTaxonSearch.trim()
            const sci = (editingAnnotationMeta?.taxon_scientific_name ?? "").trim()
            const com = (editingAnnotationMeta?.taxon_common_name ?? "").trim()
            if (sci && com) return `${com} - ${sci}`
            if (sci || com) return sci || com
            const tid =
                (formTaxonId != null && formTaxonId > 0 ? formTaxonId : null) ??
                (editingAnnotationMeta?.taxon_id != null && editingAnnotationMeta.taxon_id > 0
                    ? editingAnnotationMeta.taxon_id
                    : null)
            if (tid != null) return String(tid)
            return prevLab
        })
    }, [editingAnnotationMeta, formTaxonId, formTaxonSearch])

    const editingAnnotationCreatorDisplay = useMemo(() => {
        const creatorName = (editingAnnotationMeta?.creator_name ?? "").trim()
        if (creatorName) return creatorName
        const creatorId = editingAnnotationMeta?.creator_id
        return creatorId != null && Number.isFinite(creatorId) ? String(creatorId) : "-"
    }, [editingAnnotationMeta])
    const resolveTaxonSearchQuery = useCallback(
        (preferScientific = false) => {
            const label = formTaxonSearch.trim()
            const scientificFromMeta = (editingAnnotationMeta?.taxon_scientific_name ?? "").trim()
            const scientificFromLabel = label.includes("-")
                ? (label.split("-").pop() ?? "").trim()
                : ""
            const primary = preferScientific
                ? scientificFromMeta || scientificFromLabel || label
                : label || scientificFromMeta || scientificFromLabel
            if (primary) return primary
            return formTaxonId != null && formTaxonId > 0 ? String(formTaxonId) : ""
        },
        [editingAnnotationMeta?.taxon_scientific_name, formTaxonId, formTaxonSearch],
    )

    const editingAnnotationConfidenceValue =
        editingAnnotationMeta?.confidence != null &&
        Number.isFinite(editingAnnotationMeta.confidence)
            ? Number(editingAnnotationMeta.confidence)
            : null

    const editingAnnotationCreationDisplay = useMemo(
        () => formatReviewDateDisplay(String(editingAnnotationMeta?.creation_date ?? "")),
        [editingAnnotationMeta?.creation_date],
    )
    const editingAnnotationCreationDateOnlyDisplay = useMemo(
        () => formatReviewDateOnlyDisplay(String(editingAnnotationMeta?.creation_date ?? "")),
        [editingAnnotationMeta?.creation_date],
    )

    /** 将主声谱图视窗缩放到给定时间范围（秒）；只改当前视窗，不改用户保存的 px/s */
    const zoomSpectrogramToTimeRange = useCallback(
        (min_x: number, max_x: number) => {
            const dur = Number(media?.duration_s) || 0
            if (dur <= 0) return null
            const minT = snapTimeSec(Math.min(min_x, max_x), dur)
            const maxT = snapTimeSec(Math.max(min_x, max_x), dur)
            const span = Math.max(maxT - minT, 0.05)
            const { win, zp } = resolveSpectrogramZoomWindow(dur, span)
            const center = snapTimeSec((minT + maxT) / 2, dur)
            const vs = resolveSpectrogramViewStart(dur, center, win)
            setSpectrogramZoomPercent(zp)
            spectrogramZoomPercentRef.current = zp
            storeSpectrogramZoomPercentCookie(zp)
            spectrogramViewStartRef.current = vs
            setSpectrogramViewStart(vs)
            return vs
        },
        [media?.duration_s],
    )

    const seekAudioToTimeSilent = useCallback(
        (t: number, opts?: { ensureVisible?: boolean }) => {
            stopContinuousPlaybackRef.current()
            clearPreviewWatchInterval()
            previewSelectionActiveRef.current = false
            const dur = Number(media?.duration_s) || 0
            const tt = dur > 0 ? clamp(t, 0, dur) : Math.max(0, t)
            const el = audioRef.current
            if (el) {
                try {
                    el.pause()
                    el.currentTime = Math.max(0, tt - audioWindowStartRef.current)
                } catch {
                    /* ignore */
                }
                syncIsPlayingFromAudio()
            }
            setCurrentTime(tt)
            if (opts?.ensureVisible && dur > 0) {
                const win = spectrogramVisibleWindowSec(dur, spectrogramZoomPercentRef.current)
                if (win + 1e-6 < dur) {
                    const maxS = Math.max(0, dur - win)
                    let vs = spectrogramViewStartRef.current
                    if (tt < vs || tt > vs + win) {
                        vs = clamp(tt - win / 2, 0, maxS)
                        spectrogramViewStartRef.current = vs
                        setSpectrogramViewStart(vs)
                    }
                }
            }
        },
        [clearPreviewWatchInterval, media?.duration_s, syncIsPlayingFromAudio],
    )

    const seekToTimeAndPlay = useCallback(
        (t: number, opts?: { ensureVisible?: boolean }) => {
            stopContinuousPlaybackRef.current()
            clearPreviewWatchInterval()
            previewSelectionActiveRef.current = false
            const dur = Number(media?.duration_s) || 0
            const tt = dur > 0 ? clamp(t, 0, dur) : Math.max(0, t)
            const el = audioRef.current
            if (el) {
                try {
                    el.currentTime = Math.max(0, tt - audioWindowStartRef.current)
                } catch {
                    /* ignore */
                }
                void el.play()
                    .then(() => {
                        syncIsPlayingFromAudio()
                    })
                    .catch(() => {
                        syncIsPlayingFromAudio()
                        message.error("Could not play audio")
                    })
            }
            setCurrentTime(tt)
            if (opts?.ensureVisible && dur > 0) {
                const win = spectrogramVisibleWindowSec(dur, spectrogramZoomPercentRef.current)
                if (win + 1e-6 < dur) {
                    const maxS = Math.max(0, dur - win)
                    let vs = spectrogramViewStartRef.current
                    if (tt < vs || tt > vs + win) {
                        vs = clamp(tt - win / 2, 0, maxS)
                        spectrogramViewStartRef.current = vs
                        setSpectrogramViewStart(vs)
                    }
                }
            }
        },
        [clearPreviewWatchInterval, media?.duration_s, syncIsPlayingFromAudio],
    )

    /** 缩放/改 px·s 后：播放头对齐可见窗左缘（进度条在最左） */
    const syncPlaybackToSpectrogramViewStart = useCallback(
        (viewStartSec: number) => {
            stopContinuousPlaybackRef.current()
            clearPreviewWatchInterval()
            previewSelectionActiveRef.current = false
            const dur = Number(media?.duration_s) || 0
            const t = snapTimeSec(dur > 0 ? clamp(viewStartSec, 0, dur) : Math.max(0, viewStartSec), dur)
            audioPreserveTimeRef.current = t
            const el = audioRef.current
            const applyToAudio = () => {
                const current = audioRef.current
                if (!current) return
                try {
                    current.pause()
                    current.currentTime = Math.max(0, t - audioWindowStartRef.current)
                } catch {
                    /* ignore */
                }
            }
            if (el) applyToAudio()
            setCurrentTime(t)
            requestAnimationFrame(() => {
                applyToAudio()
                setCurrentTime(t)
            })
        },
        [clearPreviewWatchInterval, media?.duration_s],
    )

    const clearSpectrogramMagnifierBackup = useCallback(() => {
        spectrogramMagnifierBackupRef.current = null
        setSpectrogramMagnifierZoomed(false)
    }, [])

    const fitSpectrogramToFullDuration = useCallback(() => {
        setSpectrogramZoomPercent(0)
        spectrogramZoomPercentRef.current = 0
        setCookieValue(SPEC_ZOOM_COOKIE_KEY, "0")
        setSpectrogramViewStart(0)
        spectrogramViewStartRef.current = 0
    }, [])

    const forceSeekToPendingZoomStart = useCallback(() => {
        const t = pendingZoomSeekTimeRef.current
        const el = audioRef.current
        if (t == null || !Number.isFinite(t) || !el) return
        try {
            el.currentTime = Math.max(0, t)
            setCurrentTime(Math.max(0, t))
            pendingZoomSeekTimeRef.current = null
        } catch {
            /* keep pending for next retry */
        }
    }, [])

    /** 应用放大镜 layout（时间 + 频率），并排队带通音频重载 */
    const applyMagnifierZoomLayout = useCallback((layout: MagnifierLayout) => {
        const dur = Number(media?.duration_s) || 0
        const layoutWindowSec = Math.max(layout.end_time - layout.start_time, dur > 0 ? spectrogramMinWindowSec(dur) : 0)
        const zp = dur > 0 ? resolveSpectrogramZoomWindow(dur, layoutWindowSec).zp : layout.zp
        const vs = snapTimeSec(layout.start_time, dur > 0 ? dur : undefined)
        pendingAudioBandpassHzRef.current = { lo: layout.y0, hi: layout.y1 }
        activeViewportParamsKeyRef.current = null
        spectrogramViewStartRef.current = vs
        spectrogramZoomPercentRef.current = zp
        setSpecFreqMinHz(layout.y0)
        setSpecFreqMaxHz(layout.y1)
        setSpectrogramZoomPercent(zp)
        storeSpectrogramZoomPercentCookie(zp)
        setSpectrogramViewStart(vs)
        setSpectrogramMagnifierZoomed(true)
        setAudioReloadToken((n) => n + 1)
    }, [media?.duration_s])

    const openAnnotationEditorForPublic = useCallback(
        (a: AnnotationPublic, reviewsOverride?: AnnotationReviewRead[]) => {
            spectrogramMagnifierBackupRef.current = null
            setSpectrogramMagnifierZoomed(false)
            setAnnotationDraftOverlayVisible(false)
            setAnnotationDraftHasSize(false)
            populateAnnotationFormFromPublic(a)
            const annotationId = pickAnnotationIdFromPublic(a)
            setEditingAnnotationId(annotationId)
            if (annotationId != null) {
                setAnnotationLinkedHighlightId(annotationId)
                setSelectedAnnotationKeys([annotationId])
                annotationTableSelectedIdsRef.current = [annotationId]
            }
            setEditingAnnotationMeta(a)
            const revs =
                reviewsOverride ??
                normalizeAnnotationReviews((a as AnnotationWithReviews).reviews)
            setEditingAnnotationReviews(revs)
            setReviewPanelExpanded(revs.length === 0)
            pendingReviewInitRef.current = true
            setRightPanel("new-annotation")
            const sr = Number(media?.sampling_rate_hz) || 0
            const nyq = sr > 0 ? Math.round(sr / 2) : 24000
            const band = physBoxFreqBandHz(a, nyq)
            pendingAudioBandpassHzRef.current = { lo: band.lo, hi: band.hi }
            if (audioBandFilter) {
                activeViewportParamsKeyRef.current = null
                setAudioReloadToken((n) => n + 1)
            }
        },
        [audioBandFilter, media?.sampling_rate_hz, populateAnnotationFormFromPublic],
    )

	    const openAnnotationEditorById = useCallback(
	        async (
                annotationId: number,
                options?: { autoZoom?: boolean; seek?: boolean; seekAndPlay?: boolean },
            ) => {
	            if (currentProjectId == null) {
	                message.error("Missing project context.")
	                return
	            }
	            setAnnotationDraftOverlayVisible(false)
	            setMarqueePx(null)
	            setMarqueeCreating(false)
	            setAnnotationDraftHasSize(false)
	            // const loadingId = openLoadingMessage("Loading annotation…")
	            try {
	                const [detail, reviewsPaged] = await Promise.all([
	                    annotationsApi.getById(annotationId, currentProjectId, true),
	                    reviewsApi
	                        .listPaged({
	                            annotation_id: annotationId,
	                            project_id: currentProjectId,
	                            page: 1,
                            page_size: 100,
                            order_by: "creation_date",
                            order_dir: "desc",
                        }, true)
                        .catch(() => null),
                ])
                if (detail.media_id !== mediaId) {
                    message.error("This annotation belongs to another recording.")
                    return
                }
                const revsFromApi = reviewsPaged != null ? normalizeAnnotationReviews(reviewsPaged.items) : null
                const revs =
                    revsFromApi != null
                        ? revsFromApi
                        : normalizeAnnotationReviews((detail as AnnotationWithReviews).reviews)
                openAnnotationEditorForPublic(detail, revs)
                let autoZoomViewStart: number | null = null
                if (options?.autoZoom) {
                    if (isPhoto) {
                        setPhotoZoomRequest((prev) => ({
                            nonce: (prev?.nonce ?? 0) + 1,
                            box: {
                                min_x: detail.min_x,
                                max_x: detail.max_x,
                                min_y: detail.min_y,
                                max_y: detail.max_y,
                            },
                        }))
                    } else {
                        spectrogramMagnifierBackupRef.current = null
                        setSpectrogramMagnifierZoomed(false)
                        const layout = computeMagnifierLayoutForAnnotation(
                            detail,
                            Number(media?.duration_s) || 0,
                            Number(media?.sampling_rate_hz) || 0,
                        )
                        if (layout) {
                            applyMagnifierZoomLayout(layout)
                            autoZoomViewStart = layout.vs
                        }
                    }
                }
                requestAnimationFrame(() => {
                    const startSec = Math.min(detail.min_x, detail.max_x)
                    const seekTarget =
                        options?.autoZoom && autoZoomViewStart != null
                            ? autoZoomViewStart
                            : startSec
                    if (!isPhoto && options?.seekAndPlay === true) {
                        seekToTimeAndPlay(seekTarget, { ensureVisible: !options?.autoZoom })
                    } else if (!isPhoto && options?.seek === true) {
                        seekAudioToTimeSilent(seekTarget, { ensureVisible: !options?.autoZoom })
                    }
                    scrollAnnotationTableRowIntoView(annotationId)
                })
            } catch (e: unknown) {
                message.error(e instanceof Error ? e.message : "Failed to load annotation.")
            } finally {
                // closeLoadingMessage(loadingId)
            }
        },
	        [applyMagnifierZoomLayout, currentProjectId, isPhoto, media?.duration_s, media?.sampling_rate_hz, mediaId, openAnnotationEditorForPublic, scrollAnnotationTableRowIntoView, seekAudioToTimeSilent, seekToTimeAndPlay, zoomSpectrogramToTimeRange],
	    )

    useEffect(() => {
        if (routeAnnotationId == null) {
            routeAutoOpenedAnnotationKeyRef.current = ""
            return
        }
        if (loading || currentProjectId == null) return
        const key = `${mediaId}:${routeAnnotationId}`
        if (routeAutoOpenedAnnotationKeyRef.current === key) return
        routeAutoOpenedAnnotationKeyRef.current = key
        void openAnnotationEditorById(routeAnnotationId, { autoZoom: true, seek: true })
    }, [currentProjectId, loading, mediaId, openAnnotationEditorById, routeAnnotationId])

    const stopContinuousPlayback = useCallback((opts?: { keepToggle?: boolean }) => {
        const engine = continuousEngineRef.current
        continuousRunIdRef.current += 1
        clearPrefetchedSpectrogram()
        if (continuousUiTickRef.current != null) {
            cancelAnimationFrame(continuousUiTickRef.current)
            continuousUiTickRef.current = null
        }
        if (engine) {
            try {
                engine.source?.stop()
            } catch {
                /* ignore */
            }
            try {
                engine.nextSource?.stop()
            } catch {
                /* ignore */
            }
            continuousEngineRef.current = null
            try {
                void engine.ctx.close()
            } catch {
                /* ignore */
            }
        }
        continuousPlayingAnnotationRef.current = null
        setAudioLoading(false)
        setIsPlaying(false)
        if (!opts?.keepToggle) {
            setContinuousSegmentPlayback(false)
            continuousSegmentPlaybackRef.current = false
        }
    }, [clearPrefetchedSpectrogram])

    const restoreStandardAudioAfterContinuous = useCallback((resumeTime: number) => {
        audioPreserveTimeRef.current = resumeTime
        setContinuousSegmentPlayback(false)
        continuousSegmentPlaybackRef.current = false
        setAudioReloadToken((n) => n + 1)
    }, [])

    useEffect(() => {
        stopContinuousPlaybackRef.current = stopContinuousPlayback
    }, [stopContinuousPlayback])

    const buildContinuousViewportSegment = useCallback(
        (startAt?: number): ContinuousPlaybackSegment | null => {
            const dur = Number(media?.duration_s) || 0
            if (!(dur > 0)) return null
            const nominalWindowSec = spectrogramVisibleWindowSec(dur, spectrogramZoomPercentRef.current)
            const {
                windowSec: currentWindowSec,
                viewStartClamped: currentViewStart,
            } = resolveSpectrogramViewportWindow(
                dur,
                spectrogramViewStartRef.current,
                spectrogramZoomPercentRef.current,
            )
            const start = clamp(startAt ?? currentViewStart, 0, dur)
            const startInCurrentWindow =
                start >= currentViewStart - 1e-6 &&
                start < Math.min(currentViewStart + currentWindowSec, dur) - 0.02
            const viewStart = startInCurrentWindow ? currentViewStart : snapTimeSec(start, dur)
            const end = snapTimeSec(
                Math.min(startInCurrentWindow ? currentViewStart + currentWindowSec : start + nominalWindowSec, dur),
                dur,
            )
            if (end <= start + 0.02) return null
            return {
                kind: "viewport",
                start,
                end,
                viewStart,
            }
        },
        [media?.duration_s],
    )

    const buildContinuousAnnotationSegment = useCallback(
        (annotation: AnnotationPublic): ContinuousPlaybackSegment | null => {
            const dur = Number(media?.duration_s) || 0
            if (!(dur > 0)) return null
            const start = clamp(Math.min(annotation.min_x, annotation.max_x), 0, dur)
            const end = clamp(Math.max(annotation.min_x, annotation.max_x), start, dur)
            if (end <= start + 0.02) return null
            return {
                kind: "annotation",
                start,
                end,
                annotationId: annotation.annotation_id,
                viewStart: start,
            }
        },
        [media?.duration_s],
    )

    const findContinuousNextSegment = useCallback(
        (segment: ContinuousPlaybackSegment): ContinuousPlaybackSegment | null => {
            const dur = Number(media?.duration_s) || 0
            if (!(dur > 0)) return null
            if (segment.kind === "annotation" && segment.annotationId != null) {
                const next = nextAnnotationAfterByTime(
                    segment.annotationId,
                    spectrogramAnnotationsRef.current,
                )
                return next ? buildContinuousAnnotationSegment(next) : null
            }
            if (segment.end >= dur - 1e-6) return null
            const nextStart = snapTimeSec(clamp(segment.end, 0, dur), dur)
            if (nextStart <= segment.start + 1e-6) return null
            const windowSec = spectrogramVisibleWindowSec(dur, spectrogramZoomPercentRef.current)
            const viewStart = nextStart
            const end = snapTimeSec(Math.min(nextStart + windowSec, dur), dur)
            if (end <= nextStart + 0.02) return null
            return {
                kind: "viewport",
                start: nextStart,
                end,
                viewStart,
            }
        },
        [buildContinuousAnnotationSegment, media?.duration_s],
    )

    const applyContinuousSegmentVisualState = useCallback(
        (segment: ContinuousPlaybackSegment) => {
            if (segment.kind === "annotation" && segment.annotationId != null) {
                const ann =
                    spectrogramAnnotationsRef.current.find((a) => a.annotation_id === segment.annotationId) ??
                    null
                continuousPlayingAnnotationRef.current = ann
                setEditingAnnotationId(segment.annotationId)
                if (ann) setEditingAnnotationMeta(ann)
                scrollAnnotationTableRowIntoView(segment.annotationId)
                if (spectrogramMagnifierZoomedRef.current && ann) {
                    const layout = computeMagnifierLayoutForAnnotation(
                        ann,
                        Number(media?.duration_s) || 0,
                        Number(media?.sampling_rate_hz) || 0,
                    )
                    if (layout) {
                        spectrogramViewStartRef.current = layout.vs
                        spectrogramZoomPercentRef.current = layout.zp
                        pendingAudioBandpassHzRef.current = { lo: layout.y0, hi: layout.y1 }
                        activeViewportParamsKeyRef.current = null
                        setSpecFreqMinHz(layout.y0)
                        setSpecFreqMaxHz(layout.y1)
                        setSpectrogramZoomPercent(layout.zp)
                        setSpectrogramViewStart(layout.vs)
                    }
                }
                return
            }

            continuousPlayingAnnotationRef.current = null
            spectrogramViewStartRef.current = segment.viewStart
            setSpectrogramViewStart(segment.viewStart)
        },
        [media?.duration_s, media?.sampling_rate_hz, scrollAnnotationTableRowIntoView],
    )

    const decodeContinuousSegment = useCallback(
        async (
            ctx: AudioContext,
            segment: ContinuousPlaybackSegment,
            runId: number,
        ): Promise<ContinuousDecodedSegment | null> => {
            if (!media || currentProjectId == null) return null
            if (continuousRunIdRef.current !== runId) return null
            const viewport = buildMediaViewportParams({
                durationS: Number(media.duration_s) || 0,
                samplingRateHz: Number(media.sampling_rate_hz) || 0,
                viewStart: segment.start,
                windowSec: Math.max(0.02, segment.end - segment.start),
                freqMinHz: specFreqMinHz,
                freqMaxHz: specFreqMaxHz,
                fftSize: Number(fftValue),
                stereo: Number(media.channels) === 2,
                audioChannel: 1,
                bandFilter: audioBandFilterRef.current,
            })
            const { blob } = await mediaApi.fetchAudioBlob(
                mediaId,
                currentProjectId,
                toAudioQueryParams(viewport, audioReloadToken),
                true,
            )
            if (continuousRunIdRef.current !== runId) return null
            const data = await blob.arrayBuffer()
            const buffer = await ctx.decodeAudioData(data.slice(0))
            if (continuousRunIdRef.current !== runId) return null
            logAudioBufferSignal(buffer, {
                mediaId,
                source: "continuous-playback",
                segment: segment.kind === "annotation" && segment.annotationId != null
                    ? `annotation:${segment.annotationId}`
                    : segment.kind,
                viewport,
                requestedBandFilter: audioBandFilterRef.current,
            })
            return { ...segment, buffer }
        },
        [
            audioReloadToken,
            currentProjectId,
            fftValue,
            media,
            mediaId,
            specFreqMaxHz,
            specFreqMinHz,
        ],
    )

    const prefetchContinuousSpectrogram = useCallback(
        async (segment: ContinuousPlaybackSegment, runId: number) => {
            if (!media || currentProjectId == null) return
            const viewport = buildDetailViewportParams(segment.viewStart)
            if (!viewport) return
            const measuredWidth =
                viewportSizeRef.current.w > 0
                    ? Math.round(viewportSizeRef.current.w)
                    : (() => {
                        const vp = viewportRef.current
                        if (!vp) return 0
                        const { w } = readViewportLayoutSize(vp)
                        return w > 0 ? Math.round(w) : 0
                    })()
            const measuredHeight =
                viewportSizeRef.current.h > 0
                    ? Math.round(viewportSizeRef.current.h)
                    : (() => {
                        const vp = viewportRef.current
                        if (!vp) return 0
                        const { h } = readViewportLayoutSize(vp)
                        return h > 0 ? Math.round(h) : 0
                    })()
            const requestSize = resolveSpectrogramRequestSize(measuredWidth, measuredHeight)
            if (!requestSize) return
            const key = spectrogramRequestParamsKey(viewport)
            if (
                key === activeViewportParamsKeyRef.current ||
                prefetchedSpectrogramsRef.current.has(key) ||
                prefetchingSpectrogramKeysRef.current.has(key)
            ) {
                return
            }
            prefetchingSpectrogramKeysRef.current.add(key)
            try {
                const { blob } = await mediaApi.fetchSpectrogramBlob(
                    mediaId,
                    currentProjectId,
                    toSpectrogramQueryParams(viewport, requestSize.width, requestSize.height),
                    true,
                )
                if (continuousRunIdRef.current !== runId || !prefetchingSpectrogramKeysRef.current.has(key)) return
                const url = URL.createObjectURL(blob)
                if (pendingDisplayPrefetchedSpectrogramKeyRef.current === key) {
                    pendingDisplayPrefetchedSpectrogramKeyRef.current = null
                    prefetchedSpectrogramsRef.current.delete(key)
                    const current = spectrogramBlobUrlRef.current
                    spectrogramBlobUrlRef.current = url
                    setSpectrogramBlobUrl(url)
                    activeViewportParamsKeyRef.current = key
                    setSpectrogramInitialReady(true)
                    setSpectrogramLoading(false)
                    if (current) URL.revokeObjectURL(current)
                    return
                }
                const prev = prefetchedSpectrogramsRef.current.get(key)
                prefetchedSpectrogramsRef.current.set(key, { key, url, runId })
                if (prev && prev.url !== url) URL.revokeObjectURL(prev.url)
            } catch {
                if (pendingDisplayPrefetchedSpectrogramKeyRef.current === key) {
                    pendingDisplayPrefetchedSpectrogramKeyRef.current = null
                    setSpectrogramRetryToken((n) => n + 1)
                }
            } finally {
                prefetchingSpectrogramKeysRef.current.delete(key)
            }
        },
        [
            buildDetailViewportParams,
            currentProjectId,
            media,
            mediaId,
            readViewportLayoutSize,
        ],
    )

    const scheduleContinuousSegment = useCallback(
        (
            engine: ContinuousPlaybackEngine,
            segment: ContinuousDecodedSegment,
            when: number,
            runId: number,
            isNext = false,
        ) => {
            const source = engine.ctx.createBufferSource()
            source.buffer = segment.buffer
            const rate = engine.playbackRate
            source.playbackRate.value = rate
            source.connect(engine.ctx.destination)
            const duration = Math.max(0.02, segment.end - segment.start)
            const ctxDuration = duration / rate
            source.onended = () => {
                if (continuousRunIdRef.current !== runId) return
                if (isNext) return
                const currentEngine = continuousEngineRef.current
                if (!currentEngine || currentEngine.runId !== runId) return
                if (currentEngine.source !== source) return
                if (currentEngine.stopAfterCurrent) {
                    const resumeTime = segment.end
                    stopContinuousPlayback({ keepToggle: true })
                    restoreStandardAudioAfterContinuous(resumeTime)
                    setPlaybackTime(resumeTime)
                    return
                }
                if (!currentEngine.next) {
                    const resumeTime = segment.end
                    setPlaybackTime(resumeTime)
                    stopContinuousPlayback()
                    restoreStandardAudioAfterContinuous(resumeTime)
                }
            }
            source.start(when, 0, duration)
            if (isNext) {
                engine.nextSource = source
                engine.nextStartedAtCtx = when
                engine.nextCtxDuration = ctxDuration
                engine.nextScheduledEndCtx = when + ctxDuration
            } else {
                engine.source = source
                engine.startedAtCtx = when
                engine.currentCtxDuration = ctxDuration
                engine.scheduledEndCtx = when + ctxDuration
                engine.current = segment
                applyContinuousSegmentVisualState(segment)
            }
        },
        [applyContinuousSegmentVisualState, restoreStandardAudioAfterContinuous, setCurrentTime, stopContinuousPlayback],
    )

    const scheduleDecodedContinuousNext = useCallback(
        (engine: ContinuousPlaybackEngine) => {
            if (!engine.next || engine.nextSource || !engine.current) return
            const when = Math.max(
                engine.scheduledEndCtx,
                engine.ctx.currentTime + CONTINUOUS_MIN_SCHEDULE_DELAY_S,
            )
            scheduleContinuousSegment(engine, engine.next, when, engine.runId, true)
        },
        [scheduleContinuousSegment],
    )

    const ensureContinuousNextDecoded = useCallback(
        async (engine: ContinuousPlaybackEngine) => {
            if (!engine.current || engine.next || engine.prefetchingKey) return
            const nextSegment = findContinuousNextSegment(engine.current)
            if (engine.stopAfterCurrent) return
            if (!nextSegment) return
            const key = continuousSegmentKey(nextSegment)
            engine.prefetchingKey = key
            void prefetchContinuousSpectrogram(nextSegment, engine.runId)
            const decoded = await decodeContinuousSegment(engine.ctx, nextSegment, engine.runId)
            if (continuousEngineRef.current !== engine || continuousRunIdRef.current !== engine.runId) return
            engine.prefetchingKey = null
            if (decoded) {
                engine.next = decoded
                scheduleDecodedContinuousNext(engine)
            }
        },
        [decodeContinuousSegment, findContinuousNextSegment, prefetchContinuousSpectrogram, scheduleDecodedContinuousNext],
    )

    const promoteContinuousNextSegment = useCallback(
        async (engine: ContinuousPlaybackEngine) => {
            let next = engine.next
            if (engine.stopAfterCurrent) {
                const resumeTime = engine.current?.end ?? currentTime
                stopContinuousPlayback({ keepToggle: true })
                restoreStandardAudioAfterContinuous(resumeTime)
                setPlaybackTime(resumeTime)
                return
            }
            const expectedNext = engine.current ? findContinuousNextSegment(engine.current) : null
            if (expectedNext && next && continuousSegmentKey(expectedNext) !== continuousSegmentKey(next)) {
                if (engine.nextSource) {
                    try {
                        engine.nextSource.stop()
                    } catch {
                        /* ignore */
                    }
                }
                engine.next = null
                engine.nextSource = null
                engine.nextStartedAtCtx = null
                engine.nextScheduledEndCtx = null
                engine.nextCtxDuration = null
                const decoded = await decodeContinuousSegment(engine.ctx, expectedNext, engine.runId)
                if (continuousEngineRef.current !== engine || continuousRunIdRef.current !== engine.runId) return
                next = decoded
                engine.next = decoded
            }
            if (!next) {
                stopContinuousPlayback()
                return
            }
            engine.source = engine.nextSource
            engine.nextSource = null
            const when =
                engine.nextStartedAtCtx ??
                Math.max(engine.scheduledEndCtx, engine.ctx.currentTime + CONTINUOUS_MIN_SCHEDULE_DELAY_S)
            engine.next = null
            if (engine.source) {
                engine.current = next
                engine.startedAtCtx = when
                engine.currentCtxDuration =
                    engine.nextCtxDuration ?? Math.max(0.02, next.end - next.start) / engine.playbackRate
                engine.scheduledEndCtx =
                    engine.nextScheduledEndCtx ?? engine.startedAtCtx + engine.currentCtxDuration
                applyContinuousSegmentVisualState(next)
            } else {
                scheduleContinuousSegment(engine, next, when, engine.runId)
            }
            engine.nextStartedAtCtx = null
            engine.nextScheduledEndCtx = null
            engine.nextCtxDuration = null
            void ensureContinuousNextDecoded(engine)
        },
        [applyContinuousSegmentVisualState, currentTime, decodeContinuousSegment, ensureContinuousNextDecoded, findContinuousNextSegment, restoreStandardAudioAfterContinuous, scheduleContinuousSegment, setCurrentTime, stopContinuousPlayback],
    )

    const startContinuousUiTicker = useCallback(
        (engine: ContinuousPlaybackEngine) => {
            const tick = () => {
                if (continuousEngineRef.current !== engine || continuousRunIdRef.current !== engine.runId) {
                    return
                }
                const current = engine.current
                if (!current) {
                    continuousUiTickRef.current = requestAnimationFrame(tick)
                    return
                }
                const elapsed = Math.max(0, engine.ctx.currentTime - engine.startedAtCtx) * engine.playbackRate
                const absTime = clamp(current.start + elapsed, current.start, current.end)
                setPlaybackTime(absTime)

                const remaining = engine.scheduledEndCtx - engine.ctx.currentTime
                if (remaining <= CONTINUOUS_PREFETCH_LEAD_S) {
                    void ensureContinuousNextDecoded(engine)
                }
                if (
                    engine.next &&
                    !engine.nextSource &&
                    remaining <= CONTINUOUS_SCHEDULE_AHEAD_S
                ) {
                    scheduleDecodedContinuousNext(engine)
                }
                if (remaining <= -CONTINUOUS_ADVANCE_EPSILON_S) {
                    if (engine.stopAfterCurrent) {
                        const resumeTime = current.end
                        stopContinuousPlayback({ keepToggle: true })
                        restoreStandardAudioAfterContinuous(resumeTime)
                        setPlaybackTime(resumeTime)
                        return
                    }
                    if (current.end >= mediaDurationForPlaybackRef.current - 1e-6) {
                        setPlaybackTime(current.end)
                        stopContinuousPlayback()
                        restoreStandardAudioAfterContinuous(current.end)
                        return
                    }
                    void promoteContinuousNextSegment(engine)
                }
                continuousUiTickRef.current = requestAnimationFrame(tick)
            }
            continuousUiTickRef.current = requestAnimationFrame(tick)
        },
        [ensureContinuousNextDecoded, promoteContinuousNextSegment, restoreStandardAudioAfterContinuous, scheduleDecodedContinuousNext, setPlaybackTime, stopContinuousPlayback],
    )

    const startContinuousPlayback = useCallback(async (opts?: { startAt?: number; forceViewport?: boolean }) => {
        if (!media || currentProjectId == null) return
        const el = audioRef.current
        const duration = Number(media.duration_s) || 0
        const rawCurrentAbsTime =
            opts?.startAt != null && Number.isFinite(opts.startAt)
                ? opts.startAt
                : el && Number.isFinite(el.currentTime)
                    ? audioWindowStartRef.current + el.currentTime
                    : currentTime
        const currentAbsTime =
            duration > 0 && rawCurrentAbsTime >= duration - 1e-6
                ? resolveSpectrogramViewportWindow(
                    duration,
                    spectrogramViewStartRef.current,
                    spectrogramZoomPercentRef.current,
                ).viewStartClamped
                : rawCurrentAbsTime
        if (currentAbsTime !== rawCurrentAbsTime) {
            setPlaybackTime(currentAbsTime)
        }
        const firstSegment = (
            !opts?.forceViewport && playingAnnotationRef.current != null
                ? buildContinuousAnnotationSegment(playingAnnotationRef.current)
                : buildContinuousViewportSegment(
                    Number.isFinite(currentAbsTime)
                        ? currentAbsTime
                        : spectrogramViewStartRef.current,
                )
        ) ?? buildContinuousViewportSegment(spectrogramViewStartRef.current)
        if (!firstSegment) {
            setContinuousSegmentPlayback(false)
            continuousSegmentPlaybackRef.current = false
            setAudioLoading(false)
            setIsPlaying(false)
            return
        }

        stopContinuousPlayback({ keepToggle: true })
        clearPreviewWatchInterval()
        previewSelectionActiveRef.current = false
        if (el) {
            try {
                el.pause()
            } catch {
                /* ignore */
            }
        }

        const AudioCtx = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
        if (!AudioCtx) {
            message.error("Web Audio is not supported in this browser")
            setContinuousSegmentPlayback(false)
            continuousSegmentPlaybackRef.current = false
            return
        }

        const runId = continuousRunIdRef.current + 1
        continuousRunIdRef.current = runId
        try {
            const ctx = new AudioCtx()
            if (ctx.state === "suspended") await ctx.resume()
            const engine: ContinuousPlaybackEngine = {
                ctx,
                runId,
                current: null,
                next: null,
                source: null,
                nextSource: null,
                startedAtCtx: 0,
                scheduledEndCtx: 0,
                currentCtxDuration: 0,
                nextStartedAtCtx: null,
                nextScheduledEndCtx: null,
                nextCtxDuration: null,
                playbackRate: clamp(
                    playbackSpeedRef.current,
                    PLAYBACK_RATE_SLIDER_MIN,
                    PLAYBACK_RATE_SLIDER_MAX,
                ),
                prefetchingKey: null,
                stopAfterCurrent: false,
            }
            continuousEngineRef.current = engine
            setAudioLoading(true)
            const decoded = await decodeContinuousSegment(ctx, firstSegment, runId)
            if (!decoded || continuousRunIdRef.current !== runId) {
                if (continuousRunIdRef.current === runId) {
                    continuousEngineRef.current = null
                    setAudioLoading(false)
                    setIsPlaying(false)
                }
                try {
                    void ctx.close()
                } catch {
                    /* ignore */
                }
                return
            }
            setAudioLoading(false)
            setAudioReady(true)
            setIsPlaying(true)
            const when = ctx.currentTime + 0.035
            scheduleContinuousSegment(engine, decoded, when, runId)
            void ensureContinuousNextDecoded(engine)
            startContinuousUiTicker(engine)
        } catch {
            setAudioLoading(false)
            stopContinuousPlayback({ keepToggle: true })
            setContinuousSegmentPlayback(false)
            continuousSegmentPlaybackRef.current = false
            message.error("Could not start continuous playback")
        }
    }, [
        buildContinuousAnnotationSegment,
        buildContinuousViewportSegment,
        clearPreviewWatchInterval,
        currentProjectId,
        currentTime,
        decodeContinuousSegment,
        ensureContinuousNextDecoded,
        media,
        playbackSpeed,
        scheduleContinuousSegment,
        setPlaybackTime,
        startContinuousUiTicker,
        stopContinuousPlayback,
    ])

    useEffect(() => {
        startContinuousPlaybackRef.current = (opts) => {
            void startContinuousPlayback(opts)
        }
    }, [startContinuousPlayback])

    useEffect(() => {
        continuousSegmentPlaybackRef.current = continuousSegmentPlayback
        if (!continuousSegmentPlayback) {
            if (continuousEngineRef.current?.stopAfterCurrent) return
            stopContinuousPlayback({ keepToggle: true })
        }
    }, [continuousSegmentPlayback, stopContinuousPlayback])

    const toggleContinuousEnginePlayback = useCallback(() => {
        const engine = continuousEngineRef.current
        if (!engine) return
        const current = engine.current
        if (current) {
            const elapsed = Math.max(0, engine.ctx.currentTime - engine.startedAtCtx) * engine.playbackRate
            setPlaybackTime(clamp(current.start + elapsed, current.start, current.end))
        }
        if (engine.ctx.state === "running") {
            if (continuousUiTickRef.current != null) {
                cancelAnimationFrame(continuousUiTickRef.current)
                continuousUiTickRef.current = null
            }
            setIsPlaying(false)
            void engine.ctx.suspend().catch(() => {
                setIsPlaying(true)
                startContinuousUiTicker(engine)
            })
            return
        }
        if (engine.ctx.state === "suspended") {
            void engine.ctx.resume()
                .then(() => {
                    if (continuousEngineRef.current !== engine) return
                    setIsPlaying(true)
                    startContinuousUiTicker(engine)
                })
                .catch(() => {
                    stopContinuousPlayback({ keepToggle: true })
                })
            return
        }
        stopContinuousPlayback({ keepToggle: true })
    }, [setPlaybackTime, startContinuousUiTicker, stopContinuousPlayback])

    useEffect(() => {
        return () => {
            stopContinuousPlaybackRef.current()
        }
    }, [mediaId])

    const handlePlaybackBoundary = useCallback((opts?: { force?: boolean }) => {
        const a = audioRef.current
        if (!a) return
        if (!opts?.force && a.paused) return

        const dur = mediaDurationForPlaybackRef.current
        if (dur <= 0) return

        const segEnd =
            audioWindowEndRef.current > audioWindowStartRef.current
                ? clamp(audioWindowEndRef.current, 0, dur)
                : dur
        const tAbs = audioWindowStartRef.current + a.currentTime

        if (!opts?.force && tAbs < segEnd - 0.06) return
        try {
            a.pause()
            a.currentTime = Math.max(0, segEnd - audioWindowStartRef.current)
        } catch {
            /* ignore */
        }
        syncIsPlayingFromAudio()
        setCurrentTime(segEnd)
    }, [setCurrentTime, syncIsPlayingFromAudio])

    useEffect(() => {
        const a = audioRef.current
        if (!a) return

        const onTimeUpdate = () => {
            handlePlaybackBoundary()
        }

        a.addEventListener("timeupdate", onTimeUpdate)
        return () => a.removeEventListener("timeupdate", onTimeUpdate)
    }, [handlePlaybackBoundary])

    useEffect(() => {
        // 保留：仅用于避免表格勾选状态变化引发的重复副作用（不再自动 seek 播放进度）
        if (selectedAnnotationKeys.length !== 1) {
            prevSelectionSeekKeyRef.current = ""
            return
        }
        const id = Number(selectedAnnotationKeys[0])
        if (!Number.isFinite(id) || id <= 0) return
        prevSelectionSeekKeyRef.current = `sel-${id}`
    }, [selectedAnnotationKeys])

    const navigateAdjacentFromId = useCallback(
        async (baseAnnotationId: number, dir: -1 | 1, listOverride?: AnnotationPublic[]) => {
            const source = navAutoZoomToAnnotation
                ? await fetchAnnotationsForNavigation(true)
                : (listOverride ?? spectrogramAnnotations)
            const fullList = [...source].sort(compareAnnotationByMinTimeAndFrequency)
            const taskList = [...source]
                .filter((annotation) => annotationHasTaskTagForNav(annotation, meUserId))
                .sort(compareAnnotationByMinTimeAndFrequency)

            if (navOnlyTaskTagged) {
                if (taskList.length === 0) {
                    message.info("No annotation tasks on this media.")
                    return
                }
                const currentId = baseAnnotationId
                const idx = taskList.findIndex((x) => x.annotation_id === currentId)
                if (idx >= 0) {
                    const nextIdx = idx + dir
                    if (nextIdx < 0 || nextIdx >= taskList.length) {
                        message.info(
                            dir < 0
                                ? "Already at the first task annotation."
                                : "Already at the last task annotation.",
                        )
                        return
                    }
                    const nextAnn = taskList[nextIdx]
                    if (!nextAnn) return
                    void openAnnotationEditorById(nextAnn.annotation_id, {
                        autoZoom: navAutoZoomToAnnotation,
                        seek: navAutoZoomToAnnotation,
                    })
                    return
                }
                /** 当前标注不在任务子集内：按方向跳到最近一条带 Task 的标注 */
                const fullIdx = fullList.findIndex((x) => x.annotation_id === currentId)
                const taskIds = new Set(taskList.map((a) => a.annotation_id))
                const walkStart = fullIdx >= 0 ? fullIdx + dir : dir === 1 ? 0 : fullList.length - 1
                let nextAnn: AnnotationPublic | undefined
                for (let i = walkStart; i >= 0 && i < fullList.length; i += dir) {
                    const candidate = fullList[i]
                    if (candidate && taskIds.has(candidate.annotation_id)) {
                        nextAnn = candidate
                        break
                    }
                }
                if (!nextAnn) {
                    message.info(
                        dir < 0
                            ? "Already at the first task annotation."
                            : "Already at the last task annotation.",
                    )
                    return
                }
                void openAnnotationEditorById(nextAnn.annotation_id, {
                    autoZoom: navAutoZoomToAnnotation,
                    seek: navAutoZoomToAnnotation,
                })
                return
            }

            const idx = fullList.findIndex((x) => x.annotation_id === baseAnnotationId)
            if (idx < 0) {
                message.error("Current annotation is not in the navigation list.")
                return
            }
            const nextIdx = idx + dir
            if (nextIdx < 0 || nextIdx >= fullList.length) {
                message.info(dir < 0 ? "Already at the first annotation." : "Already at the last annotation.")
                return
            }
            const nextAnn = fullList[nextIdx]
            if (!nextAnn) return
            void openAnnotationEditorById(nextAnn.annotation_id, {
                autoZoom: navAutoZoomToAnnotation,
                seek: navAutoZoomToAnnotation,
            })
        },
        [
            fetchAnnotationsForNavigation,
            meUserId,
            navAutoZoomToAnnotation,
            navOnlyTaskTagged,
            openAnnotationEditorById,
            spectrogramAnnotations,
        ],
    )

    const goToAdjacentAnnotation = useCallback(
        (dir: -1 | 1) => {
            const baseId = editingAnnotationId
            if (baseId == null) return
            void navigateAdjacentFromId(baseId, dir)
        },
        [editingAnnotationId, navigateAdjacentFromId],
    )

    const handleSpectrogramAnnotationClick = useCallback(
        (e: React.MouseEvent, annotationId: number) => {
            e.preventDefault()
            e.stopPropagation()
            void openAnnotationEditorById(annotationId)
        },
        [openAnnotationEditorById],
    )

    const loadLabelPopover = useCallback(async () => {
        setLabelPopoverLoading(true)
        try {
            const list = await fetchLabelsCatalog(true)
            setToolbarLabelsCatalog(list)
            setLabelPopoverList(list)
            const rawNames = media?.labels
            const mediaLabelsNames = Array.isArray(rawNames)
                ? rawNames.filter((n): n is string => typeof n === "string" && n.trim() !== "")
                : []
            const firstMatched = mediaLabelsNames
                .map((n) => list.find((label) => label.name === n))
                .find(Boolean)
            setLabelPopoverSelectedId(firstMatched?.label_id ?? null)
        } catch {
            setLabelPopoverList([])
            message.error("Failed to load labels")
        } finally {
            setLabelPopoverLoading(false)
        }
    }, [media?.labels])

	    const applyLabelFromPopover = useCallback(
	        async (labelId: number | null) => {
	            setLabelPopoverSaving(true)
	            try {
	                if (currentProjectId == null) {
	                    message.error("Missing project context.")
	                    return
	                }
	                const res = await labelsApi.setMediaLabels([mediaId], currentProjectId, labelId)
                const c = res.code
	                if (c != null && c !== 0 && c !== 200) {
	                    message.error(res.message || "Failed to update label")
	                    return
	                }
	                const failed = Array.isArray(res.data?.failed) ? res.data.failed : []
	                if (failed.length > 0) {
	                    message.error(failed[0]?.message || "Failed to update label")
	                    return
	                }
	                const raw = await mediaApi.getRecordingDetail(mediaId, currentProjectId, true)
	                setMedia(normalizeRecordingDetail(raw))
	                setLabelPopoverSelectedId(labelId)
	                message.success(labelId == null ? "Label removed" : "Label updated")
                setLabelPopoverOpen(false)
            } catch (e: unknown) {
                message.error(e instanceof Error ? e.message : "Failed to update label")
            } finally {
                setLabelPopoverSaving(false)
            }
        },
	        [mediaId, currentProjectId],
	    )

    const handlePopoverAddLabel = useCallback(async () => {
        const name = labelPopoverNewName.trim()
        if (!name) return
        const exists = labelPopoverList.find((l) => l.name.toLowerCase() === name.toLowerCase())
        if (exists) {
            setLabelPopoverNewName("")
            await applyLabelFromPopover(exists.label_id)
            return
        }
        setLabelPopoverAdding(true)
        try {
            const res = await labelsApi.createLabel(name)
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to create label")
                return
            }
            const list = await fetchLabelsCatalog(true)
            setToolbarLabelsCatalog(list)
            setLabelPopoverList(list)
            setLabelPopoverNewName("")
            const match = list.find((l) => l.name.toLowerCase() === name.toLowerCase())
            if (match) {
                await applyLabelFromPopover(match.label_id)
            } else {
                message.success("Label created")
            }
        } catch {
            message.error("Failed to create label")
        } finally {
            setLabelPopoverAdding(false)
        }
    }, [labelPopoverNewName, labelPopoverList, applyLabelFromPopover])

    const handlePopoverDeleteLabel = useCallback(
        async (labelId: number) => {
            if (labelPopoverDeletingId != null) return
            setLabelPopoverDeletingId(labelId)
            try {
                const res = await labelsApi.deleteLabel(labelId)
                const c = res.code
                if (c != null && c !== 0 && c !== 200) {
                    message.error(res.message || "Failed to delete label")
                    return
                }
                message.success("Label deleted")
                const list = await fetchLabelsCatalog(true)
                setToolbarLabelsCatalog(list)
                setLabelPopoverList(list)
                setLabelPopoverSelectedId((cur) => (cur === labelId ? null : cur))
	                if (currentProjectId == null) {
	                    message.error("Missing project context.")
	                    return
	                }
	                const raw = await mediaApi.getRecordingDetail(mediaId, currentProjectId, true)
                setMedia(normalizeRecordingDetail(raw))
            } catch (e: unknown) {
                message.error(e instanceof Error ? e.message : "Failed to delete label")
            } finally {
                setLabelPopoverDeletingId(null)
            }
        },
	        [labelPopoverDeletingId, mediaId, currentProjectId],
	    )

    const onLabelPopoverOpenChange = useCallback(
        (open: boolean) => {
            setLabelPopoverOpen(open)
            if (!open) setLabelPopoverDeletingId(null)
            if (open) {
                setLabelPopoverNewName("")
                void loadLabelPopover()
            }
        },
        [loadLabelPopover],
    )

    useEffect(() => {
        stopContinuousPlaybackRef.current()
        setLabelPopoverOpen(false)
        setAudioChannel(1)
        spectrogramFitPendingMediaIdRef.current = mediaId
        setSpectrogramZoomPercent(0)
        setSpectrogramViewStart(0)
        setAudioBandFilter(false)
        activeViewportParamsKeyRef.current = null
        activeAudioViewportParamsKeyRef.current = null
        audioWindowStartRef.current = 0
        audioWindowEndRef.current = 0
        lastFetchedAudioReloadTokenRef.current = -1
    }, [mediaId])

    useEffect(() => {
        spectrogramMagnifierZoomedRef.current = spectrogramMagnifierZoomed
    }, [spectrogramMagnifierZoomed])

    useEffect(() => {
        if (spectrogramFitPendingMediaIdRef.current !== mediaId) return
        if (!media) return
        if (pickRecordingDetailId(media) !== mediaId) return
        const dur = Number(media.duration_s) || 0
        const w = viewportSize.w
        if (!(dur > 0) || !(w > 0)) return
        fitSpectrogramToFullDuration()
        spectrogramFitPendingMediaIdRef.current = null
    }, [mediaId, media, media?.duration_s, viewportSize.w, fitSpectrogramToFullDuration])

    const applyAudioElementPlaybackRate = useCallback((audio = audioRef.current, rate = playbackSpeedRef.current) => {
        const r = clamp(rate, PLAYBACK_RATE_SLIDER_MIN, PLAYBACK_RATE_SLIDER_MAX)
        playbackSpeedRef.current = r
        if (r !== rate) {
            setPlaybackSpeed(r)
        }
        if (!audio) return r
        try {
            const pitchAudio = audio as HTMLAudioElement & {
                preservesPitch?: boolean
                mozPreservesPitch?: boolean
                webkitPreservesPitch?: boolean
            }
            pitchAudio.preservesPitch = false
            pitchAudio.mozPreservesPitch = false
            pitchAudio.webkitPreservesPitch = false
            audio.defaultPlaybackRate = r
            audio.playbackRate = r
            return r
        } catch {
            try {
                audio.defaultPlaybackRate = 1
                audio.playbackRate = 1
            } catch {
                /* ignore */
            }
            playbackSpeedRef.current = 1
            setPlaybackSpeed(1)
            return 1
        }
    }, [])

    useEffect(() => {
        applyAudioElementPlaybackRate(audioRef.current, playbackSpeed)
    }, [applyAudioElementPlaybackRate, playbackSpeed])

    useEffect(() => {
        const resumeTime = standardPlayAfterLoadRef.current
        if (resumeTime == null || !audioReady || !audioBlobUrl) return
        const el = audioRef.current
        if (!el) return
        standardPlayAfterLoadRef.current = null
        applyAudioElementPlaybackRate(el)
        seekAudioElementToAbsoluteTime(resumeTime)
        setPlaybackTime(resumeTime)
        void el.play()
            .then(() => {
                syncIsPlayingFromAudio()
            })
            .catch(() => {
                syncIsPlayingFromAudio()
            })
    }, [
        applyAudioElementPlaybackRate,
        audioBlobUrl,
        audioReady,
        seekAudioElementToAbsoluteTime,
        setPlaybackTime,
        syncIsPlayingFromAudio,
    ])

    const getLivePlaybackTime = useCallback(() => {
        const engine = continuousEngineRef.current
        const current = engine?.current
        if (engine && current) {
            const elapsed = Math.max(0, engine.ctx.currentTime - engine.startedAtCtx) * engine.playbackRate
            return clamp(current.start + elapsed, current.start, current.end)
        }
        const el = audioRef.current
        if (el && Number.isFinite(el.currentTime)) {
            return audioWindowStartRef.current + el.currentTime
        }
        return currentTimeRef.current
    }, [])

    const interruptStandardAudioRequest = useCallback((opts?: { preserveTime?: boolean; preserveAt?: number }) => {
        const el = audioRef.current
        if (opts?.preserveTime) {
            const liveTime = opts.preserveAt ?? getLivePlaybackTime()
            if (Number.isFinite(liveTime)) {
                audioPreserveTimeRef.current = liveTime
                setPlaybackTime(liveTime)
            }
        }
        audioRequestIdRef.current += 1
        activeAudioRequestIdRef.current = audioRequestIdRef.current
        audioElementRequestIdRef.current = audioRequestIdRef.current
        activeAudioViewportParamsKeyRef.current = null
        lastFetchedAudioReloadTokenRef.current = -1
        if (el) {
            try {
                el.pause()
            } catch {
                /* ignore */
            }
            try {
                el.removeAttribute("src")
                el.load()
            } catch {
                /* ignore */
            }
        }
        setAudioBlobUrl(null)
        setAudioReady(false)
        setAudioLoading(false)
        setIsPlaying(false)
        audioWindowEndRef.current = 0
    }, [getLivePlaybackTime, setPlaybackTime])

    const handlePlayToggle = useCallback(() => {
        const continuousEngine = continuousEngineRef.current
        if (continuousEngine) {
            toggleContinuousEnginePlayback()
            return
        }
        if (continuousSegmentPlaybackRef.current) {
            const now = Date.now()
            if (now < audioControlCooldownUntilRef.current) return
            audioControlCooldownUntilRef.current = now + AUDIO_CONTROL_COOLDOWN_MS
            const el = audioRef.current
            if (el && !el.paused && !el.ended) {
                if (Number.isFinite(el.currentTime)) {
                    setPlaybackTime(audioWindowStartRef.current + el.currentTime)
                }
                el.pause()
                syncIsPlayingFromAudio()
                return
            }
            const startAt =
                Number.isFinite(currentTimeRef.current)
                    ? currentTimeRef.current
                    : Number.isFinite(currentTime)
                        ? currentTime
                    : (() => {
                        return el && Number.isFinite(el.currentTime)
                            ? audioWindowStartRef.current + el.currentTime
                            : spectrogramViewStartRef.current
                    })()
            startContinuousPlaybackRef.current({
                startAt,
                forceViewport: true,
            })
            return
        }
        if (isAudioBusy) return
        const a = audioRef.current
        if (!a?.src) return
        const now = Date.now()
        if (now < audioControlCooldownUntilRef.current) return
        audioControlCooldownUntilRef.current = now + AUDIO_CONTROL_COOLDOWN_MS

        if (a.paused) {
            applyAudioElementPlaybackRate(a)
            // If we're zoomed into a time window, start playback from the visible window start
            // (unless user already scrubbed into the window).
            const dur = mediaDurationForPlaybackRef.current
            const win =
                dur > 0 ? spectrogramVisibleWindowSec(dur, spectrogramZoomPercentRef.current) : 0
            const zoomed = dur > 0 && win > 0 && win + 1e-9 < dur
            if (zoomed) {
                const { windowSec, viewStartClamped: viewStart } = resolveSpectrogramViewportWindow(
                    dur,
                    spectrogramViewStartRef.current,
                    spectrogramZoomPercentRef.current,
                )
                const viewEnd = Math.min(viewStart + windowSec, dur)
                const tAbs = audioWindowStartRef.current + a.currentTime
                const scrubbedTime = userScrubbedPlaybackTimeRef.current
                const hasRecentScrub =
                    scrubbedTime != null &&
                    Number.isFinite(tAbs) &&
                    Math.abs(scrubbedTime - tAbs) <= 0.08
                const atOrPastViewEnd =
                    Number.isFinite(tAbs) &&
                    (tAbs >= viewEnd - 0.06 || Math.abs(currentTimeRef.current - viewEnd) <= 0.06)
                const shouldSeek =
                    !hasRecentScrub &&
                    (!Number.isFinite(tAbs) ||
                        tAbs <= viewStart + 1e-3 ||
                        tAbs < viewStart - 1e-3 ||
                        a.ended ||
                        atOrPastViewEnd)
                if (shouldSeek) {
                    seekAudioElementToAbsoluteTime(viewStart)
                    setPlaybackTime(viewStart)
                }
            }
            userScrubbedPlaybackTimeRef.current = null

            void a.play()
                .then(() => {
                    syncIsPlayingFromAudio()
                })
                .catch(() => {
                    syncIsPlayingFromAudio()
                })
        } else {
            a.pause()
            syncIsPlayingFromAudio()
        }
    }, [
        applyAudioElementPlaybackRate,
        currentTime,
        isAudioBusy,
        seekAudioElementToAbsoluteTime,
        setPlaybackTime,
        stopContinuousPlayback,
        syncIsPlayingFromAudio,
        toggleContinuousEnginePlayback,
    ])

    const handleStop = useCallback(() => {
        stopContinuousPlayback()
        const a = audioRef.current
        if (!a) return
        const now = Date.now()
        if (audioLoading || now < audioControlCooldownUntilRef.current) return
        audioControlCooldownUntilRef.current = now + AUDIO_CONTROL_COOLDOWN_MS
        const dur = mediaDurationForPlaybackRef.current
        const resetTime =
            dur > 0
                ? resolveSpectrogramViewportWindow(
                    dur,
                    spectrogramViewStartRef.current,
                    spectrogramZoomPercentRef.current,
                ).viewStartClamped
                : Math.max(0, spectrogramViewStartRef.current)
        a.pause()
        seekAudioElementToAbsoluteTime(resetTime)
        syncIsPlayingFromAudio()
        setPlaybackTime(resetTime)
    }, [audioLoading, seekAudioElementToAbsoluteTime, stopContinuousPlayback, syncIsPlayingFromAudio])

    useLayoutEffect(() => {
        if (loading || !media) return
        const el = viewportRef.current
        if (!el) return
        const update = () => {
            const { w, h } = readViewportLayoutSize(el)
            setViewportSize({ w, h })
        }
        update()
        const ro = new ResizeObserver(update)
        ro.observe(el)
        return () => ro.disconnect()
    }, [loading, media, readViewportLayoutSize, spectrogramBlobUrl])

    const dismissAnnotationPanelAfterMagnify = useCallback(() => {
        setRightPanel("info")
        setAnnotationDraft(null)
        setEditingAnnotationId(null)
        setEditingAnnotationMeta(null)
        setEditingAnnotationReviews([])
        setReviewPanelExpanded(true)
        pendingReviewInitRef.current = false
        setReviewStatusId(REVIEW_STATUS_IDS.accepted)
        setReviewNote("")
        setReviewTaxonId(null)
        setReviewTaxonSearch("")
        reviewTaxonOptionsState.reset()
        setMarqueePx(null)
        setMarqueeCreating(false)
        setAnnotationDraftHasSize(false)
        draftInteractionRef.current = null
    }, [reviewTaxonOptionsState.reset])

    const closeAnnotationPanel = useCallback(() => {
        const closingAnnotationId = editingAnnotationId
        setRightPanel("info")
        setAnnotationDraft(null)
        setEditingAnnotationId(null)
        setEditingAnnotationMeta(null)
        setEditingAnnotationReviews([])
        if (closingAnnotationId != null) {
            setSelectedAnnotationKeys((prev) => {
                const next = prev.filter((k) => Number(k) !== closingAnnotationId)
                annotationTableSelectedIdsRef.current = next
                    .map((k) => Number(k))
                    .filter((n) => Number.isFinite(n) && n > 0)
                return next
            })
            setAnnotationLinkedHighlightId((current) =>
                current === closingAnnotationId ? null : current,
            )
        }
        setReviewPanelExpanded(true)
        pendingReviewInitRef.current = false
        setReviewStatusId(REVIEW_STATUS_IDS.accepted)
        setReviewNote("")
        setReviewTaxonId(null)
        setReviewTaxonSearch("")
        reviewTaxonOptionsState.reset()
        setMarqueePx(null)
        setMarqueeCreating(false)
        setAnnotationDraftHasSize(false)
        draftInteractionRef.current = null
        clearSpectrogramMagnifierBackup()
    }, [clearSpectrogramMagnifierBackup, editingAnnotationId, reviewTaxonOptionsState.reset])

    const handleDeleteEditingAnnotation = useCallback(async () => {
        const id = reviewContextAnnotationId
        if (id == null) {
            message.error("Missing annotation id.")
            return
        }
        const loadingId = openLoadingMessage("Deleting annotation...")
        try {
            if (currentProjectId == null) {
                message.error("Missing project context.")
                return
            }
            await annotationsApi.delete(id, currentProjectId)
            updateMessageSuccess(loadingId, "Annotation deleted.")
            setDeleteEditingAnnotationConfirmOpen(false)
            setSelectedAnnotationKeys((prev) => prev.filter((k) => Number(k) !== id))
            annotationTableSelectedIdsRef.current = annotationTableSelectedIdsRef.current.filter((n) => n !== id)
            closeAnnotationPanel()
            setAnnotationListTick((n) => n + 1)
        } catch (e: unknown) {
            updateMessageError(loadingId, e instanceof Error ? e.message : "Delete failed")
        } finally {
            closeLoadingMessage(loadingId)
        }
    }, [closeAnnotationPanel, currentProjectId, reviewContextAnnotationId])

    const exitAnnotationPanelIfActive = useCallback(() => {
        if (!annotationPanelActiveRef.current) return
        closeAnnotationPanel()
    }, [closeAnnotationPanel])

    const handleAnnotToolbarMagnifierZoom = useCallback(() => {
        if (spectrogramMagnifierZoomed) return
        const dur = Number(media?.duration_s) || 0
        const sr = Number(media?.sampling_rate_hz) || 0
        if (!(dur > 0)) return

        let layout: MagnifierLayout | null = null
        if (annotationDraft) {
            const stub: AnnotationPublic = {
                annotation_id:
                    editingAnnotationId != null && editingAnnotationId > 0 ? editingAnnotationId : 0,
                min_x: annotationDraft.min_x,
                max_x: annotationDraft.max_x,
                min_y: annotationDraft.min_y,
                max_y: annotationDraft.max_y,
            } as AnnotationPublic
            layout = computeMagnifierLayoutForAnnotation(stub, dur, sr)
        } else if (editingAnnotationMeta != null && editingAnnotationId != null && editingAnnotationId > 0) {
            layout = computeMagnifierLayoutForAnnotation(editingAnnotationMeta, dur, sr)
        }
        if (!layout) return

        setAnnotationDraftOverlayVisible(false)
        applyMagnifierZoomLayout(layout)
        audioPreserveTimeRef.current = layout.vs
        syncPlaybackToSpectrogramViewStart(layout.vs)
        if (annotationPanelActiveRef.current) {
            const dismissPanel = dismissAnnotationPanelAfterMagnify
            requestAnimationFrame(() => {
                dismissPanel()
            })
        }
    }, [
        annotationDraft,
        applyMagnifierZoomLayout,
        dismissAnnotationPanelAfterMagnify,
        editingAnnotationId,
        editingAnnotationMeta,
        media?.duration_s,
        media?.sampling_rate_hz,
        spectrogramMagnifierZoomed,
        syncPlaybackToSpectrogramViewStart,
    ])

    const prepareNewAnnotationDraft = useCallback(() => {
        setEditingAnnotationId(null)
        setEditingAnnotationMeta(null)
        setEditingAnnotationReviews([])
        setReviewPanelExpanded(true)
        pendingReviewInitRef.current = false
        resetAnnotationFormFields()
        spectrogramMagnifierBackupRef.current = null
        setSpectrogramMagnifierZoomed(false)
        setAnnotationDraftOverlayVisible(true)
        setDistanceFieldUnlocked(false)
        setRightPanel("new-annotation")
    }, [resetAnnotationFormFields])

    const onMarqueePointerDown = useCallback(
        (e: React.PointerEvent<HTMLDivElement>) => {
            if (e.button !== 0) return
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault()
                e.stopPropagation()
                seekSpectrogramToClientXRef.current?.(e.clientX)
                return
            }
            setAnnotationDraftOverlayVisible(true)
            setMarqueePx(null)
            setMarqueeCreating(false)
            if (rightPanel === "new-annotation") {
                setAnnotationDraft(null)
                setEditingAnnotationId(null)
                setEditingAnnotationMeta(null)
                setEditingAnnotationReviews([])
                setReviewPanelExpanded(true)
                pendingReviewInitRef.current = false
                spectrogramMagnifierBackupRef.current = null
                setSpectrogramMagnifierZoomed(false)
                setRightPanel("info")
            } else if (rightPanel === "assign-task") {
                setRightPanel("info")
            }
            const el = viewportRef.current
            if (!el) return
            const { x, y } = clientToViewportLayoutPoint(el, e.clientX, e.clientY)
            e.preventDefault()
            e.currentTarget.setPointerCapture(e.pointerId)
            setMarqueeCreating(true)
            draftInteractionRef.current = {
                mode: "create",
                pointerId: e.pointerId,
                x0: x,
                y0: y,
                x1: x,
                y1: y,
                panelOpened: false,
            }
            setMarqueePx(null)
            setAnnotationDraftHasSize(false)
        },
        [clientToViewportLayoutPoint, rightPanel],
    )

    const onMarqueePointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
        const interaction = draftInteractionRef.current
        if (!interaction || interaction.mode !== "create" || interaction.pointerId !== e.pointerId) return
        const el = viewportRef.current
        if (!el || !media) return
        const { x, y } = clientToViewportLayoutPoint(el, e.clientX, e.clientY)
        interaction.x1 = x
        interaction.y1 = y
        const { w, h } = readViewportLayoutSize(el)
        if (w <= 0 || h <= 0) return
        const left = Math.min(interaction.x0, interaction.x1)
        const top = Math.min(interaction.y0, interaction.y1)
        const width = Math.abs(interaction.x1 - interaction.x0)
        const height = Math.abs(interaction.y1 - interaction.y0)
        const hasSize =
            width >= SPECTROGRAM_DRAFT_MIN_SIZE_PX &&
            height >= SPECTROGRAM_DRAFT_MIN_SIZE_PX
        setAnnotationDraftHasSize(hasSize)
        setMarqueePx(
            hasSize
                ? normalizeDraftPixelRect({ left, top, width, height }, w, h)
                : null,
        )
        if (!hasSize) {
            e.preventDefault()
            return
        }
        const nyq =
            Number(media.sampling_rate_hz) > 0
                ? Math.round(Number(media.sampling_rate_hz) / 2)
                : 24000
        const f0 = clamp(specFreqMinHz, 0, nyq)
        const f1 = clamp(specFreqMaxHz, f0, nyq)
        const phys = pixelsToPhysWindow(
            interaction.x0,
            interaction.y0,
            interaction.x1,
            interaction.y1,
            w,
            h,
            spectrogramLayout.viewStartClamped,
            spectrogramLayout.windowSec,
            f0,
            f1,
        )
        if (!interaction.panelOpened) {
            prepareNewAnnotationDraft()
            interaction.panelOpened = true
        }
        setAnnotationDraft(phys)
        e.preventDefault()
    }, [
        clientToViewportLayoutPoint,
        media,
        prepareNewAnnotationDraft,
        readViewportLayoutSize,
        specFreqMaxHz,
        specFreqMinHz,
        spectrogramLayout.viewStartClamped,
        spectrogramLayout.windowSec,
    ])

    const onMarqueePointerUp = useCallback(
        (
            e: React.PointerEvent<HTMLDivElement>,
            _totalDur: number,
            nyq: number,
            freqMinHz: number,
            freqMaxHz: number,
            viewStart: number,
            windowSec: number,
        ) => {
            const interaction = draftInteractionRef.current
            draftInteractionRef.current = null
            setMarqueeCreating(false)
            try {
                e.currentTarget.releasePointerCapture(e.pointerId)
            } catch {
                /* already released */
            }
            if (!interaction || interaction.mode !== "create" || interaction.pointerId !== e.pointerId) return
            const el = viewportRef.current
            if (!el) return
            const { w, h } = readViewportLayoutSize(el)
            if (w < 8 || h < 8) return
            const x0 = clamp(interaction.x0, 0, w)
            const y0 = clamp(interaction.y0, 0, h)
            const x1 = clamp(interaction.x1, 0, w)
            const y1 = clamp(interaction.y1, 0, h)
            const hasSize =
                Math.abs(x1 - x0) >= SPECTROGRAM_DRAFT_MIN_SIZE_PX &&
                Math.abs(y1 - y0) >= SPECTROGRAM_DRAFT_MIN_SIZE_PX
            if (!hasSize) {
                setMarqueePx(null)
                setAnnotationDraft(null)
                setAnnotationDraftHasSize(false)
                if (interaction.panelOpened) {
                    setRightPanel("info")
                }
                return
            }
            const rect = normalizeDraftPixelRect(
                {
                    left: Math.min(x0, x1),
                    top: Math.min(y0, y1),
                    width: Math.abs(x1 - x0),
                    height: Math.abs(y1 - y0),
                },
                w,
                h,
            )
            const f0 = clamp(freqMinHz, 0, nyq)
            const f1 = clamp(freqMaxHz, f0, nyq)
            const phys = pixelsToPhysWindow(
                x0,
                y0,
                x1,
                y1,
                w,
                h,
                viewStart,
                windowSec,
                f0,
                f1,
            )
            if (!interaction.panelOpened) {
                prepareNewAnnotationDraft()
            }
            setAnnotationDraft(phys)
            setMarqueePx(rect)
            setAnnotationDraftHasSize(true)
        },
        [prepareNewAnnotationDraft, readViewportLayoutSize],
    )

    const commitDraftRectPx = useCallback(
        (rect: PixelRect) => {
            if (!media) return
            const el = viewportRef.current
            if (!el) return
            const { w, h } = readViewportLayoutSize(el)
            if (!(w > 0) || !(h > 0)) return
            const nyq =
                Number(media.sampling_rate_hz) > 0
                    ? Math.round(Number(media.sampling_rate_hz) / 2)
                    : 24000
            const f0 = clamp(specFreqMinHz, 0, nyq)
            const f1 = clamp(specFreqMaxHz, f0, nyq)
            const normalized = normalizeDraftPixelRect(rect, w, h)
            const phys = pixelsToPhysWindow(
                normalized.left,
                normalized.top,
                normalized.left + normalized.width,
                normalized.top + normalized.height,
                w,
                h,
                spectrogramLayout.viewStartClamped,
                spectrogramLayout.windowSec,
                f0,
                f1,
            )
            setAnnotationDraft(phys)
            setMarqueePx(normalized)
        },
        [
            media,
            readViewportLayoutSize,
            specFreqMaxHz,
            specFreqMinHz,
            spectrogramLayout.viewStartClamped,
            spectrogramLayout.windowSec,
        ],
    )

    const handleDraftMovePointerDown = useCallback(
        (e: React.PointerEvent<HTMLDivElement>) => {
            if (e.button !== 0 || editingAnnotationId != null || !annotationDraftHasSize || !marqueePx) return
            e.preventDefault()
            e.stopPropagation()
            e.currentTarget.setPointerCapture(e.pointerId)
            const el = viewportRef.current
            if (!el) return
            const { w, h } = readViewportLayoutSize(el)
            draftInteractionRef.current = {
                mode: "move",
                pointerId: e.pointerId,
                startClientX: e.clientX,
                startClientY: e.clientY,
                startRect: marqueePx,
                viewportW: w,
                viewportH: h,
            }
        },
        [annotationDraftHasSize, editingAnnotationId, marqueePx, readViewportLayoutSize],
    )

    const handleDraftMovePointerMove = useCallback(
        (e: React.PointerEvent<HTMLDivElement>) => {
            const interaction = draftInteractionRef.current
            if (!interaction || interaction.mode !== "move" || interaction.pointerId !== e.pointerId) return
            e.preventDefault()
            e.stopPropagation()
            const dx = e.clientX - interaction.startClientX
            const dy = e.clientY - interaction.startClientY
            const nextRect = {
                ...interaction.startRect,
                left: clamp(
                    interaction.startRect.left + dx,
                    0,
                    Math.max(0, interaction.viewportW - interaction.startRect.width),
                ),
                top: clamp(
                    interaction.startRect.top + dy,
                    0,
                    Math.max(0, interaction.viewportH - interaction.startRect.height),
                ),
            }
            commitDraftRectPx(nextRect)
        },
        [commitDraftRectPx],
    )

    const handleDraftMovePointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
        const interaction = draftInteractionRef.current
        if (!interaction || interaction.mode !== "move" || interaction.pointerId !== e.pointerId) return
        draftInteractionRef.current = null
        try {
            e.currentTarget.releasePointerCapture(e.pointerId)
        } catch {
            /* ignore */
        }
    }, [])

    const handleDraftResizePointerDown = useCallback(
        (handle: DraftResizeHandle) => (e: React.PointerEvent<HTMLSpanElement>) => {
            if (e.button !== 0 || editingAnnotationId != null || !annotationDraftHasSize || !marqueePx) return
            e.preventDefault()
            e.stopPropagation()
            e.currentTarget.setPointerCapture(e.pointerId)
            const el = viewportRef.current
            if (!el) return
            const { w, h } = readViewportLayoutSize(el)
            draftInteractionRef.current = {
                mode: "resize",
                pointerId: e.pointerId,
                handle,
                startClientX: e.clientX,
                startClientY: e.clientY,
                startRect: marqueePx,
                viewportW: w,
                viewportH: h,
            }
        },
        [annotationDraftHasSize, editingAnnotationId, marqueePx, readViewportLayoutSize],
    )

    const handleDraftResizePointerMove = useCallback(
        (e: React.PointerEvent<HTMLSpanElement>) => {
            const interaction = draftInteractionRef.current
            if (!interaction || interaction.mode !== "resize" || interaction.pointerId !== e.pointerId) return
            e.preventDefault()
            e.stopPropagation()
            const dx = e.clientX - interaction.startClientX
            const dy = e.clientY - interaction.startClientY
            const nextRect = resizeDraftPixelRectFromHandle(
                interaction.startRect,
                interaction.handle,
                dx,
                dy,
                interaction.viewportW,
                interaction.viewportH,
            )
            commitDraftRectPx(nextRect)
        },
        [commitDraftRectPx],
    )

    const handleDraftResizePointerUp = useCallback((e: React.PointerEvent<HTMLSpanElement>) => {
        const interaction = draftInteractionRef.current
        if (!interaction || interaction.mode !== "resize" || interaction.pointerId !== e.pointerId) return
        draftInteractionRef.current = null
        try {
            e.currentTarget.releasePointerCapture(e.pointerId)
        } catch {
            /* ignore */
        }
    }, [])

    const runAnnotationPreviewPlayback = useCallback(
        (startAt: number, end: number) => {
            const a = audioRef.current
            if (!a) return
            clearPreviewWatchInterval()

            const durMedia = Number(media?.duration_s) || 0
            if (end <= startAt + 0.02) {
                message.error("Selection is too short to preview.")
                return
            }
            const bio = formSoundscape != null && formSoundscape.toLowerCase() === "biophony"
            previewSelectionEndSecRef.current = end
            previewSelectionActiveRef.current = true
            if (bio) {
                setDistanceFieldUnlocked(false)
            }

            const finishPreview = () => {
                clearPreviewWatchInterval()
                if (!previewSelectionActiveRef.current) return
                previewSelectionActiveRef.current = false
                try {
                    a.pause()
                } catch {
                    /* ignore */
                }
                syncIsPlayingFromAudio()
                setDistanceFieldUnlocked(true)
            }

            const tick = () => {
                if (!previewSelectionActiveRef.current) return
                const endSec = previewSelectionEndSecRef.current
                const durEl = Number.isFinite(a.duration) && a.duration > 0 ? a.duration : durMedia
                const effectiveEnd = durEl > 0 ? Math.min(endSec, durEl) : endSec
                const t = a.currentTime
                const pastSelection = t + 1e-3 >= effectiveEnd - 0.12
                const pastDecode =
                    durEl > 0 && t + 1e-3 >= durEl - 0.15 && endSec >= durEl - 0.05
                if (pastSelection || pastDecode || a.ended) {
                    finishPreview()
                }
            }

            try {
                a.pause()
            } catch {
                /* ignore */
            }
            syncIsPlayingFromAudio()
            a.currentTime = startAt

            let playbackStarted = false
            const startPlay = () => {
                if (playbackStarted) return
                playbackStarted = true
                void a.play()
                    .then(() => {
                        syncIsPlayingFromAudio()
                    })
                    .catch(() => {
                        syncIsPlayingFromAudio()
                        clearPreviewWatchInterval()
                        previewSelectionActiveRef.current = false
                        message.error("Could not play audio")
                    })
                previewWatchIntervalRef.current = window.setInterval(tick, 45)
                const spanSec = Math.max(0.2, end - startAt)
                const capMs = Math.min(180_000, spanSec * 1000 * 2 + 4000)
                previewSafetyTimerRef.current = window.setTimeout(() => {
                    if (previewSelectionActiveRef.current) finishPreview()
                }, capMs)
            }

            const onSeeked = () => {
                a.removeEventListener("seeked", onSeeked)
                startPlay()
            }
            a.addEventListener("seeked", onSeeked, { once: true })
            window.setTimeout(() => {
                if (!previewSelectionActiveRef.current || playbackStarted) return
                a.removeEventListener("seeked", onSeeked)
                startPlay()
            }, 120)
        },
        [clearPreviewWatchInterval, formSoundscape, media?.duration_s, syncIsPlayingFromAudio],
    )

    useEffect(() => {
        const pending = previewPlayAfterLoadRef.current
        if (!pending || !audioReady || !audioBlobUrl) return
        previewPlayAfterLoadRef.current = null
        runAnnotationPreviewPlayback(pending.startAt, pending.end)
    }, [audioBlobUrl, audioReady, runAnnotationPreviewPlayback])

    const previewAnnotationRegion = useCallback(() => {
        if (!annotationDraft) return

        const durMedia = Number(media?.duration_s) || 0
        const start = Math.min(annotationDraft.min_x, annotationDraft.max_x)
        const endRaw = Math.max(annotationDraft.min_x, annotationDraft.max_x)
        const end = durMedia > 0 ? Math.min(endRaw, durMedia) : endRaw
        const startAt = Math.max(0, start)
        if (end <= startAt + 0.02) {
            message.error("Selection is too short to preview.")
            return
        }

        if (audioBandFilter) {
            const sr = Number(media?.sampling_rate_hz) || 0
            const nyq = sr > 0 ? Math.round(sr / 2) : 24000
            const band = physBoxFreqBandHz(annotationDraft, nyq)
            pendingAudioBandpassHzRef.current = { lo: band.lo, hi: band.hi }
            const viewport = buildDetailViewportParams()
            const key = viewport ? viewportParamsKey(viewport) : null
            if (key != null && key !== activeViewportParamsKeyRef.current) {
                previewPlayAfterLoadRef.current = { startAt, end }
                activeViewportParamsKeyRef.current = null
                setAudioReloadToken((n) => n + 1)
                return
            }
        }

        runAnnotationPreviewPlayback(startAt, end)
    }, [
        annotationDraft,
        audioBandFilter,
        buildDetailViewportParams,
        media?.channels,
        media?.duration_s,
        media?.sampling_rate_hz,
        runAnnotationPreviewPlayback,
    ])

    const handleSaveAnnotation = useCallback(async () => {
        if (!annotationDraft) return
        setSavePending(true)
        try {
            if (isPhoto && formObjectType === null) {
                message.error("Please select Object Type")
                return
            }
            if (!isPhoto && formSoundscape === null) {
                message.error("Please select Soundscape")
                return
            }
            if (!isPhoto && formSoundTypeSoundId == null) {
                message.error("Please select Sound Type")
                return
            }
            if (!isPhoto && soundClassifications.length === 0) {
                message.error("Sound classifications unavailable. Refresh and try again.")
                return
            }

            const min_x = roundAnnotationCoord(Math.min(annotationDraft.min_x, annotationDraft.max_x))
            const max_x = roundAnnotationCoord(Math.max(annotationDraft.min_x, annotationDraft.max_x))
            const min_y = roundAnnotationCoord(Math.min(annotationDraft.min_y, annotationDraft.max_y))
            const max_y = roundAnnotationCoord(Math.max(annotationDraft.min_y, annotationDraft.max_y))

            const patch: UpdateAnnotationPayload = {
                min_x,
                max_x,
                min_y,
                max_y,
                sound_id: isPhoto ? null : formSoundTypeSoundId,
                object_type: isPhoto ? formObjectType : null,
            }

            if (formUncertain === "true") patch.uncertain = true
            else if (formUncertain === "false") patch.uncertain = false

            const c = formComments.trim()
            if (c) patch.comments = c
            else patch.comments = null

            if (formReference === "true") patch.reference = true
            else if (formReference === "false") patch.reference = false

            const bio = !isPhoto && formSoundscape!.toLowerCase() === "biophony"
            if (isPhoto && formObjectType === "other") {
                patch.taxon_id = null
                patch.uncertain = null
                patch.individual_num = null
                patch.animal_sound_type = null
                patch.sound_distance_m = null
                patch.distance_not_estimable = null
                patch.confidence = null
            } else if (isPhoto) {
                patch.individual_num = Math.max(1, Math.trunc(formIndividualNum) || 1)
                patch.taxon_id = formTaxonId == null ? null : Math.trunc(formTaxonId)
                patch.animal_sound_type = null
                patch.sound_distance_m = null
                patch.distance_not_estimable = null
                patch.confidence = null
            } else if (bio) {
                patch.individual_num = Math.max(1, Math.trunc(formIndividualNum) || 1)
                if (formAnimalSound.trim()) {
                    patch.animal_sound_type = formAnimalSound.trim()
                } else {
                    patch.animal_sound_type = null
                }
                if (formDistanceNotEstimable) {
                    patch.distance_not_estimable = true
                    patch.sound_distance_m = null
                } else if (formDistanceM != null && Number.isFinite(formDistanceM) && formDistanceM >= 0) {
                    patch.sound_distance_m = Math.round(formDistanceM)
                    patch.distance_not_estimable = false
                } else {
                    patch.distance_not_estimable = false
                    patch.sound_distance_m = null
                }
                if (formTaxonId != null && formTaxonId > 0) {
                    patch.taxon_id = Math.trunc(formTaxonId)
                } else {
                    const ts = formTaxonSearch.trim()
                    if (/^\d+$/.test(ts)) {
                        const tid = parseInt(ts, 10)
                        patch.taxon_id = tid > 0 ? tid : null
                    } else {
                        patch.taxon_id = null
                    }
                }
            } else {
                patch.animal_sound_type = null
                if (formTaxonId != null && formTaxonId > 0) {
                    patch.taxon_id = Math.trunc(formTaxonId)
                } else {
                    patch.taxon_id = null
                }
            }

            if (currentProjectId == null) {
                message.error("Missing project context.")
                return
            }

            const mode: AnnotationSaveMode =
                editingAnnotationId != null ? annotationSaveMode : "save"

            if (editingAnnotationId != null) {
                await annotationsApi.update(editingAnnotationId, currentProjectId, patch)
                message.success("Annotation updated")
                setAnnotationListTick((n) => n + 1)
                if (mode === "save_close") {
                    closeAnnotationPanel()
                } else if (mode === "save_next") {
                    void navigateAdjacentFromId(editingAnnotationId, 1)
                } else if (mode === "save_prev") {
                    void navigateAdjacentFromId(editingAnnotationId, -1)
                } else {
                    void openAnnotationEditorById(editingAnnotationId, { autoZoom: false })
                }
            } else {
                await annotationsApi.create({
                    project_id: currentProjectId,
                    media_id: mediaId,
                    ...patch,
                } as CreateAnnotationPayload)
                message.success("Annotation saved")
                setAnnotationListTick((n) => n + 1)
                if (mode === "save_close") {
                    closeAnnotationPanel()
                } else {
                    const fresh = await fetchSpectrogramAnnotationsForMedia()
                    setSpectrogramAnnotations(fresh)
                    const newId = pickMatchingAnnotationIdFromList(
                        fresh,
                        formSoundTypeSoundId!,
                        min_x,
                        max_x,
                        min_y,
                        max_y,
                    )
                    if (newId == null) {
                        message.warning(
                            "Saved, but could not open the annotation automatically. Use the list or refresh.",
                        )
                        closeAnnotationPanel()
                    } else if (mode === "save") {
                        void openAnnotationEditorById(newId, { autoZoom: false })
                    } else if (mode === "save_next") {
                        void navigateAdjacentFromId(newId, 1, fresh)
                    } else if (mode === "save_prev") {
                        void navigateAdjacentFromId(newId, -1, fresh)
                    }
                }
            }
        } catch (err: unknown) {
            message.error(err instanceof Error ? err.message : "Failed to save annotation")
        } finally {
            setSavePending(false)
        }
    }, [
        annotationDraft,
        annotationSaveMode,
        closeAnnotationPanel,
        editingAnnotationId,
        fetchSpectrogramAnnotationsForMedia,
        formAnimalSound,
        formComments,
        formDistanceM,
        formDistanceNotEstimable,
        formIndividualNum,
        formReference,
        formSoundTypeSoundId,
        formSoundscape,
        formObjectType,
        isPhoto,
        formTaxonId,
        formTaxonSearch,
        formUncertain,
        mediaId,
        currentProjectId,
        navigateAdjacentFromId,
        openAnnotationEditorById,
        soundClassifications.length,
    ])

    const handleReviewSubmit = useCallback(async () => {
        if (!canWriteReview) {
            message.error("You do not have permission to review annotations.")
            return
        }
        const annId =
            reviewContextAnnotationId ??
            (editingAnnotationId != null &&
                Number.isFinite(editingAnnotationId) &&
                editingAnnotationId > 0
                ? Math.trunc(editingAnnotationId)
                : null)
        if (annId == null) {
            message.error("Missing annotation id for review.")
            return
        }
        if (meUserId == null) {
            message.error("Sign in to submit a review.")
            return
        }
        const noteTrim = reviewNote.trim()
        let taxonPayload: number | null = null
        if (reviewTaxonId != null && reviewTaxonId > 0) {
            taxonPayload = Math.trunc(reviewTaxonId)
        } else {
            const ts = reviewTaxonSearch.trim()
            if (/^\d+$/.test(ts)) {
                const tid = parseInt(ts, 10)
                if (tid > 0) taxonPayload = tid
            }
        }
        if (reviewStatusRequiresTaxon(reviewStatusId) && taxonPayload == null) {
            setReviewTaxonError("Taxon is required for Revise.")
            return
        }
        if (reviewStatusDisablesTaxon(reviewStatusId)) {
            taxonPayload = null
        }
        setReviewTaxonError(null)
        const body = {
            annotation_review_status_id: reviewStatusId,
            taxon_id: taxonPayload,
            note: noteTrim ? noteTrim.slice(0, 200) : null,
        }
        setReviewSubmitPending(true)
        const updatingOwn = myAnnotationReviewRow != null
        try {
            if (currentProjectId == null) {
                message.error("Missing project context.")
                return
            }

            if (updatingOwn) {
                await reviewsApi.update(annId, meUserId, currentProjectId, body)
            } else {
                await reviewsApi.create({
                    project_id: currentProjectId,
                    annotation_id: annId,
                    annotation_review_status_id: body.annotation_review_status_id,
                    taxon_id: body.taxon_id,
                    note: body.note,
                })
            }
            const { items } = await reviewsApi.listPaged({
                annotation_id: annId,
                project_id: currentProjectId,
                page: 1,
                page_size: 100,
                order_by: "creation_date",
                order_dir: "desc",
            }, true)
            const fresh = normalizeAnnotationReviews(items)
            setEditingAnnotationReviews(fresh)
            initReviewFormFromReviews(fresh, meUserId)
            setReviewPanelExpanded(fresh.length === 0)
            setEditingAnnotationMeta((annotation) =>
                annotation?.annotation_id === annId
                    ? { ...annotation, reviews: fresh }
                    : annotation,
            )
            setSpectrogramAnnotations((annotations) =>
                annotations.map((annotation) =>
                    annotation.annotation_id === annId
                        ? { ...annotation, reviews: fresh }
                        : annotation,
                ),
            )
            setAnnotationListItems((annotations) =>
                annotations.map((annotation) =>
                    annotation.annotation_id === annId
                        ? { ...annotation, reviews: fresh }
                        : annotation,
                ),
            )
            setAnnotationListTick((n) => n + 1)
            message.success(updatingOwn ? "Review updated." : "Review submitted.")
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : "Failed to save review."
            message.error(msg)
        } finally {
            setReviewSubmitPending(false)
        }
    }, [
        reviewContextAnnotationId,
        editingAnnotationId,
        initReviewFormFromReviews,
        meUserId,
        myAnnotationReviewRow,
        reviewNote,
        reviewStatusId,
        reviewTaxonId,
        reviewTaxonSearch,
        currentProjectId,
        canWriteReview,
    ])

    useEffect(() => {
        if (loading || !media || rightPanel !== "new-annotation" || !annotationDraft) return
        if (!annotationDraftOverlayVisible) {
            setMarqueePx(null)
            setMarqueeCreating(false)
            setAnnotationDraftHasSize(false)
            return
        }
        if (draftInteractionRef.current) return
        const w = viewportSize.w
        const h = viewportSize.h
        if (w <= 0 || h <= 0) return
        const nyq =
            Number(media.sampling_rate_hz) > 0
                ? Math.round(Number(media.sampling_rate_hz) / 2)
                : 24000
        const { windowSec, viewStartClamped } = spectrogramLayout
        const draftPx = physToPixelsWindow(
            annotationDraft,
            w,
            h,
            viewStartClamped,
            windowSec,
            clamp(specFreqMinHz, 0, nyq),
            clamp(specFreqMaxHz, clamp(specFreqMinHz, 0, nyq), nyq),
        )
        const draftHasSize = Math.abs(draftPx.width) > 1 || Math.abs(draftPx.height) > 1
        setAnnotationDraftHasSize(draftHasSize)
        setMarqueePx(
            draftHasSize
                ? normalizeDraftPixelRect(draftPx, w, h)
                : {
                    left: clamp(draftPx.left, 0, w),
                    top: clamp(draftPx.top, 0, h),
                    width: 1,
                    height: 1,
                },
        )
    }, [annotationDraft, annotationDraftOverlayVisible, loading, media, rightPanel, spectrogramLayout, specFreqMaxHz, specFreqMinHz, viewportSize.w, viewportSize.h])

    useLayoutEffect(() => {
        if (loading || detailError || !media) return
        const el = annotationTableViewportRef.current
        if (!el) return
        const update = () => {
            const h = el.getBoundingClientRect().height
            const headerH =
                el.querySelector<HTMLElement>(".ant-table-header")?.getBoundingClientRect().height ?? 0
            setAnnotationTableBodyScrollY(
                Math.max(
                    120,
                    Math.floor(h - headerH - ANNOTATION_TABLE_SCROLL_BUFFER_PX),
                ),
            )
        }
        update()
        const ro = new ResizeObserver(update)
        ro.observe(el)
        return () => ro.disconnect()
    }, [loading, detailError, media, annotationTableVisible])

    const updateAnnotationTableHThumb = useCallback(() => {
        const wrap = annotationTableViewportRef.current
        const track = annotationTableHTrackRef.current
        if (!wrap || !track) return
        const body = wrap.querySelector<HTMLElement>(".ant-table-body")
        if (!body) return

        const scrollWidth = body.scrollWidth
        const clientWidth = body.clientWidth
        const scrollLeft = body.scrollLeft
        const trackWidth = track.clientWidth

        if (scrollWidth <= clientWidth + 1 || trackWidth < 4) {
            setAnnotationTableHThumb((prev) =>
                prev.show ? { show: false, size: 0, offset: 0 } : prev,
            )
            return
        }

        const thumbSize = Math.max(28, (clientWidth / scrollWidth) * trackWidth)
        const maxScroll = scrollWidth - clientWidth
        const maxOffset = Math.max(0, trackWidth - thumbSize)
        const thumbOffset = maxScroll > 0 ? (scrollLeft / maxScroll) * maxOffset : 0
        setAnnotationTableHThumb({ show: true, size: thumbSize, offset: thumbOffset })
    }, [])

    useLayoutEffect(() => {
        const wrap = annotationTableViewportRef.current
        if (!wrap) return

        let cleanupFn: (() => void) | null = null

        const attach = () => {
            cleanupFn?.()
            const body = wrap.querySelector<HTMLElement>(".ant-table-body")
            if (!body) return

            const onScroll = () => updateAnnotationTableHThumb()
            body.addEventListener("scroll", onScroll, { passive: true })
            updateAnnotationTableHThumb()

            const ro = new ResizeObserver(() => updateAnnotationTableHThumb())
            ro.observe(body)
            ro.observe(wrap)

            cleanupFn = () => {
                body.removeEventListener("scroll", onScroll)
                ro.disconnect()
            }
        }

        const t0 = window.setTimeout(attach, 0)
        const t1 = window.setTimeout(attach, 200)

        return () => {
            window.clearTimeout(t0)
            window.clearTimeout(t1)
            cleanupFn?.()
        }
    }, [
        updateAnnotationTableHThumb,
        annotationListLoading,
        annotationTableRows.length,
        annotationTableBodyScrollY,
        annotationTableVisible,
    ])

    const onAnnotationTableHThumbPointerDown = useCallback((e: PointerEvent<HTMLDivElement>) => {
        if (e.button !== 0) return
        const wrap = annotationTableViewportRef.current
        const track = annotationTableHTrackRef.current
        if (!wrap || !track) return
        const body = wrap.querySelector<HTMLElement>(".ant-table-body")
        if (!body) return

        const maxScroll = Math.max(0, body.scrollWidth - body.clientWidth)
        if (maxScroll < 1 || track.clientWidth < 4) return

        const thumbSize = Math.max(28, (body.clientWidth / body.scrollWidth) * track.clientWidth)
        const maxOffset = Math.max(0, track.clientWidth - thumbSize)
        e.preventDefault()
        e.stopPropagation()
        e.currentTarget.setPointerCapture(e.pointerId)
        annotationTableHDragRef.current = {
            pointerId: e.pointerId,
            startClient: e.clientX,
            startScroll: body.scrollLeft,
            maxScroll,
            maxOffset: Math.max(maxOffset, 1e-6),
        }
        setAnnotationTableHDragging(true)
    }, [])

    const onAnnotationTableHThumbPointerMove = useCallback((e: PointerEvent<HTMLDivElement>) => {
        const drag = annotationTableHDragRef.current
        const wrap = annotationTableViewportRef.current
        if (!drag || !wrap || e.pointerId !== drag.pointerId) return
        const body = wrap.querySelector<HTMLElement>(".ant-table-body")
        if (!body) return
        const delta = e.clientX - drag.startClient
        const ratio = drag.maxScroll / drag.maxOffset
        body.scrollLeft = Math.min(drag.maxScroll, Math.max(0, drag.startScroll + delta * ratio))
    }, [])

    const endAnnotationTableHDrag = useCallback((e: PointerEvent<HTMLDivElement>) => {
        const drag = annotationTableHDragRef.current
        if (!drag || e.pointerId !== drag.pointerId) return
        annotationTableHDragRef.current = null
        setAnnotationTableHDragging(false)
        try {
            if (e.currentTarget.hasPointerCapture(e.pointerId)) {
                e.currentTarget.releasePointerCapture(e.pointerId)
            }
        } catch {
            /* ignore */
        }
    }, [])

    const cancelAnnotationTableHDrag = useCallback(() => {
        annotationTableHDragRef.current = null
        setAnnotationTableHDragging(false)
    }, [])

    useEffect(() => {
        let cancelled = false
            ; (async () => {
                try {
                    const list = await fetchLabelsCatalog(true)
                    if (!cancelled) setToolbarLabelsCatalog(list)
                } catch {
                    if (!cancelled) setToolbarLabelsCatalog([])
                }
            })()
        return () => {
            cancelled = true
        }
    }, [mediaId])

    const audioLabelPillText = useMemo(() => {
        if (!media) return "No label"
        const tag = typeof media.label === "string" ? media.label.trim() : ""
        const raw = media.labels
        const mediaNames = Array.isArray(raw)
            ? raw.filter((x): x is string => typeof x === "string" && x.trim() !== "").map((s) => s.trim())
            : []
        const candidates: string[] = []
        if (tag) candidates.push(tag)
        for (const n of mediaNames) {
            if (!candidates.some((c) => c.toLowerCase() === n.toLowerCase())) candidates.push(n)
        }
        for (const cand of candidates) {
            const hit = toolbarLabelsCatalog.find((l) => l.name.toLowerCase() === cand.toLowerCase())
            if (hit) return hit.name
        }
        if (candidates.length > 0) return candidates[0]
        return "No label"
    }, [media, toolbarLabelsCatalog])

    const handleDownloadOriginalPhoto = useCallback(() => {
        if (!photoContentUrl) {
            message.warning("Photo is not ready yet")
            return
        }
        const link = document.createElement("a")
        link.href = photoContentUrl
        link.download =
            (typeof media?.filename === "string" && media.filename) ||
            (typeof media?.name === "string" && media.name) ||
            `photo-${mediaId}`
        document.body.appendChild(link)
        link.click()
        link.remove()
    }, [media, mediaId, photoContentUrl])

    if (loading) {
        return (
            <div className="media-detail-loading">
                <LoadingState label="Loading media detail..." variant="page" size="lg" />
            </div>
        )
    }

    if (detailError) {
        return (
            <div className="media-detail-loading">
                <span className="text-muted">{detailError}</span>
            </div>
        )
    }

    if (!media) {
        return (
            <div className="media-detail-loading">
                <span className="text-muted">Media not found.</span>
            </div>
        )
    }

    // ---- Derived display values (media is non-null here) ----
    const totalDuration = Number(media.duration_s) || 0
    const displaySr: string | null = (() => {
        const hz = Number(media.sampling_rate_hz)
        if (!Number.isNaN(hz) && hz > 0) return `${hz / 1000}kHz`
        return null
    })()
    const displaySize: string | null = (() => {
        const b = Number(media.size_b)
        if (!Number.isNaN(b) && b > 0) return `${(b / (1024 * 1024)).toFixed(2)} MB`
        return null
    })()
    const displayGain: string | null = (() => {
        if (isPhoto) return null
        if (typeof media.gain === "number" && Number.isFinite(media.gain)) return `${media.gain} dB`
        if (typeof media.gain === "string") {
            const gain = media.gain.trim()
            return gain ? gain : null
        }
        return null
    })()
    const displayDuration: string | undefined =
        totalDuration > 0
            ? formatDuration(totalDuration)
            : typeof media.duration === "string"
                ? media.duration
                : undefined
    const displayPhotoDimensions =
        isPhoto && Number(media.image_width) > 0 && Number(media.image_height) > 0
            ? `${Number(media.image_width)} x ${Number(media.image_height)}px`
            : null
    const displayPhotoFormat =
        isPhoto && typeof media.filename === "string" && media.filename.includes(".")
            ? media.filename.split(".").pop()?.toUpperCase() ?? null
            : null
    const displayPhotoExposure =
        isPhoto && media.photo_setting?.exposure_ms != null
            ? `${media.photo_setting.exposure_ms} ms`
            : null
    const displayPhotoAperture =
        isPhoto && media.photo_setting?.aperture != null
            ? `f/${media.photo_setting.aperture}`
            : null
    const displayPhotoIso =
        isPhoto && media.photo_setting?.iso != null
            ? `ISO ${media.photo_setting.iso}`
            : null
    const { displayDate, displayTime } = splitMediaDisplayDateTime({
        date_time: media.date_time,
    })
    const displaySite = media.site_name?.trim() || null
    const { windowSec: specWindowSec, viewStartClamped: specViewStart, innerW: specInnerW, offsetX: specOffsetX } =
        spectrogramLayout
    const showSpectrogramLoading = spectrogramLoading || !spectrogramInitialReady
    const showAnnotationTableLoading = annotationListLoading || !annotationListInitialReady
    const playheadViewStart = specViewStart
    const playheadWindowSec = specWindowSec
    const specVisibleEnd = snapVisibleRangeEndSec(playheadViewStart + playheadWindowSec, totalDuration)
    const progressPctVisible =
        playheadWindowSec > 0
            ? clamp(
                  ((currentTime - playheadViewStart) / playheadWindowSec) *
                      100,
                  0,
                  100,
              )
            : 0

    /** 仅当可见时间窗短于整段时长（已放大）时可平移 */
    const spectrogramCanPan =
        totalDuration > 0 && specWindowSec + 1e-9 < totalDuration
    const spectrogramCanPanLeft = spectrogramCanPan && specViewStart > 1e-9
    const spectrogramCanPanRight = spectrogramCanPan && specVisibleEnd < totalDuration - 1e-9

    const nyquistHz = (() => {
        const hz = Number(media.sampling_rate_hz)
        if (!Number.isNaN(hz) && hz > 0) return Math.round(hz / 2)
        return 24000
    })()

    /** 时间轴 + 频率轴均恢复为整段 / 全频段（由 Audio Info 旁按钮触发；小地图仅预览不重置） */
    const resetSpectrogramToFullView = () => {
        fitSpectrogramToFullDuration()
        syncPlaybackToSpectrogramViewStart(0)
        setSpecFreqMinHz(1)
        setSpecFreqMaxHz(nyquistHz)
    }

    const channelCount = Number(media.audio_setting?.channel_num ?? media.channels)
    const isMonoRecording = channelCount === 1
    const isStereoRecording = channelCount > 1

    const isBiophonyAnnotationForm =
        formSoundscape !== null && formSoundscape.toLowerCase() === "biophony"

    const editingAnnotationCreatorBadgeLabel = editingAnnotationMeta
        ? annotationCreatorTypeBadgeLabel(editingAnnotationMeta.creator_type)
        : ""
    const editingAnnotationMetaCard = editingAnnotationMeta ? (
        <div className="studio-annot-meta-card">
            <div className="studio-annot-meta-row studio-annot-meta-row--top">
                <AutoFitBadgeText label={editingAnnotationCreatorBadgeLabel} />
                <span className="studio-annot-meta-by">
                    By <strong>{editingAnnotationCreatorDisplay}</strong>
                </span>
            </div>
            <div className="studio-annot-meta-row studio-annot-meta-row--bottom">
                {editingAnnotationConfidenceValue != null ? (
                    <span
                        className={`studio-annot-meta-badge studio-annot-meta-badge--conf-${annotationConfidenceTier(
                            editingAnnotationConfidenceValue,
                        )}`}
                    >
                        {`CONF: ${editingAnnotationConfidenceValue.toFixed(4)}`}
                    </span>
                ) : (
                    <span />
                )}
                <span
                    className="studio-annot-meta-time"
                    title={editingAnnotationCreationDisplay}
                >
                    {editingAnnotationCreationDateOnlyDisplay}
                </span>
            </div>
        </div>
    ) : null

    const onFftSelect = (v: string) => {
        stopContinuousPlayback()
        setFftValue(v)
        const n = Number(v)
        if (!Number.isNaN(n)) {
            userPreferenceApi.patch({ fft: n }).catch(() => { })
        }
    }

    const applySpectrogramCentralZoomByPercent = (pctRaw: string, dir: "in" | "out") => {
        const dur = totalDuration
        const curWin = specWindowSec
        if (!(dur > 0) || !(curWin > 0)) return
        const pct = Number(pctRaw)
        if (!Number.isFinite(pct)) return
        const p = clamp(pct, 0, 100) / 100
        if (p <= 0) return

        const minWin = spectrogramMinWindowSec(dur)
        const nextWin =
            dir === "in"
                ? Math.max(minWin, curWin * (1 - p))
                : Math.min(dur, curWin * (1 + p))

        const minWinFull = spectrogramMinWindowSec(dur)
        const appliedWin = clamp(nextWin, minWinFull, dur)
        const { zp: nextZp } = resolveSpectrogramZoomWindow(dur, appliedWin)
        const center = snapTimeSec(specViewStart + curWin / 2, dur)
        const nextVs = resolveSpectrogramViewStart(dur, center, spectrogramVisibleWindowSec(dur, nextZp))

        spectrogramViewStartRef.current = nextVs
        setSpectrogramZoomPercent(nextZp)
        spectrogramZoomPercentRef.current = nextZp
        setSpectrogramViewStart(nextVs)
        storeSpectrogramZoomPercentCookie(nextZp)
        syncPlaybackToSpectrogramViewStart(nextVs)

        // Keep Y-axis (frequency) zoom in sync with X-axis zoom behavior:
        // zoom around the current visible frequency window center.
        const nyq = nyquistHz
        if (nyq > 0) {
            const f0 = clamp(specFreqMinHz, 0, nyq)
            const f1 = clamp(specFreqMaxHz, f0, nyq)
            const curFWin = f1 - f0
            // Only adjust if we have a meaningful window (and avoid jitter at extremes).
            if (curFWin > 1) {
                const minFWin = SPECTROGRAM_FREQ_WINDOW_EPSILON_HZ
                const nextFWin =
                    dir === "in"
                        ? Math.max(minFWin, curFWin * (1 - p))
                        : Math.min(nyq, curFWin * (1 + p))
                const c = (f0 + f1) / 2
                let nf0 = c - nextFWin / 2
                let nf1 = c + nextFWin / 2
                // Clamp while preserving window size as much as possible.
                if (nf0 < 0) {
                    nf1 = Math.min(nyq, nf1 - nf0)
                    nf0 = 0
                }
                if (nf1 > nyq) {
                    nf0 = Math.max(0, nf0 - (nf1 - nyq))
                    nf1 = nyq
                }
                setSpecFreqMinHz(clamp(nf0, 0, nyq))
                setSpecFreqMaxHz(clamp(nf1, clamp(nf0, 0, nyq), nyq))
            }
        }
    }
    const handleSpectrogramZoomIn = () => {
        runSpectrogramControl(() => {
            exitAnnotationPanelIfActive()
            applySpectrogramCentralZoomByPercent(spectrogramZoomDraftIn, "in")
        })
    }
    const handleSpectrogramZoomOut = () => {
        runSpectrogramControl(() => {
            exitAnnotationPanelIfActive()
            applySpectrogramCentralZoomByPercent(spectrogramZoomDraftOut, "out")
        })
    }
    const handleSpectrogramPanLeft = () => {
        if (spectrogramLoading || !spectrogramCanPanLeft) return
        const step = spectrogramVisibleWindowSec(totalDuration, spectrogramZoomPercentRef.current)
        setSpectrogramViewStart((s) => {
            const next = resolveSpectrogramViewportWindow(
                totalDuration,
                s - step,
                spectrogramZoomPercentRef.current,
            ).viewStartClamped
            spectrogramViewStartRef.current = next
            syncPlaybackToSpectrogramViewStart(next)
            return next
        })
    }
    const handleSpectrogramPanRight = () => {
        if (spectrogramLoading || !spectrogramCanPanRight) return
        const step = spectrogramVisibleWindowSec(totalDuration, spectrogramZoomPercentRef.current)
        setSpectrogramViewStart((s) => {
            const next = resolveSpectrogramViewportWindow(
                totalDuration,
                s + step,
                spectrogramZoomPercentRef.current,
            ).viewStartClamped
            spectrogramViewStartRef.current = next
            syncPlaybackToSpectrogramViewStart(next)
            return next
        })
    }

    const seekSpectrogramToClientX = (clientX: number) => {
        const wasContinuousMode = continuousSegmentPlaybackRef.current || continuousEngineRef.current != null
        if (wasContinuousMode) {
            stopContinuousPlayback({ keepToggle: true })
        }
        const vp = viewportRef.current
        const a = audioRef.current
        if (!vp || totalDuration <= 0) return
        const { x, w } = clientToViewportLayoutPoint(vp, clientX, 0)
        if (w <= 0 || specWindowSec <= 0) return
        const t = specViewStart + (x / w) * specWindowSec
        const target = clamp(t, 0, totalDuration)
        audioPreserveTimeRef.current = target
        if (wasContinuousMode) {
            setContinuousSegmentPlayback(true)
            continuousSegmentPlaybackRef.current = true
            setAudioReloadToken((n) => n + 1)
        }
        if (a) seekAudioElementToAbsoluteTime(target)
        setPlaybackTime(target)
        userScrubbedPlaybackTimeRef.current = target
    }

    seekSpectrogramToClientXRef.current = seekSpectrogramToClientX
    spectrogramShortcutHandlersRef.current.playToggle = handlePlayToggle
    spectrogramShortcutHandlersRef.current.panLeft = handleSpectrogramPanLeft
    spectrogramShortcutHandlersRef.current.panRight = handleSpectrogramPanRight

    const onSpectrogramProgressPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
        if (e.button !== 0) return
        e.preventDefault()
        e.stopPropagation()
        setSpectrogramProgressScrubbing(true)
        e.currentTarget.setPointerCapture(e.pointerId)
        seekSpectrogramToClientX(e.clientX)
    }

    const onSpectrogramProgressPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
        if (!e.currentTarget.hasPointerCapture(e.pointerId)) return
        seekSpectrogramToClientX(e.clientX)
    }

    const endSpectrogramProgressScrub = (e: React.PointerEvent<HTMLDivElement>) => {
        if (e.currentTarget.hasPointerCapture(e.pointerId)) {
            try {
                e.currentTarget.releasePointerCapture(e.pointerId)
            } catch {
                /* ignore */
            }
        }
        setSpectrogramProgressScrubbing(false)
    }

    const applySpectrogramPxPerSecDraft = () => {
        exitAnnotationPanelIfActive()
        const t = spectrogramPxPerSecDraft.trim()
        if (t === "" || t === ".") return
        const n = Number(t)
        if (!Number.isFinite(n)) return
        const next = commitSpectrogramPxPerSec(n)

        // 按输入的 px/s 重新计算可视窗：winSec = viewportWidth / pxPerSec。
        if (!media) return
        const dur = Number(media.duration_s) || 0
        const w =
            viewportSize.w > 0
                ? viewportSize.w
                : (() => {
                    const vp = viewportRef.current
                    if (!vp) return 0
                    const { w } = readViewportLayoutSize(vp)
                    return w > 0 ? w : 0
                })()
        if (!(dur > 0) || !(w > 0)) return

        const appliedWin = windowSecFromPxPerSec(dur, w, next)
        const { zp: nextZp } = resolveSpectrogramZoomWindow(dur, appliedWin)

        // 从 0 开始重新应用密度，恢复完整频段。
        const nextVs = 0
        spectrogramViewStartRef.current = nextVs
        setSpectrogramZoomPercent(nextZp)
        spectrogramZoomPercentRef.current = nextZp
        setSpectrogramViewStart(nextVs)
        setSpecFreqMinHz(1)
        setSpecFreqMaxHz(nyquistHz)
        storeSpectrogramZoomPercentCookie(nextZp)
        audioPreserveTimeRef.current = nextVs
        syncPlaybackToSpectrogramViewStart(nextVs)
    }

    return (
        <>
        <div className={`media-studio-container${isDark ? " media-studio--dark" : ""}`}>
            {/* ===== LEFT: Studio Main Section ===== */}
            <div className={`studio-main-section${annotationTableVisible ? "" : " studio-main-section--table-hidden"}`}>
                {/* Player Section */}
                {isPhoto && currentProjectId != null ? (
                    <PhotoImageViewer
                        mediaId={mediaId}
                        projectId={currentProjectId}
                        media={media}
                        annotations={renderedAnnotations}
                        annotationsVisible={annotationsVisible}
                        linkedAnnotationId={annotationLinkedHighlightId}
                        editingAnnotationId={editingAnnotationId}
                        draft={annotationDraft as PhotoAnnotationBox | null}
                        draftVisible={annotationDraftOverlayVisible}
                        userAnnotationColor={userAnnotationColor}
                        currentUserId={meUserId}
                        onAnnotationsVisibleChange={setAnnotationsVisible}
                        onContentReady={handlePhotoContentReady}
                        onLinkedAnnotationChange={(annotationId) => {
                            setAnnotationLinkedHighlightId(annotationId)
                            if (annotationId != null) {
                                scrollAnnotationTableRowIntoView(annotationId)
                            }
                        }}
                        onOpenAnnotation={(annotationId) => void openAnnotationEditorById(annotationId)}
                        onDraftStart={() => {
                            prepareNewAnnotationDraft()
                        }}
                        onDraftChange={(nextDraft) => {
                            setAnnotationDraft(nextDraft)
                            setAnnotationDraftHasSize(
                                Math.abs(nextDraft.max_x - nextDraft.min_x) > 1 ||
                                Math.abs(nextDraft.max_y - nextDraft.min_y) > 1,
                            )
                        }}
                        onDraftCancel={closeAnnotationPanel}
                        toolbarActions={null}
                        canNavigateAnnotation={editingAnnotationId != null}
                        navAutoZoomToAnnotation={navAutoZoomToAnnotation}
                        navOnlyTaskTagged={navOnlyTaskTagged}
                        onPreviousAnnotation={() => goToAdjacentAnnotation(-1)}
                        onNextAnnotation={() => goToAdjacentAnnotation(1)}
                        onToggleNavAutoZoomToAnnotation={() => setNavAutoZoomToAnnotation((v) => !v)}
                        onToggleNavOnlyTaskTagged={() => setNavOnlyTaskTagged((v) => !v)}
                        zoomRequest={photoZoomRequest}
                    />
                ) : (
                <div className="player-section">
                    {/* Top Toolbar */}
                    <div className="player-toolbar-top">
                        {/* Channel：立体声可 Popover 选左/右，与 audio & spectrogram 的 channel 参数一致 */}
                        {isStereoRecording ? (
                            <StudioCrumbDropdown
                                items={CHANNEL_DROPDOWN_ITEMS}
                                selectedId={audioChannel}
                                title="Channel"
                                icon={<Headphones size={14} />}
                                labelWidth={72}
                                dropdownMinWidth={180}
                                onSelect={(id) => {
                                    const ch = Number(id) === 2 ? 2 : 1
                                    if (audioChannel === ch) return
                                    stopContinuousPlayback()
                                    const el = audioRef.current
                                    if (el && Number.isFinite(el.currentTime)) {
                                        audioPreserveTimeRef.current = el.currentTime
                                    }
                                    setAudioChannel(ch)
                                }}
                            />
                        ) : (
                            <div
                                className="btn-toolbar btn-toolbar--static"
                                style={{ padding: "0 12px", gap: 6 }}
                                title="Channel"
                            >
                                <Headphones size={14} />
                                <span
                                    style={{
                                        fontSize: "0.85rem",
                                        fontWeight: 600,
                                        display: "inline-block",
                                        width: 64,
                                        textAlign: "center",
                                    }}
                                >
                                    Mono
                                </span>
                            </div>
                        )}

                        <StudioCrumbDropdown
                            items={FFT_DROPDOWN_ITEMS}
                            selectedId={fftValue}
                            title="FFT Window Size"
                            icon={<SquareActivity size={14} />}
                            labelWidth={40}
                            dropdownMinWidth={120}
                            tabularNums
                            onSelect={(id) => {
                                if (isSpectrogramBusy) return
                                onFftSelect(String(id))
                            }}
                        />

                        {/* Toggle Annotations */}
                        <MediaViewerToolbarButton
                            active={annotationsVisible}
                            label={annotationsVisible ? "Hide Annotations" : "Show Annotations"}
                            icon={annotationsVisible ? <Eye size={14} /> : <EyeOff size={14} />}
                            disabled={isSpectrogramBusy}
                            onClick={() => setAnnotationsVisible((v) => !v)}
                        />

                        <span className="toolbar-divider" />

                        {/* Pan controls（整图可见时无可平移） */}
                        <MediaViewerToolbarButton
                            className="btn-toolbar"
                            label={
                                spectrogramCanPanLeft
                                    ? "Pan Left (Ctrl/Cmd + Left Arrow)"
                                    : spectrogramCanPan
                                        ? "Already at the beginning (Ctrl/Cmd + Left Arrow)"
                                        : "Zoom in to pan the spectrogram (Ctrl/Cmd + Left Arrow)"
                            }
                            disabled={!spectrogramCanPanLeft || isSpectrogramBusy}
                            aria-disabled={!spectrogramCanPanLeft || isSpectrogramBusy}
                            onClick={handleSpectrogramPanLeft}
                            icon={<ChevronLeft size={14} />}
                        />
                        <MediaViewerToolbarButton
                            className="btn-toolbar"
                            label={
                                spectrogramCanPanRight
                                    ? "Pan Right (Ctrl/Cmd + Right Arrow)"
                                    : spectrogramCanPan
                                        ? "Already at the end (Ctrl/Cmd + Right Arrow)"
                                        : "Zoom in to pan the spectrogram (Ctrl/Cmd + Right Arrow)"
                            }
                            disabled={!spectrogramCanPanRight || isSpectrogramBusy}
                            aria-disabled={!spectrogramCanPanRight || isSpectrogramBusy}
                            onClick={handleSpectrogramPanRight}
                            icon={<ChevronRight size={14} />}
                        />

                        <span className="toolbar-divider" />

                        {/* Zoom controls：% 越大放大越多（可见时间窗越短）；两格共用同一缩放值 */}
                        <div className="zoom-control-wrapper">
                            <MediaViewerToolbarButton
                                variant="zoom"
                                label="Zoom In (Shift + wheel)"
                                icon={<ZoomIn size={14} />}
                                disabled={isSpectrogramBusy}
                                onClick={handleSpectrogramZoomIn}
                            />
                            <ESInput appearance="unstyled"
                                type="number"
                                min={0}
                                max={100}
                                step={SPECTROGRAM_ZOOM_STEP}
                                value={spectrogramZoomDraftIn}
                                disabled={isSpectrogramBusy}
                                onChange={(e) => {
                                    const v = e.target.value
                                    setSpectrogramZoomDraftIn(v)
                                    setCookieValue(SPEC_ZOOM_DRAFT_IN_COOKIE_KEY, v)
                                }}
                            />
                            <span>%</span>
                        </div>
                        <div className="zoom-control-wrapper">
                            <MediaViewerToolbarButton
                                variant="zoom"
                                label="Zoom Out (Shift + wheel)"
                                icon={<ZoomOut size={14} />}
                                disabled={isSpectrogramBusy}
                                onClick={handleSpectrogramZoomOut}
                            />
                            <ESInput appearance="unstyled"
                                type="number"
                                min={0}
                                max={100}
                                step={SPECTROGRAM_ZOOM_STEP}
                                value={spectrogramZoomDraftOut}
                                disabled={isSpectrogramBusy}
                                onChange={(e) => {
                                    const v = e.target.value
                                    setSpectrogramZoomDraftOut(v)
                                    setCookieValue(SPEC_ZOOM_DRAFT_OUT_COOKIE_KEY, v)
                                }}
                            />
                            <span>%</span>
                        </div>
                        <div className="zoom-control-wrapper zoom-control-wrapper--pxs">
                            <MediaViewerToolbarButton
                                variant="zoom"
                                label="Apply px/s - visible time window (s) = player width ÷ px/s"
                                icon={<StretchHorizontal size={14} />}
                                disabled={isSpectrogramBusy}
                                onClick={applySpectrogramPxPerSecDraft}
                            />
                            <ESInput appearance="unstyled"
                                type="number"
                                min={SPECTROGRAM_PX_PER_SEC_MIN}
                                step={0.01}
                                value={spectrogramPxPerSecDraft}
                                disabled={isSpectrogramBusy}
                                onChange={(e) => {
                                    const v = e.target.value
                                    setSpectrogramPxPerSecDraft(v)
                                    setCookieValue(SPEC_PXS_COOKIE_KEY, v)
                                }}
                            />
                            <span>px/s</span>
                        </div>

                        <div style={{ flex: 1 }} />

                        {/* AI Tools */}
                        {authUtils.getToken() && (
                            <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                                <ESButton appearance="unstyled"
                                    type="button"
                                    className={`data-btn media-studio-action${rightPanel === "ai-models" ? " active" : ""}`}
                                    title="Apply AI Models"
                                    onClick={() => setRightPanel("ai-models")}
                                >
                                    <Cpu size={14} /> AI Models
                                </ESButton>
                                <ESButton appearance="unstyled"
                                    type="button"
                                    className={`data-btn media-studio-action${rightPanel === "acoustic-indices" ? " active" : ""}`}
                                    title="Acoustic Indices"
                                    onClick={() => setRightPanel("acoustic-indices")}
                                >
                                    <BarChart2 size={14} /> Acoustic Indices
                                </ESButton>
                                <ESButton appearance="unstyled"
                                    type="button"
                                    className={`data-btn media-studio-action${rightPanel === "acoustic-analysis" ? " active" : ""}`}
                                    title="Acoustic Analysis"
                                    onClick={() => setRightPanel("acoustic-analysis")}
                                >
                                    <AudioLines size={14} /> Acoustic Analysis
                                </ESButton>
                            </div>
                        )}
                    </div>

                    {/* Spectrogram（实时接口 PNG blob；失败时回退静态预览图） */}
                    <div className="player-middle">
                        <audio
                            ref={audioRef}
                            src={audioBlobUrl ?? undefined}
                            preload="auto"
                            style={{ display: "none" }}
                            onLoadedMetadata={() => {
                                if (audioElementRequestIdRef.current !== activeAudioRequestIdRef.current) return
                                applyAudioElementPlaybackRate()
                                forceSeekToPendingZoomStart()
                            }}
                            onCanPlay={() => {
                                if (audioElementRequestIdRef.current !== activeAudioRequestIdRef.current) return
                                applyAudioElementPlaybackRate()
                                setAudioLoading(false)
                                setAudioReady(true)
                            }}
                            onPlay={() => {
                                applyAudioElementPlaybackRate()
                                setIsPlaying(true)
                            }}
                            onPause={() => setIsPlaying(false)}
                            onEnded={() => {
                                handlePlaybackBoundary({ force: true })
                                syncIsPlayingFromAudio()
                            }}
                            onError={() => {
                                if (audioElementRequestIdRef.current !== activeAudioRequestIdRef.current) return
                                setAudioLoading(false)
                                setAudioReady(false)
                                setIsPlaying(false)
                            }}
                        />
                        <div
                            ref={viewportRef}
                            className="spectrogram-viewport"
                            style={
                                specInnerW <= 0 && !spectrogramBlobUrl && !showSpectrogramLoading
                                    ? (media.spectrogram
                                        ? { backgroundImage: `url('${media.spectrogram}')` }
                                        : undefined)
                                    : undefined
                            }
                            onMouseMove={(e) => {
                                const vp = viewportRef.current
                                if (!vp || totalDuration <= 0 || specWindowSec <= 0) return
                                const { x, w } = clientToViewportLayoutPoint(vp, e.clientX, e.clientY)
                                if (w <= 0) return
                                const frac = clamp(x / w, 0, 1)
                                spectrogramCursorFracRef.current = frac
                                spectrogramCursorTimeRef.current = specViewStart + frac * specWindowSec
                            }}
                            onMouseLeave={() => {
                                spectrogramCursorFracRef.current = null
                                spectrogramCursorTimeRef.current = null
                            }}
                            onPointerDownCapture={(e) => {
                                if (!e.ctrlKey && !e.metaKey) return
                                e.preventDefault()
                                e.stopPropagation()
                                seekSpectrogramToClientXRef.current?.(e.clientX)
                            }}
                            onContextMenuCapture={(e) => {
                                if (!e.ctrlKey && !e.metaKey) return
                                e.preventDefault()
                                e.stopPropagation()
                            }}
                            onWheel={(e) => {
                                if (!e.shiftKey) return
                                const delta = e.deltaY !== 0 ? e.deltaY : e.deltaX
                                if (delta === 0) return
                                e.preventDefault()
                                e.stopPropagation()
                                if (delta < 0) {
                                    handleSpectrogramZoomIn()
                                } else {
                                    handleSpectrogramZoomOut()
                                }
                            }}
                        >
                            {showSpectrogramLoading ? (
                                <div className="spectrogram-loading-overlay" aria-hidden="true">
                                    <LoadingState label="Loading spectrogram..." variant="overlay" size="lg" showLabel={false} />
                                </div>
                            ) : null}
                            {specInnerW > 0 ? (
                                <div
                                    className="spectrogram-zoom-slab"
                                    style={{
                                        width: specInnerW,
                                        height: "100%",
                                        transform: `translate3d(${-specOffsetX}px,0,0)`,
                                    }}
                                >
                                    {spectrogramBlobUrl ? (
                                        <UnifiedImage
                                            className="spectrogram-dynamic-img"
                                            src={spectrogramBlobUrl}
                                            alt=""
                                            decoding="async"
                                        />
                                    ) : (
                                        <div
                                            className="spectrogram-static-fallback"
                                            style={{
                                                width: "100%",
                                                height: "100%",
                                                backgroundImage:
                                                    !showSpectrogramLoading && media.spectrogram
                                                        ? `url('${media.spectrogram}')`
                                                        : undefined,
                                                backgroundSize: "100% 100%",
                                                backgroundRepeat: "no-repeat",
                                            }}
                                        />
                                    )}
                                </div>
                            ) : spectrogramBlobUrl ? (
                                <UnifiedImage
                                    className="spectrogram-dynamic-img spectrogram-dynamic-img--degen"
                                    src={spectrogramBlobUrl}
                                    alt=""
                                    decoding="async"
                                />
                            ) : null}
                            {annotationsVisible ? (
                                <div className="annotations-layer">
                                    {annotationOverlayPx.map((box) => {
                                        const linked =
                                            annotationLinkedHighlightId === box.id ||
                                            editingAnnotationId === box.id
                                        const frameColor = hexColorToRgba(
                                            box.presentation.creatorColor,
                                            1,
                                        )
                                        return (
                                            <div
                                                key={box.id}
                                                className={mediaAnnotationClassName(
                                                    box.presentation,
                                                    linked,
                                                )}
                                                title={box.title}
                                                role="button"
                                                tabIndex={0}
                                                onClick={(e) => void handleSpectrogramAnnotationClick(e, box.id)}
                                                onKeyDown={(e) => {
                                                    if (e.key !== "Enter" && e.key !== " ") return
                                                    e.preventDefault()
                                                    e.stopPropagation()
                                                    void openAnnotationEditorById(box.id)
                                                }}
                                                onMouseEnter={() => {
                                                    setAnnotationLinkedHighlightId(box.id)
                                                    scrollAnnotationTableRowIntoView(box.id)
                                                }}
                                                onMouseLeave={() =>
                                                    setAnnotationLinkedHighlightId((cur) =>
                                                        cur === box.id ? null : cur,
                                                    )
                                                }
                                                style={
                                                    linked
                                                        ? ({
                                                            left: box.left,
                                                            top: box.top,
                                                            width: box.width,
                                                            height: box.height,
                                                            background: "transparent",
                                                        } as React.CSSProperties)
                                                        : ({
                                                            left: box.left,
                                                            top: box.top,
                                                            width: box.width,
                                                            height: box.height,
                                                            background: "transparent",
                                                            borderColor: frameColor,
                                                            "--annot-frame-color": frameColor,
                                                        } as React.CSSProperties)
                                                }
                                            />
                                        )
                                    })}
                                </div>
                            ) : null}
                            <div
                                className="spectrogram-marquee-layer"
                                onPointerDown={onMarqueePointerDown}
                                onPointerMove={onMarqueePointerMove}
                                onPointerUp={(e) =>
                                    onMarqueePointerUp(
                                        e,
                                        totalDuration,
                                        nyquistHz,
                                        specFreqMinHz,
                                        specFreqMaxHz,
                                        specViewStart,
                                        specWindowSec,
                                    )
                                }
                                onPointerCancel={(e) =>
                                    onMarqueePointerUp(
                                        e,
                                        totalDuration,
                                        nyquistHz,
                                        specFreqMinHz,
                                        specFreqMaxHz,
                                        specViewStart,
                                        specWindowSec,
                                    )
                                }
                            />
                            {annotationDraftOverlayVisible &&
                            marqueePx &&
                            editingAnnotationId == null &&
                            (rightPanel === "new-annotation" || marqueeCreating) ? (
                                <div
                                    className="media-selection-box"
                                    style={{
                                        left: marqueePx.left,
                                        top: marqueePx.top,
                                        width: annotationDraftHasSize ? marqueePx.width : 7,
                                        height: annotationDraftHasSize ? marqueePx.height : 7,
                                        zIndex: 11,
                                        pointerEvents: marqueeCreating ? "none" : "auto",
                                        cursor: marqueeCreating ? "crosshair" : "move",
                                        borderStyle: annotationDraftHasSize ? "dashed" : "solid",
                                        borderWidth: annotationDraftHasSize ? 1 : 0,
                                        borderColor: userAnnotationColor,
                                        borderRadius: annotationDraftHasSize ? 0 : "50%",
                                        background: annotationDraftHasSize ? "transparent" : hexColorToRgba(userAnnotationColor, 0.95),
                                        transform: annotationDraftHasSize ? undefined : "translate(-50%, -50%)",
                                    }}
                                    onPointerDown={handleDraftMovePointerDown}
                                    onPointerMove={handleDraftMovePointerMove}
                                    onPointerUp={handleDraftMovePointerUp}
                                    onPointerCancel={handleDraftMovePointerUp}
                                >
                                    {annotationDraftHasSize
                                        ? DRAFT_RESIZE_HANDLES.map(({ handle, className }) => (
                                            <span
                                                key={handle}
                                                className={`media-selection-handle ${className}`}
                                                onPointerDown={handleDraftResizePointerDown(handle)}
                                                onPointerMove={handleDraftResizePointerMove}
                                                onPointerUp={handleDraftResizePointerUp}
                                                onPointerCancel={handleDraftResizePointerUp}
                                            />
                                        ))
                                        : null}
                                </div>
                            ) : null}

                            <div
                                className="playback-progress-wrapper"
                                style={{
                                    left: `${progressPctVisible}%`,
                                    transition:
                                        spectrogramProgressScrubbing || isPlaying
                                            ? "none"
                                            : "left 0.1s linear",
                                }}
                                role="slider"
                                aria-label="Playback position"
                                title="Ctrl/Cmd + click the spectrogram to jump to this position"
                                aria-valuemin={0}
                                aria-valuemax={Math.max(0, totalDuration)}
                                aria-valuenow={clamp(currentTime, 0, Math.max(0, totalDuration))}
                                tabIndex={0}
                                onKeyDown={(e) => {
                                    if (totalDuration <= 0 || specWindowSec <= 0) return
                                    const step = Math.max(0.05, specWindowSec * 0.01)
                                    let next = currentTime
                                    if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
                                        e.preventDefault()
                                        next = currentTime - step
                                    } else if (e.key === "ArrowRight" || e.key === "ArrowUp") {
                                        e.preventDefault()
                                        next = currentTime + step
                                    } else {
                                        return
                                    }
                                    const t = clamp(next, 0, totalDuration)
                                    seekAudioElementToAbsoluteTime(t)
                                    setPlaybackTime(t)
                                    userScrubbedPlaybackTimeRef.current = t
                                }}
                                onPointerDown={onSpectrogramProgressPointerDown}
                                onPointerMove={onSpectrogramProgressPointerMove}
                                onPointerUp={endSpectrogramProgressScrub}
                                onPointerCancel={endSpectrogramProgressScrub}
                                onLostPointerCapture={() => setSpectrogramProgressScrubbing(false)}
                            >
                                <div className="playback-progress-line" />
                            </div>
                        </div>
                        <div
                            className="spectrogram-annot-side-toolbar"
                            role="toolbar"
                            aria-label="Annotation tools"
                        >
                            <MediaViewerToolbarButton
                                className="btn-toolbar"
                                label="Reset spectrogram time and frequency range"
                                icon={<Move size={20} strokeWidth={2} />}
                                onClick={resetSpectrogramToFullView}
                            />

                            <MediaViewerToolbarButton
                                className="btn-toolbar"
                                active={spectrogramMagnifierZoomed}
                                label={
                                    annotationDraft
                                        ? "Zoom the spectrogram to this annotation"
                                        : "Zoom the spectrogram to the selection"
                                }
                                icon={<Scan size={20} strokeWidth={2} />}
                                disabled={
                                    !(annotationDraft || (editingAnnotationMeta && editingAnnotationId)) ||
                                    spectrogramMagnifierZoomed
                                }
                                onClick={handleAnnotToolbarMagnifierZoom}
                            />

                            <MediaViewerToolbarButton
                                className="btn-toolbar"
                                label="Previous annotation"
                                icon={<ChevronLeft size={20} strokeWidth={2} />}
                                disabled={editingAnnotationId == null}
                                onClick={() => goToAdjacentAnnotation(-1)}
                            />
                            <MediaViewerToolbarButton
                                className="btn-toolbar"
                                label="Next annotation"
                                icon={<ChevronRight size={20} strokeWidth={2} />}
                                disabled={editingAnnotationId == null}
                                onClick={() => goToAdjacentAnnotation(1)}
                            />
                            <MediaViewerToolbarButton
                                className="btn-toolbar"
                                active={navAutoZoomToAnnotation}
                                label={
                                    navAutoZoomToAnnotation
                                        ? "On: Previous/Next also zooms the spectrogram to each annotation. Click to jump only."
                                        : "Off: Previous/Next only switches the annotation. Click to also auto-zoom the spectrogram."
                                }
                                icon={<Search size={20} strokeWidth={2} />}
                                onClick={() => setNavAutoZoomToAnnotation((v) => !v)}
                            />
                            <MediaViewerToolbarButton
                                className="btn-toolbar"
                                active={navOnlyTaskTagged}
                                label="When on: Previous/Next only among annotations that show the Task pill (API returned a task assignment on that row). If the current row has no Task pill, jumps to the next/previous Task by ID."
                                icon={<ClipboardList size={20} strokeWidth={2} />}
                                onClick={() => setNavOnlyTaskTagged((v) => !v)}
                            />
                        </div>
                    </div>

                    {/* Bottom Toolbar */}
                    <div className="player-toolbar-bottom">
                        {/* Play / Stop */}
                        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                            <MediaViewerToolbarButton
                                className={`btn-toolbar studio-play-toggle-btn${isPlaying ? " danger" : ""}`}
                                active={isPlaying}
                                disabled={isAudioBusy && !continuousSegmentPlayback}
                                onClick={handlePlayToggle}
                                label={
                                    isAudioBusy && !continuousSegmentPlayback
                                        ? "Loading audio… (Space)"
                                        : isPlaying
                                            ? "Pause (Space)"
                                            : "Play (Space)"
                                }
                                icon={isPlaying ? <Pause size={14} /> : <Play size={14} />}
                            />
                            <MediaViewerToolbarButton
                                className="btn-toolbar danger studio-stop-btn"
                                disabled={audioLoading}
                                onClick={handleStop}
                                label="Stop"
                                icon={<Square size={14} />}
                            />
                        </div>

                        {/* Time display */}
                        <div style={{ display: "flex", alignItems: "center", gap: 4, cursor: "default" }}>
                            <span style={{ fontWeight: 600, color: "var(--text-secondary)", fontVariantNumeric: "tabular-nums" }}>
                                {Number.isFinite(currentTime) ? currentTime.toFixed(2) : "0.00"}s
                            </span>
                            <span style={{ fontWeight: 600, color: "var(--text-secondary)" }}>/</span>
                            <span style={{ fontWeight: 600, color: "var(--text-secondary)", fontVariantNumeric: "tabular-nums" }}>
                                {totalDuration > 0 ? `${totalDuration.toFixed(2)}s` : ""}
                            </span>
                        </div>

                        <div style={{ flex: 1 }} />

                        {/* Freq/Time range info */}
                        <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600, color: "var(--text-secondary)", fontVariantNumeric: "tabular-nums" }}>
                            <span title="Visible Time Range">
                                x:{" "}
                                {totalDuration > 0
                                    ? `${formatDisplayNumber(specViewStart)} – ${formatDisplayNumber(specVisibleEnd)}`
                                    : ""}
                            </span>
                            <span style={{ width: 1, height: 12, background: "var(--border-color)" }} />
                            <span title="Visible Frequency Range">
                                y:{" "}
                                {`${formatDisplayNumber(specFreqMinHz)} – ${formatDisplayNumber(
                                    specFreqMaxHz,
                                )}`}
                            </span>
                        </div>

                        <span style={{ width: 1, height: 12, background: "var(--border-color)", margin: "0 4px" }} />

                        {/* Speed control */}
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }} title="Playback Speed">
                            <ESInput appearance="unstyled"
                                type="range"
                                min={PLAYBACK_RATE_SLIDER_MIN}
                                max={PLAYBACK_RATE_SLIDER_MAX}
                                step={0.01}
                                value={playbackSpeed}
                                className="studio-speed-slider"
                                onChange={(e) => {
                                    const v = Number(e.target.value)
                                    const nextSpeed = clamp(v, PLAYBACK_RATE_SLIDER_MIN, PLAYBACK_RATE_SLIDER_MAX)
                                    const continuousEngine = continuousEngineRef.current
                                    playbackSpeedRef.current = nextSpeed
                                    setPlaybackSpeed(v)
                                    if (continuousEngine) {
                                        const current = continuousEngine.current
                                        const liveTime = getLivePlaybackTime()
                                        continuousEngine.playbackRate = nextSpeed
                                        if (current) {
                                            const elapsedInSegment = clamp(liveTime - current.start, 0, current.end - current.start)
                                            continuousEngine.startedAtCtx =
                                                continuousEngine.ctx.currentTime - elapsedInSegment / nextSpeed
                                            continuousEngine.currentCtxDuration = Math.max(0.02, current.end - current.start) / nextSpeed
                                            continuousEngine.scheduledEndCtx =
                                                continuousEngine.startedAtCtx + continuousEngine.currentCtxDuration
                                            setPlaybackTime(liveTime)
                                        }
                                        try {
                                            continuousEngine.source?.playbackRate.setValueAtTime(
                                                nextSpeed,
                                                continuousEngine.ctx.currentTime,
                                            )
                                        } catch {
                                            try {
                                                if (continuousEngine.source) continuousEngine.source.playbackRate.value = nextSpeed
                                            } catch {
                                                /* ignore */
                                            }
                                        }
                                        if (continuousEngine.nextSource) {
                                            try {
                                                continuousEngine.nextSource.stop()
                                            } catch {
                                                /* ignore */
                                            }
                                            continuousEngine.nextSource = null
                                            continuousEngine.nextStartedAtCtx = null
                                            continuousEngine.nextScheduledEndCtx = null
                                            continuousEngine.nextCtxDuration = null
                                        }
                                        scheduleDecodedContinuousNext(continuousEngine)
                                    }
                                }}
                                style={{
                                    // @ts-ignore
                                    "--p": `${((playbackSpeed - PLAYBACK_RATE_SLIDER_MIN) / (PLAYBACK_RATE_SLIDER_MAX - PLAYBACK_RATE_SLIDER_MIN)) * 100}%`,
                                }}
                            />
                            <span style={{ fontWeight: 600, color: "var(--text-secondary)", width: 44, textAlign: "right" }}>
                                {playbackSpeed.toFixed(2)}x
                            </span>
                        </div>

                        <span style={{ width: 1, height: 12, background: "var(--border-color)" }} />

                        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                            <MediaViewerToolbarButton
                                className="btn-toolbar"
                                active={continuousSegmentPlayback}
                                label={
                                    continuousSegmentPlayback
                                        ? "Continuous Playback: ON (Web Audio scheduled playback)"
                                        : "Continuous Playback: OFF"
                                }
                                icon={<ArrowRightFromLine size={14} />}
                                disabled={!media || currentProjectId == null}
                                onClick={() => {
                                    if (continuousSegmentPlayback) {
                                        const engine = continuousEngineRef.current
                                        const wasContinuousPlaying =
                                            engine != null && engine.ctx.state === "running"
                                        const resumeTime =
                                            engine?.current
                                                ? clamp(
                                                    engine.current.start +
                                                    Math.max(0, engine.ctx.currentTime - engine.startedAtCtx) *
                                                    engine.playbackRate,
                                                    engine.current.start,
                                                    engine.current.end,
                                                )
                                                : currentTimeRef.current
                                        standardPlayAfterLoadRef.current = wasContinuousPlaying ? resumeTime : null
                                        stopContinuousPlayback({ keepToggle: true })
                                        restoreStandardAudioAfterContinuous(resumeTime)
                                        setPlaybackTime(resumeTime)
                                        return
                                    }
                                    const el = audioRef.current
                                    const shouldStartContinuous =
                                        !!(el && !el.paused && !el.ended)
                                    const startAt =
                                        el && Number.isFinite(el.currentTime)
                                            ? audioWindowStartRef.current + el.currentTime
                                            : currentTimeRef.current
                                    standardPlayAfterLoadRef.current = null
                                    interruptStandardAudioRequest({ preserveTime: true })
                                    setContinuousSegmentPlayback(true)
                                    continuousSegmentPlaybackRef.current = true
                                    if (shouldStartContinuous) {
                                        startContinuousPlaybackRef.current({
                                            startAt,
                                            forceViewport: true,
                                        })
                                    }
                                }}
                            />
                            <MediaViewerToolbarButton
                                className="btn-toolbar"
                                active={audioBandFilter}
                                label={
                                    isPlaying
                                        ? "Pause playback before changing bandpass filter"
                                        : audioBandFilter
                                        ? "Bandpass Filter: ON (audio matches visible frequency range)"
                                        : "Bandpass Filter: OFF (full spectrum for current time window)"
                                }
                                icon={<Filter size={14} />}
                                disabled={!media || currentProjectId == null || isPlaying}
                                onClick={() => {
                                    const resumeTime = getLivePlaybackTime()
                                    const continuousEngine = continuousEngineRef.current
                                    const shouldResumeContinuous =
                                        continuousEngine != null && continuousEngine.ctx.state === "running"
                                    const el = audioRef.current
                                    const shouldResumeStandard =
                                        continuousEngine == null && !!(el && !el.paused && !el.ended)
                                    const nextAudioBandFilter = !audioBandFilter
                                    if (continuousSegmentPlaybackRef.current || continuousEngine) {
                                        stopContinuousPlayback({ keepToggle: true })
                                    } else {
                                        stopContinuousPlayback()
                                    }
                                    interruptStandardAudioRequest({ preserveTime: true, preserveAt: resumeTime })
                                    activeViewportParamsKeyRef.current = null
                                    if (nextAudioBandFilter) {
                                        pendingAudioBandpassHzRef.current = null
                                        const draft = annotationDraftRef.current
                                        const sr = Number(media?.sampling_rate_hz) || 0
                                        const nyq = sr > 0 ? Math.round(sr / 2) : 24000
                                        if (annotationPanelActiveRef.current && draft) {
                                            pendingAudioBandpassHzRef.current = physBoxFreqBandHz(
                                                draft,
                                                nyq,
                                            )
                                        } else if (spectrogramMagnifierZoomedRef.current) {
                                            pendingAudioBandpassHzRef.current = {
                                                lo: Math.min(specFreqMinHz, specFreqMaxHz),
                                                hi: Math.max(specFreqMinHz, specFreqMaxHz),
                                            }
                                        }
                                    } else {
                                        pendingAudioBandpassHzRef.current = null
                                    }
                                    audioBandFilterRef.current = nextAudioBandFilter
                                    setAudioBandFilter(nextAudioBandFilter)
                                    if (shouldResumeContinuous) {
                                        standardPlayAfterLoadRef.current = null
                                        setContinuousSegmentPlayback(true)
                                        continuousSegmentPlaybackRef.current = true
                                        startContinuousPlaybackRef.current({
                                            startAt: resumeTime,
                                            forceViewport: true,
                                        })
                                    } else {
                                        standardPlayAfterLoadRef.current = shouldResumeStandard ? resumeTime : null
                                        setAudioReloadToken((n) => n + 1)
                                    }
                                }}
                            />
                        </div>
                    </div>
                </div>
                )}

                {isPhoto ? (
                    <ESButton
                        appearance="unstyled"
                        type="button"
                        className="data-btn studio-table-toolbar-button studio-photo-annotation-table-toggle"
                        title={annotationTableVisible ? "Hide annotations table" : "Show annotations table"}
                        aria-label={annotationTableVisible ? "Hide annotations table" : "Show annotations table"}
                        onClick={() => setAnnotationTableVisible((visible) => !visible)}
                    >
                        {annotationTableVisible ? <Eye size={16} aria-hidden /> : <EyeOff size={16} aria-hidden />}
                    </ESButton>
                ) : null}

                {/* Bottom: Side toolbar + Annotation table */}
                {annotationTableVisible ? (
                <div className="studio-bottom-section">
                        <>
                            {/* Side Toolbar */}
                            <div className="table-side-toolbar">
                                <ESButton appearance="unstyled"
                                    type="button"
                                    className="btn-toolbar"
                                    style={{ padding: 8, justifyContent: "center" }}
                                    title="Reset table filters and reload list"
                                    onClick={handleAnnotationTableResetToolbar}
                                >
                                    <RotateCcw size={16} />
                                </ESButton>
                                <div style={{ width: 24, height: 1, background: "var(--border-color)", margin: "6px 0", borderRadius: 1, opacity: 0.8 }} />
                                <div style={{ display: "flex", flexDirection: "column", gap: 12, width: "100%" }}>
                                    {authUtils.getToken() ? (
                                        <>
                                            <ESButton appearance="unstyled"
                                                type="button"
                                                className={`data-btn ${rightPanel === "assign-task" ? "active" : ""}`}
                                                style={{ padding: 8, justifyContent: "center" }}
                                                title="Assign task to selected annotation rows (users with collection access)"
                                                disabled={selectedAnnotationKeys.length === 0}
                                                onClick={() => void openAssignTaskPanel()}
                                            >
                                                <ClipboardList size={16} />
                                            </ESButton>
                                            <ESButton appearance="unstyled"
                                                type="button"
                                                className="data-btn danger"
                                                style={{ padding: 8, justifyContent: "center", width: "100%" }}
                                                title="Delete selected rows"
                                                disabled={selectedAnnotationKeys.length === 0}
                                                onClick={() => setDeleteAnnotationsConfirmOpen(true)}
                                            >
                                                <Trash2 size={16} />
                                            </ESButton>
                                        </>
                                    ) : null}
                                </div>
                                <div style={{ flex: 1 }} />
                                <ESButton appearance="unstyled"
                                    type="button"
                                    className="btn-toolbar"
                                    style={{ padding: 8, justifyContent: "center" }}
                                    title={
                                        isPhoto
                                            ? "Export all annotations for this photo"
                                            : "Export CSV: annotations overlapping current spectrogram time & frequency view (ignores table filters)"
                                    }
                                    onClick={() => void handleExportViewportAnnotationsCsv()}
                                >
                                    <Download size={16} />
                                </ESButton>
                                {!isPhoto ? (
                                    <ESButton appearance="unstyled"
                                        type="button"
                                        className="data-btn"
                                        style={{ padding: 8, justifyContent: "center", width: "100%" }}
                                        title="Hide annotations table"
                                        onClick={() => setAnnotationTableVisible(false)}
                                    >
                                        <Eye size={16} aria-hidden />
                                    </ESButton>
                                ) : null}
                            </div>

                            <ConfigProvider theme={antdAppTheme}>
                                <div
                                    className="data-content data-table-container studio-annotation-table-wrap data-content-media-detail"
                                    style={{
                                        display: "flex",
                                        flexDirection: "column",
                                        minHeight: 0,
                                        flex: 1,
                                        position: "relative",
                                    }}
                                >
                            {isThemeTransitioning && (
                                <div className="dpl-theme-loader-overlay">
                                    <LoadingState label="Updating theme..." variant="overlay" size="lg" showLabel={false} />
                                </div>
                            )}
                            <div
                                ref={annotationTableViewportRef}
                                className="data-table-wrapper"
                                style={
                                    {
                                        flex: 1,
                                        minHeight: 0,
                                        overflow: "hidden",
                                        display: "flex",
                                        flexDirection: "column",
                                        "--dpl-scroll-y": `${annotationTableBodyScrollY}px`,
                                    } as any
                                }
                            >
                                <div className="data-table-shell">
                                    {showAnnotationTableLoading ? (
                                        <LoadingState
                                            label="Loading data..."
                                            variant="overlay"
                                            size="lg"
                                            className="data-table-loading-overlay"
                                        />
                                    ) : null}
                                    <DataTable<StudioAnnotationRow>
                                        loading={false}
                                        rowKey="annotation_id"
                                        size="small"
                                        tableLayout="fixed"
                                        columns={annotationAntdColumns as any}
                                        dataSource={annotationTableRows}
                                        scroll={{ x: 3800, y: annotationTableBodyScrollY }}
                                        locale={{
                                            emptyText: showAnnotationTableLoading ? (
                                                <div className="data-table-empty-state studio-annotation-table-empty" />
                                            ) : (
                                                <div className="ui-state ui-state--inline data-table-empty-state studio-annotation-table-empty">
                                                    <NoDataIcon />
                                                    <span>No Data</span>
                                                </div>
                                            ),
                                        }}
                                        pagination={false}
                                        rowClassName={(record) =>
                                            record.annotation_id === annotationLinkedHighlightId ||
                                                record.annotation_id === editingAnnotationId
                                                ? "studio-annotation-row--linked"
                                                : ""
                                        }
                                        onRow={(record) => ({
                                            onClick: (e) => {
                                                const t = e.target as HTMLElement
                                                if (
                                                t.closest(".ant-checkbox-wrapper") ||
                                                t.closest("button") ||
                                                t.closest("a")
                                            ) {
                                                return
                                            }
                                            void openAnnotationEditorById(record.annotation_id)
                                        },
                                        onMouseEnter: () => setAnnotationLinkedHighlightId(record.annotation_id),
                                        onMouseLeave: () =>
                                            setAnnotationLinkedHighlightId((cur) =>
                                                cur === record.annotation_id ? null : cur,
                                            ),
                                    })}
                                    onChange={handleAnnotationTableChange}
                                />
                            </div>
                            <div ref={annotationTableHTrackRef} className="dpl-hscroll-track" aria-hidden>
                                {annotationTableHThumb.show ? (
                                    <div
                                        className={
                                            "dpl-hscroll-thumb" +
                                            (annotationTableHDragging ? " dpl-hscroll-thumb--dragging" : "")
                                        }
                                        style={{
                                            width: annotationTableHThumb.size,
                                            transform: `translateX(${annotationTableHThumb.offset}px)`,
                                        }}
                                        onPointerDown={onAnnotationTableHThumbPointerDown}
                                        onPointerMove={onAnnotationTableHThumbPointerMove}
                                        onPointerUp={endAnnotationTableHDrag}
                                        onPointerCancel={endAnnotationTableHDrag}
                                        onLostPointerCapture={() => {
                                            annotationTableHDragRef.current = null
                                            setAnnotationTableHDragging(false)
                                        }}
                                    />
                                ) : null}
                            </div>
                        </div>
                    </div>
                    </ConfigProvider>
                        </>
                </div>
                ) : !isPhoto ? (
                    <div className="studio-bottom-section">
                        <div className="table-side-toolbar">
                            <div style={{ flex: 1 }} />
                            <ESButton appearance="unstyled"
                                type="button"
                                className="data-btn"
                                style={{ padding: 8, justifyContent: "center", width: "100%" }}
                                title="Show annotations table"
                                onClick={() => setAnnotationTableVisible(true)}
                            >
                                <EyeOff size={16} aria-hidden />
                            </ESButton>
                        </div>
                    </div>
                ) : null}
            </div>

            {/* ===== RIGHT: 新建标注 / 音频信息 ===== */}
            <div className="studio-info-section">
                {rightPanel === "new-annotation" && annotationDraft ? (
                    <div className="studio-annotation-panel">
                        <div className="studio-annotation-card">
                            <div className="studio-annotation-header">
                                <ESButton appearance="unstyled"
                                    type="button"
                                    className="header-back"
                                    title="Back"
                                    onClick={closeAnnotationPanel}
                                >
                                    <ArrowLeft size={18} strokeWidth={2.25} />
                                </ESButton>
                                <span className="header-title">
                                    {editingAnnotationId != null ? "Edit Annotation" : "New Annotation"}
                                </span>
                                {editingAnnotationId != null ? (
                                    <div className="studio-annotation-header-actions">
                                        <ESButton appearance="unstyled"
                                            type="button"
                                            className="studio-annot-header-icon"
                                            title="Share annotation"
                                            aria-label="Share annotation"
                                            onClick={() => void handleShareEditingAnnotation()}
                                        >
                                            <Share2 size={15} />
                                        </ESButton>
                                        <ESButton appearance="unstyled"
                                            type="button"
                                            className="studio-annot-header-icon studio-annot-header-icon--danger"
                                            title="Delete annotation"
                                            aria-label="Delete annotation"
                                            onClick={() => setDeleteEditingAnnotationConfirmOpen(true)}
                                        >
                                            <Trash2 size={15} />
                                        </ESButton>
                                    </div>
                                ) : null}
                            </div>
                            <ConfigProvider
                                theme={antdAppTheme}
                            >
                                <div className="studio-annotation-card-scroll">
                                    <div className="studio-annotation-form-only-scroll">
                                        <CustomScrollArea variant="fill">
                                            <div>
                                                <Form
                                                    layout="vertical"
                                                    className="studio-annotation-form studio-annotation-form--antd shared-drawer-form"
                                                    requiredMark={false}
                                                >
                                                    <div className="">
                                                        <div
                                                            className={isPhoto ? "form-drawer-main-col studio-annot-photo-form-grid" : "form-drawer-main-col"}
                                                            style={{ padding: 0 }}
                                                        >
                                                            <Row gutter={[14, 0]} className={isPhoto ? "studio-annot-photo-coordinate-row" : undefined}>
                                                                <Col xs={isPhoto ? 24 : 12} sm={isPhoto ? 12 : 6}>
                                                                    <Form.Item label={renderStudioRequiredLabel("Min X")} className="studio-annot-form-item">
                                                                        <InputNumber
                                                                            style={{ width: "100%" }}
                                                                            precision={4}
                                                                            step={0.0001}
                                                                            value={annotationDraft.min_x}
                                                                            onChange={(v) => {
                                                                                if (typeof v !== "number" || Number.isNaN(v)) return
                                                                                setDistanceFieldUnlocked(false)
                                                                                setAnnotationDraft((d) => (d ? { ...d, min_x: v } : d))
                                                                            }}
                                                                        />
                                                                    </Form.Item>
                                                                </Col>
                                                                <Col xs={isPhoto ? 24 : 12} sm={isPhoto ? 12 : 6}>
                                                                    <Form.Item label={renderStudioRequiredLabel("Max X")} className="studio-annot-form-item">
                                                                        <InputNumber
                                                                            style={{ width: "100%" }}
                                                                            precision={4}
                                                                            step={0.0001}
                                                                            value={annotationDraft.max_x}
                                                                            onChange={(v) => {
                                                                                if (typeof v !== "number" || Number.isNaN(v)) return
                                                                                setDistanceFieldUnlocked(false)
                                                                                setAnnotationDraft((d) => (d ? { ...d, max_x: v } : d))
                                                                            }}
                                                                        />
                                                                    </Form.Item>
                                                                </Col>
                                                                <Col xs={isPhoto ? 24 : 12} sm={isPhoto ? 12 : 6}>
                                                                    <Form.Item label={renderStudioRequiredLabel("Min Y")} className="studio-annot-form-item">
                                                                        <InputNumber
                                                                            style={{ width: "100%" }}
                                                                            precision={4}
                                                                            step={0.0001}
                                                                            value={annotationDraft.min_y}
                                                                            onChange={(v) => {
                                                                                if (typeof v !== "number" || Number.isNaN(v)) return
                                                                                setDistanceFieldUnlocked(false)
                                                                                setAnnotationDraft((d) => (d ? { ...d, min_y: v } : d))
                                                                            }}
                                                                        />
                                                                    </Form.Item>
                                                                </Col>
                                                                <Col xs={isPhoto ? 24 : 12} sm={isPhoto ? 12 : 6}>
                                                                    <Form.Item label={renderStudioRequiredLabel("Max Y")} className="studio-annot-form-item">
                                                                        <InputNumber
                                                                            style={{ width: "100%" }}
                                                                            precision={4}
                                                                            step={0.0001}
                                                                            value={annotationDraft.max_y}
                                                                            onChange={(v) => {
                                                                                if (typeof v !== "number" || Number.isNaN(v)) return
                                                                                setDistanceFieldUnlocked(false)
                                                                                setAnnotationDraft((d) => (d ? { ...d, max_y: v } : d))
                                                                            }}
                                                                        />
                                                                    </Form.Item>
                                                                </Col>
                                                            </Row>
                                                            {isPhoto ? (
                                                                <Row gutter={[14, 0]} className="studio-annot-photo-flow-row">
                                                                    <Col xs={24} sm={12}>
                                                                        <Form.Item label={renderStudioRequiredLabel("Object Type")} className="studio-annot-form-item">
                                                                            <Select className="form-drawer-select" options={[{ value: "organism", label: "Organism" }, { value: "other", label: "Other" }]} value={formObjectType ?? undefined} onChange={(value) => setFormObjectType(value ?? null)} />
                                                                        </Form.Item>
                                                                    </Col>
                                                                </Row>
                                                            ) : null}
                                                            <Row gutter={[14, 0]} style={isPhoto ? { display: "none" } : undefined}>
                                                                <Col xs={24} sm={12}>
                                                                    <Form.Item label={renderStudioRequiredLabel("Soundscape")} className="studio-annot-form-item">
                                                                        <Select
                                                                            className="form-drawer-select"
                                                                            classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                                                            allowClear
                                                                            showSearch
                                                                            optionFilterProp="label"
                                                                            options={soundscapeSelectOptions}
                                                                            value={formSoundscape === null ? undefined : formSoundscape}
                                                                            onChange={(v) => {
                                                                                setFormSoundscape(v === undefined ? null : String(v))
                                                                                setFormSoundTypeSoundId(null)
                                                                            }}
                                                                            filterOption={selectSearchFilter}
                                                                        />
                                                                    </Form.Item>
                                                                </Col>
                                                                <Col xs={24} sm={12}>
                                                                    <Form.Item label={renderStudioRequiredLabel("Sound Type")} className="studio-annot-form-item">
                                                                        <Select
                                                                            className="form-drawer-select"
                                                                            classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                                                            allowClear
                                                                            showSearch
                                                                            optionFilterProp="label"
                                                                            options={soundTypeSelectOptions}
                                                                            value={formSoundTypeSoundId ?? undefined}
                                                                            disabled={formSoundscape === null || soundTypeSelectOptions.length === 0}
                                                                            onChange={(v) => {
                                                                                setFormSoundTypeSoundId(
                                                                                    typeof v === "number" && !Number.isNaN(v) ? v : null,
                                                                                )
                                                                            }}
                                                                            filterOption={selectSearchFilter}
                                                                        />
                                                                    </Form.Item>
                                                                </Col>
                                                            </Row>
                                                            {(isPhoto ? formObjectType === "organism" : isBiophonyAnnotationForm) ? (
                                                                <>
                                                                    <Row gutter={[14, 0]} className={isPhoto ? "studio-annot-photo-flow-row" : undefined}>
                                                                        <Col xs={24} sm={12}>
                                                                            <Form.Item
                                                                                label={
                                                                                    <div
                                                                                        className="studio-annot-taxon-label"
                                                                                        onMouseDown={(e) => {
                                                                                            e.preventDefault()
                                                                                            e.stopPropagation()
                                                                                        }}
                                                                                        onClick={(e) => {
                                                                                            e.preventDefault()
                                                                                            e.stopPropagation()
                                                                                        }}
                                                                                    >
                                                                                        <span
                                                                                            className="studio-annot-taxon-label-title"
                                                                                            onMouseDown={(e) => {
                                                                                                e.preventDefault()
                                                                                                e.stopPropagation()
                                                                                            }}
                                                                                            onClick={(e) => {
                                                                                                e.preventDefault()
                                                                                                e.stopPropagation()
                                                                                            }}
                                                                                        >
                                                                                            Taxon
                                                                                        </span>
                                                                                        <div className="studio-annot-taxon-links studio-annot-taxon-links--inline">
                                                                                            <ESButton appearance="unstyled"
                                                                                                type="button"
                                                                                                className="studio-annot-taxon-search-btn"
                                                                                                onClick={(e) => {
                                                                                                    e.preventDefault()
                                                                                                    e.stopPropagation()
                                                                                                    const q = resolveTaxonSearchQuery()
                                                                                                    if (!q) {
                                                                                                        message.error("Enter or select a taxon first.")
                                                                                                        return
                                                                                                    }
                                                                                                    window.open(
                                                                                                        `https://www.google.com/search?tbm=isch&q=${encodeURIComponent(q)}`,
                                                                                                        "_blank",
                                                                                                        "noopener,noreferrer",
                                                                                                    )
                                                                                                }}
                                                                                            >
                                                                                                Images
                                                                                            </ESButton>
                                                                                            <span className="studio-annot-link-sep" aria-hidden>
                                                                                                |
                                                                                            </span>
                                                                                            <ESButton appearance="unstyled"
                                                                                                type="button"
                                                                                                className="studio-annot-taxon-search-btn"
                                                                                                onClick={(e) => {
                                                                                                    e.preventDefault()
                                                                                                    e.stopPropagation()
                                                                                                    const q = resolveTaxonSearchQuery(true)
                                                                                                    if (!q) {
                                                                                                        message.error("Enter or select a taxon first.")
                                                                                                        return
                                                                                                    }
                                                                                                    window.open(
                                                                                                        `https://xeno-canto.org/explore?query=${encodeURIComponent(q)}`,
                                                                                                        "_blank",
                                                                                                        "noopener,noreferrer",
                                                                                                    )
                                                                                                }}
                                                                                            >
                                                                                                Xeno-canto
                                                                                            </ESButton>
                                                                                        </div>
                                                                                    </div>
                                                                                }
                                                                                className="studio-annot-form-item studio-annot-form-item--taxon"
                                                                            >
                                                                                <Select
                                                                                    className="form-drawer-select"
                                                                                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                                                                    showSearch
                                                                                    allowClear
                                                                                    filterOption={false}
                                                                                    loading={taxonOptionsState.loading}
                                                                                    options={taxonSelectMergedOptions}
                                                                                    value={formTaxonId ?? undefined}
                                                                                    optionLabelProp="label"
                                                                                    notFoundContent={
                                                                                        taxonOptionsState.loading ? (
                                                                                            <LoadingState label="Loading taxa..." variant="inline" size="sm" showLabel={false} />
                                                                                        ) : (
                                                                                            <div className="form-drawer-select-empty">
                                                                                                <NoDataIcon />
                                                                                                <span>
                                                                                                    {taxonOptionsState.query
                                                                                                        ? "No matching taxa"
                                                                                                        : "Type a taxon name to search"}
                                                                                                </span>
                                                                                            </div>
                                                                                        )
                                                                                    }
                                                                                    onSearch={taxonOptionsState.search}
                                                                                    onPopupScroll={(event) => {
                                                                                        if (
                                                                                            isSelectScrollNearBottom(
                                                                                                event.currentTarget,
                                                                                            )
                                                                                        ) {
                                                                                            taxonOptionsState.loadNext()
                                                                                        }
                                                                                    }}
                                                                                    popupRender={(menu) => (
                                                                                        <>
                                                                                            {menu}
                                                                                            {taxonOptionsState.loading ? (
                                                                                                <LoadingState
                                                                                                    label="Loading taxa..."
                                                                                                    variant="inline"
                                                                                                    size="sm"
                                                                                                    showLabel={false}
                                                                                                />
                                                                                            ) : null}
                                                                                        </>
                                                                                    )}
                                                                                    onChange={(v, option) => {
                                                                                        if (v == null || typeof v !== "number") {
                                                                                            setFormTaxonId(null)
                                                                                            setFormTaxonSearch("")
                                                                                            taxonOptionsState.setCurrentOption(null)
                                                                                            return
                                                                                        }
                                                                                        setFormTaxonId(v)
                                                                                        taxonOptionsState.setCurrentOption(
                                                                                            taxonOptionsState.options.find(
                                                                                                (item) => item.value === v,
                                                                                            ) ?? null,
                                                                                        )
                                                                                        const o = option as { label?: ReactNode } | undefined
                                                                                        const lab =
                                                                                            typeof o?.label === "string"
                                                                                                ? o.label
                                                                                                : taxonSelectMergedOptions.find(
                                                                                                    (x) => x.value === v,
                                                                                                )?.label ?? `Taxon ${v}`
                                                                                        setFormTaxonSearch(lab)
                                                                                    }}
                                                                                />
                                                                            </Form.Item>
                                                                        </Col>
                                                                        <Col xs={24} sm={12}>
                                                                            <Form.Item
                                                                                label="Uncertain"
                                                                                className="studio-annot-form-item studio-annot-switch-field"
                                                                                colon={false}
                                                                                required={false}
                                                                            >
                                                                                <Switch
                                                                                    checked={formUncertain === "true"}
                                                                                    onChange={(checked) => setFormUncertain(checked ? "true" : "false")}
                                                                                />
                                                                            </Form.Item>
                                                                        </Col>
                                                                    </Row>
                                                                    {!isPhoto ? <Row gutter={[14, 0]}>
                                                                        <Col xs={24} sm={12}>
                                                                            <Form.Item label="Animal Sound" className="studio-annot-form-item">
                                                                                <Select
                                                                                    className="form-drawer-select"
                                                                                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                                                                    allowClear
                                                                                    showSearch
                                                                                    optionFilterProp="label"
                                                                                    loading={animalSoundTypesLoading}
                                                                                    options={animalSoundSelectOptions}
                                                                                    value={formAnimalSound || undefined}
                                                                                    onChange={(v) => setFormAnimalSound(v ?? "")}
                                                                                    filterOption={selectSearchFilter}
                                                                                />
                                                                            </Form.Item>
                                                                        </Col>
                                                                        <Col xs={24} sm={12}>
                                                                            <div className="studio-annot-distance-block">
                                                                                <div className="studio-annot-distance-header">
                                                                                    <span className="studio-annot-distance-title">
                                                                                        Distance (m)
                                                                                    </span>
                                                                                    <div className="studio-annot-taxon-links studio-annot-taxon-links--inline studio-annot-distance-toggle-group">
                                                                                        <span className="studio-annot-distance-switch-text">Not Estimable</span>
                                                                                        <span className="studio-annot-link-sep" aria-hidden>
                                                                                            |
                                                                                        </span>
                                                                                        <ConfigProvider wave={{ disabled: true }}>
                                                                                            <Switch
                                                                                                size="small"
                                                                                                checked={formDistanceNotEstimable}
                                                                                                onChange={(checked) => {
                                                                                                    setFormDistanceNotEstimable(checked)
                                                                                                    if (checked) setFormDistanceM(null)
                                                                                                }}
                                                                                            />
                                                                                        </ConfigProvider>
                                                                                    </div>
                                                                                </div>
                                                                                <Space.Compact block className="studio-annot-distance-input-compact">
                                                                                    <Input
                                                                                        className="studio-annot-distance-input"
                                                                                        disabled={
                                                                                            formDistanceNotEstimable || !distanceFieldUnlocked
                                                                                        }
                                                                                        value={formDistanceM ?? ""}
                                                                                        onChange={(e) => {
                                                                                            const v = parseFloat(e.target.value)
                                                                                            if (e.target.value === "") setFormDistanceM(null)
                                                                                            else if (!Number.isNaN(v)) setFormDistanceM(v)
                                                                                        }}
                                                                                    />
                                                                                    {!isPhoto ? (
                                                                                        <Button
                                                                                            type="primary"
                                                                                            icon={<Volume2 size={16} />}
                                                                                            title={
                                                                                                audioLoading
                                                                                                    ? "Loading audio…"
                                                                                                    : "Play from selection start"
                                                                                            }
                                                                                            disabled={audioLoading || !audioReady}
                                                                                            onClick={() => previewAnnotationRegion()}
                                                                                        />
                                                                                    ) : null}
                                                                                </Space.Compact>
                                                                            </div>
                                                                        </Col>
                                                                    </Row> : null}
                                                                    <Row gutter={[14, 0]} className={isPhoto ? "studio-annot-photo-flow-row" : undefined}>
                                                                        <Col xs={24} sm={12}>
                                                                            <Form.Item label="Indiv. Num" className="studio-annot-form-item">
                                                                                <Input
                                                                                    style={{ width: "100%" }}
                                                                                    value={formIndividualNum}
                                                                                    onChange={(e) => {
                                                                                        const v = parseInt(e.target.value, 10)
                                                                                        if (e.target.value === "") setFormIndividualNum(1)
                                                                                        else if (!Number.isNaN(v)) setFormIndividualNum(Math.max(1, v))
                                                                                    }}
                                                                                />
                                                                            </Form.Item>
                                                                        </Col>
                                                                        <Col xs={24} sm={12}>
                                                                            <Form.Item
                                                                                label="Reference"
                                                                                className="studio-annot-form-item studio-annot-switch-field"
                                                                                colon={false}
                                                                                required={false}
                                                                            >
                                                                                <Switch
                                                                                    checked={formReference === "true"}
                                                                                    onChange={(checked) => setFormReference(checked ? "true" : "false")}
                                                                                />
                                                                            </Form.Item>
                                                                        </Col>
                                                                    </Row>
                                                                    <Row gutter={[14, 0]} align="bottom" className={isPhoto ? "studio-annot-photo-flow-row" : undefined}>
                                                                        <Col xs={24} sm={12}>
                                                                            <div className="studio-annot-comments-meta-shell">
                                                                                <Form.Item
                                                                                    label="Comments"
                                                                                    className="studio-annot-form-item"
                                                                                >
                                                                                    <Input
                                                                                        value={formComments}
                                                                                        onChange={(e) =>
                                                                                            setFormComments(
                                                                                                e.target.value,
                                                                                            )
                                                                                        }
                                                                                    />
                                                                                </Form.Item>
                                                                            </div>
                                                                        </Col>
                                                                        {editingAnnotationMeta ? (
                                                                            <Col
                                                                                xs={24}
                                                                                sm={12}
                                                                                className="studio-annot-comments-meta-col"
                                                                            >
                                                                                <div className="studio-annot-comments-meta-side studio-annot-comments-meta-side--row">
                                                                                    {editingAnnotationMetaCard}
                                                                                </div>
                                                                            </Col>
                                                                        ) : null}
                                                                    </Row>
                                                                </>
                                                            ) : (
                                                                <>
                                                                    <Row gutter={[14, 0]} className={isPhoto ? "studio-annot-photo-flow-row" : undefined}>
                                                                        <Col xs={24} sm={12}>
                                                                            <Form.Item
                                                                                label="Reference"
                                                                                className="studio-annot-form-item studio-annot-switch-field"
                                                                                colon={false}
                                                                                required={false}
                                                                            >
                                                                                <Switch
                                                                                    checked={formReference === "true"}
                                                                                    onChange={(checked) => setFormReference(checked ? "true" : "false")}
                                                                                />
                                                                            </Form.Item>
                                                                        </Col>
                                                                        <Col xs={24} sm={12}>
                                                                            <div className="studio-annot-comments-meta-shell">
                                                                                <Form.Item
                                                                                    label="Comments"
                                                                                    className="studio-annot-form-item"
                                                                                >
                                                                                    <div className="studio-annot-comments-inline-row">
                                                                                        <div className="studio-annot-comments-inline-main">
                                                                                            <Input
                                                                                                value={formComments}
                                                                                                onChange={(e) =>
                                                                                                    setFormComments(
                                                                                                        e.target.value,
                                                                                                    )
                                                                                                }
                                                                                            />
                                                                                        </div>
                                                                                        {editingAnnotationMeta ? (
                                                                                            <div className="studio-annot-comments-meta-side">
                                                                                                {editingAnnotationMetaCard}
                                                                                            </div>
                                                                                        ) : null}
                                                                                    </div>
                                                                                </Form.Item>
                                                                            </div>
                                                                        </Col>
                                                                    </Row>
                                                                </>
                                                            )}
                                                        </div>
                                                    </div>

                                                    <div className="studio-annot-form-actions">
                                                        <div className="studio-annot-save-row">
                                                            {editingAnnotationId == null ? (
                                                                <Button
                                                                    type="primary"
                                                                    loading={savePending}
                                                                    onClick={() => void handleSaveAnnotation()}
                                                                    title="Save"
                                                                >
                                                                    Save
                                                                </Button>
                                                            ) : (
                                                                <ConfigProvider wave={{ disabled: true }}>
                                                                    <DropdownMenuButton
                                                                        items={ANNOTATION_SAVE_MODE_MENU_ITEMS}
                                                                        selectable
                                                                        selectedKeys={[annotationSaveMode]}
                                                                        onItemClick={({ key }) => {
                                                                            persistAnnotationSaveMode(
                                                                                key as AnnotationSaveMode,
                                                                            )
                                                                        }}
                                                                        placement="bottomRight"
                                                                        type="primary"
                                                                        className="studio-annot-save-split"
                                                                        icon={
                                                                            <ChevronDown
                                                                                size={14}
                                                                                strokeWidth={2.25}
                                                                                className="studio-annot-save-mode-trigger-icon"
                                                                                aria-hidden
                                                                            />
                                                                        }
                                                                        loading={savePending}
                                                                        onClick={() => void handleSaveAnnotation()}
                                                                        title={ANNOTATION_SAVE_MODE_LABELS[annotationSaveMode]}
                                                                    >
                                                                        {ANNOTATION_SAVE_MODE_LABELS[annotationSaveMode]}
                                                                    </DropdownMenuButton>
                                                                </ConfigProvider>
                                                            )}
                                                        </div>
                                                    </div>
                                                </Form>
                                            </div>
                                        </CustomScrollArea>
                                    </div>
                                    {editingAnnotationId != null ? (
                                        <div className="studio-annot-review-module">
                                            <div className="studio-annot-review-head">
                                                <span className="studio-annot-review-title">REVIEW</span>
                                                {sortedEditingAnnotationReviews.length > 0 && !reviewPanelExpanded && canWriteReview ? (
                                                    <Button
                                                        type="primary"
                                                        className="studio-annot-review-edit-btn"
                                                        loading={reviewEditLoading}
                                                        onClick={() => void handleReviewEditClick()}
                                                    >
                                                        Edit
                                                    </Button>
                                                ) : null}
                                            </div>
                                            <div
                                                className={
                                                    reviewPanelExpanded ||
                                                        sortedEditingAnnotationReviews.length === 0
                                                        ? "studio-annot-review-cols"
                                                        : "studio-annot-review-cols studio-annot-review-cols--solo"
                                                }
                                            >
                                                <div className="studio-annot-review-history">
                                                    {sortedEditingAnnotationReviews.length === 0 ? (
                                                            <div className="studio-annot-review-empty">
                                                                <NoDataIcon />
                                                                <span>No Data</span>
                                                            </div>
                                                    ) : (
                                                        <CustomScrollArea
                                                            maxHeight={400}
                                                            bodyStyle={{ overflowY: "auto", minHeight: 0 }}
                                                        >
                                                            <ul className="studio-annot-review-list">
                                                                {sortedEditingAnnotationReviews.map((r) => {
                                                                    const vk = reviewStatusVisualKey(r.status_name)
                                                                    const canDeleteReview =
                                                                        !!authUtils.getToken() &&
                                                                        meUserId != null &&
                                                                        (meIsProjectAdmin || r.reviewer_id === meUserId)
                                                                    return (
                                                                        <li
                                                                            key={`${r.annotation_id}-${r.reviewer_id}`}
                                                                            className={`studio-annot-review-card studio-annot-review-card--${vk}`}
                                                                        >
                                                                            <div className="studio-annot-review-card-top">
                                                                                <span
                                                                                    className="studio-annot-review-card-name"
                                                                                    title={
                                                                                        r.reviewer_name?.trim() ||
                                                                                        `User ${r.reviewer_id}`
                                                                                    }
                                                                                >
                                                                                    {r.reviewer_name?.trim() ||
                                                                                        `User ${r.reviewer_id}`}
                                                                                </span>
                                                                                {canDeleteReview ? (
                                                                                    <ESButton appearance="unstyled"
                                                                                        type="button"
                                                                                        className="studio-annot-review-delete-btn"
                                                                                        title="Delete review"
                                                                                        aria-label="Delete review"
                                                                                        onClick={() => void handleDeleteReview(r)}
                                                                                    >
                                                                                        <Trash2 size={14} />
                                                                                    </ESButton>
                                                                                ) : null}
                                                                            </div>
                                                                            {r.taxon_name?.trim() ? (
                                                                                <div className="studio-annot-review-card-line">
                                                                                    {r.taxon_name.trim()}
                                                                                </div>
                                                                            ) : null}
                                                                            {r.note?.trim() ? (
                                                                                <div className="studio-annot-review-card-line">
                                                                                    {r.note.trim()}
                                                                                </div>
                                                                            ) : null}
                                                                            <div className="studio-annot-review-card-bottom">
                                                                                <span
                                                                                    className={`studio-annot-review-pill studio-annot-review-pill--${vk}`}
                                                                                >
                                                                                    {r.status_name
                                                                                        ? r.status_name.toUpperCase()
                                                                                        : ""}
                                                                                </span>
                                                                                <span
                                                                                    className="studio-annot-review-card-time"
                                                                                    title={formatReviewDateDisplay(
                                                                                        r.creation_date,
                                                                                    )}
                                                                                >
                                                                                    {formatReviewDateOnlyDisplay(
                                                                                        r.creation_date,
                                                                                    )}
                                                                                </span>
                                                                            </div>
                                                                        </li>
                                                                    )
                                                                })}
                                                            </ul>
                                                        </CustomScrollArea>
                                                    )}
                                                </div>
                                                {(reviewPanelExpanded ||
                                                    sortedEditingAnnotationReviews.length === 0) &&
                                                    authUtils.getToken() && (
                                                        <div className="studio-annot-review-form-col">
                                                            <div className="studio-annot-review-status-grid">
                                                                {(
                                                                    [
                                                                        {
                                                                            id: REVIEW_STATUS_IDS.accepted,
                                                                            label: "Accept",
                                                                            vkey: "accept" as const,
                                                                        },
                                                                        {
                                                                            id: REVIEW_STATUS_IDS.corrected,
                                                                            label: "Revise",
                                                                            vkey: "revise" as const,
                                                                        },
                                                                        {
                                                                            id: REVIEW_STATUS_IDS.rejected,
                                                                            label: "Reject",
                                                                            vkey: "reject" as const,
                                                                        },
                                                                        {
                                                                            id: REVIEW_STATUS_IDS.uncertain,
                                                                            label: "Uncertain",
                                                                            vkey: "uncertain" as const,
                                                                        },
                                                                    ] as const
                                                                ).map((s) => (
                                                                    <ESButton appearance="unstyled"
                                                                        key={s.id}
                                                                        type="button"
                                                                        className={`studio-annot-review-status-btn studio-annot-review-status-btn--${s.vkey}${reviewStatusId === s.id
                                                                            ? " studio-annot-review-status-btn--selected"
                                                                            : ""
                                                                            }`}
                                                                        onClick={() => {
                                                                            setReviewStatusId(s.id)
                                                                            setReviewTaxonError(null)
                                                                            if (s.id === REVIEW_STATUS_IDS.corrected) {
                                                                                seedReviewTaxonForReviseFromAnnotation()
                                                                            }
                                                                        }}
                                                                    >
                                                                        {s.label}
                                                                    </ESButton>
                                                                ))}
                                                            </div>

                                                            <Form
                                                                layout="vertical"
                                                                requiredMark={false}
                                                                className="studio-review-form shared-drawer-form"
                                                            >
                                                                {reviewStatusRequiresTaxon(reviewStatusId) ? (
                                                                    <Form.Item
                                                                        label="Taxon"
                                                                        required
                                                                        validateStatus={reviewTaxonError ? "error" : undefined}
                                                                        help={reviewTaxonError ?? undefined}
                                                                        className="studio-annot-form-item"
                                                                    >
                                                                        <Select
                                                                            className="form-drawer-select"
                                                                            classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                                                            showSearch
                                                                            allowClear
                                                                            filterOption={false}
                                                                            loading={reviewTaxonOptionsState.loading}
                                                                            options={reviewTaxonSelectMergedOptions}
                                                                            value={reviewTaxonId ?? undefined}
                                                                            optionLabelProp="label"
                                                                            notFoundContent={
                                                                                reviewTaxonOptionsState.loading ? (
                                                                                    <LoadingState label="Loading taxa..." variant="inline" size="sm" showLabel={false} />
                                                                                ) : (
                                                                                    <div className="form-drawer-select-empty">
                                                                                        <NoDataIcon />
                                                                                        <span>
                                                                                            {reviewTaxonOptionsState.query
                                                                                                ? "No matching taxa"
                                                                                                : "Type a taxon name to search"}
                                                                                        </span>
                                                                                    </div>
                                                                                )
                                                                            }
                                                                            onSearch={(value) => {
                                                                                setReviewTaxonError(null)
                                                                                reviewTaxonOptionsState.search(value)
                                                                            }}
                                                                            onPopupScroll={(event) => {
                                                                                if (
                                                                                    isSelectScrollNearBottom(
                                                                                        event.currentTarget,
                                                                                    )
                                                                                ) {
                                                                                    reviewTaxonOptionsState.loadNext()
                                                                                }
                                                                            }}
                                                                            popupRender={(menu) => (
                                                                                <>
                                                                                    {menu}
                                                                                    {reviewTaxonOptionsState.loading ? (
                                                                                        <LoadingState
                                                                                            label="Loading taxa..."
                                                                                            variant="inline"
                                                                                            size="sm"
                                                                                            showLabel={false}
                                                                                        />
                                                                                    ) : null}
                                                                                </>
                                                                            )}
                                                                            onChange={(v, option) => {
                                                                                setReviewTaxonError(null)
                                                                                if (v == null || typeof v !== "number") {
                                                                                    setReviewTaxonId(null)
                                                                                    setReviewTaxonSearch("")
                                                                                    reviewTaxonOptionsState.setCurrentOption(null)
                                                                                    return
                                                                                }
                                                                                setReviewTaxonId(v)
                                                                                reviewTaxonOptionsState.setCurrentOption(
                                                                                    reviewTaxonOptionsState.options.find(
                                                                                        (item) => item.value === v,
                                                                                    ) ?? null,
                                                                                )
                                                                                const o = option as { label?: ReactNode } | undefined
                                                                                const lab =
                                                                                    typeof o?.label === "string"
                                                                                        ? o.label
                                                                                        : reviewTaxonSelectMergedOptions.find(
                                                                                            (x) => x.value === v,
                                                                                        )?.label ?? `Taxon ${v}`
                                                                                setReviewTaxonSearch(
                                                                                    typeof lab === "string"
                                                                                        ? lab
                                                                                        : `Taxon ${v}`,
                                                                                )
                                                                            }}
                                                                        />
                                                                    </Form.Item>
                                                                ) : null}

                                                                <Form.Item label="Note" className="studio-annot-form-item">
                                                                    <Input
                                                                        value={reviewNote}
                                                                        onChange={(e) => setReviewNote(e.target.value)}
                                                                    />
                                                                </Form.Item>

                                                                <div className="studio-annot-review-actions">
                                                                    <Button
                                                                        type="primary"
                                                                        loading={reviewSubmitPending}
                                                                        disabled={!canWriteReview}
                                                                        title={canWriteReview ? undefined : "You do not have permission to review annotations"}
                                                                        onClick={() => void handleReviewSubmit()}
                                                                    >
                                                                        {myAnnotationReviewRow ? "Update" : "Submit"}
                                                                    </Button>
                                                                </div>
                                                            </Form>
                                                        </div>
                                                    )}
                                            </div>
                                        </div>
                                    ) : null}
                                </div>
                            </ConfigProvider>
                        </div>
                    </div>
                ) : rightPanel === "assign-task" ? (
                    <ConfigProvider theme={antdAppTheme}>
                        <div className="studio-analysis-embed">
                            <div className="studio-analysis-embed-top">
                                <ESButton appearance="unstyled"
                                    type="button"
                                    className="header-back"
                                    title="Back"
                                    onClick={closeAssignTaskPanel}
                                >
                                    <ArrowLeft size={18} strokeWidth={2.25} />
                                </ESButton>
                                <span className="header-title studio-analysis-embed-heading">Assign Tasks</span>
                            </div>
                            <div className="studio-analysis-embed-body">
                                <CustomScrollArea variant="fill">
                                    <div style={{ padding: "12px 14px" }}>
                                        {assignableLoading ? (
                                            <LoadingState label="Loading users..." variant="inline" />
                                        ) : (
                                            <div
                                                className="assign-tasks-content"
                                                style={{
                                                    background: "var(--bg-surface-secondary)",
                                                    borderRadius: "8px",
                                                    border: "1px solid var(--border-color)",
                                                    overflow: "hidden",
                                                }}
                                            >
                                                <div className="assign-tasks-list">
                                                    {assignableUsers.length === 0 ? (
                                                        <div className="studio-assign-task-empty">
                                                            <NoDataIcon />
                                                            <span>No assignable users found.</span>
                                                        </div>
                                                    ) : (
                                                        assignableUsers.map((user, index) => {
                                                            const isChecked = assignSelectedUserIds.includes(
                                                                user.user_id,
                                                            )
                                                            return (
                                                                <div
                                                                    key={user.user_id}
                                                                    className="assign-tasks-item"
                                                                    style={{
                                                                        borderBottom:
                                                                            index < assignableUsers.length - 1
                                                                                ? "1px dashed var(--border-color)"
                                                                                : "none",
                                                                        background: isChecked
                                                                            ? isDark
                                                                                ? "var(--bg-capsule)"
                                                                                : "var(--bg-surface-secondary)"
                                                                            : "transparent",
                                                                    }}
                                                                >
                                                                    <Checkbox
                                                                        checked={isChecked}
                                                                        onChange={(e) =>
                                                                            toggleAssignUser(
                                                                                user.user_id,
                                                                                e.target.checked,
                                                                            )
                                                                        }
                                                                        style={{
                                                                            fontWeight: 500,
                                                                            color: isDark
                                                                                ? "var(--text-main)"
                                                                                : "var(--text-secondary)",
                                                                        }}
                                                                    >
                                                                        {user.name?.trim() || user.username}
                                                                    </Checkbox>
                                                                </div>
                                                            )
                                                        })
                                                    )}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </CustomScrollArea>
                            </div>
                            <div className="studio-analysis-embed-foot">
                                <div className="assign-tasks-footer">
                                    <Button
                                        onClick={closeAssignTaskPanel}
                                        disabled={assignSubmitPending}
                                        className="assign-tasks-btn-cancel"
                                    >
                                        Cancel
                                    </Button>
                                    <Button
                                        type="primary"
                                        loading={assignSubmitPending}
                                        disabled={
                                            assignableLoading ||
                                            assignSelectedUserIds.length === 0 ||
                                            selectedAnnotationKeys.length === 0
                                        }
                                        onClick={() => void submitAssignTask()}
                                        className="assign-tasks-btn-save"
                                        style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
                                    >
                                        Save
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </ConfigProvider>
                ) : rightPanel === "ai-models" && !isPhoto ? (
                    <ConfigProvider theme={antdAppTheme}>
	                        <RunAIModelsDrawer
	                            embedded
	                            open
	                            mediaId={mediaId}
	                            projectId={currentProjectId}
	                            selectionMode="single"
	                            waitForCompletion
	                            onProcessingChange={handleAnalysisProcessingChange}
	                            onClose={() => setRightPanel("info")}
                            onSuccess={() => setAnnotationListTick((n) => n + 1)}
                        />
                    </ConfigProvider>
                ) : rightPanel === "acoustic-indices" ? (
                    <ConfigProvider theme={antdAppTheme}>
                        <AcousticIndicesDrawer
                            embedded
                            open
                            mediaId={mediaId}
                            projectId={currentProjectId}
                            selectionMode="single"
                            selection={acousticIndexSelection}
                            channel={isMonoRecording ? "mono" : audioChannel === 2 ? "right" : "left"}
                            waitForCompletion
                            onProcessingChange={handleAnalysisProcessingChange}
                            onClose={() => setRightPanel("info")}
                            onSuccess={() => setAnnotationListTick((n) => n + 1)}
                        />
                    </ConfigProvider>
                ) : rightPanel === "acoustic-analysis" ? (
                    <ConfigProvider theme={antdAppTheme}>
                        <AcousticAnalysisStudioPanel
                            mediaId={mediaId}
                            projectId={currentProjectId}
                            selection={acousticIndexSelection}
                            isFullTimeWindow={acousticAnalysisIsFullTimeWindow}
                            channel={isMonoRecording ? "mono" : audioChannel === 2 ? "right" : "left"}
                            onProcessingChange={handleAnalysisProcessingChange}
                            onSuccess={() => setAnnotationListTick((n) => n + 1)}
                            onBack={() => setRightPanel("info")}
                        />
                    </ConfigProvider>
                ) : (
                    <>
                        <div className="studio-info-header studio-info-header--audio-info">
                            <div className="studio-info-header-title">
                                <span className="studio-info-header-icon" aria-hidden="true">
                                    <Info size={18} strokeWidth={2.25} />
                                </span>
                                <span>{isPhoto ? "Photo Info" : "Audio Info"}</span>
                            </div>
                            <div className="studio-info-header-actions">
                                {/* Audio Label - Popover：列表 + 新建（GET/PUT /v1/labels） */}
                                <ConfigProvider theme={antdAppTheme}>
                                    <Popover
                                        open={labelPopoverOpen}
                                        onOpenChange={onLabelPopoverOpenChange}
                                        trigger="click"
                                        placement="bottomRight"
                                        zIndex={12000}
                                        overlayClassName="studio-label-popover-overlay"
                                        content={
                                            <div
                                                className="studio-label-popover-inner"
                                                onClick={(e) => e.stopPropagation()}
                                            >
                                                {labelPopoverLoading ? (
                                                    <div className="studio-label-popover-spin">
                                                        <LoadingState label="Loading labels..." variant="inline" size="sm" showLabel={false} />
                                                    </div>
                                                ) : (
                                                    <>
                                                        <CustomScrollArea
                                                            className="studio-label-popover-list-scroll"
                                                            maxHeight={260}
                                                        >
                                                            <div
                                                                className="studio-label-popover-list"
                                                                role="listbox"
                                                                aria-label="Labels"
                                                            >
                                                                {labelPopoverList.length === 0 ? (
                                                                    <div className="studio-label-popover-empty">
                                                                        <NoDataIcon />
                                                                        <span>No labels</span>
                                                                    </div>
                                                                ) : (
                                                                    labelPopoverList.map((l) => {
                                                                        const canDelete =
                                                                            !!authUtils.getToken() &&
                                                                            !isLabelSystemProtected(l)
                                                                        const deletingThis =
                                                                            labelPopoverDeletingId === l.label_id
                                                                        const listBusy =
                                                                            labelPopoverSaving ||
                                                                            labelPopoverAdding ||
                                                                            labelPopoverDeletingId != null
                                                                        return (
                                                                            <div
                                                                                key={l.label_id}
                                                                                className="studio-label-popover-row"
                                                                            >
                                                                                <ESButton appearance="unstyled"
                                                                                    type="button"
                                                                                    role="option"
                                                                                    aria-selected={
                                                                                        labelPopoverSelectedId ===
                                                                                        l.label_id
                                                                                    }
                                                                                    className={`studio-label-popover-item${labelPopoverSelectedId ===
                                                                                        l.label_id
                                                                                        ? " selected"
                                                                                        : ""
                                                                                        }`}
                                                                                    disabled={labelPopoverSaving}
                                                                                    onClick={() =>
                                                                                        void applyLabelFromPopover(
                                                                                            l.label_id,
                                                                                        )
                                                                                    }
                                                                                >
                                                                                    {l.name}
                                                                                </ESButton>
                                                                                {labelPopoverSelectedId === l.label_id ? (
                                                                                    <ESButton
                                                                                        appearance="unstyled"
                                                                                        type="button"
                                                                                        className="studio-label-popover-remove-btn"
                                                                                        title="Remove label from this media"
                                                                                        aria-label={`Remove ${l.name} from this media`}
                                                                                        disabled={listBusy}
                                                                                        onClick={(e) => {
                                                                                            e.stopPropagation()
                                                                                            void applyLabelFromPopover(null)
                                                                                        }}
                                                                                    >
                                                                                        <X size={14} aria-hidden="true" />
                                                                                    </ESButton>
                                                                                ) : null}
                                                                                {canDelete ? (
                                                                                    <Popconfirm
                                                                                        title="Delete this label?"
                                                                                        description="Media items that used it may no longer show this tag."
                                                                                        okText="Delete"
                                                                                        cancelText="Cancel"
                                                                                        okButtonProps={{
                                                                                            danger: true,
                                                                                            loading: deletingThis,
                                                                                        }}
                                                                                        disabled={listBusy}
                                                                                        onConfirm={() =>
                                                                                            void handlePopoverDeleteLabel(
                                                                                                l.label_id,
                                                                                            )
                                                                                        }
                                                                                    >
                                                                                        <ESButton appearance="unstyled"
                                                                                            type="button"
                                                                                            className="studio-label-popover-delete-btn"
                                                                                            title="Delete label"
                                                                                            disabled={listBusy}
                                                                                            aria-label={`Delete ${l.name}`}
                                                                                            onClick={(e) =>
                                                                                                e.stopPropagation()
                                                                                            }
                                                                                        >
                                                                                            <Trash2 size={14} />
                                                                                        </ESButton>
                                                                                    </Popconfirm>
                                                                                ) : null}
                                                                            </div>
                                                                        )
                                                                    })
                                                                )}
                                                            </div>
                                                        </CustomScrollArea>
                                                        <Divider
                                                            style={{
                                                                margin: "12px 0",
                                                                borderColor: "var(--border-color)",
                                                            }}
                                                        />
                                                        {authUtils.getToken() && (
                                                            <div className="studio-label-popover-add-row">
                                                                <Input
                                                                    className="set-labels-input"
                                                                    value={labelPopoverNewName}
                                                                    onChange={(e) =>
                                                                        setLabelPopoverNewName(e.target.value)
                                                                    }
                                                                    onPressEnter={() => void handlePopoverAddLabel()}
                                                                />
                                                                <Button
                                                                    type="primary"
                                                                    className="set-labels-btn-add"
                                                                    loading={labelPopoverAdding}
                                                                    disabled={labelPopoverSaving}
                                                                    onClick={() => void handlePopoverAddLabel()}
                                                                >
                                                                    Add
                                                                </Button>
                                                            </div>
                                                        )}
                                                    </>
                                                )}
                                            </div>
                                        }
                                    >
                                        <ESButton appearance="unstyled"
                                            type="button"
                                            className={`btn-toolbar studio-label-tag${labelPopoverOpen ? " active" : ""}`}
                                            title="Media label"
                                        >
                                            <Tag size={14} />
                                            <span className="studio-label-text">{audioLabelPillText}</span>
                                        </ESButton>
                                    </Popover>
                                </ConfigProvider>
                            </div>
                        </div>

                        <div
                            className={`studio-minimap${isPhoto ? " studio-minimap--photo" : ""}`}
                            style={{
                                // Preview uses the current photo blob or the recording spectrogram.
                                backgroundImage: (isPhoto ? photoContentUrl : media.spectrogram)
                                    ? `url('${isPhoto ? photoContentUrl : media.spectrogram}')`
                                    : undefined,
                            }}
                        >
                            {!isPhoto ? <div
                                className="studio-minimap-viewport"
                                style={{
                                    left: `${clamp((specViewStart / Math.max(1e-6, totalDuration)) * 100, 0, 100)}%`,
                                    width: `${clamp((specWindowSec / Math.max(1e-6, totalDuration)) * 100, 0, 100)}%`,
                                    top: `${clamp(
                                        (1 - clamp(specFreqMaxHz, 0, Math.max(1e-6, nyquistHz)) / Math.max(1e-6, nyquistHz)) *
                                            100,
                                        0,
                                        100,
                                    )}%`,
                                    height: `${clamp(
                                        (clamp(specFreqMaxHz, 0, Math.max(1e-6, nyquistHz)) -
                                            clamp(specFreqMinHz, 0, Math.max(1e-6, nyquistHz))) /
                                            Math.max(1e-6, nyquistHz) *
                                            100,
                                        0,
                                        100,
                                    )}%`,
                                }}
                            /> : null}
                        </div>

                        <div className="studio-filename-block">
                            <div className="studio-filename-text">
                                {(typeof media.name === "string" && media.name) ||
                                    (typeof media.filename === "string" && media.filename) ||
                                    `Media ${mediaId}`}
                            </div>
                            {typeof media.uuid === "string" && media.uuid ? (
                                <div className="studio-uuid-text">{media.uuid}</div>
                            ) : null}
                        </div>

                        <div className="studio-badge-row">
                            {isPhoto && displayPhotoDimensions ? <span className="studio-badge">{displayPhotoDimensions}</span> : null}
                            {isPhoto && displaySize ? <span className="studio-badge">{displaySize}</span> : null}
                            {isPhoto && displayPhotoExposure ? <span className="studio-badge">{displayPhotoExposure}</span> : null}
                            {isPhoto && displayPhotoAperture ? <span className="studio-badge">{displayPhotoAperture}</span> : null}
                            {isPhoto && displayPhotoIso ? <span className="studio-badge">{displayPhotoIso}</span> : null}
                            {!isPhoto && displayDuration ? <span className="studio-badge">{displayDuration}</span> : null}
                            {!isPhoto && displaySize ? <span className="studio-badge">{displaySize}</span> : null}
                            {!isPhoto && displaySr ? <span className="studio-badge">{displaySr}</span> : null}
                            {!isPhoto && typeof media.bit_depth === "string" && media.bit_depth ? (
                                <span className="studio-badge">{media.bit_depth}-bit</span>
                            ) : null}
                            {displayGain ? <span className="studio-badge">{displayGain}</span> : null}
                        </div>

                        <div className="studio-info-scroll">
                            <div className="studio-kv-grid">
                                <span className="studio-kv-label">Date Time</span>
                                <span className="studio-kv-val">
                                    {displayDate && displayTime
                                        ? `${displayDate} ${displayTime}`
                                        : displayDate || displayTime || "-"}
                                </span>

                                <span className="studio-kv-label">Site</span>
                                <span className={`studio-kv-val${displaySite ? " studio-kv-brand" : ""}`}>
                                    {displaySite ? <MapPin size={12} style={{ flexShrink: 0 }} /> : null}
                                    {displaySite || "-"}
                                </span>

                                <span className="studio-kv-label">Sensor</span>
                                <span className="studio-kv-val">{media.sensor_name || "-"}</span>

                                <span className="studio-kv-label">Medium</span>
                                <span className="studio-kv-val">{media.medium || "-"}</span>

                                <div className="studio-kv-divider" />

                                <span className="studio-kv-label">Creator</span>
                                <span className="studio-kv-val">{media.creator_name || media.creator_id || "-"}</span>

                                <span className="studio-kv-label">Uploader</span>
                                <span className="studio-kv-val">{media.uploader_name || media.uploader_id || "-"}</span>

                                <span className="studio-kv-label">License</span>
                                <span className="studio-kv-val">{media.license_name || "-"}</span>

                                <span className="studio-kv-label">DOI</span>
                                <span className="studio-kv-val" style={{ wordBreak: "break-all" }}>{media.doi || "-"}</span>
                            </div>

                            {typeof media.note === "string" && media.note.trim() ? (
                                <div className="studio-note-block">
                                    <span className="studio-kv-label">Note</span>
                                    <div className="studio-note-text">{media.note}</div>
                                </div>
                            ) : null}
                        </div>

                        <div className="studio-info-footer">
                            {isPhoto ? (
                                <ESButton appearance="unstyled"
                                    type="button"
                                    className="btn-toolbar studio-download-btn"
                                    title="Download original photo"
                                    disabled={!photoContentUrl}
                                    onClick={handleDownloadOriginalPhoto}
                                >
                                    <Download size={14} /> Original Photo
                                </ESButton>
                            ) : (
                                <>
                                    <ESButton appearance="unstyled"
                                        type="button"
                                        className="btn-toolbar studio-download-btn"
                                        title="Download audio for current viewport"
                                        onClick={() => void handleDownloadViewportAudio()}
                                    >
                                        <Download size={14} /> Audio
                                    </ESButton>
                                    <ESButton appearance="unstyled"
                                        type="button"
                                        className="btn-toolbar studio-download-btn"
                                        title="Download spectrogram for current viewport"
                                        onClick={() => void handleDownloadViewportSpectrogram()}
                                    >
                                        <Download size={14} /> Spectrogram
                                    </ESButton>
                                </>
                            )}
                        </div>
                    </>
                )}
            </div>
            {!isPhoto && analysisBlocking ? (
                <div className="media-detail-analysis-blocker" role="status" aria-live="polite" aria-label="Analysis processing">
                    <LoadingState label="Processing analysis..." variant="overlay" size="lg" />
                </div>
            ) : null}
        </div>
        <ConfirmDialog
            open={deleteAnnotationsConfirmOpen}
            onClose={() => setDeleteAnnotationsConfirmOpen(false)}
            title="Delete Records"
            message={`Are you sure you want to delete ${selectedAnnotationKeys.length} selected record${selectedAnnotationKeys.length === 1 ? "" : "s"}? This action cannot be undone.`}
            confirmLabel="Delete"
            cancelLabel="Cancel"
            variant="danger"
            onConfirm={() => void handleDeleteSelectedAnnotations()}
        />
        <ConfirmDialog
            open={annotationExportConfirmOpen}
            onClose={() => {
                annotationExportActionRef.current = null
                setAnnotationExportConfirmOpen(false)
            }}
            title="Export Records"
            message={`Records to export: ${annotationExportConfirmCount.toLocaleString()}. Continue?`}
            confirmLabel="Export"
            cancelLabel="Cancel"
            onConfirm={() => {
                const action = annotationExportActionRef.current
                annotationExportActionRef.current = null
                void action?.()
            }}
        />
        <ConfirmDialog
            open={deleteEditingAnnotationConfirmOpen}
            onClose={() => setDeleteEditingAnnotationConfirmOpen(false)}
            title="Delete Annotation"
            message="Are you sure you want to delete this annotation? This action cannot be undone."
            confirmLabel="Delete"
            cancelLabel="Cancel"
            variant="danger"
            onConfirm={() => void handleDeleteEditingAnnotation()}
        />
        </>
    )
}
