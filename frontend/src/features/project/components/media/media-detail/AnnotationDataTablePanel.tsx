import type { ComponentProps, CSSProperties, PointerEventHandler, RefObject } from "react"
import {
    ConfigProvider,
    DataTable,
    EmptyState,
    LoadingState,
    ToolbarButton,
    type TableProps,
} from "@/components/ui"
import { ClipboardList, Download, Eye, EyeOff, RotateCcw, Trash2 } from "lucide-react"
import type { StudioAnnotationRow } from "./mediaDetailSupport"

type ThemeContract = ComponentProps<typeof ConfigProvider>["theme"]
type TableChangeHandler = NonNullable<TableProps<StudioAnnotationRow>["onChange"]>

export interface AnnotationTableScrollContract {
    viewportRef: RefObject<HTMLDivElement>
    trackRef: RefObject<HTMLDivElement>
    bodyHeight: number
    thumb: { show: boolean; size: number; offset: number }
    dragging: boolean
    onThumbPointerDown: PointerEventHandler<HTMLDivElement>
    onThumbPointerMove: PointerEventHandler<HTMLDivElement>
    onThumbPointerEnd: PointerEventHandler<HTMLDivElement>
    onThumbPointerLost: () => void
}

export interface AnnotationTableActionsContract {
    canManage: boolean
    assignActive: boolean
    selectedCount: number
    onReset: () => void
    onAssign: () => void | Promise<void>
    onDelete: () => void
    onExport: () => void | Promise<void>
    onVisibilityChange: (visible: boolean) => void
    onOpenRow: (annotationId: number) => void | Promise<void>
    onHighlightRow: (annotationId: number, highlighted: boolean) => void
}

export interface AnnotationDataTablePanelProps {
    visible: boolean
    isPhoto: boolean
    theme: ThemeContract
    themeTransitioning: boolean
    loading: boolean
    rows: StudioAnnotationRow[]
    columns: NonNullable<TableProps<StudioAnnotationRow>["columns"]>
    linkedHighlightId: number | null
    editingAnnotationId: number | null
    scroll: AnnotationTableScrollContract
    actions: AnnotationTableActionsContract
    onTableChange: TableChangeHandler
}

export function AnnotationDataTablePanel({
    visible,
    isPhoto,
    theme,
    themeTransitioning,
    loading,
    rows,
    columns,
    linkedHighlightId,
    editingAnnotationId,
    scroll,
    actions,
    onTableChange,
}: AnnotationDataTablePanelProps) {
    if (!visible) {
        if (isPhoto) return null
        return (
            <div className="studio-bottom-section">
                <div className="table-side-toolbar">
                    <div className="studio-table-toolbar-spacer" />
                    <ToolbarButton
                        className="data-btn studio-table-toolbar-button"
                        label="Show annotations table"
                        icon={<EyeOff size={16} aria-hidden />}
                        onClick={() => actions.onVisibilityChange(true)}
                    />
                </div>
            </div>
        )
    }

    const viewportStyle = {
        "--dpl-scroll-y": `${scroll.bodyHeight}px`,
    } as CSSProperties

    return (
        <div className="studio-bottom-section">
            <div className="table-side-toolbar">
                <ToolbarButton
                    className="btn-toolbar studio-table-toolbar-button"
                    label="Reset table filters and reload list"
                    icon={<RotateCcw size={16} />}
                    onClick={actions.onReset}
                />
                <div className="studio-table-toolbar-divider" />
                <div className="studio-table-toolbar-actions">
                    {actions.canManage ? (
                        <>
                            <ToolbarButton
                                className="data-btn studio-table-toolbar-button"
                                active={actions.assignActive}
                                label="Assign selected annotations"
                                icon={<ClipboardList size={16} />}
                                disabled={actions.selectedCount === 0}
                                onClick={() => void actions.onAssign()}
                            />
                            <ToolbarButton
                                className="data-btn danger studio-table-toolbar-button"
                                label="Delete selected annotations"
                                icon={<Trash2 size={16} />}
                                disabled={actions.selectedCount === 0}
                                onClick={actions.onDelete}
                            />
                        </>
                    ) : null}
                </div>
                <div className="studio-table-toolbar-spacer" />
                <ToolbarButton
                    className="btn-toolbar studio-table-toolbar-button"
                    label={
                        isPhoto
                            ? "Export all annotations for this photo"
                            : "Export annotations overlapping the current spectrogram viewport"
                    }
                    icon={<Download size={16} />}
                    onClick={() => void actions.onExport()}
                />
                <ToolbarButton
                    className="data-btn studio-table-toolbar-button"
                    active
                    label="Hide annotations table"
                    icon={<Eye size={16} aria-hidden />}
                    onClick={() => actions.onVisibilityChange(false)}
                />
            </div>

            <ConfigProvider theme={theme}>
                <div className="data-content data-table-container studio-annotation-table-wrap data-content-media-detail studio-annotation-table-container">
                    {themeTransitioning ? (
                        <div className="dpl-theme-loader-overlay">
                            <LoadingState label="Updating theme..." variant="overlay" size="lg" showLabel={false} />
                        </div>
                    ) : null}
                    <div
                        ref={scroll.viewportRef}
                        className="data-table-wrapper data-table-wrapper--media-detail studio-annotation-table-viewport"
                        style={viewportStyle}
                    >
                        <div className="data-table-shell">
                            {loading ? (
                                <LoadingState
                                    label="Loading data..."
                                    variant="overlay"
                                    size="lg"
                                    className="data-table-loading-overlay"
                                />
                            ) : null}
                            <DataTable<StudioAnnotationRow>
                                className="studio-annotation-data-table"
                                loading={false}
                                rowKey="annotation_id"
                                size="small"
                                tableLayout="fixed"
                                columns={columns}
                                dataSource={rows}
                                scroll={{ x: 3800, y: scroll.bodyHeight }}
                                emptyState={
                                    loading ? (
                                        <div className="data-table-empty-state studio-annotation-table-empty" />
                                    ) : (
                                        <EmptyState
                                            title="No Data"
                                            className="ui-state--inline data-table-empty-state studio-annotation-table-empty"
                                        />
                                    )
                                }
                                pagination={false}
                                rowClassName={(record) =>
                                    record.annotation_id === linkedHighlightId ||
                                    record.annotation_id === editingAnnotationId
                                        ? "studio-annotation-row--linked"
                                        : ""
                                }
                                onRow={(record) => ({
                                    onClick: (event) => {
                                        const target = event.target as HTMLElement
                                        if (
                                            target.closest(".ant-checkbox-wrapper") ||
                                            target.closest("button") ||
                                            target.closest("a")
                                        ) {
                                            return
                                        }
                                        void actions.onOpenRow(record.annotation_id)
                                    },
                                    onMouseEnter: () => actions.onHighlightRow(record.annotation_id, true),
                                    onMouseLeave: () => actions.onHighlightRow(record.annotation_id, false),
                                })}
                                onChange={onTableChange}
                            />
                        </div>
                        <div ref={scroll.trackRef} className="dpl-hscroll-track" aria-hidden>
                            {scroll.thumb.show ? (
                                <div
                                    className={`dpl-hscroll-thumb${scroll.dragging ? " dpl-hscroll-thumb--dragging" : ""}`}
                                    style={{
                                        width: scroll.thumb.size,
                                        transform: `translateX(${scroll.thumb.offset}px)`,
                                    }}
                                    onPointerDown={scroll.onThumbPointerDown}
                                    onPointerMove={scroll.onThumbPointerMove}
                                    onPointerUp={scroll.onThumbPointerEnd}
                                    onPointerCancel={scroll.onThumbPointerEnd}
                                    onLostPointerCapture={scroll.onThumbPointerLost}
                                />
                            ) : null}
                        </div>
                    </div>
                </div>
            </ConfigProvider>
        </div>
    )
}
