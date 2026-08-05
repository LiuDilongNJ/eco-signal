import type { ComponentProps } from "react"
import type { RecordingDetail } from "../../../../../api/endpoints/media"
import type { LabelPublic } from "../../../../../api/endpoints/labels"
import {
    Button,
    Button as ESButton,
    ConfigProvider,
    CustomScrollArea,
    Divider,
    Input,
    LoadingState,
    EmptyState,
    Popconfirm,
    Popover,
} from "@/components/ui"
import { Download, Info, MapPin, Tag, Trash2 } from "lucide-react"
import { authUtils } from "@/utils/auth"
import { clamp, isLabelSystemProtected } from "./mediaDetailSupport"

type ThemeContract = ComponentProps<typeof ConfigProvider>["theme"]

export interface MediaInfoLabelsContract {
    open: boolean
    loading: boolean
    saving: boolean
    adding: boolean
    deletingId: number | null
    items: LabelPublic[]
    selectedId: number | null
    newName: string
    pillText: string
    onOpenChange: (open: boolean) => void
    onNewNameChange: (value: string) => void
    onApply: (labelId: number) => void | Promise<void>
    onAdd: () => void | Promise<void>
    onDelete: (labelId: number) => void | Promise<void>
}

export interface MediaInfoViewportContract {
    start: number
    window: number
    duration: number
    minFrequency: number
    maxFrequency: number
    nyquist: number
}

export interface MediaInfoDisplayContract {
    photoDimensions?: string | null
    size?: string | null
    photoExposure?: string | null
    photoAperture?: string | null
    photoIso?: string | null
    duration?: string | null
    sampleRate?: string | null
    gain?: string | null
    date?: string | null
    time?: string | null
    site?: string | null
}

export interface MediaInfoDownloadsContract {
    onOriginalPhoto: () => void
    onViewportAudio: () => void | Promise<void>
    onViewportSpectrogram: () => void | Promise<void>
}

export interface MediaInfoPanelProps {
    theme: ThemeContract
    media: RecordingDetail
    mediaId: number
    isPhoto: boolean
    photoContentUrl?: string | null
    labels: MediaInfoLabelsContract
    viewport: MediaInfoViewportContract
    display: MediaInfoDisplayContract
    downloads: MediaInfoDownloadsContract
}

export function MediaInfoPanel({
    theme: antdAppTheme,
    media,
    mediaId,
    isPhoto,
    photoContentUrl,
    labels,
    viewport,
    display,
    downloads,
}: MediaInfoPanelProps) {
    const {
        open: labelPopoverOpen,
        loading: labelPopoverLoading,
        saving: labelPopoverSaving,
        adding: labelPopoverAdding,
        deletingId: labelPopoverDeletingId,
        items: labelPopoverList,
        selectedId: labelPopoverSelectedId,
        newName: labelPopoverNewName,
        pillText: audioLabelPillText,
        onOpenChange: onLabelPopoverOpenChange,
        onNewNameChange: onNewLabelNameChange,
        onApply: applyLabelFromPopover,
        onAdd: handlePopoverAddLabel,
        onDelete: handlePopoverDeleteLabel,
    } = labels
    const {
        start: specViewStart,
        window: specWindowSec,
        duration: totalDuration,
        minFrequency: specFreqMinHz,
        maxFrequency: specFreqMaxHz,
        nyquist: nyquistHz,
    } = viewport
    const {
        photoDimensions: displayPhotoDimensions,
        size: displaySize,
        photoExposure: displayPhotoExposure,
        photoAperture: displayPhotoAperture,
        photoIso: displayPhotoIso,
        duration: displayDuration,
        sampleRate: displaySr,
        gain: displayGain,
        date: displayDate,
        time: displayTime,
        site: displaySite,
    } = display
    const {
        onOriginalPhoto: handleDownloadOriginalPhoto,
        onViewportAudio: handleDownloadViewportAudio,
        onViewportSpectrogram: handleDownloadViewportSpectrogram,
    } = downloads

    return (
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
                                                                            <EmptyState className="studio-label-popover-empty" title="No labels" />
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
                                                                        borderColor: "var(--es-color-border)",
                                                                    }}
                                                                />
                                                                {authUtils.getToken() && (
                                                                    <div className="studio-label-popover-add-row">
                                                                        <Input
                                                                            className="set-labels-input"
                                                                            value={labelPopoverNewName}
                                                                            onChange={(e) =>
                                                                                onNewLabelNameChange(e.target.value)
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
    )
}
