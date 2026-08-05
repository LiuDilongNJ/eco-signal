import { useState, useCallback } from "react"
import { DataPageLayout } from "../DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../DataPageLayout"
import { message } from "@/components/ui"
import { reviewsApi, type ReviewsExportParams, type ReviewsListParams } from "../../../../../api/endpoints/reviews"
import { useProjectStore } from "../../../stores/useProjectStore"
import { ClipboardCheck } from "lucide-react"
import { ReviewFormDrawer } from "../../modals/ReviewFormDrawer"
import { downloadFile } from "@/utils/download"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "annotation_id", label: "Annotation ID", type: "number", width: "160px", sortable: true, filterable: true },
    { key: "media_name", label: "Media Name", type: "text", width: "180px", sortable: true, filterable: true },
    { key: "media_type", label: "Media Type", type: "text", width: "150px", sortable: true, filterable: true },
    { key: "reviewer_name", label: "Reviewer", type: "text", width: "160px", sortable: true, filterable: true },
    {
        key: "status_name",
        label: "Status",
        type: "badge",
        badgeSemantic: "review",
        width: "140px",
        sortable: true,
        filterable: true,
    },
    {
        key: "taxon_name",
        label: "Taxon",
        type: "text",
        width: "160px",
        sortable: true,
        filterable: true,
    },
    { key: "note", label: "Note", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "creation_date", label: "Created", type: "date", width: "180px", sortable: true, filterable: true, filterType: "dateRange" },
]

const DEFAULT_STATUS_OPTIONS = [
    { label: "Accepted", value: 1 },
    { label: "Corrected", value: 2 },
    { label: "Rejected", value: 3 },
    { label: "Uncertain", value: 4 },
]

function applyReviewFilters(params: ReviewsListParams, filters: Record<string, unknown>) {
    Object.entries(filters).forEach(([k, v]) => {
        if (v === "" || v === null || v === undefined) return
        if (k === "creation_date") {
            const [start, end] = String(v).split(",")
            if (start) params.creation_date_from = start
            if (end) params.creation_date_to = end
        } else if (k === "annotation_id") {
            params.annotation_id = Number(v)
        } else if (k === "reviewer_name" || k === "status_name" || k === "taxon_name" || k === "media_type") {
            params[k] = String(v).trim()
        } else if (k === "media_name" || k === "note") {
            params[k] = String(v)
        }
    })
}

const FORM_FIELDS: FormFieldDef[] = [
    { key: "status", label: "Status", type: "select", options: DEFAULT_STATUS_OPTIONS.map((option) => option.label) },
    { key: "annotation_id", label: "Annotation ID", type: "text", readonly: true },
    { key: "taxon", label: "Taxon", type: "select" },
    { key: "media_name", label: "Media Name", type: "text", readonly: true },
    { key: "note", label: "Note", type: "textarea" },
    { key: "reviewer_name", label: "Reviewer", type: "text", readonly: true },
    { key: "creation_date", label: "Created", type: "text", readonly: true },
]

export function ReviewsPage() {
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [tableState, setTableState] = useState<TableState | null>(null)

    const [editDrawerOpen, setEditDrawerOpen] = useState(false)
    const [editData, setEditData] = useState<Record<string, any>>({})
    const [submitting, setSubmitting] = useState(false)

    const currentProjectId = useProjectStore((s) => s.currentProjectId)
    const currentCollectionId = useProjectStore((s) => s.currentCollectionId)

    const fetchTableData = useCallback(
        async (state: TableState) => {
            setLoading(true)
            try {
                const params: ReviewsListParams = {
                    page: state.page,
                    page_size: state.pageSize,
                }

                if (state.sortKey) {
                    params.order_by = state.sortKey
                    params.order_dir = state.sortDir || "asc"
                }

                applyReviewFilters(params, state.filters)

                if (currentProjectId) {
                    params.project_id = Number(currentProjectId)
                }
                if (currentCollectionId && currentCollectionId !== "all") {
                    params.collection_id = Number(currentCollectionId)
                }

                const res = await reviewsApi.getList(params)
                if (res.code !== 0) {
                    throw new Error(res.message || "Failed to load reviews")
                }

                const formattedRows = (res.data ?? []).map((r: any) => {
                    const rid = r.review_id
                    const id =
                        rid != null && Number.isFinite(Number(rid))
                            ? Number(rid)
                            : `${r.annotation_id}-${r.reviewer_id}`
                    return {
                        ...r,
                        id,
                        media_name: r.media_name ?? "",
                        media_type: r.media_type ?? "",
                        note: r.note ?? "",
                        taxon_name: r.taxon_name ?? "",
                    }
                })
                setRows(formattedRows as RowData[])
                setTotalRows(res.page_info ? res.page_info.total : (res.data?.length || 0))
            } catch (error) {
                console.error("Failed to fetch reviews:", error)
                message.error("Failed to load reviews")
                setRows([])
                setTotalRows(0)
            } finally {
                setLoading(false)
            }
        },
        [currentProjectId, currentCollectionId],
    )

    const scheduleTableFetch = useTableFetchScheduler(fetchTableData)

    const handleTableChange = useCallback((state: TableState) => {
        setTableState(state)
        scheduleTableFetch(state)
    }, [scheduleTableFetch])

    const handleEdit = (selectedRowKeys: any[]) => {
        if (selectedRowKeys.length !== 1) {
            message.warning("Please select exactly one review to edit")
            return
        }
        const id = selectedRowKeys[0]
        const row = rows.find((r) => r.id === id)
        if (row) {
            let statusStr = "Uncertain"
            const sName = String(row.status_name || "").toLowerCase()
            if (sName.includes("accept")) statusStr = "Accepted"
            else if (sName.includes("reject")) statusStr = "Rejected"
            else if (sName.includes("correct") || sName.includes("revis")) statusStr = "Corrected"

            setEditData({
                ...row,
                status: statusStr,
                taxon: row.taxon_id || "",
            })
            setEditDrawerOpen(true)
        }
    }

    const handleSubmit = async (values: Record<string, any>) => {
        const annotationId = Number(values.annotation_id)
        const reviewerId = Number(values.reviewer_id)
        if (!annotationId || !reviewerId || !currentProjectId) return

        setSubmitting(true)

        let statusId = 4
        const s = String(values.status).toLowerCase()
        if (s.includes("accept")) statusId = 1
        else if (s.includes("correct") || s.includes("revis")) statusId = 2
        else if (s.includes("reject")) statusId = 3

        const payload: any = {
            annotation_review_status_id: statusId,
            note: values.note || "",
        }

        if (statusId === 2 && values.taxon) {
            payload.taxon_id = Number(values.taxon)
        } else {
            payload.taxon_id = null
        }

        try {
            await reviewsApi.update(Number(annotationId), Number(reviewerId), Number(currentProjectId), payload)
            message.success("Review updated successfully")
            setEditDrawerOpen(false)
            if (tableState) handleTableChange(tableState)
        } catch (error: any) {
            message.error(error.message || "Failed to update review")
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
        const hide = message.loading(`Deleting ${selectedRowKeys.length} review(s)...`, 0)
        let successCount = 0
        try {
            for (const key of selectedRowKeys) {
                const row = rows.find((r) => r.id === key)
                if (row && row.annotation_id && row.reviewer_id) {
                    await reviewsApi.delete(Number(row.annotation_id), Number(row.reviewer_id), Number(currentProjectId))
                    successCount++
                }
            }
            message.success(`Successfully deleted ${successCount} review(s)`)
            if (tableState) handleTableChange(tableState)
        } catch (error: any) {
            console.error("Failed to delete reviews:", error)
            message.error(error.message || "Failed to delete some reviews")
        } finally {
            hide()
        }
    }

    const handleExport = useCallback(async () => {
        try {
            setLoading(true)
            const params: ReviewsExportParams = {}
            if (tableState?.sortKey) {
                params.order_by = tableState.sortKey
                params.order_dir = tableState.sortDir || "asc"
            }

            if (tableState) {
                applyReviewFilters(params, tableState.filters)
            }

            if (currentProjectId) {
                params.project_id = Number(currentProjectId)
            }
            if (currentCollectionId && currentCollectionId !== "all") {
                params.collection_id = Number(currentCollectionId)
            }

            const download = await reviewsApi.exportCsv(params)
            downloadFile(download)
        } catch (error: any) {
            console.error("Export error:", error)
            message.error(error?.message || "An error occurred while exporting")
        } finally {
            setLoading(false)
        }
    }, [tableState, currentProjectId, currentCollectionId])

    return (
        <>
            <DataPageLayout
                title="Reviews"
                icon={ClipboardCheck}
                columns={COLUMNS}
                rows={rows}
                formFields={FORM_FIELDS}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="id"
                onTableStateChange={handleTableChange}
                defaultSortKey="annotation_id"
                defaultSortDir="asc"
                onEditCustom={handleEdit}
                onDeleteCustom={handleDelete}
                onExportCustom={handleExport}
                hideView={true}
                hideAdd={true}
            />
            <ReviewFormDrawer
                open={editDrawerOpen}
                onClose={() => setEditDrawerOpen(false)}
                mode="edit"
                fields={FORM_FIELDS}
                initialData={editData}
                onSubmit={handleSubmit}
                submitting={submitting}
            />
        </>
    )
}
