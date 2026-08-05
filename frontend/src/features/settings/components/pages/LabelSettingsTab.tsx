import { CustomScrollArea } from "@/components/ui"
import { useCallback, useEffect, useState } from "react"
import { Button, ConfigProvider, Form, Input, Select, Space, Typography, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { Tag } from "lucide-react"
import { ApiError } from "../../../../api/client"
import {
    labelSettingsApi,
    type LabelAdminPublic,
    type LabelType,
} from "../../../../api/endpoints/labelSettings"
import { DataPageLayout } from "../../../project/components/data/DataPageLayout"
import type { ColumnDef, RowData, TableState } from "../../../project/components/data/DataPageLayout"
import { useAppStore } from "@/store/useAppStore"
import { useAppDefaultAntdBrandConfig } from "../../../project/hooks/useAntdBrandConfig"
import "../../../project/components/modals/styles/FormDrawer.css"
import "../style/settings-forms.css"
import { downloadFile } from "@/utils/download"
import { renderRequiredLabel } from "../../utils/formValidation"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const { Title } = Typography

const TYPE_OPTIONS: { label: string; value: LabelType }[] = [
    { label: "Private", value: "private" },
    { label: "Public", value: "public" },
]

const BASE_COLUMNS: ColumnDef[] = [
    { key: "label_id", label: "ID", type: "number", width: "72px", sortable: true, filterable: true },
    { key: "name", label: "Name", type: "text", width: "200px", sortable: true, filterable: true },
    {
        key: "type",
        label: "Type",
        type: "badge",
        width: "100px",
        sortable: true,
        filterable: true,
        badgeSemantic: "labelType",
    },
    {
        key: "creator",
        label: "Creator",
        type: "text",
        width: "160px",
        sortable: true,
        filterable: true,
    },
    {
        key: "creation_date",
        label: "Created",
        type: "date",
        width: "180px",
        sortable: true,
        filterable: true,
        filterType: "dateRange",
    },
]

function orderByForApi(sortKey: string | null): string {
    if (
        sortKey === "name" ||
        sortKey === "label_id" ||
        sortKey === "type" ||
        sortKey === "creator_id" ||
        sortKey === "creator_name" ||
        sortKey === "creation_date" ||
        sortKey === "creator"
    ) {
        return sortKey === "creator" ? "creator_name" : sortKey
    }
    return "label_id"
}

function listParamsFromTableState(state: TableState) {
    const order_by = orderByForApi(state.sortKey)
    const order_dir: "asc" | "desc" = state.sortDir === "desc" ? "desc" : "asc"
    const params: Record<string, string | number> = {
        page: state.page,
        page_size: state.pageSize,
        order_by,
        order_dir,
    }

    const nameFilter = state.filters.name?.trim()
    const search = state.searchQuery?.trim()
    if (search) params.name = search
    else if (nameFilter) params.name = nameFilter

    if (state.filters.label_id) params.label_id = state.filters.label_id
    if (state.filters.type) params.type = String(state.filters.type)

    Object.entries(state.filters).forEach(([k, v]) => {
        if (v === "" || v === null || v === undefined) return
        if (k === "creator") {
            params.creator_name = String(v).trim()
        } else if (k === "creation_date") {
            const [start, end] = String(v).split(",")
            if (start) params.creation_date_from = start
            if (end) params.creation_date_to = end
        }
    })

    return params
}

type LabelFormValues = {
    name?: string
    type?: LabelType
}

export function LabelSettingsTab() {
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
    const [form] = Form.useForm<LabelFormValues>()

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const res = await labelSettingsApi.list(listParamsFromTableState(state))
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load labels")
                setRows([])
                setTotalRows(0)
                return
            }
            const list = res.data ?? []
            setRows(
                list.map((r: LabelAdminPublic) => ({
                    label_id: r.label_id,
                    id: r.label_id,
                    name: r.name ?? "",
                    type: r.type ?? "",
                    creator: r.creator_name ?? (r.creator_id != null ? String(r.creator_id) : ""),
                    creator_id: r.creator_id,
                    creation_date: r.creation_date ?? "",
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
            message.error(e instanceof Error ? e.message : "Failed to load labels")
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
        form.setFieldsValue({ type: "private" })
        setFormOpen(true)
    }

    const handleEdit = (selectedKeys: unknown[]) => {
        if (selectedKeys.length !== 1) {
            message.warning("Please select exactly one label to edit")
            return
        }
        const id = selectedKeys[0] as number
        const row = rows.find((r) => r.id === id || r.label_id === id)
        setFormMode("edit")
        setEditingId(id)
        form.setFieldsValue({
            name: row?.name != null ? String(row.name) : "",
            type: (row?.type === "public" ? "public" : "private") as LabelType,
        })
        setFormOpen(true)
    }

    useEffect(() => {
        if (formOpen && formMode === "edit" && editingId) {
            const row = rows.find((r) => r.id === editingId || r.label_id === editingId)
            if (row) {
                form.setFieldsValue({
                    name: row.name != null ? String(row.name) : "",
                    type: (row.type === "public" ? "public" : "private") as LabelType,
                })
            }
        }
    }, [formOpen, formMode, editingId, rows, form])

    const submitForm = async () => {
        try {
            const vals = await form.validateFields()
            const name = vals.name?.trim() ?? ""
            setFormSaving(true)
            if (formMode === "create") {
                const res = await labelSettingsApi.create({
                    name,
                    type: vals.type ?? "private",
                })
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Create failed")
                    return
                }
                message.success("Label created")
            } else if (editingId != null) {
                const res = await labelSettingsApi.update(editingId, {
                    name,
                    type: vals.type,
                })
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

    const handleDelete = async (selectedKeys: unknown[]) => {
        const hideLoading = message.loading(`Deleting ${selectedKeys.length} record(s)...`, 0)
        try {
            for (const id of selectedKeys) {
                const res = await labelSettingsApi.delete(id as number)
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
        const hide = message.loading("Exporting labels…", 0)
        try {
            const params = listParamsFromTableState(tableState)
            delete params.page
            delete params.page_size
            const download = await labelSettingsApi.exportCsv(params)
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
                You do not have permission to manage labels (admin required). Contact an administrator if you need
                access.
            </div>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <DataPageLayout
                title="Label"
                icon={Tag}
                columns={BASE_COLUMNS}
                rows={rows}
                defaultSortKey="label_id"
                defaultSortDir="asc"
                formFields={[]}
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
            />

            <FormDrawer
                closable={false}
                title={
                    <Title level={4} style={{ margin: 0 }}>
                        {formMode === "create" ? "Add label" : "Edit label"}
                    </Title>
                }
                open={formOpen}
                maskClosable={false}
                onClose={() => setFormOpen(false)}
                destroyOnClose
                styles={{
                    wrapper: { width: 520 },
                    header: {
                        background: isDark ? "var(--bg-surface)" : undefined,
                        borderBottomColor: isDark ? "var(--border-color)" : undefined,
                        color: "var(--text-main)",
                    },
                    body: {
                        background: isDark ? "var(--bg-surface)" : undefined,
                        padding: 0,
                        overflow: "hidden",
                    },
                    footer: {
                        background: isDark ? "var(--bg-surface)" : undefined,
                    },
                    mask: { backdropFilter: "blur(4px)" },
                }}
                extra={
                    <Space>
                        <Button onClick={() => setFormOpen(false)} disabled={formSaving}>
                            Cancel
                        </Button>
                        <Button
                            type="primary"
                            onClick={() => void submitForm()}
                            loading={formSaving}
                        >
                            Save
                        </Button>
                    </Space>
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: 24 }}>
                        <Form form={form} layout="vertical" requiredMark={false} className="shared-drawer-form">
                            <Form.Item
                                name="name"
                                label={renderRequiredLabel("Name")}
                                rules={[
                                    {
                                        validator: async (_, value) => {
                                            const trimmed = String(value ?? "").trim()
                                            if (!trimmed) throw new Error("Enter a name")
                                        },
                                    },
                                    { max: 20, message: "Maximum 20 characters" },
                                ]}
                            >
                                <Input maxLength={20} showCount />
                            </Form.Item>
                            <Form.Item
                                name="type"
                                label={renderRequiredLabel("Type")}
                                rules={[{ required: true, message: "Select a type" }]}
                            >
                                <Select
                                    className="form-drawer-select"
                                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                    options={TYPE_OPTIONS}
                                />
                            </Form.Item>
                        </Form>
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
