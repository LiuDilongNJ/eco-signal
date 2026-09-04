import { CustomScrollArea } from "@/components/ui"
import { useCallback, useEffect, useState } from "react"
import { Descriptions, Form, Input, ConfigProvider, Space, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { Aperture, FileUp, Info, Plus } from "lucide-react"
import { ApiError } from "../../../../api/client"
import { lensesApi, type LensListItem, type LensPublic } from "../../../../api/endpoints/lenses"
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
import "../style/settings-forms.css"
import "../style/camera-settings.css"
import { downloadFile } from "@/utils/download"
import { buildLensWritePayload } from "../../utils/settingsPayload"
import { useSettingsCsvImport } from "../../utils/useSettingsCsvImport"
import { renderRequiredLabel } from "../../utils/formValidation"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "lens_id", label: "ID", type: "number", width: "72px", sortable: true, filterable: true },
    { key: "uuid", label: "UUID", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "name", label: "Name", type: "text", width: "160px", sortable: true, filterable: true },
    { key: "focal_length", label: "Focal length", type: "text", width: "120px", sortable: true, filterable: true },
    { key: "max_aperture", label: "Max aperture", type: "text", width: "120px", sortable: true, filterable: true },
    { key: "brand", label: "Brand", type: "text", width: "120px", sortable: true, filterable: true },
]

const FORM_FIELDS: FormFieldDef[] = [
    { key: "name", label: "Name", type: "text" },
    { key: "focal_length", label: "Focal length", type: "text" },
    { key: "max_aperture", label: "Max aperture", type: "text" },
    { key: "brand", label: "Brand", type: "text" },
]

function orderByForApi(sortKey: string | null): string {
    if (
        sortKey === "lens_id" ||
        sortKey === "uuid" ||
        sortKey === "name" ||
        sortKey === "focal_length" ||
        sortKey === "max_aperture" ||
        sortKey === "brand"
    ) return sortKey
    return "lens_id"
}

export function LensSettingsTab() {
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
    const [form] = Form.useForm<{ name?: string; focal_length?: string; max_aperture?: string; brand?: string }>()

    const [detailOpen, setDetailOpen] = useState(false)
    const [detailLens, setDetailLens] = useState<LensPublic | null>(null)
    const [detailLoading, setDetailLoading] = useState(false)
    const csvImport = useSettingsCsvImport("lenses", lensesApi.importCsv, () => tableState && handleTableChange(tableState))

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const order_by = orderByForApi(state.sortKey)
            const order_dir: "asc" | "desc" = state.sortDir === "desc" ? "desc" : "asc"
            const res = await lensesApi.list({
                page: state.page,
                page_size: state.pageSize,
                name: (state.searchQuery?.trim() || state.filters.name?.trim()) || undefined,
                focal_length: state.filters.focal_length?.trim() || undefined,
                max_aperture: state.filters.max_aperture?.trim() || undefined,
                brand: state.filters.brand?.trim() || undefined,
                lens_id: state.filters.lens_id || undefined,
                uuid: state.filters.uuid?.trim() || undefined,
                order_by,
                order_dir,
            })
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load lenses")
                setRows([])
                setTotalRows(0)
                return
            }
            const list = res.data ?? []
            setRows(
                list.map((r: LensListItem) => ({
                    ...r,
                    id: r.lens_id,
                    uuid: String(r.uuid),
                    name: r.name ?? "",
                    focal_length: r.focal_length ?? "",
                    max_aperture: r.max_aperture ?? "",
                    brand: r.brand ?? "",
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
            message.error(e instanceof Error ? e.message : "Failed to load lenses")
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
            message.warning("Please select exactly one lens to edit")
            return
        }
        const id = selectedKeys[0] as number
        const row = rows.find((r) => r.id === id || r.lens_id === id)
        setFormMode("edit")
        setEditingId(id)
        form.setFieldsValue({
            name: row?.name != null ? String(row.name) : "",
            focal_length: row?.focal_length != null ? String(row.focal_length) : "",
            max_aperture: row?.max_aperture != null ? String(row.max_aperture) : "",
            brand: row?.brand != null ? String(row.brand) : "",
        })
        setFormOpen(true)
    }

    useEffect(() => {
        if (formOpen && formMode === "edit" && editingId) {
            const row = rows.find((r) => r.id === editingId || r.lens_id === editingId)
            if (row) {
                form.setFieldsValue({
                    name: row.name != null ? String(row.name) : "",
                    focal_length: row.focal_length != null ? String(row.focal_length) : "",
                    max_aperture: row.max_aperture != null ? String(row.max_aperture) : "",
                    brand: row.brand != null ? String(row.brand) : "",
                })
            }
        }
    }, [formOpen, formMode, editingId, rows, form])

    const submitForm = async () => {
        try {
            const vals = await form.validateFields()
            const body = buildLensWritePayload(vals)
            setFormSaving(true)
            if (formMode === "create") {
                const res = await lensesApi.create(body)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Create failed")
                    return
                }
                message.success("Lens created")
            } else if (editingId != null) {
                const res = await lensesApi.update(editingId, body)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Update failed")
                    return
                }
                message.success("Saved")
            }
            setFormOpen(false)
            if (tableState) handleTableChange(tableState)
            if (detailOpen && detailLens && editingId === detailLens.lens_id) {
                const r = await lensesApi.get(detailLens.lens_id)
                if (r.code === 0 || r.code === 200) setDetailLens(r.data!)
            }
        } catch (e: unknown) {
            if (e && typeof e === "object" && "errorFields" in e) return
            message.error(e instanceof Error ? e.message : "Save failed")
        } finally {
            setFormSaving(false)
        }
    }

    const openDetail = async (lensId: number) => {
        setDetailOpen(true)
        setDetailLoading(true)
        setDetailLens(null)
        try {
            const res = await lensesApi.get(lensId)
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load detail")
                setDetailOpen(false)
                return
            }
            setDetailLens(res.data!)
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
                const res = await lensesApi.delete(id as number)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Delete failed")
                    return
                }
            }
            message.success(`Deleted ${selectedKeys.length} record(s)`)
            if (detailLens && selectedKeys.includes(detailLens.lens_id)) {
                setDetailOpen(false)
                setDetailLens(null)
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
        const hide = message.loading("Exporting lenses…", 0)
        try {
            const order_by = orderByForApi(tableState.sortKey)
            const order_dir: "asc" | "desc" = tableState.sortDir === "desc" ? "desc" : "asc"
            const base = {
                name: tableState.filters.name?.trim() || undefined,
                focal_length: tableState.filters.focal_length?.trim() || undefined,
                max_aperture: tableState.filters.max_aperture?.trim() || undefined,
                brand: tableState.filters.brand?.trim() || undefined,
                lens_id: tableState.filters.lens_id || undefined,
                uuid: tableState.filters.uuid?.trim() || undefined,
                order_by,
                order_dir,
            }
            const download = await lensesApi.exportCsv(base)
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
                You do not have permission to manage lenses (admin required). Contact an administrator if you need
                access.
            </div>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            {csvImport.input}
            <DataPageLayout
                title="Lenses"
                icon={Aperture}
                columns={COLUMNS}
                rows={rows}
                defaultSortKey="lens_id"
                defaultSortDir="asc"
                formFields={FORM_FIELDS}
                antdThemeOverride={drawerTheme}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="id"
                onTableStateChange={handleTableChange}
                addDropdownItems={[
                    { key: "new", label: "New Lens", icon: <Plus size={14} />, onClick: openCreate },
                    { type: "divider" as const },
                    { key: "import", label: "Import Data", icon: <FileUp size={14} />, onClick: () => csvImport.triggerImport() },
                    { key: "instructions", label: "Import Instructions", icon: <Info size={14} />, onClick: () => csvImport.showInstructions() },
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
                        {formMode === "create" ? "New Lens" : "Edit Lens"}
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
                    <Form.Item name="focal_length" label="Focal length" rules={[{ max: 50, message: "Focal length must be at most 50 characters" }]}>
                        <Input maxLength={50} />
                    </Form.Item>
                    <Form.Item name="max_aperture" label="Max aperture" rules={[{ max: 20, message: "Max aperture must be at most 20 characters" }]}>
                        <Input maxLength={20} />
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
                title={<SettingsDrawerTitle>Lens Details</SettingsDrawerTitle>}
                open={detailOpen}
                maskClosable={false}
                onClose={() => {
                    setDetailOpen(false)
                    setDetailLens(null)
                }}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_COMPACT)}
                extra={
                    <SettingsDrawerCancelExtra
                        onClose={() => {
                            setDetailOpen(false)
                            setDetailLens(null)
                        }}
                        disabled={detailLoading}
                    />
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                {detailLoading ? (
                    <SettingsDetailLoading />
                ) : detailLens ? (
                    <Space direction="vertical" size="large" style={{ width: "100%" }}>
                        <Descriptions column={1} size="small" className="camera-settings__detail-meta" bordered>
                            <Descriptions.Item label="ID">{detailLens.lens_id}</Descriptions.Item>
                            <Descriptions.Item label="UUID">{String(detailLens.uuid)}</Descriptions.Item>
                            <Descriptions.Item label="Name">{detailLens.name || "-"}</Descriptions.Item>
                            <Descriptions.Item label="Focal length">{detailLens.focal_length || "-"}</Descriptions.Item>
                            <Descriptions.Item label="Max aperture">{detailLens.max_aperture || "-"}</Descriptions.Item>
                            <Descriptions.Item label="Brand">{detailLens.brand || "-"}</Descriptions.Item>
                        </Descriptions>
                    </Space>
                ) : null}
            </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
