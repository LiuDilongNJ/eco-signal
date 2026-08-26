import {
    Button as ESButton,
    Input as ESInput,
    LoadingState,
    message,
    UnifiedImage,
} from "@/components/ui"
import {
    useCallback,
    useEffect,
    useRef,
    useState,
    type CSSProperties,
    type PointerEvent as ReactPointerEvent,
    type ReactNode,
} from "react"
import {
    ChevronLeft,
    ChevronRight,
    ClipboardList,
    Eye,
    EyeOff,
    Move,
    Scan,
    Search,
    ZoomIn,
    ZoomOut,
} from "lucide-react"
import { mediaApi, type RecordingDetail } from "../../../../api/endpoints/media"
import type { AnnotationPublic } from "../../../../api/endpoints/annotations"
import { COOKIE_RETENTION_DAYS, isFunctionalCookiesAllowed } from "../../../home/cookieConsent"
import { MediaViewerToolbarButton } from "./MediaViewerToolbarButton"
import {
    getMediaAnnotationPresentation,
    mediaAnnotationClassName,
} from "./mediaAnnotationPresentation"

export type PhotoAnnotationBox = {
    min_x: number
    max_x: number
    min_y: number
    max_y: number
}

export type PhotoZoomRequest = {
    nonce: number
    box: PhotoAnnotationBox
}

type Point = { x: number; y: number }
type DraftResizeHandle = "n" | "s" | "e" | "w" | "nw" | "ne" | "sw" | "se"
type DraftInteraction =
    | { kind: "move"; pointerId: number; startClient: Point; startBox: PhotoAnnotationBox }
    | {
        kind: "resize"
        pointerId: number
        handle: DraftResizeHandle
        startClient: Point
        startBox: PhotoAnnotationBox
    }
type PendingDraw = {
    pointerId: number
    startClient: Point
    startImage: Point
    replaceExistingDraft: boolean
}

type PhotoImageViewerProps = {
    mediaId: number
    projectId: number
    media: RecordingDetail
    annotations: AnnotationPublic[]
    annotationsVisible: boolean
    linkedAnnotationId: number | null
    editingAnnotationId: number | null
    draft: PhotoAnnotationBox | null
    draftVisible: boolean
    userAnnotationColor: string
    currentUserId: number | null
    onAnnotationsVisibleChange: (visible: boolean) => void
    onDraftStart: () => void
    onDraftChange: (draft: PhotoAnnotationBox) => void
    onDraftCancel: () => void
    onOpenAnnotation: (annotationId: number) => void
    onLinkedAnnotationChange: (annotationId: number | null) => void
    onContentReady?: (url: string | null) => void
    toolbarActions?: ReactNode
    canNavigateAnnotation?: boolean
    navAutoZoomToAnnotation?: boolean
    navOnlyTaskTagged?: boolean
    onPreviousAnnotation?: () => void
    onNextAnnotation?: () => void
    onToggleNavAutoZoomToAnnotation?: () => void
    onToggleNavOnlyTaskTagged?: () => void
    zoomRequest?: PhotoZoomRequest | null
}

const MIN_SCALE = 0.1
const MAX_SCALE = 8
const PHOTO_DRAFT_MIN_DRAG_PX = 12
const PHOTO_ZOOM_DRAFT_IN_COOKIE_KEY = "ecoSignal_photo_zoom_percent_draft_in"
const PHOTO_ZOOM_DRAFT_OUT_COOKIE_KEY = "ecoSignal_photo_zoom_percent_draft_out"
const DRAFT_RESIZE_HANDLES: DraftResizeHandle[] = ["nw", "n", "ne", "w", "e", "sw", "s", "se"]

function getCookieValue(name: string): string | null {
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

function setCookieValue(name: string, value: string, days = COOKIE_RETENTION_DAYS): void {
    if (typeof document === "undefined") return
    if (!isFunctionalCookiesAllowed()) return
    const d = new Date()
    d.setTime(d.getTime() + days * 24 * 60 * 60 * 1000)
    document.cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; expires=${d.toUTCString()}; path=/; samesite=lax`
}

function parsePhotoZoomDraft(raw: string | null): string {
    const n = raw != null ? Number(raw) : NaN
    return Number.isFinite(n) ? String(clamp(Math.round(n), 0, 100)) : "50"
}

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value))
}

function normalizeBox(box: PhotoAnnotationBox): PhotoAnnotationBox {
    return {
        min_x: Math.min(box.min_x, box.max_x),
        max_x: Math.max(box.min_x, box.max_x),
        min_y: Math.min(box.min_y, box.max_y),
        max_y: Math.max(box.min_y, box.max_y),
    }
}

function roundBox(box: PhotoAnnotationBox): PhotoAnnotationBox {
    const normalized = normalizeBox(box)
    return {
        min_x: Math.round(normalized.min_x),
        max_x: Math.round(normalized.max_x),
        min_y: Math.round(normalized.min_y),
        max_y: Math.round(normalized.max_y),
    }
}

function clampBoxToImage(
    box: PhotoAnnotationBox,
    imageWidth: number,
    imageHeight: number,
): PhotoAnnotationBox {
    const normalized = normalizeBox(box)
    return {
        min_x: clamp(normalized.min_x, 0, imageWidth),
        max_x: clamp(normalized.max_x, 0, imageWidth),
        min_y: clamp(normalized.min_y, 0, imageHeight),
        max_y: clamp(normalized.max_y, 0, imageHeight),
    }
}

function annotationTitle(annotation: AnnotationPublic, label: string): string {
    const box = normalizeBox(annotation)
    return `ID ${annotation.annotation_id} · ${label} · Min X ${box.min_x}px · Max X ${box.max_x}px · Min Y ${box.min_y}px · Max Y ${box.max_y}px`
}

function moveBox(
    startBox: PhotoAnnotationBox,
    dx: number,
    dy: number,
    imageWidth: number,
    imageHeight: number,
): PhotoAnnotationBox {
    const box = normalizeBox(startBox)
    const width = box.max_x - box.min_x
    const height = box.max_y - box.min_y
    const minX = clamp(box.min_x + dx, 0, Math.max(0, imageWidth - width))
    const minY = clamp(box.min_y + dy, 0, Math.max(0, imageHeight - height))
    return { min_x: minX, max_x: minX + width, min_y: minY, max_y: minY + height }
}

function resizeBox(
    startBox: PhotoAnnotationBox,
    handle: DraftResizeHandle,
    dx: number,
    dy: number,
    imageWidth: number,
    imageHeight: number,
    minWidth: number,
    minHeight: number,
): PhotoAnnotationBox {
    const box = normalizeBox(startBox)
    let { min_x: minX, max_x: maxX, min_y: minY, max_y: maxY } = box

    if (handle.includes("w")) minX = clamp(box.min_x + dx, 0, box.max_x - minWidth)
    if (handle.includes("e")) maxX = clamp(box.max_x + dx, box.min_x + minWidth, imageWidth)
    if (handle.includes("n")) minY = clamp(box.min_y + dy, 0, box.max_y - minHeight)
    if (handle.includes("s")) maxY = clamp(box.max_y + dy, box.min_y + minHeight, imageHeight)

    return { min_x: minX, max_x: maxX, min_y: minY, max_y: maxY }
}

export function PhotoImageViewer({
    mediaId,
    projectId,
    media,
    annotations,
    annotationsVisible,
    linkedAnnotationId,
    editingAnnotationId,
    draft,
    draftVisible,
    userAnnotationColor,
    currentUserId,
    onAnnotationsVisibleChange,
    onDraftStart,
    onDraftChange,
    onDraftCancel,
    onOpenAnnotation,
    onLinkedAnnotationChange,
    onContentReady,
    toolbarActions,
    canNavigateAnnotation,
    navAutoZoomToAnnotation,
    navOnlyTaskTagged,
    onPreviousAnnotation,
    onNextAnnotation,
    onToggleNavAutoZoomToAnnotation,
    onToggleNavOnlyTaskTagged,
    zoomRequest,
}: PhotoImageViewerProps) {
    const stageRef = useRef<HTMLDivElement>(null)
    const imageRef = useRef<HTMLImageElement>(null)
    const pendingDrawRef = useRef<PendingDraw | null>(null)
    const drawStartRef = useRef<Point | null>(null)
    const drawingDraftRef = useRef<PhotoAnnotationBox | null>(null)
    const draftInteractionRef = useRef<DraftInteraction | null>(null)
    const interactionDraftRef = useRef<PhotoAnnotationBox | null>(null)
    const suppressAnnotationClickRef = useRef(false)
    const panStartRef = useRef<{ clientX: number; clientY: number; offsetX: number; offsetY: number } | null>(null)
    const objectUrlRef = useRef<string | null>(null)
    const [imageUrl, setImageUrl] = useState<string | null>(null)
    const [imageSize, setImageSize] = useState({
        width: Number(media.image_width) || 0,
        height: Number(media.image_height) || 0,
    })
    const [loading, setLoading] = useState(true)
    const [scale, setScale] = useState(1)
    const [scaleY, setScaleY] = useState(1)
    const [photoZoomDraftIn, setPhotoZoomDraftIn] = useState(() =>
        parsePhotoZoomDraft(getCookieValue(PHOTO_ZOOM_DRAFT_IN_COOKIE_KEY)),
    )
    const [photoZoomDraftOut, setPhotoZoomDraftOut] = useState(() =>
        parsePhotoZoomDraft(getCookieValue(PHOTO_ZOOM_DRAFT_OUT_COOKIE_KEY)),
    )
    const [offset, setOffset] = useState({ x: 0, y: 0 })
    const scaleRef = useRef(1)
    const scaleYRef = useRef(1)
    const offsetRef = useRef({ x: 0, y: 0 })
    const [interactionDraft, setInteractionDraft] = useState<PhotoAnnotationBox | null>(null)

    const applyViewportState = useCallback((next: { scale: number; scaleY?: number; offset: Point }) => {
        const nextScaleY = next.scaleY ?? next.scale
        scaleRef.current = next.scale
        scaleYRef.current = nextScaleY
        offsetRef.current = next.offset
        setScale(next.scale)
        setScaleY(nextScaleY)
        setOffset(next.offset)
    }, [])

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        void mediaApi.getMediaContent(mediaId, projectId)
            .then(({ blob }) => {
                if (cancelled) return
                const next = URL.createObjectURL(blob)
                const previous = objectUrlRef.current
                objectUrlRef.current = next
                setImageUrl(next)
                onContentReady?.(next)
                if (previous) URL.revokeObjectURL(previous)
            })
            .catch((error: unknown) => {
                if (!cancelled) {
                    message.error(error instanceof Error ? error.message : "Unable to load photo")
                }
            })
            .finally(() => {
                if (!cancelled) setLoading(false)
            })
        return () => {
            cancelled = true
            const current = objectUrlRef.current
            objectUrlRef.current = null
            onContentReady?.(null)
            if (current) URL.revokeObjectURL(current)
        }
    }, [mediaId, onContentReady, projectId])

    const fitToViewport = useCallback(() => {
        const stage = stageRef.current
        if (!stage || imageSize.width <= 0 || imageSize.height <= 0) return
        const availableWidth = Math.max(1, stage.clientWidth - 48)
        const availableHeight = Math.max(1, stage.clientHeight - 48)
        const nextScale = clamp(Math.min(availableWidth / imageSize.width, availableHeight / imageSize.height), MIN_SCALE, 1)
        applyViewportState({
            scale: nextScale,
            offset: {
                x: (stage.clientWidth - imageSize.width * nextScale) / 2,
                y: (stage.clientHeight - imageSize.height * nextScale) / 2,
            },
        })
    }, [applyViewportState, imageSize.height, imageSize.width])

    const applyUniformScaleMultiplier = useCallback((multiplier: number) => {
        const stage = stageRef.current
        if (!stage || !(multiplier > 0)) return
        const rect = stage.getBoundingClientRect()
        const centerX = rect.width / 2
        const centerY = rect.height / 2
        const currentScale = scaleRef.current
        const currentScaleY = scaleYRef.current
        const currentOffset = offsetRef.current
        const nextScale = clamp(currentScale * multiplier, MIN_SCALE, MAX_SCALE)
        const nextScaleY = clamp(currentScaleY * multiplier, MIN_SCALE, MAX_SCALE)
        const imageCenterX = (centerX - currentOffset.x) / Math.max(currentScale, 1e-6)
        const imageCenterY = (centerY - currentOffset.y) / Math.max(currentScaleY, 1e-6)
        applyViewportState({
            scale: nextScale,
            scaleY: nextScaleY,
            offset: {
                x: centerX - imageCenterX * nextScale,
                y: centerY - imageCenterY * nextScaleY,
            },
        })
    }, [applyViewportState])

    const applyPhotoZoomByPercent = useCallback((pctRaw: string, dir: "in" | "out") => {
        const pct = Number(pctRaw)
        if (!Number.isFinite(pct)) return
        const p = clamp(pct, 0, 100) / 100
        if (p <= 0) return
        applyUniformScaleMultiplier(dir === "in" ? 1 + p : 1 - p)
    }, [applyUniformScaleMultiplier])

    const zoomToBox = useCallback((box: PhotoAnnotationBox | null) => {
        const stage = stageRef.current
        if (!stage || !box || imageSize.width <= 0 || imageSize.height <= 0) return
        const normalized = clampBoxToImage(box, imageSize.width, imageSize.height)
        const boxWidth = Math.max(1, normalized.max_x - normalized.min_x)
        const boxHeight = Math.max(1, normalized.max_y - normalized.min_y)
        const availableWidth = Math.max(1, stage.clientWidth)
        const availableHeight = Math.max(1, stage.clientHeight)
        const nextScale = clamp(Math.min(availableWidth / boxWidth, availableHeight / boxHeight), MIN_SCALE, MAX_SCALE)
        applyViewportState({
            scale: nextScale,
            offset: {
                x: -normalized.min_x * nextScale + (availableWidth - boxWidth * nextScale) / 2,
                y: -normalized.min_y * nextScale + (availableHeight - boxHeight * nextScale) / 2,
            },
        })
    }, [applyViewportState, imageSize.height, imageSize.width])

    const activeBox = draft ?? annotations.find((annotation) => annotation.annotation_id === editingAnnotationId) ?? null

    useEffect(() => {
        if (!zoomRequest) return
        zoomToBox(zoomRequest.box)
    }, [zoomRequest, zoomToBox])

    useEffect(() => {
        fitToViewport()
    }, [fitToViewport])

    useEffect(() => {
        const stage = stageRef.current
        if (!stage) return
        const observer = new ResizeObserver(() => {
            fitToViewport()
        })
        observer.observe(stage)
        return () => observer.disconnect()
    }, [fitToViewport])

    useEffect(() => {
        const stage = stageRef.current
        if (!stage) return
        const onWheel = (event: WheelEvent) => {
            if (!event.shiftKey) return
            const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX
            if (delta === 0) return
            event.preventDefault()
            applyUniformScaleMultiplier(delta < 0 ? 1.12 : 1 / 1.12)
        }
        stage.addEventListener("wheel", onWheel, { passive: false })
        return () => stage.removeEventListener("wheel", onWheel)
    }, [applyUniformScaleMultiplier])

    const imagePoint = useCallback((event: ReactPointerEvent): Point | null => {
        const image = imageRef.current
        if (!image || imageSize.width <= 0 || imageSize.height <= 0) return null
        const bounds = image.getBoundingClientRect()
        if (bounds.width <= 0 || bounds.height <= 0) return null
        return {
            x: clamp(((event.clientX - bounds.left) / bounds.width) * imageSize.width, 0, imageSize.width),
            y: clamp(((event.clientY - bounds.top) / bounds.height) * imageSize.height, 0, imageSize.height),
        }
    }, [imageSize.height, imageSize.width])

    const clientDeltaToImage = useCallback((dx: number, dy: number): Point => {
        const bounds = imageRef.current?.getBoundingClientRect()
        if (!bounds || bounds.width <= 0 || bounds.height <= 0) return { x: 0, y: 0 }
        return {
            x: (dx / bounds.width) * imageSize.width,
            y: (dy / bounds.height) * imageSize.height,
        }
    }, [imageSize.height, imageSize.width])

    const commitInteractionDraft = useCallback((box: PhotoAnnotationBox | null) => {
        if (!box) return
        interactionDraftRef.current = null
        setInteractionDraft(null)
        onDraftChange(roundBox(clampBoxToImage(box, imageSize.width, imageSize.height)))
    }, [imageSize.height, imageSize.width, onDraftChange])

    const startPointerInteraction = (event: ReactPointerEvent<HTMLDivElement>) => {
        if (event.button === 1 || event.shiftKey) {
            panStartRef.current = {
                clientX: event.clientX,
                clientY: event.clientY,
                offsetX: offset.x,
                offsetY: offset.y,
            }
            event.currentTarget.setPointerCapture(event.pointerId)
            event.preventDefault()
            return
        }
        if (event.button !== 0) return
        const point = imagePoint(event)
        if (!point) return
        const replaceExistingDraft = Boolean(draftVisible && draft && editingAnnotationId == null)
        suppressAnnotationClickRef.current = false
        pendingDrawRef.current = {
            pointerId: event.pointerId,
            startClient: { x: event.clientX, y: event.clientY },
            startImage: point,
            replaceExistingDraft,
        }
        event.currentTarget.setPointerCapture(event.pointerId)
        event.preventDefault()
    }

    const updatePointerInteraction = (event: ReactPointerEvent<HTMLDivElement>) => {
        const panStart = panStartRef.current
        if (panStart) {
            const nextOffset = {
                x: panStart.offsetX + event.clientX - panStart.clientX,
                y: panStart.offsetY + event.clientY - panStart.clientY,
            }
            offsetRef.current = nextOffset
            setOffset(nextOffset)
            return
        }
        const pendingDraw = pendingDrawRef.current
        if (
            pendingDraw &&
            pendingDraw.pointerId === event.pointerId &&
            drawStartRef.current == null
        ) {
            const dx = Math.abs(event.clientX - pendingDraw.startClient.x)
            const dy = Math.abs(event.clientY - pendingDraw.startClient.y)
            if (dx < PHOTO_DRAFT_MIN_DRAG_PX || dy < PHOTO_DRAFT_MIN_DRAG_PX) return
            onDraftStart()
            drawStartRef.current = pendingDraw.startImage
            const initialDraft = {
                min_x: pendingDraw.startImage.x,
                max_x: pendingDraw.startImage.x,
                min_y: pendingDraw.startImage.y,
                max_y: pendingDraw.startImage.y,
            }
            drawingDraftRef.current = initialDraft
            interactionDraftRef.current = initialDraft
            setInteractionDraft(initialDraft)
            suppressAnnotationClickRef.current = true
            event.currentTarget.setPointerCapture(event.pointerId)
        }
        const start = drawStartRef.current
        const point = imagePoint(event)
        if (!start || !point) return
        const nextDraft = normalizeBox({
            min_x: start.x,
            max_x: point.x,
            min_y: start.y,
            max_y: point.y,
        })
        drawingDraftRef.current = nextDraft
        interactionDraftRef.current = nextDraft
        setInteractionDraft(nextDraft)
        onDraftChange(roundBox(nextDraft))
        event.preventDefault()
    }

    const finishPointerInteraction = (event: ReactPointerEvent<HTMLDivElement>) => {
        const pendingDraw = pendingDrawRef.current
        const shouldCancelExistingDraft =
            pendingDraw?.pointerId === event.pointerId &&
            pendingDraw.replaceExistingDraft &&
            drawStartRef.current == null
        pendingDrawRef.current = null
        drawStartRef.current = null
        panStartRef.current = null
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId)
        }
        const completedDraft = drawingDraftRef.current
        drawingDraftRef.current = null
        if (shouldCancelExistingDraft) {
            onDraftCancel()
            interactionDraftRef.current = null
            setInteractionDraft(null)
            return
        }
        if (completedDraft) {
            commitInteractionDraft(completedDraft)
        }
    }

    const startDraftInteraction = (
        event: ReactPointerEvent<HTMLElement>,
        handle?: DraftResizeHandle,
    ) => {
        if (event.button !== 0 || !draft) return
        event.preventDefault()
        event.stopPropagation()
        const interaction: DraftInteraction = handle
            ? {
                kind: "resize",
                pointerId: event.pointerId,
                handle,
                startClient: { x: event.clientX, y: event.clientY },
                startBox: normalizeBox(draft),
            }
            : {
                kind: "move",
                pointerId: event.pointerId,
                startClient: { x: event.clientX, y: event.clientY },
                startBox: normalizeBox(draft),
            }
        draftInteractionRef.current = interaction
        interactionDraftRef.current = interaction.startBox
        setInteractionDraft(interaction.startBox)
        event.currentTarget.setPointerCapture(event.pointerId)
    }

    const updateDraftInteraction = (event: ReactPointerEvent<HTMLElement>) => {
        const interaction = draftInteractionRef.current
        if (!interaction || interaction.pointerId !== event.pointerId) return
        event.preventDefault()
        event.stopPropagation()
        const delta = clientDeltaToImage(
            event.clientX - interaction.startClient.x,
            event.clientY - interaction.startClient.y,
        )
        const next =
            interaction.kind === "move"
                ? moveBox(interaction.startBox, delta.x, delta.y, imageSize.width, imageSize.height)
                : resizeBox(
                    interaction.startBox,
                    interaction.handle,
                    delta.x,
                    delta.y,
                    imageSize.width,
                    imageSize.height,
                    0,
                    0,
                )
        interactionDraftRef.current = next
        setInteractionDraft(next)
        onDraftChange(roundBox(clampBoxToImage(next, imageSize.width, imageSize.height)))
    }

    const finishDraftInteraction = (event: ReactPointerEvent<HTMLElement>) => {
        const interaction = draftInteractionRef.current
        if (!interaction || interaction.pointerId !== event.pointerId) return
        event.preventDefault()
        event.stopPropagation()
        draftInteractionRef.current = null
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId)
        }
        commitInteractionDraft(interactionDraftRef.current ?? interaction.startBox)
    }

    const visibleDraft = drawStartRef.current
        ? interactionDraft
        : draftVisible && editingAnnotationId == null
            ? interactionDraft ?? draft
            : null
    const overlayStyle = {
        "--media-overlay-scale": String(Math.max(scale, scaleY)),
    } as CSSProperties

    return (
        <div className="player-section photo-player-section">
            <div className="player-toolbar-top">
                <MediaViewerToolbarButton
                    active={annotationsVisible}
                    label={annotationsVisible ? "Hide Annotations" : "Show Annotations"}
                    icon={annotationsVisible ? <Eye size={14} /> : <EyeOff size={14} />}
                    onClick={() => onAnnotationsVisibleChange(!annotationsVisible)}
                />
                <span className="toolbar-divider" />
                <div className="zoom-control-wrapper">
                    <MediaViewerToolbarButton
                        variant="zoom"
                        label="Zoom In (Shift + wheel)"
                        icon={<ZoomIn size={14} />}
                        onClick={() => applyPhotoZoomByPercent(photoZoomDraftIn, "in")}
                    />
                    <ESInput appearance="unstyled"
                        type="number"
                        min={0}
                        max={100}
                        step={10}
                        aria-label="Photo zoom percentage"
                        value={photoZoomDraftIn}
                        onChange={(event) => {
                            const v = event.target.value
                            setPhotoZoomDraftIn(v)
                            setCookieValue(PHOTO_ZOOM_DRAFT_IN_COOKIE_KEY, v)
                        }}
                    />
                    <span>%</span>
                </div>
                <div className="zoom-control-wrapper">
                    <MediaViewerToolbarButton
                        variant="zoom"
                        label="Zoom Out (Shift + wheel)"
                        icon={<ZoomOut size={14} />}
                        onClick={() => applyPhotoZoomByPercent(photoZoomDraftOut, "out")}
                    />
                    <ESInput appearance="unstyled"
                        type="number"
                        min={0}
                        max={100}
                        step={10}
                        aria-label="Photo zoom percentage"
                        value={photoZoomDraftOut}
                        onChange={(event) => {
                            const v = event.target.value
                            setPhotoZoomDraftOut(v)
                            setCookieValue(PHOTO_ZOOM_DRAFT_OUT_COOKIE_KEY, v)
                        }}
                    />
                    <span>%</span>
                </div>
                <div style={{ flex: 1 }} />
                {toolbarActions}
            </div>

            <div className="player-middle photo-player-middle">
                <div
                    ref={stageRef}
                    className="photo-image-stage"
                    onPointerDown={startPointerInteraction}
                    onPointerMove={updatePointerInteraction}
                    onPointerUp={finishPointerInteraction}
                    onPointerCancel={finishPointerInteraction}
                    >
                    {loading ? <LoadingState label="Loading photo..." variant="overlay" size="lg" /> : null}
                    {imageUrl ? (
                        <>
                            <div
                                className="photo-image-transform"
                                style={{
                                    width: imageSize.width,
                                    height: imageSize.height,
                                    transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale}, ${scaleY})`,
                                    ...overlayStyle,
                                }}
                            >
                            <UnifiedImage
                                ref={imageRef}
                                src={imageUrl}
                                alt={media.name || media.filename || "Photo"}
                                width={imageSize.width || undefined}
                                height={imageSize.height || undefined}
                                draggable={false}
                                onLoad={(event) => {
                                    setImageSize({
                                        width: event.currentTarget.naturalWidth,
                                        height: event.currentTarget.naturalHeight,
                                    })
                                }}
                                onError={() => {
                                    if (imageSize.width > 0 && imageSize.height > 0) return
                                    const stage = stageRef.current
                                    setImageSize({
                                        width: Math.max(1, stage?.clientWidth ?? 1),
                                        height: Math.max(1, stage?.clientHeight ?? 1),
                                    })
                                }}
                            />
                            </div>
                            <div
                                className="photo-annotation-layer"
                                style={{
                                    left: offset.x,
                                    top: offset.y,
                                    width: imageSize.width * scale,
                                    height: imageSize.height * scaleY,
                                    "--media-overlay-scale": "1",
                                } as CSSProperties}
                            >
                            {annotationsVisible
                                ? annotations.map((annotation) => {
                                    const linked =
                                        linkedAnnotationId === annotation.annotation_id ||
                                        editingAnnotationId === annotation.annotation_id
                                    const presentation = getMediaAnnotationPresentation(
                                        annotation,
                                        userAnnotationColor,
                                        currentUserId,
                                    )
                                    const box = clampBoxToImage(annotation, imageSize.width, imageSize.height)
                                    return (
                                        <div
                                            key={annotation.annotation_id}
                                            className={mediaAnnotationClassName(presentation, linked)}
                                            title={annotationTitle(annotation, presentation.label)}
                                            role="button"
                                            tabIndex={0}
                                            onClick={(event) => {
                                                event.stopPropagation()
                                                if (suppressAnnotationClickRef.current) {
                                                    suppressAnnotationClickRef.current = false
                                                    return
                                                }
                                                onOpenAnnotation(annotation.annotation_id)
                                            }}
                                            onPointerDown={(event) => event.stopPropagation()}
                                            onKeyDown={(event) => {
                                                if (event.key !== "Enter" && event.key !== " ") return
                                                event.preventDefault()
                                                event.stopPropagation()
                                                onOpenAnnotation(annotation.annotation_id)
                                            }}
                                            onPointerEnter={() => onLinkedAnnotationChange(annotation.annotation_id)}
                                            onPointerLeave={() => onLinkedAnnotationChange(null)}
                                            style={{
                                                left: box.min_x * scale,
                                                top: box.min_y * scaleY,
                                                width: (box.max_x - box.min_x) * scale,
                                                height: (box.max_y - box.min_y) * scaleY,
                                                background: "transparent",
                                                borderColor: linked ? undefined : presentation.creatorColor,
                                                "--annot-frame-color": linked
                                                    ? "var(--brand)"
                                                    : presentation.creatorColor,
                                            } as CSSProperties}
                                        />
                                    )
                                })
                                : null}
                            {visibleDraft ? (() => {
                                const box = clampBoxToImage(visibleDraft, imageSize.width, imageSize.height)
                                return (
                                    <div
                                        className="media-selection-box"
                                        style={{
                                            left: box.min_x * scale,
                                            top: box.min_y * scaleY,
                                            width: (box.max_x - box.min_x) * scale,
                                            height: (box.max_y - box.min_y) * scaleY,
                                            borderColor: userAnnotationColor,
                                            pointerEvents: drawStartRef.current ? "none" : "auto",
                                            cursor: drawStartRef.current ? "crosshair" : "move",
                                        }}
                                        onPointerDown={(event) => startDraftInteraction(event)}
                                        onPointerMove={updateDraftInteraction}
                                        onPointerUp={finishDraftInteraction}
                                        onPointerCancel={finishDraftInteraction}
                                    >
                                        {drawStartRef.current == null
                                            ? DRAFT_RESIZE_HANDLES.map((handle) => (
                                                <span
                                                    key={handle}
                                                    className={`media-selection-handle media-selection-handle--${handle}`}
                                                    style={{ background: userAnnotationColor }}
                                                    onPointerDown={(event) =>
                                                        startDraftInteraction(event, handle)
                                                    }
                                                    onPointerMove={updateDraftInteraction}
                                                    onPointerUp={finishDraftInteraction}
                                                    onPointerCancel={finishDraftInteraction}
                                                />
                                            ))
                                            : null}
                                    </div>
                                )
                            })() : null}
                            </div>
                        </>
                    ) : !loading ? (
                        <UnifiedImage
                            className="photo-image-missing"
                            src=""
                            alt={media.name || media.filename || "Photo"}
                        />
                    ) : null}
                </div>
                <div
                    className="spectrogram-annot-side-toolbar"
                    role="toolbar"
                    aria-label="Annotation tools"
                >
                    <ESButton appearance="unstyled"
                        type="button"
                        className="btn-toolbar"
                        style={{ padding: 8, justifyContent: "center" }}
                        title="Reset photo view"
                        aria-label="Reset photo view"
                        onClick={fitToViewport}
                    >
                        <Move size={20} strokeWidth={2} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="btn-toolbar"
                        style={{ padding: 8, justifyContent: "center" }}
                        title={activeBox ? "Zoom the photo to this annotation" : "Zoom the photo to the selection"}
                        disabled={!activeBox}
                        onClick={() => zoomToBox(activeBox)}
                    >
                        <Scan size={20} strokeWidth={2} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="btn-toolbar"
                        style={{ padding: 8, justifyContent: "center" }}
                        title="Previous annotation"
                        disabled={!canNavigateAnnotation}
                        onClick={onPreviousAnnotation}
                    >
                        <ChevronLeft size={22} strokeWidth={2} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="btn-toolbar"
                        style={{ padding: 8, justifyContent: "center" }}
                        title="Next annotation"
                        disabled={!canNavigateAnnotation}
                        onClick={onNextAnnotation}
                    >
                        <ChevronRight size={22} strokeWidth={2} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`btn-toolbar${navAutoZoomToAnnotation ? " active" : ""}`}
                        style={{ padding: 8, justifyContent: "center" }}
                        title={
                            navAutoZoomToAnnotation
                                ? "On: Previous/Next also zooms the viewer to each annotation. Click to jump only."
                                : "Off: Previous/Next only switches the annotation. Click to also auto-zoom the viewer."
                        }
                        aria-pressed={navAutoZoomToAnnotation}
                        onClick={onToggleNavAutoZoomToAnnotation}
                    >
                        <Search size={20} strokeWidth={2} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`btn-toolbar${navOnlyTaskTagged ? " active" : ""}`}
                        style={{ padding: 8, justifyContent: "center" }}
                        title="When on: Previous/Next only among annotations that show the Task pill."
                        aria-pressed={navOnlyTaskTagged}
                        onClick={onToggleNavOnlyTaskTagged}
                    >
                        <ClipboardList size={20} strokeWidth={2} />
                    </ESButton>
                </div>
            </div>

            <div className="player-toolbar-bottom photo-player-toolbar-bottom">
                <div style={{ flex: 1 }} />
                <span className="photo-viewer-help">
                    Shift + drag or middle-button drag to pan · click and drag to draw an annotation box ·
                </span>
                <span>
                    {Math.round(scale * 100)}
                    {Math.abs(scaleY - scale) > 0.001 ? `/${Math.round(scaleY * 100)}` : ""}%
                </span>
            </div>
        </div>
    )
}
