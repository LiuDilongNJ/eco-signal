/**
 * QueuePage - Queue 数据页面
 */

import { useState, useCallback } from "react"
import { DataPageLayout } from "../DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../DataPageLayout"
import { message, Tooltip } from "@/components/ui"
import { queueApi } from "../../../../../api/endpoints/queue"
import type { QueueExportParams, QueueListItem, QueueQueryParams } from "../../../../../api/endpoints/queue"
import { Activity } from "lucide-react"
import { downloadFile } from "@/utils/download"
import { applyQueueFilters, resolveQueueOrderBy } from "./queueQueryParams"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "queue_id", label: "ID", type: "number", width: "220px", sortable: true, filterable: true },
    { key: "type", label: "Type", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "user", label: "User", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "completed", label: "Completed", type: "number", width: "220px", sortable: true, filterable: true },
    { key: "total", label: "Total", type: "number", width: "220px", sortable: true, filterable: true },
    {
        key: "status",
        label: "Status",
        type: "badge",
        badgeSemantic: "queue",
        width: "220px",
        sortable: true,
        filterable: true,
    },
    { key: "start_time", label: "Start Time", type: "date", width: "220px", sortable: true, filterable: true, filterType: "dateRange" },
    { key: "stop_time", label: "Stop Time", type: "date", width: "220px", sortable: true, filterable: true, filterType: "dateRange" },
    {
        key: "error",
        label: "Error",
        type: "text",
        width: "220px",
        sortable: true,
        filterable: true,
        renderCell: (value) => {
            const error = value == null ? "" : String(value)
            if (!error) return null
            return (
                <Tooltip title={error}>
                    <span className="dpl-cell-text">{error}</span>
                </Tooltip>
            )
        },
    },
    {
        key: "warning",
        label: "Warning",
        type: "text",
        width: "220px",
        sortable: true,
        filterable: true,
        renderCell: (value) => {
            const warning = value == null ? "" : String(value)
            if (!warning) return null
            return (
                <Tooltip title={warning}>
                    <span className="dpl-cell-text">{warning}</span>
                </Tooltip>
            )
        },
    },
]

const FORM_FIELDS: FormFieldDef[] = []

export function QueuePage() {
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [tableState, setTableState] = useState<TableState | null>(null)

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const params: QueueQueryParams & Record<string, unknown> = {
                page: state.page,
                page_size: state.pageSize,
            }

            const resolvedOrderBy = resolveQueueOrderBy(state.sortKey)
            if (resolvedOrderBy) {
                params.order_by = resolvedOrderBy
                params.order_dir = state.sortDir || "asc"
            }

            applyQueueFilters(params, state.filters)

            const res = await queueApi.getList(params)
            if (res && res.data) {
                const formattedRows = res.data.map((r: QueueListItem, idx: number) => ({
                    ...r,
                    __key: `${r.queue_id}_${idx}`,
                    id: r.queue_id,
                    queue_id: r.queue_id,
                    start_time: r.start_time,
                    stop_time: r.stop_time,
                    user: r.username,
                }))
                setRows(formattedRows as RowData[])
                setTotalRows(res.page_info ? res.page_info.total : (res.data.length || 0))
            }
        } catch (error) {
            console.error("Failed to fetch queue list:", error)
            message.error("Failed to load queue data")
        } finally {
            setLoading(false)
        }
    }, [])

    const scheduleTableFetch = useTableFetchScheduler(fetchTableData)

    const handleTableChange = useCallback((state: TableState) => {
        setTableState(state)
        scheduleTableFetch(state)
    }, [scheduleTableFetch])

    const handleExport = useCallback(async () => {
        try {
            setLoading(true)
            const params: QueueExportParams = {}
            if (tableState) {
                const resolvedOrderBy = resolveQueueOrderBy(tableState.sortKey)
                if (resolvedOrderBy) {
                    params.order_by = resolvedOrderBy
                    params.order_dir = tableState.sortDir || "asc"
                }
            }

            const download = await queueApi.exportCsv(params)
            downloadFile(download)
        } catch (error: unknown) {
            console.error("Export error:", error)
            message.error(error instanceof Error ? error.message : "An error occurred while exporting")
        } finally {
            setLoading(false)
        }
    }, [tableState])

    const handleDelete = useCallback(async (selectedKeys: unknown[]) => {
        const selectedKeySet = new Set(selectedKeys.map((key) => String(key)))
        const queueIds = Array.from(new Set(
            rows
                .filter((row) => selectedKeySet.has(String(row.__key ?? row.queue_id ?? row.id)))
                .map((row) => Number(row.queue_id ?? row.id))
                .filter((id) => Number.isFinite(id) && id > 0),
        ))

        if (queueIds.length === 0) {
            message.warning("No deletable queue item selected")
            return
        }

        try {
            setLoading(true)
            const res: any = await queueApi.deleteItems(queueIds)
            if (res && typeof res === "object" && "code" in res && res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to delete queue items")
                return
            }
            const result = res?.data
            if (result?.deleted_ids?.length) {
                const label = result.deleted_ids.length === 1 ? "Task" : "Tasks"
                message.success(`${label} deleted successfully`)
            }
            if (result?.cancelling_ids?.length) {
                const label = result.cancelling_ids.length === 1 ? "Task" : "Tasks"
                message.warning(`${label} deletion requested`)
            }
            if (result?.unavailable_ids?.length) {
                const label = result.unavailable_ids.length === 1 ? "Task" : "Tasks"
                message.error(`${label} failed to delete`)
            }
            if (!result?.deleted_ids?.length && !result?.cancelling_ids?.length && !result?.unavailable_ids?.length) {
                message.warning("No tasks were deleted")
            }
            if (tableState) {
                handleTableChange(tableState)
            }
        } catch (error: any) {
            console.error("Delete queue error:", error)
            message.error(error?.message || "Failed to delete tasks")
        } finally {
            setLoading(false)
        }
    }, [rows, tableState, handleTableChange])

    return (
        <DataPageLayout
            title="Queue"
            icon={Activity}
            columns={COLUMNS}
            rows={rows}
            formFields={FORM_FIELDS}
            loading={loading}
            serverSide={true}
            totalRows={totalRows}
            rowKey="__key"
            onTableStateChange={handleTableChange}
            defaultSortKey="queue_id"
            defaultSortDir="asc"
            onExportCustom={handleExport}
            onDeleteCustom={handleDelete}
            hideView={true}
            hideAdd={true}
            hideEdit={true}
        />
    )
}
