import { Button as ESButton } from "@/components/ui"
import { CustomScrollArea } from "@/components/ui"
import { useCallback, useEffect, useState } from "react"
import { ConfigProvider, Descriptions, Form, Input, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { Copyright, Eye } from "lucide-react"
import { ApiError } from "../../../../api/client"
import { licensesApi, type LicensePublic } from "../../../../api/endpoints/licenses"
import { DataPageLayout } from "../../../project/components/data/DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../../../project/components/data/DataPageLayout"
import { useAppStore } from "@/store/useAppStore"
import { useAppDefaultAntdBrandConfig } from "../../../project/hooks/useAntdBrandConfig"
import { httpUrlRule } from "../../../project/utils/urlValidation"
import {
    SETTINGS_DRAWER_BODY_PADDING,
    SETTINGS_DRAWER_WIDTH_STANDARD,
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
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "license_id", label: "ID", type: "number", width: "72px", sortable: true, filterable: true },
    { key: "name", label: "Name", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "link", label: "Link", type: "text", width: "320px", sortable: true, filterable: true },
]

const FORM_FIELDS: FormFieldDef[] = [
    { key: "name", label: "Name", type: "text" },
    { key: "link", label: "Link", type: "text" },
]

function orderByForApi(sortKey: string | null): string {
    if (sortKey === "license_id" || sortKey === "name" || sortKey === "link") return sortKey
    return "license_id"
}

export function CopyrightSettingsTab() {
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
    const [form] = Form.useForm<{ name?: string; link?: string }>()

    const [detailOpen, setDetailOpen] = useState(false)
    const [detailLicense, setDetailLicense] = useState<LicensePublic | null>(null)
    const [detailLoading, setDetailLoading] = useState(false)

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const order_by = orderByForApi(state.sortKey)
            const order_dir: "asc" | "desc" = state.sortDir === "desc" ? "desc" : "asc"
            const res = await licensesApi.list({
                page: state.page,
                page_size: state.pageSize,
                name: (state.searchQuery?.trim() || state.filters.name?.trim()) || undefined,
                link: state.filters.link?.trim() || undefined,
                license_id: state.filters.license_id || undefined,
                order_by,
                order_dir,
            })
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load licenses")
                setRows([])
                setTotalRows(0)
                return
            }
            const list = res.data ?? []
            setRows(
                list.map((r: LicensePublic) => ({
                    license_id: r.license_id,
                    id: r.license_id,
                    name: r.name ?? "",
                    link: r.link ?? "",
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
            message.error(e instanceof Error ? e.message : "Failed to load licenses")
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
            message.warning("Please select exactly one license to edit")
            return
        }
        const id = selectedKeys[0] as number
        const row = rows.find((r) => r.id === id || r.license_id === id)
        setFormMode("edit")
        setEditingId(id)
        form.setFieldsValue({
            name: row?.name != null ? String(row.name) : "",
            link: row?.link != null ? String(row.link) : "",
        })
        setFormOpen(true)
    }

    useEffect(() => {
        if (formOpen && formMode === "edit" && editingId) {
            const row = rows.find((r) => r.id === editingId || r.license_id === editingId)
            if (row) {
                form.setFieldsValue({
                    name: row.name != null ? String(row.name) : "",
                    link: row.link != null ? String(row.link) : "",
                })
            }
        }
    }, [formOpen, formMode, editingId, rows, form])

    const submitForm = async () => {
        try {
            const vals = await form.validateFields()
            setFormSaving(true)
            if (formMode === "create") {
                const name = vals.name?.trim() ?? ""
                const link = vals.link?.trim() ?? ""
                if (!name || !link) {
                    message.warning("Name and link are required")
                    return
                }
                const res = await licensesApi.create({ name, link })
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Create failed")
                    return
                }
                message.success("License created")
            } else if (editingId != null) {
                const res = await licensesApi.update(editingId, {
                    name: vals.name?.trim() || undefined,
                    link: vals.link?.trim() || undefined,
                })
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Update failed")
                    return
                }
                message.success("Saved")
            }
            setFormOpen(false)
            if (tableState) handleTableChange(tableState)
            if (detailOpen && detailLicense && editingId === detailLicense.license_id) {
                const r = await licensesApi.get(detailLicense.license_id)
                if (r.code === 0 || r.code === 200) setDetailLicense(r.data!)
            }
        } catch (e: unknown) {
            if (e && typeof e === "object" && "errorFields" in e) return
            message.error(e instanceof Error ? e.message : "Save failed")
        } finally {
            setFormSaving(false)
        }
    }

    const openDetail = async (licenseId: number) => {
        setDetailOpen(true)
        setDetailLoading(true)
        setDetailLicense(null)
        try {
            const res = await licensesApi.get(licenseId)
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load detail")
                setDetailOpen(false)
                return
            }
            setDetailLicense(res.data!)
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
                const res = await licensesApi.delete(id as number)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Delete failed")
                    return
                }
            }
            message.success(`Deleted ${selectedKeys.length} record(s)`)
            if (detailLicense && selectedKeys.includes(detailLicense.license_id)) {
                setDetailOpen(false)
                setDetailLicense(null)
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
        const hide = message.loading("Exporting licenses…", 0)
        try {
            const order_by = orderByForApi(tableState.sortKey)
            const order_dir: "asc" | "desc" = tableState.sortDir === "desc" ? "desc" : "asc"
            const base = {
                name: tableState.filters.name?.trim() || undefined,
                link: tableState.filters.link?.trim() || undefined,
                license_id: tableState.filters.license_id || undefined,
                order_by,
                order_dir,
            }
            const download = await licensesApi.exportCsv(base)
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
                You do not have permission to manage licenses (admin required). Contact an administrator if you need
                access.
            </div>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <DataPageLayout
                title="Copyright"
                icon={Copyright}
                columns={COLUMNS}
                rows={rows}
                defaultSortKey="license_id"
                defaultSortDir="asc"
                formFields={FORM_FIELDS}
                antdThemeOverride={drawerTheme}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="id"
                onTableStateChange={handleTableChange}
                onAddCustom={openCreate}
                onEditCustom={handleEdit}
                onDeleteCustom={handleDelete}
                onExportCustom={handleExport}
                hideView={true}
                renderCustomActions={(selectedRows) => (
                    <ESButton appearance="unstyled"
                        type="button"
                        className="data-btn"
                        title="View"
                        disabled={selectedRows.size !== 1}
                        onClick={() => void openDetail(Array.from(selectedRows)[0] as number)}
                    >
                        <Eye size={14} /> View
                    </ESButton>
                )}
            />

            <FormDrawer
                closable={false}
                title={
                    <SettingsDrawerTitle>
                        {formMode === "create" ? "Add license" : "Edit license"}
                    </SettingsDrawerTitle>
                }
                open={formOpen}
                maskClosable={false}
                onClose={() => setFormOpen(false)}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_STANDARD)}
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
                                rules={[{ required: true, message: "Enter a name" }]}
                            >
                                <Input />
                            </Form.Item>
                            <Form.Item
                                name="link"
                                label={renderRequiredLabel("Link")}
                                rules={[
                                    { required: formMode === "create", message: "Enter a URL or reference" },
                                    httpUrlRule("Link"),
                                ]}
                            >
                                <Input type="url" inputMode="url" autoComplete="off" />
                            </Form.Item>
                        </Form>
                    </div>
                </CustomScrollArea>
            </FormDrawer>

            <FormDrawer
                closable={false}
                title={<SettingsDrawerTitle>License detail</SettingsDrawerTitle>}
                open={detailOpen}
                maskClosable={false}
                onClose={() => {
                    setDetailOpen(false)
                    setDetailLicense(null)
                }}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_STANDARD)}
                extra={
                    <SettingsDrawerCancelExtra
                        onClose={() => {
                            setDetailOpen(false)
                            setDetailLicense(null)
                        }}
                        disabled={detailLoading}
                    />
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                        {detailLoading ? (
                            <SettingsDetailLoading />
                        ) : detailLicense ? (
                            <Descriptions column={1} size="small" className="camera-settings__detail-meta" bordered>
                                <Descriptions.Item label="ID">{detailLicense.license_id}</Descriptions.Item>
                                <Descriptions.Item label="Name">{detailLicense.name || "-"}</Descriptions.Item>
                                <Descriptions.Item label="Link">
                                    {detailLicense.link ? (
                                        <a href={detailLicense.link} target="_blank" rel="noopener noreferrer">
                                            {detailLicense.link}
                                        </a>
                                    ) : (
                                        "-"
                                    )}
                                </Descriptions.Item>
                            </Descriptions>
                        ) : null}
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
