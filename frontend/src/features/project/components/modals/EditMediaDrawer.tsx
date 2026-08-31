import { useState, useEffect, useMemo } from "react"
import { Button, Form, Input, Select, DatePicker, message, ConfigProvider } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { renderRequiredMark } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { StableText } from "@/components/ui"
import dayjs from "dayjs"
import { EmptyState } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { mediaApi } from "../../../../api/endpoints/media"

import type { SiteOption } from "../../../../api/endpoints/sites"
import type { LicenseOption } from "../../../../api/endpoints/licenses"
import type { SensorOption } from "../../../../api/endpoints/sensors"
import type { UserOption } from "../../../../api/endpoints/users"
import {
    buildMediaUpdatePayload,
    filterSensorsForMediaType,
    formatSensorOptionLabel,
    MEDIA_EDIT_TITLES,
    resolveEditableMediaKind,
} from "./mediaForm"
import "./styles/FormDrawer.css"

// function formatMediaTypeLabel(raw: unknown, isMetadata: boolean): string | null {
//     if (isMetadata) return "Metadata"
//     if (typeof raw !== "string") return null
//     const value = raw.trim().toLowerCase()
//     if (!value) return null
//     if (value === "audio") return "audio"
//     return `${value.charAt(0).toUpperCase()}${value.slice(1)}`
// }

const selectPopupClassName = "form-drawer-select-popup"

export interface EditMediaDrawerProps {
    open: boolean
    mediaId: number | null
    projectId: number | null
    siteOptions?: SiteOption[]
    licenseOptions?: LicenseOption[]
    sensorOptions?: SensorOption[]
    userOptions?: UserOption[]
    onClose: () => void
    onSuccess?: () => void
}

export function EditMediaDrawer({
    open,
    mediaId,
    projectId,
    siteOptions = [],
    licenseOptions = [],
    sensorOptions = [],
    userOptions = [],
    onClose,
    onSuccess
}: EditMediaDrawerProps) {
    const isDark = useAppStore(s => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [form] = Form.useForm()
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [detailMediaType, setDetailMediaType] = useState<string | null>(null)
    const [detailIsMetadata, setDetailIsMetadata] = useState(false)

    const selectEmptyState = (
        <EmptyState className="media-state form-drawer-select-empty" title="No Data" />
    )

    useEffect(() => {
        if (open && mediaId && projectId) {
            fetchDetail(mediaId)
        } else {
            setDetailMediaType(null)
            setDetailIsMetadata(false)
            form.resetFields()
        }
    }, [open, mediaId, projectId, form])

    const fetchDetail = async (id: number) => {
        if (!projectId) return
        setLoading(true)
        try {
            const res = await mediaApi.getMediaDetail(id, projectId)
            if (res.data) {
                const { audio_setting, ...rest } = res.data as any
                const rawMediaType =
                    typeof rest.media_type === "string" ? rest.media_type.trim().toLowerCase() : ""
                const isMetadata = rest.is_metadata === true
                setDetailMediaType(rawMediaType || null)
                setDetailIsMetadata(isMetadata)

                const dateForPicker = rest.date_time ?? rest.creation_date
                form.setFieldsValue({
                    name: rest.name,
                    date_time: dateForPicker ? dayjs(dateForPicker) : null,
                    site_id: rest.site_id,
                    sensor_id: rest.sensor_id,
                    medium: rest.medium,
                    recording_gain_db: audio_setting?.recording_gain_db,
                    sampling_rate_hz: audio_setting?.sampling_rate_hz,
                    bit_depth: audio_setting?.bit_depth,
                    channel_num: audio_setting?.channel_num,
                    duration_s: audio_setting?.duration_s,
                    duty_cycle_recording: rest.duty_cycle_recording,
                    duty_cycle_period: rest.duty_cycle_period,
                    license_id: rest.license_id,
                    doi: rest.doi,
                    note: rest.note,
                    // Read only fields populated for completeness
                    id: rest.media_id || id,
                    uuid: rest.uuid,
                    media_type: rest.media_type,
                    type: isMetadata ? "metadata" : "file",
                    filename: rest.filename,
                    size_b: rest.size_b,
                    uploader: rest.uploader_name ?? rest.uploader ?? null,
                    creator: rest.creator_name ?? rest.creator ?? null,
                    creator_id: rest.creator_id,
                    creation_date: rest.creation_date ? dayjs(rest.creation_date).format('YYYY-MM-DD HH:mm:ss') : null,
                })
            }
        } catch (err: any) {
            console.error('[fetchDetail] failed:', err)
            message.error(err.message || 'Failed to fetch media details')

        } finally {
            setLoading(false)
        }
    }

    const onFinish = async (values: any) => {
        if (!mediaId || !projectId) return
        setSaving(true)
        try {
            const payload = buildMediaUpdatePayload(values, mediaKind)
            await mediaApi.updateMedia(mediaId, projectId, payload)
            message.success(`${mediaLabel} updated successfully`)
            if (onSuccess) onSuccess()
            onClose()
        } catch (err: any) {
            console.error('[updateMedia] failed:', err)
            message.error(err.message || `Failed to update ${mediaLabel.toLowerCase()}`)

        } finally {
            setSaving(false)
        }
    }

    const mediaKind = resolveEditableMediaKind(detailMediaType, detailIsMetadata)
    const isAudioMedia = mediaKind === "audio"
    const isMetadataMedia = mediaKind === "metadata"
    const mediaLabel = mediaKind === "metadata" ? "Metadata" : "Audio"
    const mediaTitle = mediaKind === "metadata" ? MEDIA_EDIT_TITLES.metadata : MEDIA_EDIT_TITLES.audio
    const mediaSensors = useMemo(() => {
        return filterSensorsForMediaType(sensorOptions, detailMediaType)
    }, [detailMediaType, sensorOptions])

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={<span className="form-drawer-title"><StableText>{mediaTitle}</StableText></span>}
                placement="right"
                forceRender
                onClose={onClose}
                open={open}
                styles={{
                    wrapper: {
                        width: 800,
                    },
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
                    mask: {
                        backdropFilter: "blur(4px)",
                    },
                }}
                extra={
                    <div style={{ gap: 8, display: 'flex' }}>
                        <Button onClick={onClose} disabled={saving}><StableText>Cancel</StableText></Button>
                        <Button
                            type="primary"
                            onClick={() => form.submit()}
                            loading={saving}
                            style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
                        >
                            <StableText>Save</StableText>
                        </Button>
                    </div>
                }
            >
                <CustomScrollArea variant="fill">
                    <Form
                        form={form}
                        layout="vertical"
                        onFinish={onFinish}
                        requiredMark={renderRequiredMark}
                        disabled={loading}
                        initialValues={{ medium: 'Air' }}
                        className="shared-drawer-form"
                        style={{ padding: "24px" }}
                    >
                        <div className="form-drawer-layout">
                            <div className="form-drawer-main-col">
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
                                    <DatePicker showTime format="YYYY-MM-DD HH:mm:ss" style={{ width: '100%' }} />
                                </Form.Item>

                                <Form.Item name="site_id" label={<StableText>Site</StableText>}>
                                    <Select
                                        className="form-drawer-select"
                                        classNames={{ popup: { root: selectPopupClassName } }}
                                        getPopupContainer={(trigger) => trigger.parentElement ?? document.body}
                                        options={siteOptions.map(s => ({ label: s.name, value: s.site_id }))}
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
                                        className="form-drawer-select"
                                        classNames={{ popup: { root: selectPopupClassName } }}
                                        getPopupContainer={(trigger) => trigger.parentElement ?? document.body}
                                        options={mediaSensors.map(s => ({ label: formatSensorOptionLabel(s), value: s.sensor_id }))}
                                        allowClear
                                        notFoundContent={selectEmptyState}
                                    />

                                </Form.Item>

                                <Form.Item name="medium" label={<StableText>Medium</StableText>}>
                                    <Select
                                        className="form-drawer-select"
                                        classNames={{ popup: { root: selectPopupClassName } }}
                                        getPopupContainer={(trigger) => trigger.parentElement ?? document.body}
                                        options={[
                                            { label: <StableText>Air</StableText>, value: 'Air' },
                                            { label: <StableText>Water</StableText>, value: 'Water' }
                                        ]}
                                        allowClear
                                    />

                                </Form.Item>

                                {isAudioMedia ? (
                                    <Form.Item
                                        name="recording_gain_db"
                                        label={<StableText>Gain (dB)</StableText>}
                                        rules={[{ required: true, message: "Please enter Gain (dB)" }]}
                                    >
                                        <Input type="number" />
                                    </Form.Item>
                                ) : null}

                                {isMetadataMedia ? (
                                    <>
                                        <Form.Item
                                            name="sampling_rate_hz"
                                            label={<StableText>Sample Rate (Hz)</StableText>}
                                            rules={[{ required: true, message: "Please enter Sample Rate (Hz)" }]}
                                        >
                                            <Input type="number" />
                                        </Form.Item>

                                        <Form.Item name="bit_depth" label={<StableText>Bit Depth</StableText>} required={false}>
                                            <Input type="number" />
                                        </Form.Item>

                                        <Form.Item name="channel_num" label={<StableText>Channels</StableText>} required={false}>
                                            <Input type="number" />
                                        </Form.Item>

                                        <Form.Item
                                            name="duration_s"
                                            label={<StableText>Duration (s)</StableText>}
                                            rules={[{ required: true, message: "Please enter Duration (s)" }]}
                                        >
                                            <Input type="number" />
                                        </Form.Item>

                                        <Form.Item name="recording_gain_db" label={<StableText>Gain (dB)</StableText>} required={false}>
                                            <Input type="number" />
                                        </Form.Item>

                                        <Form.Item name="duty_cycle_recording" label={<StableText>Duty Rec (s)</StableText>} required={false}>
                                            <Input type="number" />
                                        </Form.Item>

                                        <Form.Item name="duty_cycle_period" label={<StableText>Duty Period (s)</StableText>} required={false}>
                                            <Input type="number" />
                                        </Form.Item>
                                    </>
                                ) : null}

                                <Form.Item name="license_id" label={<StableText>License</StableText>}>
                                    <Select
                                        className="form-drawer-select"
                                        classNames={{ popup: { root: selectPopupClassName } }}
                                        getPopupContainer={(trigger) => trigger.parentElement ?? document.body}
                                        options={licenseOptions.map(l => ({ label: l.name, value: l.license_id }))}
                                        allowClear
                                        notFoundContent={selectEmptyState}
                                    />

                                </Form.Item>

                                <Form.Item name="doi" label={<StableText>DOI</StableText>}>
                                    <Input />
                                </Form.Item>

                                <Form.Item name="note" label={<StableText>Note</StableText>}>
                                    <Input />
                                </Form.Item>

                                <Form.Item name="creator_id" label={<StableText>Creator</StableText>} required={false}>
                                    <Select
                                        className="form-drawer-select"
                                        classNames={{ popup: { root: selectPopupClassName } }}
                                        getPopupContainer={(trigger) => trigger.parentElement ?? document.body}
                                        options={userOptions.map((user) => ({ label: user.name, value: user.user_id }))}
                                        allowClear
                                        notFoundContent={selectEmptyState}
                                    />
                                </Form.Item>
                            </div>

                            <div className="form-drawer-side-col">
                                <Form.Item name="id" label={<StableText>ID</StableText>} required={false}>
                                    <Input disabled className="media-readonly-field" />
                                </Form.Item>

                                <Form.Item name="uuid" label={<StableText>UUID</StableText>} required={false}>
                                    <Input disabled className="media-readonly-field" />
                                </Form.Item>

                                <Form.Item name="media_type" label={<StableText>Media Type</StableText>} required={false}>
                                    <Input disabled className="media-readonly-field" />
                                </Form.Item>

                                <Form.Item name="type" label={<StableText>Type</StableText>} required={false}>
                                    <Input disabled className="media-readonly-field" />
                                </Form.Item>

                                {isAudioMedia ? (
                                    <>
                                        <Form.Item name="filename" label={<StableText>Filename</StableText>} required={false}>
                                            <Input disabled className="media-readonly-field" />
                                        </Form.Item>

                                        <Form.Item name="sampling_rate_hz" label={<StableText>Sample Rate (Hz)</StableText>} required={false}>
                                            <Input disabled className="media-readonly-field" />
                                        </Form.Item>

                                        <Form.Item name="bit_depth" label={<StableText>Bit Depth</StableText>} required={false}>
                                            <Input disabled className="media-readonly-field" />
                                        </Form.Item>

                                        <Form.Item name="channel_num" label={<StableText>Channels</StableText>} required={false}>
                                            <Input disabled className="media-readonly-field" />
                                        </Form.Item>

                                        <Form.Item name="duration_s" label={<StableText>Duration (s)</StableText>} required={false}>
                                            <Input disabled className="media-readonly-field" />
                                        </Form.Item>

                                        <Form.Item name="size_b" label={<StableText>Size (Bytes)</StableText>} required={false}>
                                            <Input disabled className="media-readonly-field" />
                                        </Form.Item>
                                    </>
                                ) : null}

                                <Form.Item name="uploader" label={<StableText>Uploader</StableText>} required={false}>
                                    <Input disabled className="media-readonly-field" />
                                </Form.Item>

                                <Form.Item name="creation_date" label={<StableText>Created</StableText>} required={false}>
                                    <Input disabled className="media-readonly-field" />
                                </Form.Item>
                            </div>
                        </div>
                    </Form>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
