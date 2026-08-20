import { Button as ESButton } from "@/components/ui"
import { useEffect, useMemo, useState } from "react"
import { Button, ConfigProvider, DatePicker, Form, Input, message, Progress, Select, Switch, Typography } from "@/components/ui"
import { CheckCircle2, Image as ImageIcon, RefreshCw, Upload as UploadIcon } from "lucide-react"
import { FormDrawer } from "@/components/ui"
import { CustomScrollArea } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import { StableText } from "@/components/ui"
import { UnifiedImage } from "@/components/ui"
import { renderRequiredLabel, renderRequiredMark } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import type { QueueFile } from "./UploadAudioDrawer"
import { mediaApi, type MediaPublic } from "../../../../api/endpoints/media"
import type { LicenseOption } from "../../../../api/endpoints/licenses"
import type { SiteOption } from "../../../../api/endpoints/sites"
import type { SensorOption } from "../../../../api/endpoints/sensors"
import {
    buildMediaUpdatePayload,
    filterSensorsForMediaType,
    MEDIA_ADD_TITLES,
    MEDIA_EDIT_TITLES,
} from "./mediaForm"
import dayjs from "dayjs"
import "./styles/FormDrawer.css"
import "./styles/PhotoMediaDrawer.css"

type AddPhotoProps = {
    mode: "add"
    open: boolean
    files: QueueFile[]
    sites: SiteOption[]
    licenses: LicenseOption[]
    sensors: SensorOption[]
    onClose: () => void
    onAddFiles: () => void
    onRetry?: (file: QueueFile) => void
    onSave: (values: Record<string, unknown>) => void | Promise<void>
}

type EditPhotoProps = {
    mode: "edit"
    open: boolean
    mediaId: number | null
    projectId: number | null
    sites: SiteOption[]
    licenses: LicenseOption[]
    sensors: SensorOption[]
    onClose: () => void
    onSuccess?: () => void
}

type PhotoMediaDrawerProps = AddPhotoProps | EditPhotoProps

const selectPopupClassName = "form-drawer-select-popup"

export function PhotoMediaDrawer(props: PhotoMediaDrawerProps) {
    const { open, sites, licenses, sensors, onClose } = props
    const mode = props.mode
    const editMediaId = props.mode === "edit" ? props.mediaId : null
    const editProjectId = props.mode === "edit" ? props.projectId : null
    const addFiles = props.mode === "add" ? props.files : undefined
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const theme = useAntdBrandConfig(isDark)
    const [form] = Form.useForm()
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [detail, setDetail] = useState<MediaPublic | null>(null)
    const [dateFromFilename, setDateFromFilename] = useState(false)
    const files = useMemo(() => addFiles ?? [], [addFiles])
    const active = files.some((file) => file.status === "pending" || file.status === "uploading")
    const hasCompletedFiles = files.some((file) => file.status === "done")
    const completedCount = files.filter((file) => file.status === "done").length
    const queueFingerprint = files.map((file) => `${file.id}:${file.status}:${file.progress}`).join("|")
    const photoSensors = useMemo(
        () => filterSensorsForMediaType(sensors, "photo"),
        [sensors],
    )
    const selectEmptyState = <EmptyState className="form-drawer-select-empty" title="No Data" />

    useEffect(() => {
        if (!open) {
            form.resetFields()
            setDetail(null)
            setLoading(false)
            setDateFromFilename(false)
            return
        }
        if (mode === "add") {
            setLoading(false)
            setDateFromFilename(false)
            form.setFieldsValue({ medium: "Air" })
            return
        }
        if (!editMediaId || !editProjectId) return

        let cancelled = false
        setLoading(true)
        mediaApi.getMediaDetail(editMediaId, editProjectId)
            .then((response) => {
                if (cancelled || !response.data) return
                const media = response.data
                setDetail(media)
                const dateValue = media.date_time ?? media.creation_date
                form.setFieldsValue({
                    name: media.name,
                    date_time: dateValue ? dayjs(dateValue) : null,
                    site_id: media.site_id,
                    sensor_id: media.sensor_id,
                    medium: media.medium,
                    license_id: media.license_id,
                    doi: media.doi,
                    note: media.note,
                    id: media.media_id ?? media.id,
                    uuid: media.uuid,
                    media_type: String(media.media_type ?? "photo").trim().toLowerCase() || "photo",
                    type: media.is_metadata === true ? "metadata" : "file",
                    filename: media.filename,
                    size_b: media.size_b,
                    exposure_ms: media.photo_setting?.exposure_ms,
                    aperture: media.photo_setting?.aperture,
                    iso: media.photo_setting?.iso,
                    uploader: media.uploader_name ?? media.uploader_id,
                    creator: media.creator_name ?? media.creator_id,
                    creation_date: media.creation_date,
                })
            })
            .catch((error: unknown) => {
                console.error("Failed to fetch photo details:", error)
                message.error(error instanceof Error ? error.message : "Failed to fetch photo details")
            })
            .finally(() => {
                if (!cancelled) setLoading(false)
            })

        return () => {
            cancelled = true
        }
    }, [editMediaId, editProjectId, form, mode, open])

    const handleFinish = async (values: Record<string, unknown>) => {
        setSaving(true)
        try {
            if (props.mode === "add") {
                await props.onSave({ ...values, date_from_filename: dateFromFilename })
                return
            }
            if (!props.mediaId || !props.projectId) return
            await mediaApi.updateMedia(
                props.mediaId,
                props.projectId,
                buildMediaUpdatePayload(values, "photo"),
            )
            message.success("Photo updated successfully")
            props.onSuccess?.()
            onClose()
        } catch (error: unknown) {
            console.error(`Failed to ${props.mode === "add" ? "create" : "update"} photo media:`, error)
            message.error(error instanceof Error ? error.message : `Failed to ${props.mode === "add" ? "save photos" : "update photo"}`)
        } finally {
            setSaving(false)
        }
    }

    const resolveUploadErrorText = (file: QueueFile): string | null => {
        const direct = file.errorMessage
        if (direct && String(direct).trim()) return String(direct).trim()

        const error = file.error ?? file.message
        if (!error) return null
        if (typeof error === "string" && error.trim()) return error.trim()
        if (error instanceof Error && error.message) return error.message

        const maybeError = error as {
            response?: { data?: { message?: unknown; detail?: unknown } }
            data?: { message?: unknown }
            detail?: unknown
            message?: unknown
        }
        const nested =
            maybeError.response?.data?.message ??
            maybeError.response?.data?.detail ??
            maybeError.data?.message ??
            maybeError.detail ??
            maybeError.message
        if (typeof nested === "string" && nested.trim()) return nested.trim()

        try {
            const serialized = JSON.stringify(error)
            return serialized && serialized !== "{}" ? serialized : null
        } catch {
            return null
        }
    }

    const commonFields = (
        <>
            {props.mode === "edit" ? (
                <>
                    <Form.Item
                        name="name"
                        label={<StableText>Name</StableText>}
                        rules={[{ required: true, message: "Please enter a name" }]}
                    >
                        <Input />
                    </Form.Item>
                    <Form.Item
                        name="date_time"
                        label={<StableText>Date Time</StableText>}
                        rules={[{ required: true, message: "Please select Date Time" }]}
                    >
                        <DatePicker showTime format="YYYY-MM-DD HH:mm:ss" />
                    </Form.Item>
                </>
            ) : (
                <Form.Item
                    name="date_time"
                    className="photo-media-drawer-datetime-item"
                    label={
                        <div className="photo-media-drawer-label-row">
                            <span className="photo-media-drawer-label-title">
                                {renderRequiredLabel(<StableText>Date Time</StableText>)}
                            </span>
                            <div className="photo-media-drawer-label-toggle">
                                <span className="photo-media-drawer-label-toggle-text">From filename</span>
                                <span className="photo-media-drawer-label-toggle-sep" aria-hidden>|</span>
                                <ConfigProvider wave={{ disabled: true }}>
                                    <Switch
                                        size="small"
                                        checked={dateFromFilename}
                                        onChange={(checked) => {
                                            setDateFromFilename(checked)
                                            if (checked) {
                                                form.setFieldValue("date_time", null)
                                                form.setFields([{ name: "date_time", errors: [] }])
                                            }
                                        }}
                                    />
                                </ConfigProvider>
                            </div>
                        </div>
                    }
                    rules={[
                        {
                            validator: (_, value) => {
                                if (dateFromFilename || value) return Promise.resolve()
                                return Promise.reject(new Error("Please select Date Time"))
                            },
                        },
                    ]}
                >
                    <DatePicker showTime format="YYYY-MM-DD HH:mm:ss" disabled={dateFromFilename} />
                </Form.Item>
            )}
            <Form.Item name="site_id" label={<StableText>Site</StableText>}>
                <Select
                    showSearch
                    optionFilterProp="label"
                    className="form-drawer-select"
                    classNames={{ popup: { root: selectPopupClassName } }}
                    options={sites.map((site) => ({ value: site.site_id, label: site.name }))}
                    allowClear
                    notFoundContent={selectEmptyState}
                />
            </Form.Item>
            <Form.Item
                name="sensor_id"
                label={<StableText>Sensor</StableText>}
                rules={[{ required: true, message: "Please select Sensor" }]}
            >
                <Select
                    showSearch
                    optionFilterProp="label"
                    className="form-drawer-select"
                    classNames={{ popup: { root: selectPopupClassName } }}
                    options={photoSensors.map((sensor) => ({ value: sensor.sensor_id, label: sensor.name }))}
                    allowClear
                    notFoundContent={selectEmptyState}
                />
            </Form.Item>
            <Form.Item name="medium" label={<StableText>Medium</StableText>}>
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: selectPopupClassName } }}
                    options={[{ value: "Air", label: "Air" }, { value: "Water", label: "Water" }]}
                    allowClear
                />
            </Form.Item>
            <Form.Item name="license_id" label={<StableText>License</StableText>}>
                <Select
                    showSearch
                    optionFilterProp="label"
                    className="form-drawer-select"
                    classNames={{ popup: { root: selectPopupClassName } }}
                    options={licenses.map((license) => ({ value: license.license_id, label: license.name }))}
                    allowClear
                    notFoundContent={selectEmptyState}
                />
            </Form.Item>
            <Form.Item name="doi" label={<StableText>DOI</StableText>}>
                <Input maxLength={255} />
            </Form.Item>
            <Form.Item name="note" label={<StableText>Note</StableText>} className="photo-media-drawer-note-item">
                <Input maxLength={500} />
            </Form.Item>
        </>
    )

    return (
        <ConfigProvider theme={theme}>
            <FormDrawer
                title={
                    <span className="form-drawer-title">
                        <StableText>{props.mode === "add" ? MEDIA_ADD_TITLES.photo : MEDIA_EDIT_TITLES.photo}</StableText>
                    </span>
                }
                open={open}
                onClose={onClose}
                placement="right"
                closable={false}
                maskClosable={false}
                forceRender
                styles={{
                    wrapper: { width: 800 },
                    header: { borderBottom: "none", color: "var(--text-main)" },
                    body: { padding: 0, overflow: "hidden" },
                    mask: { backdropFilter: "blur(4px)" },
                }}
                extra={
                    <div className="photo-media-drawer-actions">
                        <Button onClick={onClose} disabled={saving}>Cancel</Button>
                        <Button
                            type="primary"
                            className="photo-media-drawer-save-btn"
                            loading={saving}
                            disabled={props.mode === "add" && (active || !hasCompletedFiles)}
                            onClick={() => form.submit()}
                        >
                            Save
                        </Button>
                    </div>
                }
            >
                <CustomScrollArea variant="fill">
                    <Form
                        form={form}
                        layout="vertical"
                        onFinish={handleFinish}
                        requiredMark={renderRequiredMark}
                        disabled={loading}
                        initialValues={{ medium: "Air" }}
                        className="shared-drawer-form photo-media-drawer-form"
                    >
                        <div className={`form-drawer-layout photo-media-drawer-layout${props.mode === "add" ? " photo-media-drawer-layout--add" : ""}`}>
                            {props.mode === "add" ? (
                                <>
                                    <div className="form-drawer-main-col photo-media-drawer-upload-col">
                                        <div className="photo-media-drawer-queue-header">
                                            <Typography.Text strong>Queue</Typography.Text>
                                            <Typography.Text type="secondary" className="photo-media-drawer-queue-total">
                                                Total: {files.length} | Completed: {completedCount}
                                            </Typography.Text>
                                        </div>
                                        <CustomScrollArea
                                            className="photo-media-drawer-queue-scroll"
                                            bodyClassName="photo-media-drawer-queue-scroll__body"
                                            variant="fill"
                                            contentFingerprint={queueFingerprint}
                                        >
                                            <div className="photo-media-drawer-queue-list">
                                                {files.map((file) => {
                                                    const errorText = file.status === "error" ? resolveUploadErrorText(file) : null
                                                    const statusText =
                                                        file.status === "done"
                                                            ? "Completed"
                                                        : file.status === "uploading"
                                                                    ? "Uploading..."
                                                                    : file.status === "pending"
                                                                        ? "Pending"
                                                                        : null
                                                    return (
                                                        <div key={file.id} className="photo-media-drawer-queue-item">
                                                            <div className="photo-media-drawer-queue-item-row">
                                                                {file.status === "done" ? (
                                                                    <CheckCircle2 size={16} color="var(--brand)" />
                                                                ) : (
                                                                    <ImageIcon size={16} color="var(--brand)" />
                                                                )}
                                                                <Typography.Text className="photo-media-drawer-queue-file-name">
                                                                    {file.name}
                                                                </Typography.Text>
                                                            </div>
                                                            <Progress
                                                                percent={file.progress}
                                                                size="small"
                                                                status={file.status === "error" ? "exception" : file.status === "done" ? "success" : "active"}
                                                                strokeColor="var(--brand)"
                                                                styles={{ indicator: { color: "var(--brand)" } }}
                                                            />
                                                            {statusText ? (
                                                                <Typography.Text
                                                                    type="secondary"
                                                                    className="photo-media-drawer-queue-status"
                                                                >
                                                                    {statusText}
                                                                </Typography.Text>
                                                            ) : null}
                                                            {errorText ? (
                                                                <Typography.Text className="photo-media-drawer-queue-error">
                                                                    {errorText}
                                                                </Typography.Text>
                                                            ) : null}
                                                            {file.status === "error" && props.onRetry ? (
                                                                <ESButton appearance="unstyled"
                                                                    type="button"
                                                                    className="photo-media-drawer-queue-retry"
                                                                    onClick={() => props.onRetry?.(file)}
                                                                    title="Retry upload"
                                                                >
                                                                    <RefreshCw size={12} />
                                                                </ESButton>
                                                            ) : null}
                                                        </div>
                                                    )
                                                })}
                                            </div>
                                        </CustomScrollArea>
                                        <div className="photo-media-drawer-upload-action">
                                            <Button
                                                className="photo-media-drawer-upload-btn"
                                                icon={<UploadIcon size={16} />}
                                                onClick={props.onAddFiles}
                                            >
                                                Upload
                                            </Button>
                                        </div>
                                    </div>
                                    <div className="form-drawer-side-col">
                                        {commonFields}
                                    </div>
                                </>
                            ) : (
                                <>
                                    <div className="form-drawer-main-col">
                                        {commonFields}
                                    </div>
                                    <div className="form-drawer-side-col">
                                        {detail?.preview_url ? (
                                            <UnifiedImage
                                                className="photo-media-drawer-preview"
                                                src={detail.preview_url}
                                                alt={detail.name || detail.filename || "Photo"}
                                            />
                                        ) : null}
                                        <Form.Item name="id" label={<StableText>ID</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="uuid" label={<StableText>UUID</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="media_type" label={<StableText>Media Type</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="type" label={<StableText>Type</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="filename" label={<StableText>Filename</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="size_b" label={<StableText>Size (Bytes)</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="exposure_ms" label={<StableText>Exposure (ms)</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="aperture" label={<StableText>Aperture</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="iso" label={<StableText>ISO</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="uploader" label={<StableText>Uploader</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="creator" label={<StableText>Creator</StableText>}><Input readOnly /></Form.Item>
                                        <Form.Item name="creation_date" label={<StableText>Created</StableText>}><Input readOnly /></Form.Item>
                                    </div>
                                </>
                            )}
                        </div>
                    </Form>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
