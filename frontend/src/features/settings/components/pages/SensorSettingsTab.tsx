import { CustomScrollArea } from "@/components/ui"
import { useCallback, useRef, useState } from "react"
import { ConfigProvider, Form, Input, Select, Switch, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import { LoadingState } from "@/components/ui"

import { Radio } from "lucide-react"
import { ApiError } from "../../../../api/client"
import { camerasApi, type CameraListItem } from "../../../../api/endpoints/cameras"
import { fetchLensListAll, type LensListItem } from "../../../../api/endpoints/lenses"
import { microphonesApi } from "../../../../api/endpoints/microphones"
import { recordersApi, type RecorderOption } from "../../../../api/endpoints/recorders"
import { sensorsApi, type SensorUpdateBody } from "../../../../api/endpoints/sensors"
import { DataPageLayout } from "../../../project/components/data/DataPageLayout"
import type { FormFieldDef, RowData, TableState } from "../../../project/components/data/DataPageLayout"
import { useAppStore } from "@/store/useAppStore"
import { useAppDefaultAntdBrandConfig } from "../../../project/hooks/useAntdBrandConfig"
import {
    SETTINGS_DRAWER_BODY_PADDING,
    SETTINGS_DRAWER_WIDTH_STANDARD,
    SettingsDrawerFormExtra,
    SettingsDrawerTitle,
    getSettingsStageDrawerStyles,
} from "../settingsDrawerUi"
import "../../../project/components/modals/styles/FormDrawer.css"
import "../style/settings-forms.css"
import "../style/camera-settings.css"
import { downloadFile } from "@/utils/download"
import { renderRequiredLabel } from "../../utils/formValidation"
import { displayApiDateTime } from "../../utils/dateTimeDisplay"
import { isSelectScrollNearBottom, usePagedSelectOptions } from "@/hooks/usePagedSelectOptions"
import {
    buildSensorWritePayload,
    getUniqueDefaultLensId,
    resolveCameraLensDefault,
    resolveRecorderMicrophoneDefault,
    type SensorFormValues,
} from "../../utils/sensorForm"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"
import { SENSOR_COLUMNS } from "./sensorSettingsColumns"

const FORM_FIELDS: FormFieldDef[] = [{ key: "name", label: "Name", type: "text" }]

function orderByForApi(sortKey: string | null): string {
    if (
        sortKey === "sensor_id" ||
        sortKey === "uuid" ||
        sortKey === "name" ||
        sortKey === "sensor_type" ||
        sortKey === "recorder_name" ||
        sortKey === "microphone_name" ||
        sortKey === "camera_name" ||
        sortKey === "lens_name" ||
        sortKey === "creation_date"
    ) return sortKey
    return "sensor_id"
}

export function SensorSettingsTab() {
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
    const [formAuxLoading, setFormAuxLoading] = useState(false)
    const [cameraLensDefaultTouched, setCameraLensDefaultTouched] = useState(false)
    const [recorderMicrophoneDefaultTouched, setRecorderMicrophoneDefaultTouched] = useState(false)
    const [form] = Form.useForm<SensorFormValues>()

    const [recorderSelectOptions, setRecorderSelectOptions] = useState<{ value: number; label: string }[]>([])
    const [micSelectOptions, setMicSelectOptions] = useState<{ value: number; label: string }[]>([])
    const [lensSelectOptions, setLensSelectOptions] = useState<{ value: number; label: string }[]>([])
    const microphoneRequestIdRef = useRef(0)
    const lensRequestIdRef = useRef(0)

    const fetchCameraPage = useCallback(async (query: string, page: number, pageSize: number) => {
        const response = await camerasApi.list({
            page,
            page_size: pageSize,
            name: query || undefined,
            order_by: "name",
            order_dir: "asc",
        })
        return {
            items: (response.data ?? []).map((camera: CameraListItem) => ({
                value: camera.camera_id,
                label: [camera.name || `Camera #${camera.camera_id}`, camera.brand].filter(Boolean).join(" · "),
            })),
            hasMore: page < (response.page_info?.total_pages ?? 1),
        }
    }, [])
    const cameraOptions = usePagedSelectOptions({
        pageSize: 100,
        getKey: (option: { value: number; label: string }) => option.value,
        fetchPage: fetchCameraPage,
    })

    const loadFormOptionLists = useCallback(async () => {
        const [recRes, lensAll] = await Promise.all([
            recordersApi.getOptions(),
            fetchLensListAll({ order_by: "name", order_dir: "asc" }),
        ])
        if (recRes.code === 0 || recRes.code === 200) {
            setRecorderSelectOptions(
                (recRes.data ?? []).map((r: RecorderOption) => ({
                    value: r.recorder_id,
                    label: r.name || `Recorder #${r.recorder_id}`,
                })),
            )
        }
        if (lensAll.errorMessage) {
            message.error(lensAll.errorMessage)
            setLensSelectOptions([])
        } else {
            setLensSelectOptions(
                lensAll.data.map((l: LensListItem) => ({
                    value: l.lens_id,
                    label: [l.name || `Lens #${l.lens_id}`, l.brand].filter(Boolean).join(" · "),
                })),
            )
        }
    }, [])

    const loadMicsForRecorder = useCallback(async (recorderId: number | undefined) => {
        const requestId = ++microphoneRequestIdRef.current
        if (recorderId == null) {
            setMicSelectOptions([])
            return
        }
        try {
            const res = await microphonesApi.getOptions({ recorder_id: recorderId })
            if (requestId !== microphoneRequestIdRef.current) return
            if (res.code === 0 || res.code === 200) {
                setMicSelectOptions(
                    (res.data ?? []).map((m) => ({
                        value: m.microphone_id,
                        label: m.name || `Microphone #${m.microphone_id}`,
                    })),
                )
            } else {
                setMicSelectOptions([])
            }
        } catch {
            if (requestId === microphoneRequestIdRef.current) setMicSelectOptions([])
        }
    }, [])

    const loadLensesForCamera = useCallback(async (cameraId: number | undefined) => {
        const requestId = ++lensRequestIdRef.current
        if (cameraId == null) {
            setLensSelectOptions([])
            form.setFieldValue("lens_id", undefined)
            form.setFieldValue("camera_lens_is_default", false)
            return
        }
        try {
            const response = await camerasApi.get(cameraId)
            if (requestId !== lensRequestIdRef.current) return
            if (response.code !== 0 && response.code !== 200) {
                setLensSelectOptions([])
                return
            }
            const lenses = response.data?.lenses ?? []
            setLensSelectOptions(
                lenses.map((lens) => ({
                    value: lens.lens_id,
                    label: lens.name?.trim() || `Lens #${lens.lens_id}`,
                })),
            )
            const selectedLensId = form.getFieldValue("lens_id") as number | undefined
            const compatibleLens = lenses.some((lens) => lens.lens_id === selectedLensId)
            if (!compatibleLens) {
                const defaultLensId = getUniqueDefaultLensId(lenses)
                form.setFieldValue("lens_id", defaultLensId)
                form.setFieldValue("camera_lens_is_default", defaultLensId != null)
            }
        } catch {
            if (requestId === lensRequestIdRef.current) setLensSelectOptions([])
        }
    }, [form])

    const syncCameraLensDefault = useCallback(async (cameraId?: number, lensId?: number) => {
        setCameraLensDefaultTouched(false)
        form.setFieldValue("camera_lens_is_default", false)
        if (cameraId == null) return

        try {
            const response = await camerasApi.get(cameraId)
            if (response.code !== 0 && response.code !== 200) return
            const lenses = response.data?.lenses ?? []
            if (lensId == null) {
                const defaultLensId = getUniqueDefaultLensId(lenses)
                form.setFieldValue("lens_id", defaultLensId)
                form.setFieldValue("camera_lens_is_default", defaultLensId != null)
                return
            }
            form.setFieldValue(
                "camera_lens_is_default",
                resolveCameraLensDefault(lenses, lensId),
            )
        } catch {
            // The backend still initializes a new association as non-default on save.
        }
    }, [form])

    const syncRecorderMicrophoneDefault = useCallback(async (recorderId?: number, microphoneId?: number) => {
        setRecorderMicrophoneDefaultTouched(false)
        form.setFieldValue("recorder_microphone_is_default", false)
        if (recorderId == null || microphoneId == null) return

        try {
            const response = await recordersApi.get(recorderId)
            if (response.code !== 0 && response.code !== 200) return
            const microphones = response.data?.microphones ?? []
            form.setFieldValue(
                "recorder_microphone_is_default",
                resolveRecorderMicrophoneDefault(microphones, microphoneId),
            )
        } catch {
            // The backend still initializes a new association as non-default on save.
        }
    }, [form])

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const order_by = orderByForApi(state.sortKey)
            const order_dir: "asc" | "desc" = state.sortDir === "desc" ? "desc" : "asc"
            const res = await sensorsApi.list({
                page: state.page,
                page_size: state.pageSize,
                name: (state.searchQuery?.trim() || state.filters.name?.trim()) || undefined,
                sensor_type: state.filters.sensor_type?.trim() || undefined,
                sensor_id:
                    state.filters.sensor_id && String(state.filters.sensor_id).trim() !== ""
                        ? Number(state.filters.sensor_id)
                        : undefined,
                uuid: state.filters.uuid?.trim() || undefined,
                recorder_name: state.filters.recorder_name?.trim() || undefined,
                microphone_name: state.filters.microphone_name?.trim() || undefined,
                camera_name: state.filters.camera_name?.trim() || undefined,
                lens_name: state.filters.lens_name?.trim() || undefined,
                description: state.filters.description?.trim() || undefined,
                creation_date_from: state.filters.creation_date?.split(",")[0]?.slice(0, 10) || undefined,
                creation_date_to: state.filters.creation_date?.split(",")[1]?.slice(0, 10) || undefined,
                order_by,
                order_dir,
            })
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load sensors")
                setRows([])
                setTotalRows(0)
                return
            }
            const list = res.data ?? []
            setRows(
                list.map((r) => {
                    const created = displayApiDateTime(r.creation_date)
                    return {
                        sensor_id: r.sensor_id,
                        id: r.sensor_id,
                        uuid: String(r.uuid),
                        name: r.name ?? "",
                        is_default: r.is_default ?? false,
                        sensor_type: r.sensor_type ?? "",
                        recorder_name: r.recorder_name ?? "",
                        microphone_name: r.microphone_name ?? "",
                        camera_name: r.camera_name ?? "",
                        lens_name: r.lens_name ?? "",
                        description: r.description ?? "",
                        creation_date: created,
                    } as RowData
                }),
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
            message.error(e instanceof Error ? e.message : "Failed to load sensors")
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

    const openCreate = async () => {
        setFormMode("create")
        setEditingId(null)
        form.resetFields()
        setCameraLensDefaultTouched(false)
        setRecorderMicrophoneDefaultTouched(false)
        cameraOptions.reset()
        setFormAuxLoading(true)
        setFormOpen(true)
        try {
            await Promise.all([loadFormOptionLists(), cameraOptions.loadFirst()])
            setMicSelectOptions([])
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Failed to load form options")
        } finally {
            setFormAuxLoading(false)
        }
    }

    const handleEdit = async (selectedKeys: unknown[]) => {
        if (selectedKeys.length !== 1) {
            message.warning("Please select exactly one sensor to edit")
            return
        }
        const id = selectedKeys[0] as number
        setFormAuxLoading(true)
        setFormOpen(true)
        setFormMode("edit")
        setEditingId(id)
        try {
            cameraOptions.reset()
            const [, , res] = await Promise.all([
                loadFormOptionLists(),
                cameraOptions.loadFirst(),
                sensorsApi.get(id),
            ])
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load sensor")
                setFormOpen(false)
                return
            }
            const s = res.data!
            if (s.camera_id != null) {
                cameraOptions.setCurrentOption({
                    value: s.camera_id,
                    label: s.camera_name?.trim() || `Camera #${s.camera_id}`,
                })
            }
            form.setFieldsValue({
                name: s.name,
                sensor_type: s.sensor_type as "audio" | "photo",
                recorder_id: s.recorder_id ?? undefined,
                microphone_id: s.microphone_id ?? undefined,
                camera_id: s.camera_id ?? undefined,
                lens_id: s.lens_id ?? undefined,
                camera_lens_is_default:
                    s.camera_lens_is_default ?? (s.sensor_type === "photo" ? s.is_default ?? false : false),
                recorder_microphone_is_default:
                    s.recorder_microphone_is_default ?? (s.sensor_type === "audio" ? s.is_default ?? false : false),
                description: s.description ?? "",
            })
            if (s.camera_id != null) {
                await loadLensesForCamera(s.camera_id)
                form.setFieldValue("lens_id", s.lens_id ?? undefined)
            }
            setCameraLensDefaultTouched(false)
            setRecorderMicrophoneDefaultTouched(false)
            if (s.sensor_type === "audio" && s.recorder_id != null) {
                await loadMicsForRecorder(s.recorder_id)
            } else {
                setMicSelectOptions([])
            }
        } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : "Failed to load sensor")
            setFormOpen(false)
        } finally {
            setFormAuxLoading(false)
        }
    }

    const submitForm = async () => {
        try {
            const vals = await form.validateFields()
            setFormSaving(true)
            const payload = buildSensorWritePayload(
                vals,
                cameraLensDefaultTouched,
                recorderMicrophoneDefaultTouched,
            )
            if (formMode === "create") {
                const res = await sensorsApi.create(payload)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Create failed")
                    return
                }
                message.success("Sensor created")
            } else if (editingId != null) {
                const res = await sensorsApi.update(editingId, payload as SensorUpdateBody)
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
                const res = await sensorsApi.delete(id as number)
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
        const hide = message.loading("Exporting sensors…", 0)
        try {
            const order_by = orderByForApi(tableState.sortKey)
            const order_dir: "asc" | "desc" = tableState.sortDir === "desc" ? "desc" : "asc"
            const base = {
                name: (tableState.searchQuery?.trim() || tableState.filters.name?.trim()) || undefined,
                sensor_type: tableState.filters.sensor_type?.trim() || undefined,
                sensor_id:
                    tableState.filters.sensor_id && String(tableState.filters.sensor_id).trim() !== ""
                        ? Number(tableState.filters.sensor_id)
                        : undefined,
                uuid: tableState.filters.uuid?.trim() || undefined,
                recorder_name: tableState.filters.recorder_name?.trim() || undefined,
                microphone_name: tableState.filters.microphone_name?.trim() || undefined,
                camera_name: tableState.filters.camera_name?.trim() || undefined,
                lens_name: tableState.filters.lens_name?.trim() || undefined,
                description: tableState.filters.description?.trim() || undefined,
                creation_date_from: tableState.filters.creation_date?.split(",")[0]?.slice(0, 10) || undefined,
                creation_date_to: tableState.filters.creation_date?.split(",")[1]?.slice(0, 10) || undefined,
                order_by,
                order_dir,
            }
            const download = await sensorsApi.exportCsv(base)
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
                You do not have permission to manage sensors (admin required). Contact an administrator if you need
                access.
            </div>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <DataPageLayout
                title="Sensors"
                icon={Radio}
                columns={SENSOR_COLUMNS}
                rows={rows}
                defaultSortKey="sensor_id"
                defaultSortDir="asc"
                formFields={FORM_FIELDS}
                antdThemeOverride={drawerTheme}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="id"
                onTableStateChange={handleTableChange}
                onAddCustom={() => void openCreate()}
                onEditCustom={(keys) => void handleEdit(keys)}
                onDeleteCustom={handleDelete}
                onExportCustom={() => void handleExport()}
                hideView={true}
            />

            <FormDrawer
                closable={false}
                title={
                    <SettingsDrawerTitle>
                        {formMode === "create" ? "New Sensor" : "Edit Sensor"}
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
                <div className="settings-drawer-loading-frame">
                    {formAuxLoading ? (
                        <LoadingState
                            label="Loading form options..."
                            variant="overlay"
                            size="md"
                            className="settings-drawer-loading-overlay"
                        />
                    ) : null}
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
                                { max: 255, message: "Name must be at most 255 characters" },
                            ]}
                        >
                            <Input maxLength={255} />
                        </Form.Item>
                        <Form.Item
                            name="sensor_type"
                            label={renderRequiredLabel("Type")}
                            rules={[{ required: true, message: "Select type" }]}
                        >
                            {formMode === "edit" ? (
                                <Input readOnly />
                            ) : (
                                <Select
                                    className="form-drawer-select"
                                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                    options={[
                                        { value: "audio", label: "Audio" },
                                        { value: "photo", label: "Photo" },
                                    ]}
                                />
                            )}
                        </Form.Item>
                        <Form.Item
                            noStyle
                            shouldUpdate={(prev, cur) =>
                                prev.sensor_type !== cur.sensor_type ||
                                prev.recorder_id !== cur.recorder_id ||
                                prev.microphone_id !== cur.microphone_id ||
                                prev.camera_id !== cur.camera_id ||
                                prev.lens_id !== cur.lens_id
                            }
                        >
                            {() => {
                                const t = form.getFieldValue("sensor_type") as string | undefined
                                if (t === "audio") {
                                    return (
                                        <>
                                            <Form.Item
                                                name="recorder_id"
                                                label={renderRequiredLabel("Recorder")}
                                                rules={[{ required: true, message: "Select a recorder" }]}
                                            >
                                                <Select
                                                    className="form-drawer-select"
                                                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                                    options={recorderSelectOptions}
                                                    showSearch
                                                    optionFilterProp="label"
                                                    onChange={(rid: number) => {
                                                        form.setFieldValue("microphone_id", undefined)
                                                        void loadMicsForRecorder(rid)
                                                        void syncRecorderMicrophoneDefault(rid)
                                                    }}
                                                />
                                            </Form.Item>
                                            <Form.Item
                                                name="microphone_id"
                                                label={renderRequiredLabel("Microphone")}
                                                rules={[{ required: true, message: "Select a microphone" }]}
                                            >
                                                <Select
                                                    className="form-drawer-select"
                                                    options={micSelectOptions}
                                                    showSearch
                                                    optionFilterProp="label"
                                                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                                    onChange={(microphoneId: number) => {
                                                        void syncRecorderMicrophoneDefault(
                                                            form.getFieldValue("recorder_id"),
                                                            microphoneId,
                                                        )
                                                    }}
                                                    notFoundContent={
                                                        micSelectOptions.length ? undefined : (
                                                            <EmptyState
                                                                className="form-drawer-select-empty"
                                                                title={form.getFieldValue("recorder_id") == null
                                                                    ? "Pick a recorder first"
                                                                    : "No compatible microphones for this recorder"}
                                                            />
                                                        )
                                                    }
                                                />
                                            </Form.Item>
                                            <Form.Item
                                                className="form-drawer-switch-row"
                                                label="Default combination"
                                                tooltip="Use this recorder–microphone pairing as the default when creating an audio sensor."
                                                colon={false}
                                                required={false}
                                            >
                                                <Form.Item name="recorder_microphone_is_default" valuePropName="checked" noStyle>
                                                    <Switch onChange={() => setRecorderMicrophoneDefaultTouched(true)} />
                                                </Form.Item>
                                            </Form.Item>
                                        </>
                                    )
                                }
                                if (t === "photo") {
                                    return (
                                        <>
                                            <Form.Item
                                                name="camera_id"
                                                label={renderRequiredLabel("Camera")}
                                                rules={[{ required: true, message: "Select a camera" }]}
                                            >
                                                <Select
                                                    className="form-drawer-select"
                                                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                                    options={cameraOptions.options}
                                                    loading={cameraOptions.loading}
                                                    showSearch
                                                    filterOption={false}
                                                    onSearch={cameraOptions.search}
                                                    onPopupScroll={(event) => {
                                                        if (isSelectScrollNearBottom(event.currentTarget)) {
                                                            cameraOptions.loadNext()
                                                        }
                                                    }}
                                                    popupRender={(menu) => (
                                                        <>
                                                            {menu}
                                                            {cameraOptions.loading ? (
                                                                <div
                                                                    style={{
                                                                        display: "flex",
                                                                        justifyContent: "center",
                                                                        padding: 8,
                                                                    }}
                                                                >
                                                                    <LoadingState size="sm" showLabel={false} />
                                                                </div>
                                                            ) : null}
                                                        </>
                                                    )}
                                                    onChange={(cameraId: number) => {
                                                        cameraOptions.setCurrentOption(
                                                            cameraOptions.options.find(
                                                                (option) => option.value === cameraId,
                                                            ) ?? null,
                                                        )
                                                        setCameraLensDefaultTouched(false)
                                                        form.setFieldValue("lens_id", undefined)
                                                        void loadLensesForCamera(cameraId)
                                                    }}
                                                />
                                            </Form.Item>
                                            <Form.Item
                                                name="lens_id"
                                                label={renderRequiredLabel("Lens")}
                                                rules={[{ required: true, message: "Select a lens" }]}
                                            >
                                                <Select
                                                    className="form-drawer-select"
                                                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                                    options={lensSelectOptions}
                                                    showSearch
                                                    optionFilterProp="label"
                                                    onChange={(lensId: number) => {
                                                        void syncCameraLensDefault(form.getFieldValue("camera_id"), lensId)
                                                    }}
                                                    notFoundContent={
                                                        lensSelectOptions.length ? undefined : (
                                                            <EmptyState
                                                                className="form-drawer-select-empty"
                                                                title={form.getFieldValue("camera_id") == null
                                                                    ? "Pick a camera first"
                                                                    : "No compatible lenses for this camera"}
                                                            />
                                                        )
                                                    }
                                                />
                                            </Form.Item>
                                            <Form.Item
                                                className="form-drawer-switch-row"
                                                label="Default combination"
                                                tooltip="Use this camera–lens pairing as the default when creating a photo sensor."
                                                colon={false}
                                                required={false}
                                            >
                                                <Form.Item name="camera_lens_is_default" valuePropName="checked" noStyle>
                                                    <Switch onChange={() => setCameraLensDefaultTouched(true)} />
                                                </Form.Item>
                                            </Form.Item>
                                        </>
                                    )
                                }
                                return null
                            }}
                        </Form.Item>
                        <Form.Item
                            name="description"
                            label="Description"
                            rules={[{ max: 500, message: "Description must be at most 500 characters" }]}
                        >
                            <Input.TextArea rows={4} maxLength={500} />
                        </Form.Item>
                    </Form>
                </div>
            </div>
                </CustomScrollArea>
            </FormDrawer>

        </ConfigProvider>
    )
}
