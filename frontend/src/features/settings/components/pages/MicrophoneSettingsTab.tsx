import { CustomScrollArea } from "@/components/ui"
import { useCallback, useState } from "react"
import { ConfigProvider, Descriptions, Form, Input, InputNumber, Space, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { FileUp, Info, Mic, Plus } from "lucide-react"
import { ApiError } from "../../../../api/client"
import { microphonesApi, type MicrophonePublic } from "../../../../api/endpoints/microphones"
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
import { buildMicrophoneWritePayload } from "../../utils/settingsPayload"
import { useSettingsCsvImport } from "../../utils/useSettingsCsvImport"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "microphone_id", label: "ID", type: "number", width: "72px", sortable: true, filterable: true },
    { key: "uuid", label: "UUID", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "name", label: "Name", type: "text", width: "160px", sortable: true, filterable: true },
    { key: "microphone_element", label: "Element", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "sensitivity", label: "Sensitivity", type: "number", width: "120px", sortable: true, filterable: true, filterType: 'numberRange' },
    { key: "signal_to_noise_ratio", label: "Signal to Noise Ratio", type: "number", width: "120px", sortable: true, filterable: true, filterType: 'numberRange' },
    {
        key: "recorder_count",
        label: "Recorders",
        type: "number",
        width: "240px",
        sortable: true,
        filterable: true,
        renderCell: renderSettingsRelationPills,
    },
]

const FORM_FIELDS: FormFieldDef[] = [
    { key: "name", label: "Name", type: "text" },
    { key: "microphone_element", label: "Element", type: "text" },
    { key: "sensitivity", label: "Sensitivity", type: "number" },
    { key: "signal_to_noise_ratio", label: "Signal to Noise Ratio", type: "number" },
]

function orderByForApi(sortKey: string | null): string {
    if (
        sortKey === "microphone_id" ||
        sortKey === "uuid" ||
        sortKey === "name" ||
        sortKey === "microphone_element" ||
        sortKey === "sensitivity" ||
        sortKey === "signal_to_noise_ratio" ||
        sortKey === "recorder_count"
    ) return sortKey
    return "microphone_id"
}

type MicrophoneFormValues = {
    name?: string
    microphone_element?: string
    sensitivity?: number
    signal_to_noise_ratio?: number
}

export function MicrophoneSettingsTab() {
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
    const [form] = Form.useForm<MicrophoneFormValues>()

    const [detailOpen, setDetailOpen] = useState(false)
    const [detailMicrophone, setDetailMicrophone] = useState<MicrophonePublic | null>(null)
    const [detailLoading, setDetailLoading] = useState(false)
    const csvImport = useSettingsCsvImport("microphones", microphonesApi.importCsv, () => tableState && handleTableChange(tableState))

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const order_by = orderByForApi(state.sortKey)
            const order_dir: "asc" | "desc" = state.sortDir === "desc" ? "desc" : "asc"
            const microphoneIdRaw = state.filters.microphone_id?.trim()
            const res = await microphonesApi.list({
                page: state.page,
                page_size: state.pageSize,
                microphone_id: microphoneIdRaw ? Number(microphoneIdRaw) : undefined,
                uuid: state.filters.uuid?.trim() || undefined,
                name: (state.searchQuery?.trim() || state.filters.name?.trim()) || undefined,
                microphone_element: state.filters.microphone_element?.trim() || undefined,
                sensitivity: state.filters.sensitivity || undefined,
                signal_to_noise_ratio: state.filters.signal_to_noise_ratio || undefined,
                recorder_count: state.filters.recorder_count?.trim() || undefined,
                order_by,
                order_dir,
            })
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load microphones")
                setRows([])
                setTotalRows(0)
                return
            }
            const list = res.data ?? []
            setRows(
                list.map((r) => ({
                    microphone_id: r.microphone_id,
                    id: r.microphone_id,
                    uuid: String(r.uuid),
                    name: r.name ?? "",
                    microphone_element: r.microphone_element ?? "",
                    sensitivity: r.sensitivity ?? null,
                    signal_to_noise_ratio: r.signal_to_noise_ratio ?? null,
                    recorder_count: r.recorder_count || 0,
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
            message.error(e instanceof Error ? e.message : "Failed to load microphones")
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
            message.warning("Please select exactly one microphone to edit")
            return
        }
        const id = selectedKeys[0] as number
        setFormOpen(true)
        setFormMode("edit")
        setEditingId(id)
        try {
            const res = await microphonesApi.get(id)
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load microphone")
                setFormOpen(false)
                return
            }
            const r = res.data!
            form.setFieldsValue({
                name: r.name,
                microphone_element: r.microphone_element,
                sensitivity: r.sensitivity,
                signal_to_noise_ratio: r.signal_to_noise_ratio,
            })
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Failed to load microphone")
            setFormOpen(false)
        }
    }

    const submitForm = async () => {
        try {
            const vals = await form.validateFields()
            setFormSaving(true)
            const payload = buildMicrophoneWritePayload(vals)
            if (formMode === "create") {
                const res = await microphonesApi.create(payload)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Create failed")
                    return
                }
                message.success("Microphone created")
            } else if (editingId != null) {
                const res = await microphonesApi.update(editingId, payload)
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

    const openDetail = async (microphoneId: number) => {
        setDetailOpen(true)
        setDetailLoading(true)
        setDetailMicrophone(null)
        try {
            const res = await microphonesApi.get(microphoneId)
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load detail")
                setDetailOpen(false)
                return
            }
            setDetailMicrophone(res.data!)
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
                const res = await microphonesApi.delete(id as number)
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
        const hide = message.loading("Exporting microphones…", 0)
        try {
            const order_by = orderByForApi(tableState.sortKey)
            const order_dir: "asc" | "desc" = tableState.sortDir === "desc" ? "desc" : "asc"
            const base = {
                name: tableState.filters.name?.trim() || undefined,
                microphone_element: tableState.filters.microphone_element?.trim() || undefined,
                sensitivity: tableState.filters.sensitivity || undefined,
                signal_to_noise_ratio: tableState.filters.signal_to_noise_ratio || undefined,
                microphone_id: tableState.filters.microphone_id || undefined,
                uuid: tableState.filters.uuid?.trim() || undefined,
                order_by,
                order_dir,
            }
            const download = await microphonesApi.exportCsv(base)
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
                You do not have permission to manage microphones (admin required). Contact an administrator if you need
                access.
            </div>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            {csvImport.input}
            <DataPageLayout
                title="Microphones"
                icon={Mic}
                columns={COLUMNS}
                rows={rows}
                defaultSortKey="microphone_id"
                defaultSortDir="asc"
                formFields={FORM_FIELDS}
                antdThemeOverride={drawerTheme}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="id"
                onTableStateChange={handleTableChange}
                addDropdownItems={[
                    { key: "new", label: "New Microphone", icon: <Plus size={14} />, onClick: openCreate },
                    { type: "divider" as const },
                    { key: "import", label: "Import Data", icon: <FileUp size={14} />, onClick: csvImport.triggerImport },
                    { key: "instructions", label: "Import Instructions", icon: <Info size={14} />, onClick: csvImport.showInstructions },
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
                        {formMode === "create" ? "New Microphone" : "Edit Microphone"}
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
                            <Form.Item
                                name="microphone_element"
                                label="Element"
                                rules={[{ max: 100, message: "Element must be at most 100 characters" }]}
                            >
                                <Input maxLength={100} />
                            </Form.Item>
                            <Form.Item name="sensitivity" label="Sensitivity">
                                <InputNumber style={{ width: '100%' }} />
                            </Form.Item>
                            <Form.Item name="signal_to_noise_ratio" label="Signal to Noise Ratio">
                                <InputNumber style={{ width: '100%' }} />
                            </Form.Item>
                        </Form>
                    </div>
                </CustomScrollArea>
            </FormDrawer>

            <FormDrawer
                closable={false}
                title={<SettingsDrawerTitle>Microphone Details</SettingsDrawerTitle>}
                open={detailOpen}
                maskClosable={false}
                onClose={() => {
                    setDetailOpen(false)
                    setDetailMicrophone(null)
                }}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_COMPACT)}
                extra={
                    <SettingsDrawerCancelExtra
                        onClose={() => {
                            setDetailOpen(false)
                            setDetailMicrophone(null)
                        }}
                        disabled={detailLoading}
                    />
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                        {detailLoading ? (
                            <SettingsDetailLoading />
                        ) : detailMicrophone ? (
                            <Space direction="vertical" size="large" style={{ width: "100%" }}>
                                <Descriptions column={1} size="small" className="camera-settings__detail-meta" bordered>
                                    <Descriptions.Item label="ID">{detailMicrophone.microphone_id}</Descriptions.Item>
                                    <Descriptions.Item label="UUID">{String(detailMicrophone.uuid)}</Descriptions.Item>
                                    <Descriptions.Item label="Name">{detailMicrophone.name || "-"}</Descriptions.Item>
                                    <Descriptions.Item label="Element">
                                        {detailMicrophone.microphone_element || "-"}
                                    </Descriptions.Item>
                                    <Descriptions.Item label="Sensitivity">
                                        {detailMicrophone.sensitivity != null
                                            ? `${detailMicrophone.sensitivity} dB`
                                            : "-"}
                                    </Descriptions.Item>
                                    <Descriptions.Item label="SNR">
                                        {detailMicrophone.signal_to_noise_ratio != null
                                            ? `${detailMicrophone.signal_to_noise_ratio} dB`
                                            : "-"}
                                    </Descriptions.Item>
                                </Descriptions>
                                <SettingsRelationDetailList
                                    title="Linked Recorders"
                                    fallbackLabel="Recorder"
                                    emptyMessage="No recorders associated with this microphone."
                                    isDark={isDark}
                                    items={detailMicrophone.recorders.map((recorder) => ({
                                        id: recorder.recorder_id,
                                        name: recorder.name,
                                        notes: recorder.notes,
                                    }))}
                                />
                            </Space>
                        ) : null}
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}

export default MicrophoneSettingsTab
