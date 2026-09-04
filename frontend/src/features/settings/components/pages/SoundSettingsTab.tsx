import { CustomScrollArea } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { downloadFile } from "@/utils/download"
import { useCallback, useState } from "react"
import {
    ConfigProvider,
    Form,
    Input,
    message,
} from "@/components/ui"
import { AudioLines, FileUp, Info, Plus } from "lucide-react"
import { ApiError } from "../../../../api/client"

import {
    soundClassificationsApi,
    type SoundClassificationRecord,
} from "../../../../api/endpoints/soundClassifications"
import { DataPageLayout } from "../../../project/components/data/DataPageLayout"
import type { RowData, TableState } from "../../../project/components/data/DataPageLayout"
import { useAppDefaultAntdBrandConfig } from "../../../project/hooks/useAntdBrandConfig"
import { useAppStore } from "@/store/useAppStore"
import {
    SETTINGS_DRAWER_BODY_PADDING,
    SETTINGS_DRAWER_WIDTH_STANDARD,
    SettingsDrawerFormExtra,
    SettingsDrawerTitle,
    getSettingsStageDrawerStyles,
} from "../settingsDrawerUi"
import { renderRequiredLabel } from "../../utils/formValidation"
import {
    SOUND_COLUMNS,
    soundListParamsFromTableState,
    soundOrderByForApi,
    soundWritePayload,
    type SoundFormValues,
} from "../../utils/soundSettingsModel"
import { useSettingsCsvImport } from "../../utils/useSettingsCsvImport"
import "../../../project/components/modals/styles/FormDrawer.css"
import "../style/settings-forms.css"
import "../style/sound-settings.css"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

function apiMessage(error: unknown, fallback: string): string {
    return error instanceof Error ? error.message : fallback
}

export function SoundSettingsTab() {
    const isDark = useAppStore((state) => state.effectiveTheme === "dark")
    const drawerTheme = useAppDefaultAntdBrandConfig(isDark)
    const [forbidden, setForbidden] = useState(false)
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [tableState, setTableState] = useState<TableState | null>(null)

    const [formOpen, setFormOpen] = useState(false)
    const [formMode, setFormMode] = useState<"create" | "edit">("create")
    const [editingId, setEditingId] = useState<number | null>(null)
    const [formLoading, setFormLoading] = useState(false)
    const [formSaving, setFormSaving] = useState(false)
    const [form] = Form.useForm<SoundFormValues>()


    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const response = await soundClassificationsApi.list(soundListParamsFromTableState(state))
            if (response.code !== 0 && response.code !== 200) {
                message.error(response.message || "Failed to load sounds")
                setRows([])
                setTotalRows(0)
                return
            }
            const items = response.data ?? []
            setRows(items.map((item: SoundClassificationRecord) => ({
                id: item.sound_id,
                sound_id: item.sound_id,
                soundscape_component: item.soundscape_component ?? "",
                sound_type: item.sound_type ?? "",
            })))
            setTotalRows(response.page_info?.total ?? items.length)
            setForbidden(false)
        } catch (error: unknown) {
            if (error instanceof ApiError && error.status === 403) {
                setForbidden(true)
                setRows([])
                setTotalRows(0)
                return
            }
            message.error(apiMessage(error, "Failed to load sounds"))
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

    const refreshTable = () => {
        if (tableState) handleTableChange(tableState)
    }
    const csvImport = useSettingsCsvImport("sounds", soundClassificationsApi.importCsv, refreshTable)

    const openCreate = () => {
        setFormMode("create")
        setEditingId(null)
        form.resetFields()
        setFormOpen(true)
    }

    const openEdit = async (selectedKeys: unknown[]) => {
        if (selectedKeys.length !== 1) {
            message.warning("Please select exactly one sound to edit")
            return
        }
        const soundId = Number(selectedKeys[0])
        setFormMode("edit")
        setEditingId(soundId)
        form.resetFields()
        setFormOpen(true)
        setFormLoading(true)
        try {
            const response = await soundClassificationsApi.get(soundId)
            if (response.code !== 0 && response.code !== 200) {
                message.error(response.message || "Failed to load sound")
                setFormOpen(false)
                return
            }
            form.setFieldsValue({
                soundscape_component: response.data.soundscape_component ?? "",
                sound_type: response.data.sound_type ?? "",
            })
        } catch (error: unknown) {
            message.error(apiMessage(error, "Failed to load sound"))
            setFormOpen(false)
        } finally {
            setFormLoading(false)
        }
    }

    const submitForm = async () => {
        try {
            const values = await form.validateFields()
            const payload = soundWritePayload(values)
            setFormSaving(true)
            const response = formMode === "create"
                ? await soundClassificationsApi.create(payload)
                : await soundClassificationsApi.update(editingId!, payload)
            if (response.code !== 0 && response.code !== 200) {
                message.error(response.message || "Save failed")
                return
            }
            message.success(formMode === "create" ? "Sound created" : "Sound saved")
            setFormOpen(false)
            refreshTable()
        } catch (error: unknown) {
            if (error && typeof error === "object" && "errorFields" in error) return
            message.error(apiMessage(error, "Save failed"))
        } finally {
            setFormSaving(false)
        }
    }

    const handleDelete = async (selectedKeys: unknown[]) => {
        const hideLoading = message.loading(`Deleting ${selectedKeys.length} record(s)...`, 0)
        let deleted = 0
        const failures: string[] = []
        try {
            for (const key of selectedKeys) {
                try {
                    const response = await soundClassificationsApi.delete(Number(key))
                    if (response.code !== 0 && response.code !== 200) {
                        failures.push(response.message || `Sound #${String(key)} could not be deleted`)
                    } else {
                        deleted += 1
                    }
                } catch (error: unknown) {
                    failures.push(apiMessage(error, `Sound #${String(key)} could not be deleted`))
                }
            }
            if (deleted > 0) message.success(`Deleted ${deleted} record(s)`)
            if (failures.length > 0) {
                message.error(failures.length === 1 ? failures[0] : `${failures.length} records could not be deleted: ${failures[0]}`)
            }
            refreshTable()
        } finally {
            hideLoading()
        }
    }

    const handleExport = async () => {
        if (!tableState) {
            message.warning("Table is not ready yet.")
            return
        }
        const hideLoading = message.loading("Exporting sounds...", 0)
        try {
            const response = await soundClassificationsApi.exportCsv({
                order_by: soundOrderByForApi(tableState.sortKey),
                order_dir: tableState.sortDir === "desc" ? "desc" : "asc",
            })
            downloadFile(response, "sound-classifications.csv")
            message.success("Export successful")
        } catch (error: unknown) {
            message.error(apiMessage(error, "Export failed"))
        } finally {
            hideLoading()
        }
    }

    const addDropdownItems = [
        { key: "new", label: "New Sound", icon: <Plus size={14} />, onClick: openCreate },
        { type: "divider" as const },
        {
            key: "import",
            label: "Import Data",
            icon: <FileUp size={14} />,
            onClick: () => csvImport.triggerImport(),
        },
        {
            key: "instructions",
            label: "Import Instructions",
            icon: <Info size={14} />,
            onClick: () => csvImport.showInstructions(),
        },
    ]

    if (forbidden) {
        return (
            <div className="settings-form__status settings-form__status--error">
                You do not have permission to manage sounds (admin required). Contact an administrator if you need access.
            </div>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            {csvImport.input}
            <DataPageLayout
                title="Sounds"
                icon={AudioLines}
                columns={SOUND_COLUMNS}
                rows={rows}
                defaultSortKey="sound_id"
                defaultSortDir="asc"
                formFields={[]}
                antdThemeOverride={drawerTheme}
                loading={loading}
                serverSide
                totalRows={totalRows}
                rowKey="id"
                onTableStateChange={handleTableChange}
                addDropdownItems={addDropdownItems}
                addDisabled={csvImport.importing}
                onEditCustom={openEdit}
                onDeleteCustom={handleDelete}
                onExportCustom={handleExport}
                hideView
            />

            <FormDrawer
                closable={false}
                title={<SettingsDrawerTitle>{formMode === "create" ? "New Sound" : "Edit Sound"}</SettingsDrawerTitle>}
                open={formOpen}
                maskClosable={false}
                onClose={() => setFormOpen(false)}
                destroyOnClose
                styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_STANDARD)}
                extra={
                    <SettingsDrawerFormExtra
                        onClose={() => setFormOpen(false)}
                        onSave={() => void submitForm()}
                        saving={formSaving || formLoading}
                    />
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                        <Form form={form} layout="vertical" requiredMark={false} className="shared-drawer-form" disabled={formLoading}>
                            <Form.Item
                                name="soundscape_component"
                                label={renderRequiredLabel("Soundscape Component")}
                                rules={[
                                    { required: true, whitespace: true, message: "Enter a soundscape component" },
                                    { max: 200, message: "Soundscape Component must be at most 200 characters" },
                                ]}
                            >
                                <Input maxLength={200} />
                            </Form.Item>
                            <Form.Item
                                name="sound_type"
                                label="Sound Type"
                                rules={[{ max: 30, message: "Sound Type must be at most 30 characters" }]}
                            >
                                <Input maxLength={30} />
                            </Form.Item>
                        </Form>
                    </div>
                </CustomScrollArea>
            </FormDrawer>

        </ConfigProvider>
    )
}
