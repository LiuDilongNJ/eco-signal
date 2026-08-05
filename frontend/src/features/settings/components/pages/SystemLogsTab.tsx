import { CustomScrollArea } from "@/components/ui"
import { useCallback, useState } from "react"
import { ConfigProvider, Descriptions, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { ScrollText } from "lucide-react"
import { ApiError } from "../../../../api/client"
import { systemApi, type OperationLogRead } from "../../../../api/endpoints/system"
import { DataPageLayout } from "../../../project/components/data/DataPageLayout"
import type { ColumnDef, RowData, TableState } from "../../../project/components/data/DataPageLayout"
import { useAppStore } from "@/store/useAppStore"
import { useAppDefaultAntdBrandConfig } from "../../../project/hooks/useAntdBrandConfig"
import {
    SETTINGS_DRAWER_BODY_PADDING,
    SETTINGS_DRAWER_WIDTH_STANDARD,
    SettingsDrawerCancelExtra,
    SettingsDrawerTitle,
    getSettingsStageDrawerStyles,
} from "../settingsDrawerUi"
import "../../../project/components/modals/styles/FormDrawer.css"
import "../style/settings-forms.css"
import "../style/camera-settings.css"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "log_id", label: "ID", type: "number", width: "72px", sortable: true, filterable: true },
    { key: "username", label: "User", type: "text", width: "120px", sortable: true, filterable: true },
    { key: "action", label: "Action", type: "text", width: "100px", sortable: true, filterable: true },
    { key: "resource_type", label: "Resource", type: "text", width: "120px", sortable: true, filterable: true },
    { key: "description", label: "Description", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "status_code", label: "Status", type: "number", width: "80px", sortable: true, filterable: true },
    {
        key: "creation_date",
        label: "Created",
        type: "date",
        width: "160px",
        sortable: true,
        filterable: true,
        filterType: "dateRange",
    },
]

export function SystemLogsTab() {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const drawerTheme = useAppDefaultAntdBrandConfig(isDark)
    const [forbidden, setForbidden] = useState(false)
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [, setTableState] = useState<TableState | null>(null)

    const [detailOpen, setDetailOpen] = useState(false)
    const [detailLog, setDetailLog] = useState<OperationLogRead | null>(null)

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const order_by = state.sortKey || "log_id"
            const order_dir: "asc" | "desc" = state.sortDir === "desc" ? "desc" : "asc"

            let date_from: string | undefined
            let date_to: string | undefined
            const cr = state.filters.creation_date?.trim()
            if (cr) {
                const [start, end] = cr.split(",")
                if (start) date_from = start.slice(0, 10)
                if (end) date_to = end.slice(0, 10)
            }

            const logIdRaw = state.filters.log_id?.trim()
            const statusCodeRaw = state.filters.status_code?.trim()

            const res = await systemApi.getOperationLogs({
                page: state.page,
                page_size: state.pageSize,
                log_id: logIdRaw ? Number(logIdRaw) : undefined,
                username: state.filters.username?.trim() || undefined,
                description: state.filters.description?.trim() || undefined,
                status_code: statusCodeRaw ? Number(statusCodeRaw) : undefined,
                search: state.searchQuery?.trim() || undefined,
                action: state.filters.action?.trim() || undefined,
                resource_type: state.filters.resource_type?.trim() || undefined,
                date_from,
                date_to,
                order_by,
                order_dir,
            })

            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load logs")
                setRows([])
                setTotalRows(0)
                return
            }

            const list = res.data ?? []
            setRows(
                list.map((r) => ({
                    ...r,
                    id: r.log_id,
                })) as RowData[],
            )
            setTotalRows(res.page_info?.total ?? list.length)
            setForbidden(false)
        } catch (e: unknown) {
            if (e instanceof ApiError && e.status === 403) {
                setForbidden(true)
                setRows([])
                setTotalRows(0)
                return
            }
            message.error(e instanceof Error ? e.message : "Failed to load logs")
            setRows([])
            setTotalRows(0)
        } finally {
            setLoading(false)
        }
    }, [])

    const scheduleTableFetch = useTableFetchScheduler(fetchTableData)

    const handleTableChange = useCallback((state: TableState) => {
        setTableState(state)
        scheduleTableFetch(state)
    }, [scheduleTableFetch])

    const openDetail = (log: OperationLogRead) => {
        setDetailLog(log)
        setDetailOpen(true)
    }

    if (forbidden) {
        return (
            <div className="settings-form__status settings-form__status--error">
                You do not have permission to view system logs (administrator required).
            </div>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <DataPageLayout
                title="System Logs"
                icon={ScrollText}
                columns={COLUMNS}
                rows={rows}
                defaultSortKey="log_id"
                defaultSortDir="asc"
                antdThemeOverride={drawerTheme}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="id"
                onTableStateChange={handleTableChange}
                formFields={[]}
                hideAdd={true}
                hideEdit={true}
                hideDelete={true}
                hideExport={true}
                onRowDoubleClickCustom={(record) => openDetail(record as unknown as OperationLogRead)}
                onViewCustom={(selectedKeys) => {
                    const log = rows.find((r) => r.id === selectedKeys[0]) as OperationLogRead | undefined
                    if (log) openDetail(log)
                }}
            />

            <FormDrawer
                closable={false}
                title={<SettingsDrawerTitle>Log Details</SettingsDrawerTitle>}
                open={detailOpen}
                maskClosable={false}
                onClose={() => {
                    setDetailOpen(false)
                    setDetailLog(null)
                }}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_STANDARD)}
                extra={
                    <SettingsDrawerCancelExtra
                        onClose={() => {
                            setDetailOpen(false)
                            setDetailLog(null)
                        }}
                    />
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                        {detailLog && (
                            <Descriptions column={1} size="small" bordered className="camera-settings__detail-meta">
                                <Descriptions.Item label="Log ID">{detailLog.log_id}</Descriptions.Item>
                                <Descriptions.Item label="User">{detailLog.username || `ID: ${detailLog.user_id}`}</Descriptions.Item>
                                <Descriptions.Item label="Action">{detailLog.action}</Descriptions.Item>
                                <Descriptions.Item label="Resource Type">{detailLog.resource_type}</Descriptions.Item>
                                <Descriptions.Item label="Resource ID">{detailLog.resource_id || "-"}</Descriptions.Item>
                                <Descriptions.Item label="Status Code">{detailLog.status_code}</Descriptions.Item>
                                <Descriptions.Item label="IP Address">{detailLog.req_ip || "-"}</Descriptions.Item>
                                <Descriptions.Item label="Endpoint">{detailLog.req_endpoint || "-"}</Descriptions.Item>
                                <Descriptions.Item label="Created At">{detailLog.creation_date}</Descriptions.Item>
                                <Descriptions.Item label="Description">{detailLog.description || "-"}</Descriptions.Item>
                                <Descriptions.Item label="Payload">
                                    <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all", maxHeight: "300px", overflow: "auto" }}>
                                        {detailLog.payload ? JSON.stringify(detailLog.payload, null, 2) : "-"}
                                    </pre>
                                </Descriptions.Item>
                            </Descriptions>
                        )}
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
