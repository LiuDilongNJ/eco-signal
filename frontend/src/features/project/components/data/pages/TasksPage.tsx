/**
 * TasksPage - Tasks 数据页面
 */

import { useState, useCallback } from "react"
import { DataPageLayout } from "../DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../DataPageLayout"
import { message } from "@/components/ui"
import { tasksApi } from "../../../../../api/endpoints/tasks"
import type { TaskExportParams, TaskListItem, TaskQueryParams } from "../../../../../api/endpoints/tasks"
import { useProjectStore } from "../../../stores/useProjectStore"
import { ListChecks } from "lucide-react"
import { downloadFile } from "@/utils/download"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "task_id", label: "ID", type: "number", width: "220px", sortable: true, filterable: true },
    {
        key: "type",
        label: "Type",
        type: "text",
        width: "220px",
        sortable: true,
        filterable: true,
    },
    { key: "media_name", label: "Media Name", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "media_type", label: "Media Type", type: "text", width: "150px", sortable: true, filterable: true },
    { key: "annotation_id", label: "Annotation ID", type: "number", width: "220px", sortable: true, filterable: true },
    { key: "assigner_name", label: "Assigner", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "assignee_name", label: "Assignee", type: "text", width: "220px", sortable: true, filterable: true },
    {
        key: "status",
        label: "Status",
        type: "badge",
        badgeSemantic: "task",
        width: "220px",
        sortable: true,
        filterable: true,
    },
    { key: "comment", label: "Comment", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "datetime", label: "Created", type: "date", width: "220px", sortable: true, filterable: true, filterType: "dateRange" },
]

const FORM_FIELDS: FormFieldDef[] = []

function isAnnotationTaskRow(row: RowData): boolean {
    const raw = String(row.type_raw ?? row.type ?? "").trim().toLowerCase()
    return raw === "annotation"
}

function openTaskViewTab(projectId: number, mediaId: number, taskId: number, annotationId?: number) {
    const query = annotationId != null ? `?annotation_id=${encodeURIComponent(String(annotationId))}` : ""
    window.open(
        `/dashboard/${projectId}/media/${mediaId}${query}`,
        `eco-task-view-${taskId}`,
        "noopener,noreferrer",
    )
}

function normalizeTaskStatus(value: unknown): string {
    const normalized = String(value ?? "").trim().toLowerCase()
    if (normalized === "assigned") return "Assigned"
    if (normalized === "reviewed") return "Reviewed"
    return String(value ?? "")
}

function applyTaskFilters(params: Record<string, unknown>, filters: Record<string, unknown>) {
    Object.entries(filters).forEach(([k, v]) => {
        if (v === "" || v === null || v === undefined) return
        if (k === "task_id") {
            params.task_id = Number(v)
        } else if (k === "datetime") {
            const [start, end] = String(v).split(",")
            if (start) params.datetime_from = start
            if (end) params.datetime_to = end
        } else {
            params[k] = String(v).trim()
        }
    })
}

export function TasksPage() {
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [tableState, setTableState] = useState<TableState | null>(null)

    const currentProjectId = useProjectStore(s => s.currentProjectId)
    const currentCollectionId = useProjectStore(s => s.currentCollectionId)

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const params: TaskQueryParams & Record<string, unknown> = {
                page: state.page,
                page_size: state.pageSize,
            }

            if (state.sortKey) {
                params.order_by = state.sortKey
                params.order_dir = state.sortDir || "asc"
            }

            applyTaskFilters(params, state.filters)

            if (currentProjectId) {
                params.project_id = Number(currentProjectId)
            }
            if (currentCollectionId && currentCollectionId !== 'all') {
                params.collection_id = Number(currentCollectionId)
            }

            const res = await tasksApi.getList(params)
            if (res && res.data) {
                const formattedRows = res.data.map((r: TaskListItem) => {
                    return {
                        ...r,
                        type_raw: r.type,
                        type: r.type,
                        status: normalizeTaskStatus(r.status),
                        media_id: r.media_id,
                        assigner_name: r.assigner_name ?? String(r.assigner_id),
                        assignee_name: r.assignee_name ?? String(r.assignee_id),
                        media_name: r.media_name ?? "",
                        media_type: r.media_type ?? "",
                        comment: r.comment ?? "",
                    }
                })
                setRows(formattedRows as RowData[])
                setTotalRows(res.page_info ? res.page_info.total : (res.data.length || 0))
            }
        } catch (error) {
            console.error("Failed to fetch tasks:", error)
            message.error("Failed to load tasks")
        } finally {
            setLoading(false)
        }
    }, [currentProjectId, currentCollectionId])

    const scheduleTableFetch = useTableFetchScheduler(fetchTableData)

    const handleTableChange = useCallback((state: TableState) => {
        setTableState(state)
        scheduleTableFetch(state)
    }, [scheduleTableFetch])

    const handleExport = useCallback(async () => {
        if (!currentProjectId) {
            message.warning("Please select a project first")
            return
        }

        try {
            setLoading(true)
            const params: TaskExportParams = {
                project_id: Number(currentProjectId),
            }
            if (currentCollectionId && currentCollectionId !== "all") {
                params.collection_id = Number(currentCollectionId)
            }
            if (tableState) {
                if (tableState.sortKey) {
                    params.order_by = tableState.sortKey
                    params.order_dir = tableState.sortDir || "asc"
                }
            }

            const download = await tasksApi.exportCsv(params)
            downloadFile(download)
        } catch (error: unknown) {
            console.error("Export error:", error)
            message.error(error instanceof Error ? error.message : "An error occurred while exporting")
        } finally {
            setLoading(false)
        }
    }, [tableState, currentProjectId, currentCollectionId])

    const handleView = useCallback((selectedKeys: unknown[]) => {
        if (selectedKeys.length === 0) {
            message.warning("Please select at least one task to view")
            return
        }
        if (!currentProjectId) {
            message.warning("Please select a project first")
            return
        }
        const projectId = Number(currentProjectId)
        let openedCount = 0
        let skippedCount = 0

        for (const key of selectedKeys) {
            const taskId = Number(key)
            const row = rows.find((r) => Number(r.task_id) === taskId)
            const mediaId = row?.media_id != null ? Number(row.media_id) : NaN
            if (!row || !Number.isFinite(taskId) || taskId <= 0 || !Number.isFinite(mediaId) || mediaId <= 0) {
                skippedCount += 1
                continue
            }

            let annotationId: number | undefined
            if (isAnnotationTaskRow(row)) {
                const rawAnnotationId = row.annotation_id != null ? Number(row.annotation_id) : NaN
                if (!Number.isFinite(rawAnnotationId) || rawAnnotationId <= 0) {
                    skippedCount += 1
                    continue
                }
                annotationId = rawAnnotationId
            }

            openTaskViewTab(projectId, mediaId, taskId, annotationId)
            openedCount += 1
        }

        if (openedCount === 0) {
            message.warning("No viewable task selected")
        } else if (skippedCount > 0) {
            message.warning(`Skipped ${skippedCount} task(s) without viewable media or annotation`)
        }
    }, [currentProjectId, rows])

    const handleDelete = useCallback(async (selectedKeys: unknown[]) => {
        const taskIds = selectedKeys
            .map((key) => Number(key))
            .filter((id) => Number.isFinite(id) && id > 0)

        if (taskIds.length === 0) {
            message.warning("No deletable task selected")
            return
        }

        try {
            setLoading(true)
            for (const taskId of taskIds) {
                const res = await tasksApi.deleteTask(taskId)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || `Failed to delete task ${taskId}`)
                    return
                }
            }
            message.success(`Deleted ${taskIds.length} task${taskIds.length > 1 ? "s" : ""}`)
            if (tableState) {
                handleTableChange(tableState)
            }
        } catch (error: any) {
            console.error("Delete task error:", error)
            message.error(error?.message || "An error occurred while deleting tasks")
        } finally {
            setLoading(false)
        }
    }, [tableState, handleTableChange])

    return (
        <DataPageLayout
            title="Tasks"
            importConfig={{
                endpoint: "/v1/tasks/imports",
                resourceKey: "tasks",
                importOnly: true,
                fields: { project_id: currentProjectId, collection_id: currentCollectionId },
                disabled: !currentProjectId || !currentCollectionId || currentCollectionId === "all",
                disabledReason: "Select a project and collection before importing tasks",
            }}
            icon={ListChecks}
            columns={COLUMNS}
            rows={rows}
            formFields={FORM_FIELDS}
            loading={loading}
            serverSide={true}
            totalRows={totalRows}
            rowKey="task_id"
            onTableStateChange={handleTableChange}
            defaultSortKey="task_id"
            defaultSortDir="asc"
            onViewCustom={handleView}
            viewRequiresSingle={false}
            onExportCustom={handleExport}
            onDeleteCustom={handleDelete}
            hideAdd={true}
            hideEdit={true}
            hideView={false}
        />
    )
}
