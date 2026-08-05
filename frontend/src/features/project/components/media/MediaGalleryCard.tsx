/**
 * 与 MediaTab Gallery 视图一致的媒体卡片；Map 侧栏 Recordings 等复用。
 */

import { Calendar, Clock, FileAudio, HardDrive, Image as ImageIcon, Play, Timer } from "lucide-react"
import { Link } from "react-router-dom"
import type { MediaPublic } from "../../../../api/endpoints/media"

import { UnifiedImage } from "@/components/ui"
import { getRealmAccentVars, getRealmTagPillStyle } from "../../sphereTheme"
import { useMediaSpectrogramUrl } from "./useMediaSpectrogramUrl"

/** 仅在非 Metadata 时进入详情 */
export function resolveMediaDetailTo(item: MediaPublic, projectId: number | string): string | undefined {
    if (isGalleryMetadataItem(item)) return undefined
    const mid = resolveMediaNumericId(item)
    return mid != null ? `/dashboard/${projectId}/media/${mid}` : undefined
}

export function resolveMediaNumericId(item: MediaPublic): number | null {
    const raw = item.id ?? (item as Record<string, unknown>).media_id
    if (raw === undefined || raw === null) return null
    const n = typeof raw === "number" ? raw : Number(String(raw).trim())
    return Number.isFinite(n) ? n : null
}

export function formatDuration(seconds: number | undefined | null): string | undefined {
    if (typeof seconds !== "number") return undefined
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    if (h > 0) {
        return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
    }
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
}

export function safeArray(val: unknown, splitChar = ","): string[] {
    if (Array.isArray(val)) return val.map(String)
    if (typeof val === "string") return val.split(splitChar).map((x) => x.trim()).filter(Boolean)
    return []
}

function labelNameFromValue(value: unknown): string | null {
    if (value === null || value === undefined) return null
    if (typeof value === "string") {
        const s = value.trim()
        return s || null
    }
    if (typeof value === "number" || typeof value === "boolean") {
        return String(value)
    }
    if (typeof value !== "object") return null

    const record = value as Record<string, unknown>
    const candidates = [
        record.name,
        record.label,
        record.label_name,
        record.title,
        record.value,
    ]
    for (const candidate of candidates) {
        const name = labelNameFromValue(candidate)
        if (name) return name
    }
    return null
}

export function getMediaLabelNames(item: MediaPublic): string[] {
    const record = item as Record<string, unknown>
    const direct = labelNameFromValue(record.label)
    if (direct) return [direct]

    const listCandidates = [
        record.labels,
        record.label_names,
        record.label_list,
        record.label_values,
    ]
    for (const candidate of listCandidates) {
        if (Array.isArray(candidate)) {
            const names = candidate
                .map(labelNameFromValue)
                .filter((name): name is string => Boolean(name))
            if (names.length > 0) return names
            continue
        }
        const names = safeArray(candidate)
        if (names.length > 0) return names
    }

    return safeArray(record.annotations)
}

export function formatMetadataProgress(item: MediaPublic): string {
    const record = item as Record<string, unknown>

    const directKeys = ["progress_text", "progress", "meta_progress", "metadata_progress"]
    for (const key of directKeys) {
        const raw = record[key]
        if (typeof raw === "string" && raw.includes("/")) return raw.trim()
    }

    const dutyCycleSide = (raw: unknown): string | null => {
        if (raw === null || raw === undefined) return null
        if (typeof raw === "string" && raw.trim() === "") return null
        const n = typeof raw === "number" ? raw : Number(String(raw).trim())
        if (!Number.isFinite(n)) return null
        return String(Math.round(n))
    }

    const recPart = dutyCycleSide(record.duty_cycle_recording)
    const periodPart = dutyCycleSide(record.duty_cycle_period)
    if (periodPart !== null || recPart !== null) {
        return `${recPart ?? "-"}/${periodPart ?? "-"}`
    }

    const pairs: Array<[string, string]> = [
        ["processed", "total"],
        ["processed_count", "total_count"],
        ["analysed", "total"],
        ["analyzed", "total"],
        ["imported", "total"],
        ["records", "total_records"],
        ["row_count", "total_row_count"],
    ]

    const pairSideNum = (raw: unknown): number | null => {
        if (raw === null || raw === undefined) return null
        if (typeof raw === "string" && raw.trim() === "") return null
        const n = typeof raw === "number" ? raw : Number(String(raw).trim())
        if (!Number.isFinite(n)) return null
        return n
    }

    for (const [currentKey, totalKey] of pairs) {
        const current = pairSideNum(record[currentKey])
        const total = pairSideNum(record[totalKey])
        if (current !== null && total !== null && total >= 0) {
            return `${Math.round(current)}/${Math.round(total)}`
        }
    }
    return "-"
}

export function hasCompleteMetadataDutyCycle(item: MediaPublic): boolean {
    const record = item as Record<string, unknown>
    const hasValue = (raw: unknown): boolean => {
        if (raw === null || raw === undefined) return false
        if (typeof raw === "string") return raw.trim() !== ""
        return true
    }
    return hasValue(record.duty_cycle_period) && hasValue(record.duty_cycle_recording)
}

type MediaDatetimeFields = Pick<MediaPublic, "date_time"> & {
    date?: string
    time?: string
}

export function mediaDisplayDatetimeRaw(item: MediaDatetimeFields): string | undefined {
    const raw = item.date_time
    if (typeof raw === "string" && raw.trim()) return raw.trim()
    return undefined
}

export function splitMediaDisplayDateTime(item: MediaDatetimeFields): {
    displayDate?: string
    displayTime?: string
} {
    const raw = mediaDisplayDatetimeRaw(item)
    if (!raw) {
        return { displayDate: item.date, displayTime: item.time }
    }
    const dtParts = raw.split(/[T\s]/)
    return {
        displayDate: dtParts[0] || item.date,
        displayTime: dtParts[1]?.split(/[.Z+-]/)[0] || item.time,
    }
}

/** 将 getMedia 等接口行转为 Gallery 卡片所需字段 */
export function mediaRowToGalleryItem(row: Record<string, any>): MediaPublic {
    const as = row.audio_setting
    const id = row.id ?? row.media_id
    return {
        ...row,
        id,
        name: row.name || row.filename || `Media #${id}`,
        sampling_rate_hz: row.sampling_rate_hz ?? as?.sampling_rate_hz,
        duration_s: row.duration_s ?? as?.duration_s,
        spectrogram: row.spectrogram ?? row.preview_url,
        size_b: row.size_b,
    } as unknown as MediaPublic
}

export function isGalleryMetadataItem(item: Pick<MediaPublic, "media_type" | "filename" | "is_metadata">): boolean {
    if (item.is_metadata === true) return true
    const t = (item.media_type || "").toLowerCase()
    if (t === "metadata") return true
    const f = String(item.filename || "")
    return /\.(csv|json|xml)$/i.test(f)
}

export function getMetadataMediaKind(
    item: Pick<MediaPublic, "media_type" | "filename" | "name">,
): "audio" | "photo" {
    const mediaType = String(item.media_type ?? "").toLowerCase()
    if (mediaType === "photo") return "photo"
    if (mediaType === "audio") return "audio"

    const fileName = `${item.name ?? ""} ${item.filename ?? ""}`.toLowerCase()
    return /\b(photo|image|jpg|jpeg|png|gif|webp|bmp|tif|tiff)\b/.test(fileName)
        ? "photo"
        : "audio"
}

export function resolveMediaThemeValue(
    item: MediaPublic,
    preferredTheme?: string | null,
): string | null {
    const record = item as Record<string, unknown>
    const candidates: unknown[] = [
        preferredTheme,
        record.theme_value,
        record.sphere,
        record.realm_name,
        record.site_realm_name,
        record.site_realm,
        record.realm,
    ]

    for (const candidate of candidates) {
        if (typeof candidate !== "string") continue
        const next = candidate.trim()
        if (next) return next
    }

    return null
}

interface MediaGalleryCardProps {
    item: MediaPublic
    /** 点击卡片触发（无 detailTo 时使用） */
    onDetail?: () => void
    /** 使用 Router Link 进入详情，避免纯 div 点击与路由不同步 */
    detailTo?: string
    projectId?: number | null
    /** 强制指定 Sphere 主题（如 Map 侧栏按 site 设置） */
    sphere?: string | null
}


export function MediaGalleryCard({ item, onDetail, detailTo, projectId, sphere }: MediaGalleryCardProps) {
    const isMetadata = isGalleryMetadataItem(item)
    const isPhoto = String(item.media_type ?? "").toLowerCase() === "photo"
    const metadataMediaKind = isMetadata ? getMetadataMediaKind(item) : null
    const rawSpectrogram =
        item.spectrogram ?? (item as Record<string, unknown>).preview_url ?? undefined
    const spectrogramDisplayUrl = useMediaSpectrogramUrl(
        typeof rawSpectrogram === "string" ? rawSpectrogram : undefined,
        resolveMediaNumericId(item),
        projectId,
    )

    const srHz = Number(item.sampling_rate_hz)
    const displaySr =
        !Number.isNaN(srHz) && srHz > 0 ? `${srHz / 1000}kHz` : undefined

    const sizeB = Number(item.size_b)
    const displaySize =
        !Number.isNaN(sizeB) && sizeB > 0
            ? `${(sizeB / (1024 * 1024)).toFixed(2)} MB`
            : undefined

    const durS = Number(item.duration_s)
    const displayDuration =
        !Number.isNaN(durS) && durS > 0 ? formatDuration(durS) : undefined

    const { displayDate, displayTime } = splitMediaDisplayDateTime(item as any)

    const labelNames = getMediaLabelNames(item)
    const metadataProgress = isMetadata ? formatMetadataProgress(item) : "-"
    const showMetadataProgress = isMetadata && hasCompleteMetadataDutyCycle(item)

    const themeValue = resolveMediaThemeValue(item, sphere)

    const tagPillStyle = getRealmTagPillStyle(themeValue)
    const accentStyle = getRealmAccentVars(themeValue)

    const cardClass = "media-item-card"

    return (
        <div className={cardClass} style={accentStyle}>
            <ActionLink detailTo={detailTo} onDetail={onDetail} className="spectrogram-cover">
                {isMetadata ? (
                    <div className="metadata-cover">
                        {metadataMediaKind === "photo" ? (
                            <ImageIcon className="metadata-icon" />
                        ) : (
                            <FileAudio className="metadata-icon" />
                        )}
                        <span className="metadata-text">
                            {metadataMediaKind === "photo" ? "PHOTO METADATA" : "AUDIO METADATA"}
                        </span>
                    </div>
                ) : (
                    <>
                        <UnifiedImage
                            src={spectrogramDisplayUrl}
                            className="spectrogram-img"
                            alt={isPhoto ? item.name || item.filename || "Photo" : ""}
                        />
                        {!isPhoto ? (
                            <div className="play-overlay">
                                <div className="play-circle">
                                    <Play size={16} fill="currentColor" />
                                </div>
                            </div>
                        ) : null}
                    </>
                )}
                {isPhoto && Number(item.image_width) > 0 && Number(item.image_height) > 0 ? (
                    <div className="sr-badge"><ImageIcon size={12} /> {Number(item.image_width)} × {Number(item.image_height)}</div>
                ) : null}
                {!isPhoto && displaySr ? <div className="sr-badge">{displaySr}</div> : null}
                {!isPhoto && displayDuration ? <div className="duration-badge">{displayDuration}</div> : null}
            </ActionLink>
            <div className="media-card-info">
                <ActionLink
                    detailTo={detailTo}
                    onDetail={onDetail}
                    className={`media-name${isMetadata ? " media-name--static" : ""}`}
                    title={item.name ?? undefined}
                >
                    {item.name}
                </ActionLink>
                <div className="annotations-row">
                    {labelNames.length > 0
                        ? labelNames.map((lab: string, idx: number) => (
                            <span key={`lab-${idx}`} className="media-annotation" style={tagPillStyle}>
                                {lab}
                            </span>
                        ))
                        : null}
                </div>
                <div className="media-meta-row">
                    <div className="meta-icon-text">
                        <Calendar size={18} /> {displayDate || "-"}
                    </div>
                    <div className="meta-icon-text">
                        <Clock size={18} /> {displayTime || "-"}
                    </div>
                    {isMetadata ? (
                        showMetadataProgress ? (
                            <div className="meta-icon-text">
                                <Timer size={18} /> {metadataProgress}
                            </div>
                        ) : null
                    ) : (
                        <div className="meta-icon-text">
                            <HardDrive size={18} /> {displaySize || "-"}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

/** 辅助组件：根据 detailTo / onDetail 渲染 Link 或 div，且确保 Link 为 block 布局 */
export function ActionLink({
    children,
    className,
    title,
    detailTo,
    onDetail,
}: {
    children: React.ReactNode
    className?: string
    title?: string
    detailTo?: string
    onDetail?: () => void
}) {
    const commonProps = { className, title }
    // Do not set `color` inline; allow CSS (e.g. `.media-name:hover`) to control link color.
    const linkStyle = { display: "block", textDecoration: "none" as const }

    if (detailTo) {
        return (
            <Link to={detailTo} {...commonProps} style={linkStyle} className={`${className || ""} action-link-hit`}>
                {children}
            </Link>
        )
    }
    if (onDetail) {
        return (
            <div
                onClick={onDetail}
                {...commonProps}
                className={`${className || ""} cursor-pointer`}
                role="button"
                tabIndex={0}
            >
                {children}
            </div>
        )
    }
    return <div {...commonProps}>{children}</div>
}
