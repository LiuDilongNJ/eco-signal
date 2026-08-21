import { Button as ESButton } from "@/components/ui"
import { useEffect, useMemo, useState } from "react"
import { Button, ConfigProvider, Typography, Select, Input, Switch, Progress, Form, DatePicker } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { Music2, CheckCircle2, Upload, RefreshCw } from "lucide-react"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { CustomScrollArea } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import type { SiteOption } from "../../../../api/endpoints/sites"

import type { LicenseOption } from "../../../../api/endpoints/licenses"
import type { SensorOption } from "../../../../api/endpoints/sensors"
import type { UserOption } from "../../../../api/endpoints/users"
import { MEDIA_ADD_TITLES, filterSensorsForMediaType } from "./mediaForm"
import "./styles/FormDrawer.css"
import "./styles/UploadAudioDrawer.css"

export interface QueueFile {
    id: string
    name: string
    file: File
    status: 'pending' | 'uploading' | 'done' | 'error'
    progress: number
    file_upload_id?: number
    /** 上传失败原因（由上传逻辑填充） */
    errorMessage?: string
    /** 兼容历史字段（可能是 string / Error / axios error） */
    error?: unknown
    message?: unknown
}

interface UploadAudioDrawerProps {
    open: boolean
    initialFiles?: QueueFile[]
    batchId?: string | null
    siteOptions?: SiteOption[]
    licenseOptions?: LicenseOption[]
    sensorOptions?: SensorOption[]
    userOptions?: UserOption[]
    onClose: () => void
    onSave?: (
        files: QueueFile[],
        formData: Record<string, any>,
    ) => boolean | void | Promise<boolean | void>
    onAddMoreFiles?: () => void
    onRetry?: (file: QueueFile) => void
}

const MEDIUM_OPTIONS = ["Air", "Water"]

type UploadAudioValidationField = "date_time" | "sensor_id" | "gain"

export function UploadAudioDrawer({ open, initialFiles = [], siteOptions = [], licenseOptions = [], sensorOptions = [], userOptions = [], onClose, onSave, onAddMoreFiles, onRetry }: UploadAudioDrawerProps) {
    const isDark = useAppStore(s => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [formData, setFormData] = useState<Record<string, any>>({})
    const [validationErrors, setValidationErrors] = useState<Partial<Record<UploadAudioValidationField, string>>>({})
    const queueFiles = initialFiles

    const completedCount = queueFiles.filter(f => f.status === 'done').length
    const hasActiveUploads = queueFiles.some(
        (f) => f.status === "pending" || f.status === "uploading",
    )
    const queueFingerprint = queueFiles.map(f => `${f.id}:${f.status}:${f.progress}`).join("|")
    const selectEmptyState = <EmptyState className="form-drawer-select-empty" title="No Data" />
    const audioSensors = useMemo(
        () => filterSensorsForMediaType(sensorOptions, "audio"),
        [sensorOptions],
    )

    useEffect(() => {
        if (!open) {
            setValidationErrors({})
        }
    }, [open])

    const clearValidationError = (field: UploadAudioValidationField) => {
        setValidationErrors((prev) => {
            if (!prev[field]) return prev
            const next = { ...prev }
            delete next[field]
            return next
        })
    }

    const validateBeforeSave = () => {
        const nextErrors: Partial<Record<UploadAudioValidationField, string>> = {}
        const useFilenameDate = Boolean(formData.dateFromFilename)
        const hasDateTime = typeof formData.date_time === "string" && formData.date_time.trim() !== ""
        if (!useFilenameDate && !hasDateTime) {
            nextErrors.date_time = "Please set Date Time or enable From filename"
        }
        if (formData.sensor_id == null) {
            nextErrors.sensor_id = "Please select Sensor"
        }
        if (formData.gain == null || String(formData.gain).trim() === "") {
            nextErrors.gain = "Please enter Gain (dB)"
        }
        setValidationErrors(nextErrors)
        return Object.keys(nextErrors).length === 0
    }

    const renderRequiredLabel = (label: string) => (
        <>
            {label}
            <span className="form-drawer-required-suffix">*</span>
        </>
    )

    const resolveUploadErrorText = (f: QueueFile): string | null => {
        const direct = f.errorMessage
        if (direct && String(direct).trim()) return String(direct).trim()

        const e: any = (f as any).error ?? (f as any).message
        if (!e) return null
        if (typeof e === "string" && e.trim()) return e.trim()
        if (e instanceof Error && e.message) return e.message

        // axios / fetch-like shapes
        const nested =
            e?.response?.data?.message ??
            e?.response?.data?.detail ??
            e?.data?.message ??
            e?.detail ??
            e?.message
        if (typeof nested === "string" && nested.trim()) return nested.trim()

        try {
            const s = JSON.stringify(e)
            return s && s !== "{}" ? s : null
        } catch {
            return null
        }
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={MEDIA_ADD_TITLES.audio}
                open={open}
                onClose={onClose}
                placement="right"
                styles={{
                    wrapper: {
                        width: 800,
                    },
                    header: {
                        color: "var(--text-main)",
                        borderBottom: "none",
                    },
                    body: {
                        padding: 0,
                        overflow: "hidden",
                    },
                    mask: { backdropFilter: "blur(4px)" },
                }}
                extra={
                    <div style={{ display: 'flex', gap: 12 }}>
                        <Button onClick={onClose}>Cancel</Button>
                        <Button
                            type="primary"
                            className="upload-audio-drawer-save-btn"
                            disabled={hasActiveUploads}
                            onClick={async () => {
                                if (hasActiveUploads) return
                                if (!validateBeforeSave()) return
                                const saved = await onSave?.(queueFiles, formData)
                                if (saved === false) return
                                onClose()
                            }}
                        >
                            Save
                        </Button>
                    </div>
                }
            >
                <CustomScrollArea variant="fill">
                    <div className="form-drawer-layout upload-audio-drawer-layout" style={{ padding: "24px" }}>
                        <div className="form-drawer-main-col upload-audio-drawer-queue-col">
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                                <Typography.Text strong>Queue</Typography.Text>
                                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                    Total: {queueFiles.length} | Completed: {completedCount}
                                </Typography.Text>
                            </div>
                            <CustomScrollArea
                                className="upload-audio-drawer-queue-scroll"
                                bodyClassName="upload-audio-drawer-queue-scroll__body"
                                variant="fill"
                                contentFingerprint={queueFingerprint}
                            >
                                <div className="upload-audio-drawer-queue-list">
                                    {queueFiles.map(f => (
                                        <div key={f.id} style={{
                                            border: '1px solid var(--border-color)',
                                            borderRadius: 8,
                                            padding: '10px 14px',
                                            background: 'var(--bg-surface)',
                                        }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                                {f.status === 'done'
                                                    ? <CheckCircle2 size={16} color="var(--brand)" />
                                                    : <Music2 size={16} color="var(--brand)" />}
                                                <Typography.Text style={{ fontSize: 13, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {f.name}
                                                </Typography.Text>
                                            </div>
                                            <Progress
                                                percent={f.progress}
                                                size="small"
                                                status={f.status === 'error' ? 'exception' : f.status === 'done' ? 'success' : 'active'}
                                                strokeColor="var(--brand)"
                                                styles={{ indicator: { color: "var(--brand)" } }}
                                            />
                                            {(() => {
                                                const errText = f.status === "error" ? resolveUploadErrorText(f) : null
                                                const statusText =
                                                    f.status === 'done'
                                                        ? 'Completed'
                                                        : f.status === 'uploading'
                                                            ? 'Uploading...'
                                                            : f.status === 'pending'
                                                                ? 'Pending'
                                                                : null
                                                return (
                                                    <>
                                                        {statusText ? (
                                                            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                                                                {statusText}
                                                            </Typography.Text>
                                                        ) : null}
                                                        {errText ? (
                                                            <Typography.Text
                                                                style={{
                                                                    display: "block",
                                                                    marginTop: 4,
                                                                    fontSize: 11,
                                                                    color: "var(--danger)",
                                                                }}
                                                            >
                                                                {errText}
                                                            </Typography.Text>
                                                        ) : null}
                                                    </>
                                                )
                                            })()}
                                            {f.status === 'error' && onRetry && (
                                                <ESButton appearance="unstyled"
                                                    onClick={() => onRetry(f)}
                                                    style={{
                                                        background: 'none', border: 'none', cursor: 'pointer', padding: 0, marginLeft: 8,
                                                        display: 'flex', alignItems: 'center', color: 'var(--text-muted)'
                                                    }}
                                                    title="Retry upload"
                                                >
                                                    <RefreshCw size={12} />
                                                </ESButton>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </CustomScrollArea>
                            <div className="upload-audio-drawer-upload-action">
                                <Button
                                    className="upload-audio-drawer-upload-btn"
                                    onClick={onAddMoreFiles}
                                    icon={<Upload size={16} />}
                                    disabled={!onAddMoreFiles}
                                >
                                    Upload
                                </Button>
                            </div>
                        </div>

                        {/* Right: Metadata Form */}
                        <div className="form-drawer-side-col upload-audio-drawer-form-col">
                            <Form layout="vertical" className="upload-audio-form shared-drawer-form">
                                <Form.Item
                                    validateStatus={validationErrors.date_time ? "error" : undefined}
                                    help={validationErrors.date_time}
                                    label={
                                        <div className="upload-audio-form-label-row">
                                            <span>
                                                Date Time
                                                <span className="form-drawer-required-suffix">*</span>
                                            </span>
                                            <div className="upload-audio-form-label-toggle">
                                                <span className="upload-audio-form-label-toggle-text">From filename</span>
                                                <span className="upload-audio-form-label-toggle-sep" aria-hidden>
                                                    |
                                                </span>
                                                <ConfigProvider wave={{ disabled: true }}>
                                                    <Switch
                                                        size="small"
                                                        checked={formData.dateFromFilename || false}
                                                        onChange={v => {
                                                            setFormData(p => ({
                                                                ...p,
                                                                dateFromFilename: v,
                                                                date_time: v ? undefined : p.date_time,
                                                            }))
                                                            clearValidationError("date_time")
                                                        }}
                                                    />
                                                </ConfigProvider>
                                            </div>
                                        </div>
                                    }
                                >
                                    <DatePicker
                                        showTime
                                        style={{ width: '100%' }}
                                        disabled={formData.dateFromFilename}
                                        onChange={(_, str) => {
                                            setFormData(p => ({ ...p, date_time: str }))
                                            clearValidationError("date_time")
                                        }}
                                    />
                                </Form.Item>
                                <Form.Item label="Site">
                                    <Select
                                        showSearch
                                        optionFilterProp="label"
                                        classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                        notFoundContent={selectEmptyState}

                                        options={siteOptions.map(s => ({ value: s.site_id, label: s.name }))}
                                        onChange={v => setFormData(p => ({ ...p, site_id: v }))}
                                    />
                                </Form.Item>
                                <Form.Item
                                    label={renderRequiredLabel("Sensor")}
                                    validateStatus={validationErrors.sensor_id ? "error" : undefined}
                                    help={validationErrors.sensor_id}
                                >
                                    <Select
                                        showSearch
                                        optionFilterProp="label"
                                        classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                        notFoundContent={selectEmptyState}

                                        options={audioSensors.map(s => ({ value: s.sensor_id, label: s.name }))}
                                        onChange={v => {
                                            setFormData(p => ({ ...p, sensor_id: v }))
                                            clearValidationError("sensor_id")
                                        }}
                                    />
                                </Form.Item>
                                <Form.Item label="Medium">
                                    <Select
                                        showSearch
                                        optionFilterProp="label"
                                        classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                        value={MEDIUM_OPTIONS.includes(formData.medium) ? formData.medium : undefined}
                                        options={MEDIUM_OPTIONS.map(s => ({ value: s, label: s }))}
                                        onChange={v => setFormData(p => ({ ...p, medium: v }))}
                                    />
                                </Form.Item>
                                <Form.Item label="License">
                                    <Select
                                        showSearch
                                        optionFilterProp="label"
                                        classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                        notFoundContent={selectEmptyState}

                                        options={licenseOptions.map(l => ({ value: l.license_id, label: l.name }))}
                                        onChange={v => setFormData(p => ({ ...p, license_id: v }))}
                                    />
                                </Form.Item>
                                <Form.Item label="Creator">
                                    <Select
                                        showSearch
                                        optionFilterProp="label"
                                        classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                        notFoundContent={selectEmptyState}
                                        options={userOptions.map((user) => ({ value: user.user_id, label: user.name }))}
                                        onChange={v => setFormData(p => ({ ...p, creator_id: v }))}
                                    />
                                </Form.Item>
                                <Form.Item
                                    label={renderRequiredLabel("Gain (dB)")}
                                    validateStatus={validationErrors.gain ? "error" : undefined}
                                    help={validationErrors.gain}
                                >
                                    <Input
                                        type="number"
                                        onChange={e => {
                                            setFormData(p => ({ ...p, gain: e.target.value }))
                                            clearValidationError("gain")
                                        }}
                                    />
                                </Form.Item>
                                <Form.Item label="DOI">
                                    <Input onChange={e => setFormData(p => ({ ...p, doi: e.target.value }))} />
                                </Form.Item>
                                <Form.Item label="Note">
                                    <Input onChange={e => setFormData(p => ({ ...p, note: e.target.value }))} />
                                </Form.Item>
                                <Form.Item label="Sound Name Prefix">
                                    <Input onChange={e => setFormData(p => ({ ...p, sound_name_prefix: e.target.value }))} />
                                </Form.Item>
                            </Form>
                        </div>
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
