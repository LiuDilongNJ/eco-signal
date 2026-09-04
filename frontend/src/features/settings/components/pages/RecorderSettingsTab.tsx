import { CustomScrollArea } from "@/components/ui"
import { useCallback, useState } from "react"
import { Button, ConfigProvider, Descriptions, Form, Input, Modal, Select, Space, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { CassetteTape, FileUp, Info, Link2, Plus } from "lucide-react"
import { ApiError } from "../../../../api/client"
import { recordersApi, type RecorderPublic } from "../../../../api/endpoints/recorders"
import { fetchMicrophoneListAll, microphonesApi, type MicrophoneListItem, type MicrophonePublic } from "../../../../api/endpoints/microphones"
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
        tooltip: "Number of microphones associated with this recorder",
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

type RecorderMicrophoneFormValues = {
    microphone_id: number
    notes?: string
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
    const [microphoneDetailOpen, setMicrophoneDetailOpen] = useState(false)
    const [microphoneDetail, setMicrophoneDetail] = useState<MicrophonePublic | null>(null)
    const [microphoneDetailLoading, setMicrophoneDetailLoading] = useState(false)
    const [viewingMicrophoneId, setViewingMicrophoneId] = useState<number | null>(null)
    const [relationFormOpen, setRelationFormOpen] = useState(false)
    const [relationSaving, setRelationSaving] = useState(false)
    const [relationLoading, setRelationLoading] = useState(false)
    const [removingMicrophoneId, setRemovingMicrophoneId] = useState<number | null>(null)
    const [relationRecorderId, setRelationRecorderId] = useState<number | null>(null)
    const [availableMicrophones, setAvailableMicrophones] = useState<MicrophoneListItem[]>([])
    const [relationForm] = Form.useForm<RecorderMicrophoneFormValues>()
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

    const reloadDetail = async () => {
        if (!detailRecorder) return
        const response = await recordersApi.get(detailRecorder.recorder_id)
        if (response.code === 0 || response.code === 200) setDetailRecorder(response.data!)
    }

    const openMicrophoneDetail = async (microphoneId: number) => {
        setMicrophoneDetailOpen(true)
        setMicrophoneDetailLoading(true)
        setViewingMicrophoneId(microphoneId)
        setMicrophoneDetail(null)
        try {
            const response = await microphonesApi.get(microphoneId)
            if (response.code !== 0 && response.code !== 200) {
                message.error(response.message || "Failed to load microphone detail")
                setMicrophoneDetailOpen(false)
                return
            }
            setMicrophoneDetail(response.data!)
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Failed to load microphone detail")
            setMicrophoneDetailOpen(false)
        } finally {
            setMicrophoneDetailLoading(false)
            setViewingMicrophoneId(null)
        }
    }

    const openRelationForm = async (recorderId: number) => {
        setRelationRecorderId(recorderId)
        relationForm.resetFields()
        setRelationFormOpen(true)
        setRelationLoading(true)
        try {
            const [recorderResponse, microphoneResponse] = await Promise.all([
                recordersApi.get(recorderId),
                fetchMicrophoneListAll({ order_by: "name", order_dir: "asc" }),
            ])
            if (recorderResponse.code !== 0 && recorderResponse.code !== 200) {
                message.error(recorderResponse.message || "Failed to load recorder")
                setAvailableMicrophones([])
                return
            }
            if (microphoneResponse.errorMessage) {
                message.error(microphoneResponse.errorMessage)
                setAvailableMicrophones([])
                return
            }
            setDetailRecorder(recorderResponse.data!)
            const linkedIds = new Set(recorderResponse.data?.microphones.map((microphone) => microphone.microphone_id) ?? [])
            setAvailableMicrophones(microphoneResponse.data.filter((microphone) => !linkedIds.has(microphone.microphone_id)))
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Failed to load microphones")
            setAvailableMicrophones([])
        } finally {
            setRelationLoading(false)
        }
    }

    const submitRelation = async () => {
        if (relationRecorderId == null) return
        try {
            const values = await relationForm.validateFields()
            setRelationSaving(true)
            const response = await recordersApi.addMicrophone(relationRecorderId, {
                microphone_id: values.microphone_id,
                notes: values.notes?.trim() || null,
            })
            if (response.code !== 0 && response.code !== 200) {
                message.error(response.message || "Failed to associate microphone")
                return
            }
            message.success("Microphone associated")
            setRelationFormOpen(false)
            if (detailRecorder?.recorder_id === relationRecorderId) await reloadDetail()
            if (tableState) handleTableChange(tableState)
        } catch (e: unknown) {
            if (e && typeof e === "object" && "errorFields" in e) return
            message.error(e instanceof Error ? e.message : "Failed to associate microphone")
        } finally {
            setRelationSaving(false)
        }
    }

    const confirmRemoveMicrophone = (microphoneId: number, microphoneName?: string | null) => {
        Modal.confirm({
            title: "Remove microphone association?",
            content: `Remove ${microphoneName || `Microphone #${microphoneId}`} from this recorder?`,
            okText: "Remove",
            cancelText: "Cancel",
            okButtonProps: { danger: true, className: "settings-form-modal-ok" },
            cancelButtonProps: { className: "settings-form-modal-cancel" },
            onOk: async () => {
                if (!detailRecorder) return
                setRemovingMicrophoneId(microphoneId)
                try {
                    const response = await recordersApi.removeMicrophone(detailRecorder.recorder_id, microphoneId)
                    if (response.code !== 0 && response.code !== 200) {
                        message.error(response.message || "Failed to remove association")
                        return
                    }
                    message.success("Microphone association removed")
                    await reloadDetail()
                    if (tableState) handleTableChange(tableState)
                } catch (e: unknown) {
                    message.error(e instanceof Error ? e.message : "Failed to remove association")
                } finally {
                    setRemovingMicrophoneId(null)
                }
            },
        })
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
                icon={CassetteTape}
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
                    { type: "divider" as const },
                    { key: "import", label: "Import Data", icon: <FileUp size={14} />, onClick: csvImport.triggerImport },
                    { key: "instructions", label: "Import Instructions", icon: <Info size={14} />, onClick: csvImport.showInstructions },
                ]}
                addDisabled={csvImport.importing}
                onEditCustom={handleEdit}
                onDeleteCustom={handleDelete}
                onExportCustom={handleExport}
                renderCustomActions={(selectedRows) => {
                    const selectedRecorderId = selectedRows.size === 1 ? Number(Array.from(selectedRows)[0]) : undefined
                    return (
                        <Button
                            appearance="unstyled"
                            type="button"
                            className="data-btn"
                            title="Link a microphone to the selected recorder"
                            disabled={selectedRecorderId == null || !Number.isFinite(selectedRecorderId)}
                            onClick={() => selectedRecorderId != null && void openRelationForm(selectedRecorderId)}
                        >
                            <Link2 size={14} /> Link
                        </Button>
                    )
                }}
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
                                    onView={(microphoneId) => void openMicrophoneDetail(microphoneId)}
                                    viewingId={viewingMicrophoneId}
                                    onRemove={(microphoneId) => {
                                        const microphone = detailRecorder.microphones.find((item) => item.microphone_id === microphoneId)
                                        confirmRemoveMicrophone(microphoneId, microphone?.name)
                                    }}
                                    removingId={removingMicrophoneId}
                                    items={detailRecorder.microphones.map((microphone) => ({
                                        id: microphone.microphone_id,
                                        name: microphone.name,
                                        notes: microphone.notes,
                                    }))}
                                />
                            </Space>
                        ) : null}
                    </div>
                </CustomScrollArea>
            </FormDrawer>

            <FormDrawer
                closable={false}
                title={<SettingsDrawerTitle>Microphone Details</SettingsDrawerTitle>}
                open={microphoneDetailOpen}
                maskClosable={false}
                onClose={() => {
                    setMicrophoneDetailOpen(false)
                    setMicrophoneDetail(null)
                }}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_COMPACT)}
                extra={
                    <SettingsDrawerCancelExtra
                        onClose={() => {
                            setMicrophoneDetailOpen(false)
                            setMicrophoneDetail(null)
                        }}
                        disabled={microphoneDetailLoading}
                    />
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                        {microphoneDetailLoading ? (
                            <SettingsDetailLoading />
                        ) : microphoneDetail ? (
                            <Descriptions column={1} size="small" className="camera-settings__detail-meta" bordered>
                                <Descriptions.Item label="ID">{microphoneDetail.microphone_id}</Descriptions.Item>
                                <Descriptions.Item label="UUID">{String(microphoneDetail.uuid)}</Descriptions.Item>
                                <Descriptions.Item label="Name">{microphoneDetail.name || "-"}</Descriptions.Item>
                                <Descriptions.Item label="Element">{microphoneDetail.microphone_element || "-"}</Descriptions.Item>
                                <Descriptions.Item label="Sensitivity">
                                    {microphoneDetail.sensitivity != null ? `${microphoneDetail.sensitivity} dB` : "-"}
                                </Descriptions.Item>
                                <Descriptions.Item label="SNR">
                                    {microphoneDetail.signal_to_noise_ratio != null
                                        ? `${microphoneDetail.signal_to_noise_ratio} dB`
                                        : "-"}
                                </Descriptions.Item>
                            </Descriptions>
                        ) : null}
                    </div>
                </CustomScrollArea>
            </FormDrawer>

            <FormDrawer
                closable={false}
                title={<SettingsDrawerTitle>Associate Microphone</SettingsDrawerTitle>}
                open={relationFormOpen}
                maskClosable={false}
                onClose={() => setRelationFormOpen(false)}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_COMPACT)}
                extra={
                    <SettingsDrawerFormExtra
                        onClose={() => setRelationFormOpen(false)}
                        onSave={() => void submitRelation()}
                        saving={relationSaving}
                    />
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                        <Form form={relationForm} layout="vertical" requiredMark={false} className="shared-drawer-form">
                            <Form.Item
                                name="microphone_id"
                                label={renderRequiredLabel("Microphone")}
                                rules={[{ required: true, message: "Select a microphone" }]}
                            >
                                <Select
                                    className="form-drawer-select"
                                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                    loading={relationLoading}
                                    showSearch
                                    optionFilterProp="label"
                                    placeholder="Select a microphone"
                                    options={availableMicrophones.map((microphone) => ({
                                        value: microphone.microphone_id,
                                        label: microphone.name || `Microphone #${microphone.microphone_id}`,
                                    }))}
                                    notFoundContent={relationLoading ? "Loading microphones…" : "No unlinked microphones available"}
                                />
                            </Form.Item>
                            <Form.Item name="notes" label="Notes" rules={[{ max: 500, message: "Notes must be at most 500 characters" }]}>
                                <Input.TextArea rows={4} maxLength={500} showCount />
                            </Form.Item>
                        </Form>
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
