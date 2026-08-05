import { CustomScrollArea } from "@/components/ui"
import { useCallback, useEffect, useState } from "react"
import { ConfigProvider, Descriptions, Form, Input, Space, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { Camera, FileUp, Info, Plus } from "lucide-react"
import { ApiError } from "../../../../api/client"
import { camerasApi, type CameraListItem, type CameraPublic } from "../../../../api/endpoints/cameras"
import { useAppDefaultAntdBrandConfig } from "../../../project/hooks/useAntdBrandConfig"
import { DataPageLayout } from "../../../project/components/data/DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../../../project/components/data/DataPageLayout"
import { useAppStore } from "@/store/useAppStore"
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
import "../style/settings-forms.css"
import "../style/camera-settings.css"
import { downloadFile } from "@/utils/download"
import { renderSettingsRelationPills } from "../settingsRelationPills"
import { SettingsRelationDetailList } from "../SettingsRelationDetailList"
import { buildCameraWritePayload } from "../../utils/settingsPayload"
import { useSettingsCsvImport } from "../../utils/useSettingsCsvImport"
import { CsvImportInstructionsDrawer } from "../CsvImportInstructionsDrawer"
import { SETTINGS_CSV_IMPORT_CONFIG } from "../../utils/settingsCsvImportConfig"
import { renderRequiredLabel } from "../../utils/formValidation"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "camera_id", label: "ID", type: "number", width: "80px", sortable: true, filterable: true },
    { key: "uuid", label: "UUID", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "name", label: "Name", type: "text", width: "160px", sortable: true, filterable: true },
    { key: "version", label: "Version", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "brand", label: "Brand", type: "text", width: "120px", sortable: true, filterable: true },
    {
        key: "lens_count",
        label: "Lenses",
        type: "number",
        width: "220px",
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
        sortKey === "camera_id" ||
        sortKey === "uuid" ||
        sortKey === "name" ||
        sortKey === "version" ||
        sortKey === "brand" ||
        sortKey === "lens_count"
    ) return sortKey
    return "camera_id"
}

export function CameraSettingsTab() {
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
    const [form] = Form.useForm<{ name?: string; version?: string; brand?: string }>()

    const [detailOpen, setDetailOpen] = useState(false)
    const [detailCamera, setDetailCamera] = useState<CameraPublic | null>(null)
    const [detailLoading, setDetailLoading] = useState(false)
    const csvImport = useSettingsCsvImport("cameras", camerasApi.importCsv, () => tableState && handleTableChange(tableState))

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const order_by = orderByForApi(state.sortKey)
            const order_dir = state.sortDir === "desc" ? "desc" : "asc"
            const res = await camerasApi.list({
                page: state.page,
                page_size: state.pageSize,
                name: (state.searchQuery?.trim() || state.filters.name?.trim()) || undefined,
                brand: state.filters.brand?.trim() || undefined,
                version: state.filters.version?.trim() || undefined,
                camera_id: state.filters.camera_id || undefined,
                uuid: state.filters.uuid?.trim() || undefined,
                lens_count: state.filters.lens_count || undefined,
                order_by,
                order_dir,
            })
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load cameras")
                setRows([])
                setTotalRows(0)
                return
            }
            const list = res.data ?? []
            setRows(
                list.map((r: CameraListItem) => ({
                    ...r,
                    id: r.camera_id,
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
            message.error(e instanceof Error ? e.message : "Failed to load cameras")
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

    const handleEdit = (selectedKeys: unknown[]) => {
        if (selectedKeys.length !== 1) {
            message.warning("Please select exactly one camera to edit")
            return
        }
        const id = selectedKeys[0] as number
        const row = rows.find((r) => r.id === id || r.camera_id === id)
        setFormMode("edit")
        setEditingId(id)
        form.setFieldsValue({
            name: row?.name != null ? String(row.name) : "",
            version: row?.version != null ? String(row.version) : "",
            brand: row?.brand != null ? String(row.brand) : "",
        })
        setFormOpen(true)
    }

    useEffect(() => {
        if (formOpen && formMode === "edit" && editingId) {
            const row = rows.find((r) => r.id === editingId || r.camera_id === editingId)
            if (row) {
                form.setFieldsValue({
                    name: row.name != null ? String(row.name) : "",
                    version: row.version != null ? String(row.version) : "",
                    brand: row.brand != null ? String(row.brand) : "",
                })
            }
        }
    }, [formOpen, formMode, editingId, rows, form])

    const submitForm = async () => {
        try {
            const vals = await form.validateFields()
            setFormSaving(true)
            const payload = buildCameraWritePayload(vals)
            if (formMode === "create") {
                const res = await camerasApi.create(payload)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Create failed")
                    return
                }
                message.success("Camera created")
            } else if (editingId != null) {
                const res = await camerasApi.update(editingId, payload)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Update failed")
                    return
                }
                message.success("Saved")
            }
            setFormOpen(false)
            if (tableState) handleTableChange(tableState)
            if (detailOpen && detailCamera && editingId === detailCamera.camera_id) {
                const detailResponse = await camerasApi.get(detailCamera.camera_id)
                if (detailResponse.code === 0 || detailResponse.code === 200) {
                    setDetailCamera(detailResponse.data!)
                }
            }
        } catch (e: unknown) {
            if (e && typeof e === "object" && "errorFields" in e) return
            message.error(e instanceof Error ? e.message : "Save failed")
        } finally {
            setFormSaving(false)
        }
    }

    const openDetail = async (cameraId: number) => {
        setDetailOpen(true)
        setDetailLoading(true)
        setDetailCamera(null)
        try {
            const res = await camerasApi.get(cameraId)
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load detail")
                setDetailOpen(false)
                return
            }
            setDetailCamera(res.data!)
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
                const res = await camerasApi.delete(id as number)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Delete failed")
                    return
                }
            }
            message.success(`Deleted ${selectedKeys.length} record(s)`)
            if (detailCamera && selectedKeys.includes(detailCamera.camera_id)) {
                setDetailOpen(false)
                setDetailCamera(null)
            }
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
        const hide = message.loading("Exporting cameras…", 0)
        try {
            const order_by = orderByForApi(tableState.sortKey)
            const order_dir: "asc" | "desc" = tableState.sortDir === "desc" ? "desc" : "asc"
            const base = {
                name: tableState.filters.name?.trim() || undefined,
                brand: tableState.filters.brand?.trim() || undefined,
                version: tableState.filters.version?.trim() || undefined,
                camera_id: tableState.filters.camera_id || undefined,
                uuid: tableState.filters.uuid?.trim() || undefined,
                lens_count: tableState.filters.lens_count || undefined,
                order_by,
                order_dir,
            }
            const download = await camerasApi.exportCsv(base)
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
                You do not have permission to manage cameras (admin required). Contact an administrator if you need
                access.
            </div>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            {csvImport.input}
            <DataPageLayout
                title="Cameras"
                icon={Camera}
                columns={COLUMNS}
                rows={rows}
                defaultSortKey="camera_id"
                defaultSortDir="asc"
                formFields={FORM_FIELDS}
                antdThemeOverride={drawerTheme}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="id"
                onTableStateChange={handleTableChange}
                addDropdownItems={[
                    { key: "new", label: "New Camera", icon: <Plus size={14} />, onClick: openCreate },
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
                        {formMode === "create" ? "New Camera" : "Edit Camera"}
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
                <Form form={form} layout="vertical" requiredMark={false} className="shared-drawer-form">
                    <Form.Item
                        name="name"
                        label={renderRequiredLabel("Name")}
                        rules={[
                            { required: true, whitespace: true, message: "Name is required" },
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
                title={<SettingsDrawerTitle>Camera Details</SettingsDrawerTitle>}
                open={detailOpen}
                maskClosable={false}
                onClose={() => {
                    setDetailOpen(false)
                    setDetailCamera(null)
                }}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_COMPACT)}
                extra={
                    <SettingsDrawerCancelExtra
                        onClose={() => {
                            setDetailOpen(false)
                            setDetailCamera(null)
                        }}
                        disabled={detailLoading}
                    />
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                        {detailLoading ? (
                            <SettingsDetailLoading />
                        ) : detailCamera ? (
                            <Space direction="vertical" size="large" style={{ width: "100%" }}>
                                <Descriptions column={1} size="small" className="camera-settings__detail-meta" bordered>
                                    <Descriptions.Item label="ID">{detailCamera.camera_id}</Descriptions.Item>
                                    <Descriptions.Item label="UUID">{String(detailCamera.uuid)}</Descriptions.Item>
                                    <Descriptions.Item label="Name">{detailCamera.name || "-"}</Descriptions.Item>
                                    <Descriptions.Item label="Version">{detailCamera.version || "-"}</Descriptions.Item>
                                    <Descriptions.Item label="Brand">{detailCamera.brand || "-"}</Descriptions.Item>
                                </Descriptions>
                                <SettingsRelationDetailList
                                    title="Linked Lenses"
                                    fallbackLabel="Lens"
                                    emptyMessage="No lenses associated with this camera."
                                    isDark={isDark}
                                    items={detailCamera.lenses.map((lens) => ({
                                        id: lens.lens_id,
                                        name: lens.name,
                                        isDefault: lens.is_default,
                                        notes: lens.notes,
                                    }))}
                                />
                            </Space>
                        ) : null}
                    </div>
                </CustomScrollArea>
            </FormDrawer>

            <CsvImportInstructionsDrawer config={SETTINGS_CSV_IMPORT_CONFIG.cameras} isDark={isDark} open={csvImport.instructionsOpen} onClose={csvImport.hideInstructions} />
        </ConfigProvider>
    )
}
