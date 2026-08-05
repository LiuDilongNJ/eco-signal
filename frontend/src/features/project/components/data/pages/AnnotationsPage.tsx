import { Button as ESButton } from "@/components/ui"
/**
 * AnnotationsPage - Annotations 数据页面
 */

import { useState, useCallback } from "react"
import { DataPageLayout } from "../DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../DataPageLayout"
import { message } from "@/components/ui"
import { annotationsApi } from "../../../../../api/endpoints/annotations"
import { useProjectStore } from "../../../stores/useProjectStore"
import { FileText, ClipboardList } from "lucide-react"
import { AssignTasksDrawer } from "../../modals/AssignTasksDrawer"
import { AnnotationFormDrawer } from "../../modals/AnnotationFormDrawer"
import { downloadFile } from "@/utils/download"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "annotation_id", label: "ID", type: "number", width: "80px", sortable: true, filterable: true },
    { key: "uuid", label: "UUID", type: "text", width: "300px", sortable: true, filterable: true },
    { key: "media_name", label: "Media Name", type: "text", width: "180px", sortable: true, filterable: true },
    { key: "media_type", label: "Media Type", type: "text", width: "150px", sortable: true, filterable: true },
    { key: "min_x", label: "Min X", type: "number", width: "130px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "max_x", label: "Max X", type: "number", width: "130px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "min_y", label: "Min Y", type: "number", width: "130px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "max_y", label: "Max Y", type: "number", width: "130px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "creator_type", label: "Creator Type", type: "text", width: "130px", sortable: true, filterable: true },
    { key: "soundscape_component", label: "Soundscape", type: "text", width: "130px", sortable: true, filterable: true },
    { key: "sound_type", label: "Sound Type", type: "text", width: "130px", sortable: true, filterable: true },
    { key: "taxon_name", label: "Taxon", type: "text", width: "130px", sortable: true, filterable: true },
    { key: "animal_sound_type", label: "Animal Sound", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "confidence", label: "Confidence", type: "number", width: "120px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "uncertain", label: "Uncertain", type: "boolean", width: "110px", sortable: true, filterable: true },
    { key: "sound_distance_m", label: "Distance (m)", type: "number", width: "130px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "distance_not_estimable", label: "Not Estimable", type: "badge", width: "140px", sortable: true, filterable: true, filterOptions: ["True", "False"] },
    { key: "individual_num", label: "Indiv. Num", type: "number", width: "110px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "reference", label: "Reference", type: "badge", width: "140px", sortable: true, filterable: true, filterOptions: ["True", "False"] },
    { key: "comments", label: "Comments", type: "text", width: "180px", maxWidth: "180px", sortable: true, filterable: true },
    { key: "creator_name", label: "Creator", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "creation_date", label: "Created", type: "date", width: "160px", sortable: true, filterable: true, filterType: "dateRange" },
]

function openAnnotationViewTab(projectId: number, mediaId: number, annotationId: number) {
    window.open(
        `/dashboard/${projectId}/media/${mediaId}?annotation_id=${encodeURIComponent(String(annotationId))}`,
        `eco-annotation-view-${annotationId}`,
        "noopener,noreferrer",
    )
}

const FORM_FIELDS: FormFieldDef[] = [
    { key: "min_x", label: "Min X", type: "number" },
    { key: "max_x", label: "Max X", type: "number" },
    { key: "min_y", label: "Min Y", type: "number" },
    { key: "max_y", label: "Max Y", type: "number" },
    { key: "soundscape", label: "Soundscape", type: "select" },
    { key: "sound_type", label: "Sound Type", type: "select" },
    { key: "taxon", label: "Taxon", type: "select" },
    { key: "uncertain", label: "Uncertain", type: "select", options: ["True", "False"] },
    { key: "animal_sound", label: "Animal Sound", type: "select" },
    { key: "distance_m", label: "Distance (m)", type: "number" },
    { key: "individual_num", label: "Indiv. Num", type: "number" },
    { key: "reference", label: "Reference", type: "select", options: ["True", "False"] },
    { key: "comments", label: "Comments", type: "textarea" },
]

/** 列表/导出共用：列 key 已与后端参数名一致，仅处理类型转换与日期区间拆分 */
function applyAnnotationFilters(params: Record<string, unknown>, filters: Record<string, unknown>) {
    Object.entries(filters).forEach(([k, v]) => {
        if (v === "" || v === null || v === undefined) return
        if (k === "annotation_id") {
            params.annotation_id = Number(v)
        } else if (k === "creation_date") {
            const [start, end] = String(v).split(",")
            if (start) params.creation_date_from = start
            if (end) params.creation_date_to = end
        } else if (k === "distance_not_estimable" || k === "reference") {
            params[k] = String(v).toLowerCase() === "true"
        } else {
            params[k] = String(v).trim()
        }
    })
}

export function AnnotationsPage() {
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const currentProjectId = useProjectStore(s => s.currentProjectId)
    const currentCollectionId = useProjectStore(s => s.currentCollectionId)

    // Assignment drawer state（tag 任务需 annotation_ids；单选行时为当前标注 ID）
    const [assignTasksOpen, setAssignTasksOpen] = useState(false)
    const [selectedMediaId, setSelectedMediaId] = useState<number | null>(null)
    const [assignAnnotationIds, setAssignAnnotationIds] = useState<number[] | undefined>(undefined)

    // Edit drawer state
    const [editDrawerOpen, setEditDrawerOpen] = useState(false)
    const [editData, setEditData] = useState<Record<string, any>>({})
    const [editId, setEditId] = useState<number | null>(null)
    const [submitting, setSubmitting] = useState(false)
    const [tableState, setTableState] = useState<TableState | null>(null)

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const params: any = {
                page: state.page,
                page_size: state.pageSize,
            }

            if (state.sortKey) {
                params.order_by = state.sortKey
                params.order_dir = state.sortDir || "asc"
            }

            applyAnnotationFilters(params, state.filters)

            if (currentProjectId) {
                params.project_id = Number(currentProjectId)
            }
            if (currentCollectionId && currentCollectionId !== 'all') {
                params.collection_id = Number(currentCollectionId)
            }

            const res = await annotationsApi.getList(params)
            if (res && res.data) {
                const formattedRows = res.data.map((a: any) => ({
                    ...a,
                    creator_name: a.creator_name ?? String(a.creator_id ?? ""),
                    media_name: a.media_name || "",
                    media_type: a.media_type ?? "",
                    taxon_name: a.taxon_scientific_name ?? a.taxon_common_name ?? "",
                    distance_not_estimable:
                        a.distance_not_estimable === true
                            ? "True"
                            : a.distance_not_estimable === false
                              ? "False"
                              : "",
                    reference:
                        a.reference === true
                            ? "True"
                            : a.reference === false
                              ? "False"
                              : "",
                }))
                setRows(formattedRows as RowData[])
                setTotalRows(res.page_info ? res.page_info.total : (res.data.length || 0))
            }
        } catch (error) {
            console.error("Failed to fetch annotations:", error)
            message.error("Failed to load annotations")
        } finally {
            setLoading(false)
        }
    }, [currentProjectId, currentCollectionId])

    const scheduleTableFetch = useTableFetchScheduler(fetchTableData)

    const handleTableChange = useCallback((state: TableState) => {
        setTableState(state)
        scheduleTableFetch(state)
    }, [scheduleTableFetch])

    const handleEdit = async (selectedRowKeys: any[]) => {
        if (!currentProjectId) {
            message.warning("Please select a project first")
            return
        }
        if (selectedRowKeys.length === 1) {
            const id = selectedRowKeys[0] as number
            try {
                const res = await annotationsApi.getById(id, Number(currentProjectId))
                if (res) {
                    setEditId(id)
                    setEditData({
                        ...res,
                        soundscape: res.soundscape_component,
                        sound_type: res.sound_id == null ? undefined : String(res.sound_id),
                        taxon: res.taxon_id,
                        animal_sound: res.animal_sound_type,
                        reference: res.reference === true,
                        uncertain: res.uncertain === true,
                        distance_not_estimable: res.distance_not_estimable === true,
                        distance_m: res.sound_distance_m,
                        individual_num: res.individual_num,
                    })
                    setEditDrawerOpen(true)
                }
            } catch (err: any) {
                console.error("Failed to fetch annotation details", err)
                message.error("Failed to load details")
            }
        } else {
            message.warning("Please select exactly one annotation to edit")
        }
    }

    const handleSubmit = async (values: Record<string, any>) => {
        if (!editId || !currentProjectId) return
        setSubmitting(true)
        try {
            const payload: any = {}
            if (values.min_x !== undefined) payload.min_x = Number(values.min_x)
            if (values.max_x !== undefined) payload.max_x = Number(values.max_x)
            if (values.min_y !== undefined) payload.min_y = Number(values.min_y)
            if (values.max_y !== undefined) payload.max_y = Number(values.max_y)
            payload.confidence = values.confidence === undefined ? null : Number(values.confidence)
            const distanceRaw = values.distance_m
            const hasDistance =
                distanceRaw !== undefined &&
                distanceRaw !== null &&
                String(distanceRaw).trim() !== ""
            if (hasDistance) {
                payload.sound_distance_m = Number(distanceRaw)
                payload.distance_not_estimable = false
            } else {
                payload.sound_distance_m = null
                if (values.distance_not_estimable === true || values.distance_not_estimable === "True") {
                    payload.distance_not_estimable = true
                } else if (values.distance_not_estimable === false || values.distance_not_estimable === "False") {
                    payload.distance_not_estimable = false
                } else {
                    payload.distance_not_estimable = null
                }
            }
            payload.individual_num = values.individual_num === undefined ? null : Number(values.individual_num)
            payload.comments = values.comments ?? null
            payload.sound_id = values.sound_type === undefined ? null : Number(values.sound_type)
            payload.taxon_id = values.taxon === undefined ? null : (values.taxon ? Number(values.taxon) : null)
            payload.animal_sound_type = values.animal_sound ?? null
            
            if (typeof values.reference === "boolean") payload.reference = values.reference
            else if (values.reference === "True") payload.reference = true
            else if (values.reference === "False") payload.reference = false
            else payload.reference = null

            if (typeof values.uncertain === "boolean") payload.uncertain = values.uncertain
            else if (values.uncertain === "True") payload.uncertain = true
            else if (values.uncertain === "False") payload.uncertain = false
            else payload.uncertain = null

            await annotationsApi.update(editId, Number(currentProjectId), payload)
            message.success("Annotation updated successfully")
            setEditDrawerOpen(false)
            if (tableState) {
                handleTableChange(tableState)
            }
        } catch (err: any) {
            console.error("Failed to update annotation", err)
            message.error(err.message || "Failed to update annotation")
        } finally {
            setSubmitting(false)
        }
    }

    const handleDelete = async (selectedRowKeys: any[]) => {
        if (!selectedRowKeys || selectedRowKeys.length === 0) return
        if (!currentProjectId) {
            message.warning("Please select a project first")
            return
        }
        const hide = message.loading(`Deleting ${selectedRowKeys.length} annotation(s)...`, 0)
        let successCount = 0
        try {
            for (const id of selectedRowKeys) {
                await annotationsApi.delete(id, Number(currentProjectId))
                successCount++
            }
            message.success(`Successfully deleted ${successCount} annotation(s)`)
            if (tableState) {
                handleTableChange(tableState)
            }
        } catch (err: any) {
            console.error("Failed to delete annotations", err)
            message.error(err.message || "Failed to delete some annotations")
        } finally {
            hide()
        }
    }

    const handleExport = useCallback(async () => {
        try {
            setLoading(true)
            const params: any = {}
            if (tableState?.sortKey) {
                params.order_by = tableState.sortKey
                params.order_dir = tableState.sortDir || "asc"
            }
            if (tableState) {
                applyAnnotationFilters(params, tableState.filters)
            }

            if (currentProjectId) {
                params.project_id = Number(currentProjectId)
            }
            if (currentCollectionId && currentCollectionId !== 'all') {
                params.collection_id = Number(currentCollectionId)
            }

            const download = await annotationsApi.exportCsv(params)
            downloadFile(download)
        } catch (error: any) {
            console.error("Export error:", error)
            message.error(error?.message || "An error occurred while exporting")
        } finally {
            setLoading(false)
        }
    }, [tableState, currentProjectId, currentCollectionId])

    const handleView = useCallback((selectedRowKeys: unknown[]) => {
        if (selectedRowKeys.length === 0) {
            message.warning("Please select at least one annotation to view")
            return
        }
        if (!currentProjectId) {
            message.warning("Please select a project first")
            return
        }
        const projectId = Number(currentProjectId)
        let openedCount = 0
        let skippedCount = 0

        for (const key of selectedRowKeys) {
            const annotationId = Number(key)
            const row = rows.find((r) => Number(r.annotation_id) === annotationId)
            const mediaId = row?.media_id != null ? Number(row.media_id) : NaN
            if (
                !row ||
                !Number.isFinite(annotationId) ||
                annotationId <= 0 ||
                !Number.isFinite(mediaId) ||
                mediaId <= 0
            ) {
                skippedCount += 1
                continue
            }
            openAnnotationViewTab(projectId, mediaId, annotationId)
            openedCount += 1
        }

        if (openedCount === 0) {
            message.warning("No viewable annotation selected")
        } else if (skippedCount > 0) {
            message.warning(`Skipped ${skippedCount} annotation(s) without associated media`)
        }
    }, [currentProjectId, rows])

    return (
        <>
            <DataPageLayout
                title="Annotations"
                icon={FileText}
                columns={COLUMNS}
                rows={rows}
                formFields={FORM_FIELDS}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="annotation_id"
                onTableStateChange={handleTableChange}
                defaultSortKey="annotation_id"
                defaultSortDir="asc"
                onEditCustom={handleEdit}
                onDeleteCustom={handleDelete}
                onExportCustom={handleExport}
                onViewCustom={handleView}
                viewRequiresSingle={false}
                hideView={false}
                hideAdd={true}
                renderCustomActions={(selectedRows) => {
                    const selectedIds = Array.from(selectedRows).map((id) => Number(id))
                    const selectedAnnotations = rows.filter((row) => selectedIds.includes(Number(row.annotation_id)))
                    const mediaIds = Array.from(
                        new Set(
                            selectedAnnotations
                                .map((row) => Number(row.media_id))
                                .filter((id) => Number.isFinite(id) && id > 0),
                        ),
                    )
                    const canAssign = selectedAnnotations.length > 0 && mediaIds.length === 1

                    return (
                        <ESButton appearance="unstyled"
                            className="data-btn"
                            title="Assignment"
                            disabled={!canAssign}
                            onClick={() => {
                                if (selectedAnnotations.length === 0) {
                                    message.warning("Please select at least one annotation")
                                    return
                                }
                                if (mediaIds.length !== 1) {
                                    message.warning("Selected annotations must belong to the same media")
                                    return
                                }
                                setSelectedMediaId(mediaIds[0]!)
                                setAssignAnnotationIds(
                                    selectedAnnotations
                                        .map((row) => Number(row.annotation_id))
                                        .filter((id) => Number.isFinite(id) && id > 0),
                                )
                                setAssignTasksOpen(true)
                            }}
                        >
                            <ClipboardList size={14} /> Assignment
                        </ESButton>
                    )
                }}
            />
            {/* Assign Tasks Drawer */}
            <AssignTasksDrawer
                open={assignTasksOpen}
                mediaId={selectedMediaId}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                annotationIds={assignAnnotationIds}
                onClose={() => {
                    setAssignTasksOpen(false)
                    setSelectedMediaId(null)
                    setAssignAnnotationIds(undefined)
                }}
            />
            <AnnotationFormDrawer
                open={editDrawerOpen}
                mode="edit"
                fields={FORM_FIELDS}
                initialData={editData}
                submitting={submitting}
                onClose={() => setEditDrawerOpen(false)}
                onSubmit={handleSubmit}
            />
        </>
    )
}
