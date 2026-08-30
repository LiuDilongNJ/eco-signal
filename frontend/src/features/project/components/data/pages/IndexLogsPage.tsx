/**
 * IndexLogsPage - Index Logs 数据页面
 */

import { useState, useCallback, useMemo } from "react"
import { DataPageLayout } from "../DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../DataPageLayout"
import { message } from "@/components/ui"
import {
    formatIndexLogRow,
    indexLogsApi,
    type IndexLogDeleteItem,
    type IndexLogExportParams,
    type ListIndexLogsParams,
} from "../../../../../api/endpoints/indexLogs"
import { useProjectStore } from "../../../stores/useProjectStore"
import { ScrollText } from "lucide-react"
import { downloadFile } from "@/utils/download"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"
import { rowCan } from "../rowCapabilities"

const COLUMNS: ColumnDef[] = [
    { key: "log_id", label: "ID", type: "number", width: "120px", sortable: true, filterable: true },
    { key: "media_name", label: "Media", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "user_name", label: "User", type: "text", width: "160px", sortable: true, filterable: true },
    { key: "index_name", label: "Index Type", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "version", label: "Version", type: "text", width: "120px", sortable: true, filterable: true },
    { key: "min_time", label: "Min T", type: "number", width: "160px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "max_time", label: "Max T", type: "number", width: "160px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "min_frequency", label: "Min F", type: "number", width: "160px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "max_frequency", label: "Max F", type: "number", width: "160px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "variable_type", label: "Var Type", type: "text", width: "150px", sortable: true, filterable: true },
    { key: "variable_order", label: "Var Order", type: "number", width: "160px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "variable_name", label: "Var Name", type: "text", width: "180px", sortable: true, filterable: true },
    { key: "variable_value", label: "Var Value", type: "text", width: "160px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "creation_date", label: "Created", type: "date", width: "180px", sortable: true, filterable: true, filterType: "dateRange" },
]

const FORM_FIELDS: FormFieldDef[] = []

const RANGE_FILTER_PARAMS: Record<string, [keyof ListIndexLogsParams, keyof ListIndexLogsParams]> = {
    min_time: ["min_t_min", "min_t_max"],
    max_time: ["max_t_min", "max_t_max"],
    min_frequency: ["min_f_min", "min_f_max"],
    max_frequency: ["max_f_min", "max_f_max"],
    variable_order: ["var_order_min", "var_order_max"],
    variable_value: ["var_value_min", "var_value_max"],
}

const FILTER_KEY_MAP: Record<string, keyof ListIndexLogsParams> = {
    user_name: "user",
    index_name: "index_type",
    variable_type: "var_type",
    variable_name: "var_name",
}

const ORDER_KEY_MAP: Record<string, string> = {
    log_id: "log_id",
    media_name: "media_name",
    user_name: "user_name",
    index_name: "index_name",
    version: "version",
    min_time: "min_time",
    max_time: "max_time",
    min_frequency: "min_frequency",
    max_frequency: "max_frequency",
    variable_type: "variable_type",
    variable_order: "variable_order",
    variable_name: "variable_name",
    variable_value: "variable_value",
    creation_date: "creation_date",
}

function applyScopeParams(
    params: { project_id?: number; collection_id?: number },
    currentProjectId: number | string | null,
    currentCollectionId: number | string | null,
) {
    if (currentProjectId) {
        params.project_id = Number(currentProjectId)
    }
    if (currentCollectionId && currentCollectionId !== "all") {
        params.collection_id = Number(currentCollectionId)
    }
}

function applyTableFilters(params: ListIndexLogsParams, filters: TableState["filters"]) {
    const writableParams = params as Record<string, string | number | undefined>
    Object.entries(filters).forEach(([key, rawValue]) => {
        if (rawValue === "" || rawValue === null || rawValue === undefined) return
        const value = String(rawValue)
        if (key === "creation_date") {
            const [from, to] = value.split(",")
            if (from) params.creation_date_from = from
            if (to) params.creation_date_to = to
            return
        }
        const rangeParams = RANGE_FILTER_PARAMS[key]
        if (rangeParams) {
            const [minValue, maxValue] = value.split(",")
            if (minValue) writableParams[rangeParams[0]] = minValue
            if (maxValue) writableParams[rangeParams[1]] = maxValue
            return
        }
        const mappedKey = FILTER_KEY_MAP[key] ?? (key as keyof ListIndexLogsParams)
        writableParams[mappedKey] = value
    })
}

export function IndexLogsPage() {
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [tableState, setTableState] = useState<TableState | null>(null)

    const currentProjectId = useProjectStore((s) => s.currentProjectId)
    const currentCollectionId = useProjectStore((s) => s.currentCollectionId)

    const deletePayloadByRowKey = useMemo(() => {
        const mapping = new Map<string, IndexLogDeleteItem>()
        for (const row of rows) {
            const rowKey = row.__key
            const logId = row.log_id
            const mediaId = row.media_id
            const indexId = row.index_id
            if (rowKey === undefined || logId === undefined || mediaId === undefined || indexId === undefined) {
                continue
            }
            mapping.set(String(rowKey), {
                log_id: Number(logId),
                media_id: Number(mediaId),
                index_id: Number(indexId),
            })
        }
        return mapping
    }, [rows])

    const fetchTableData = useCallback(
        async (state: TableState) => {
            setLoading(true)
            try {
                const params: ListIndexLogsParams = {
                    page: state.page,
                    page_size: state.pageSize,
                }

                if (state.sortKey) {
                    params.order_by = ORDER_KEY_MAP[state.sortKey] ?? state.sortKey
                    params.order_dir = state.sortDir || "asc"
                }

                applyTableFilters(params, state.filters)
                applyScopeParams(params, currentProjectId, currentCollectionId)

                const res = await indexLogsApi.getList(params)
                if (res.code !== 0) {
                    throw new Error(res.message || "Failed to load index logs")
                }

                const list = res.data ?? []
                const formattedRows = list.map((r, idx) => formatIndexLogRow(r, idx))
                setRows(formattedRows as RowData[])
                setTotalRows(res.page_info?.total ?? list.length)
            } catch (error) {
                console.error("Failed to fetch index logs:", error)
                message.error("Failed to load index logs")
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

    const handleExport = useCallback(async () => {
        if (!tableState) {
            message.warning("Table is not ready yet.")
            return
        }
        const hide = message.loading("Exporting index logs…", 0)
        try {
            const params: IndexLogExportParams = {}
            if (tableState.sortKey) {
                params.order_by = ORDER_KEY_MAP[tableState.sortKey] ?? tableState.sortKey
                params.order_dir = tableState.sortDir || "asc"
            }
            applyScopeParams(params, currentProjectId, currentCollectionId)

            const download = await indexLogsApi.exportCsv(params)
            downloadFile(download)
            message.success("Export successful")
        } catch (error: unknown) {
            console.error("Export error:", error)
            message.error(error instanceof Error ? error.message : "An error occurred while exporting")
        } finally {
            hide()
        }
    }, [tableState, currentProjectId, currentCollectionId])

    const handleDelete = useCallback(
        async (selectedRowKeys: any[]) => {
            const payload = selectedRowKeys
                .map((key) => deletePayloadByRowKey.get(String(key)))
                .filter((item): item is IndexLogDeleteItem => item !== undefined)

            if (payload.length !== selectedRowKeys.length) {
                message.error("Failed to resolve one or more selected index log groups")
                return
            }

            const hideLoading = message.loading(`Deleting ${payload.length} log group${payload.length > 1 ? "s" : ""}...`, 0)
            try {
                if (!currentProjectId) {
                    message.error("Select a project before deleting index logs")
                    return
                }
                await indexLogsApi.deleteGroups(Number(currentProjectId), payload)
                message.success(`Successfully deleted ${payload.length} log group${payload.length > 1 ? "s" : ""}`)
                if (tableState) {
                    handleTableChange(tableState)
                }
            } catch (error: any) {
                console.error("Failed to delete index logs:", error)
                message.error(error?.message || "Failed to delete index log groups")
            } finally {
                hideLoading()
            }
        },
        [currentProjectId, deletePayloadByRowKey, handleTableChange, tableState],
    )

    return (
        <DataPageLayout
            title="Index Logs"
            importConfig={{
                endpoint: "/v1/index-logs/imports",
                resourceKey: "indexLogs",
                importOnly: true,
                fields: { project_id: currentProjectId, collection_id: currentCollectionId },
                disabled: !currentProjectId || !currentCollectionId || currentCollectionId === "all",
                disabledReason: "Select a project and collection before importing index logs",
            }}
            icon={ScrollText}
            columns={COLUMNS}
            rows={rows}
            formFields={FORM_FIELDS}
            loading={loading}
            serverSide={true}
            totalRows={totalRows}
            rowKey="__key"
            onTableStateChange={handleTableChange}
            defaultSortKey="log_id"
            defaultSortDir="asc"
            onExportCustom={handleExport}
            onDeleteCustom={handleDelete}
            canDeleteRecord={(record) => rowCan(record, "delete")}
            hideView={true}
            hideAdd={true}
            hideEdit={true}
        />
    )
}
