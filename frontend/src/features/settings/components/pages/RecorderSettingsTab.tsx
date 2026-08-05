import { CustomScrollArea } from "@/components/ui"
import { useCallback, useState } from "react"
import { ConfigProvider, Descriptions, Form, Input, Space, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { FileUp, Info, Mic, Plus } from "lucide-react"
import { ApiError } from "../../../../api/client"
import { recordersApi, type RecorderPublic } from "../../../../api/endpoints/recorders"
import { DataPageLayout } from "../../../project/components/data/DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../../../project/components/data/DataPageLayout"
import { useAppStore } from "@/store/useAppStore"
import { useAppDefaultAntdBrandConfig } from "../../../project/hooks/useAntdBrandConfig"
import {
    SETTINGS_DRAWER_BODY_PADDING,
    SETTINGS_DRAWER_WIDTH_COMPACT,
    SettingsDetailLoading,
    SettingsDrawerCancelExtra,
    SettingsDrawerFormExtra,
    SettingsDrawerTitle,
    getSettingsStageDrawerStyles,
} from "../settingsDrawerUi"
import "../../../project/components/modals/styles/FormDrawer.css"
import { renderRequiredLabel } from "../../utils/formValidation"
import "../style/settings-forms.css"
import "../style/camera-settings.css"
import { downloadFile } from "@/utils/download"
import { renderSettingsRelationPills } from "../settingsRelationPills"
import { SettingsRelationDetailList } from "../SettingsRelationDetailList"
import { buildRecorderWritePayload } from "../../utils/settingsPayload"
import { useSettingsCsvImport } from "../../utils/useSettingsCsvImport"
import { CsvImportInstructionsDrawer } from "../CsvImportInstructionsDrawer"
import { SETTINGS_CSV_IMPORT_CONFIG } from "../../utils/settingsCsvImportConfig"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "recorder_id", label: "ID", type: "number", width: "72px", sortable: true, filterable: true },
    { key: "uuid", label: "UUID", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "name", label: "Name", type: "text", width: "160px", sortable: true, filterable: true },
    { key: "version", label: "Version", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "brand", label: "Brand", type: "text", width: "120px", sortable: true, filterable: true },
    {
        key: "microphone_count",
        label: "Microphones",
        type: "number",
        width: "240px",
        sortable: true,
        filterable: true,
        renderCell: renderSettingsRelationPills,
    },
]

const FORM_FIELDS: FormFieldDef[] = [
    { key: "name", label: "Name", type: "text" },
    { key: "version", label: "Version", type: "text" },
    { key: "brand", label: "Brand", type: "text" },
]

function orderByForApi(sortKey: string | null): string {
    if (
        sortKey === "recorder_id" ||
        sortKey === "uuid" ||
        sortKey === "name" ||
        sortKey === "version" ||
        sortKey === "brand" ||
        sortKey === "microphone_count"
    ) return sortKey
    return "recorder_id"
}

type RecorderFormValues = {
    name?: string
    version?: string
    brand?: string
}

export function RecorderSettingsTab() {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const drawerTheme = useAppDefaultAntdBrandConfig(isDark)
    const [forbidden, setForbidden] = useState(false)
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [tableState, setTableState] = useState<TableState | null>(null)

    const [formOpen, setFormOpen] = useState(false)
    const [formMode, setFormMode] = useState<"create" | "edit">("create")
    const [editingId, setEditingId] = useState<number | null>(null)
    const [formSaving, setFormSaving] = useState(false)
    const [form] = Form.useForm<RecorderFormValues>()

    const [detailOpen, setDetailOpen] = useState(false)
    const [detailRecorder, setDetailRecorder] = useState<RecorderPublic | null>(null)
    const [detailLoading, setDetailLoading] = useState(false)
    const csvImport = useSettingsCsvImport("recorders", recordersApi.importCsv, () => tableState && handleTableChange(tableState))

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const order_by = orderByForApi(state.sortKey)
            const order_dir: "asc" | "desc" = state.sortDir === "desc" ? "desc" : "asc"
            const recorderIdRaw = state.filters.recorder_id?.trim()
            const res = await recordersApi.list({
                page: state.page,
                page_size: state.pageSize,
                recorder_id: recorderIdRaw ? Number(recorderIdRaw) : undefined,
                uuid: state.filters.uuid?.trim() || undefined,
                name: (state.searchQuery?.trim() || state.filters.name?.trim()) || undefined,
                version: state.filters.version?.trim() || undefined,
                brand: state.filters.brand?.trim() || undefined,
                microphone_count: state.filters.microphone_count?.trim() || undefined,
                order_by,
                order_dir,
            })
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load recorders")
                setRows([])
                setTotalRows(0)
                return
            }
            const list = res.data ?? []
            setRows(
                list.map((r) => ({
                    recorder_id: r.recorder_id,
                    id: r.recorder_id,
                    uuid: String(r.uuid),
                    name: r.name ?? "",
                    version: r.version ?? "",
                    brand: r.brand ?? "",
                    microphone_count: r.microphone_count || 0,
                } as RowData)),
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
            message.error(e instanceof Error ? e.message : "Failed to load recorders")
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

    const openCreate = () => {
        setFormMode("create")
        setEditingId(null)
        form.resetFields()
        setFormOpen(true)
    }

    const handleEdit = async (selectedKeys: unknown[]) => {
        if (selectedKeys.length !== 1) {
            message.warning("Please select exactly one recorder to edit")
            return
        }
        const id = selectedKeys[0] as number
        setFormOpen(true)
        setFormMode("edit")
        setEditingId(id)
        try {
            const res = await recordersApi.get(id)
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load recorder")
                setFormOpen(false)
                return
            }
            const r = res.data!
            form.setFieldsValue({
                name: r.name,
                version: r.version,
                brand: r.brand,
            })
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Failed to load recorder")
            setFormOpen(false)
        }
    }

    const submitForm = async () => {
        try {
            const vals = await form.validateFields()
            setFormSaving(true)
            const payload = buildRecorderWritePayload(vals)
            if (formMode === "create") {
                const res = await recordersApi.create(payload)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Create failed")
                    return
                }
                message.success("Recorder created")
            } else if (editingId != null) {
                const res = await recordersApi.update(editingId, payload)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Update failed")
                    return
                }
                message.success("Saved")
            }
            setFormOpen(false)
            if (tableState) handleTableChange(tableState)
        } catch (e: unknown) {
            if (e && typeof e === "object" && "errorFields" in e) return
            message.error(e instanceof Error ? e.message : "Save failed")
        } finally {
            setFormSaving(false)
        }
    }

    const openDetail = async (recorderId: number) => {
        setDetailOpen(true)
        setDetailLoading(true)
        setDetailRecorder(null)
        try {
            const res = await recordersApi.get(recorderId)
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load detail")
                setDetailOpen(false)
                return
            }
            setDetailRecorder(res.data!)
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Failed to load detail")
            setDetailOpen(false)
        } finally {
            setDetailLoading(false)
        }
    }

    const handleDelete = async (selectedKeys: unknown[]) => {
        const hideLoading = message.loading(`Deleting ${selectedKeys.length} record(s)...`, 0)
        try {
            for (const id of selectedKeys) {
                const res = await recordersApi.delete(id as number)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Delete failed")
                    return
                }
            }
            message.success(`Deleted ${selectedKeys.length} record(s)`)
            if (tableState) handleTableChange(tableState)
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Delete failed")
        } finally {
            hideLoading()
        }
    }

    const handleExport = async () => {
        if (!tableState) {
            message.warning("Table is not ready yet.")
            return
        }
        const hide = message.loading("Exporting recorders…", 0)
        try {
            const order_by = orderByForApi(tableState.sortKey)
            const order_dir: "asc" | "desc" = tableState.sortDir === "desc" ? "desc" : "asc"
            const base = {
                name: tableState.filters.name?.trim() || undefined,
                brand: tableState.filters.brand?.trim() || undefined,
                version: tableState.filters.version?.trim() || undefined,
                recorder_id: tableState.filters.recorder_id || undefined,
                uuid: tableState.filters.uuid?.trim() || undefined,
                microphone_count: tableState.filters.microphone_count || undefined,
                order_by,
                order_dir,
            }
            const download = await recordersApi.exportCsv(base)
            downloadFile(download)
            message.success("Export successful")
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Export failed")
        } finally {
            hide()
        }
    }

    if (forbidden) {
        return (
            <div className="settings-form__status settings-form__status--error">
                You do not have permission to manage recorders (admin required). Contact an administrator if you need
                access.
            </div>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            {csvImport.input}
            <DataPageLayout
                title="Recorders"
                icon={Mic}
                columns={COLUMNS}
                rows={rows}
                defaultSortKey="recorder_id"
                defaultSortDir="asc"
                formFields={FORM_FIELDS}
                antdThemeOverride={drawerTheme}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="id"
                onTableStateChange={handleTableChange}
                addDropdownItems={[
                    { key: "new", label: "New Recorder", icon: <Plus size={14} />, onClick: openCreate },
                    { key: "import", label: "Import CSV", icon: <FileUp size={14} />, onClick: csvImport.triggerImport },
                    { key: "instructions", label: "CSV Instructions", icon: <Info size={14} />, onClick: csvImport.showInstructions },
                ]}
                addDisabled={csvImport.importing}
                onEditCustom={handleEdit}
                onDeleteCustom={handleDelete}
                onExportCustom={handleExport}
                onViewCustom={(selectedKeys) => void openDetail(selectedKeys[0] as number)}
            />

            <FormDrawer
                closable={false}
                title={
                    <SettingsDrawerTitle>
                        {formMode === "create" ? "New Recorder" : "Edit Recorder"}
                    </SettingsDrawerTitle>
                }
                open={formOpen}
                maskClosable={false}
                onClose={() => setFormOpen(false)}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_COMPACT)}
                extra={
                    <SettingsDrawerFormExtra
                        onClose={() => setFormOpen(false)}
                        onSave={() => void submitForm()}
                        saving={formSaving}
                    />
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                        <Form
                            form={form}
                            layout="vertical"
                            requiredMark={false}
                            className="shared-drawer-form"
                        >
                            <Form.Item
                                name="name"
                                label={renderRequiredLabel("Name")}
                                rules={[
                                    { required: true, message: "Enter a name" },
                                    { max: 100, message: "Name must be at most 100 characters" },
                                ]}
                            >
                                <Input maxLength={100} />
                            </Form.Item>
                            <Form.Item name="version" label="Version" rules={[{ max: 100, message: "Version must be at most 100 characters" }]}>
                                <Input maxLength={100} />
                            </Form.Item>
                            <Form.Item name="brand" label="Brand" rules={[{ max: 100, message: "Brand must be at most 100 characters" }]}>
                                <Input maxLength={100} />
                            </Form.Item>
                        </Form>
                    </div>
                </CustomScrollArea>
            </FormDrawer>

            <FormDrawer
                closable={false}
                title={<SettingsDrawerTitle>Recorder Details</SettingsDrawerTitle>}
                open={detailOpen}
                maskClosable={false}
                onClose={() => {
                    setDetailOpen(false)
                    setDetailRecorder(null)
                }}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_COMPACT)}
                extra={
                    <SettingsDrawerCancelExtra
                        onClose={() => {
                            setDetailOpen(false)
                            setDetailRecorder(null)
                        }}
                        disabled={detailLoading}
                    />
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                        {detailLoading ? (
                            <SettingsDetailLoading />
                        ) : detailRecorder ? (
                            <Space direction="vertical" size="large" style={{ width: "100%" }}>
                                <Descriptions column={1} size="small" className="camera-settings__detail-meta" bordered>
                                    <Descriptions.Item label="ID">{detailRecorder.recorder_id}</Descriptions.Item>
                                    <Descriptions.Item label="UUID">{String(detailRecorder.uuid)}</Descriptions.Item>
                                    <Descriptions.Item label="Name">{detailRecorder.name || "-"}</Descriptions.Item>
                                    <Descriptions.Item label="Version">{detailRecorder.version || "-"}</Descriptions.Item>
                                    <Descriptions.Item label="Brand">{detailRecorder.brand || "-"}</Descriptions.Item>
                                </Descriptions>

                                <SettingsRelationDetailList
                                    title="Linked Microphones"
                                    fallbackLabel="Microphone"
                                    emptyMessage="No microphones associated with this recorder."
                                    isDark={isDark}
                                    items={detailRecorder.microphones.map((microphone) => ({
                                        id: microphone.microphone_id,
                                        name: microphone.name,
                                        isDefault: microphone.is_default,
                                        notes: microphone.notes,
                                    }))}
                                />
                            </Space>
                        ) : null}
                    </div>
                </CustomScrollArea>
            </FormDrawer>
            <CsvImportInstructionsDrawer config={SETTINGS_CSV_IMPORT_CONFIG.recorders} isDark={isDark} open={csvImport.instructionsOpen} onClose={csvImport.hideInstructions} />
        </ConfigProvider>
    )
}
