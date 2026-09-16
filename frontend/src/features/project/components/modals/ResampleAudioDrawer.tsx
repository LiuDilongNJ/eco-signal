import { useEffect, useState } from "react"
import { Alert, Button, ConfigProvider, Form, Select, Typography, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { mediaApi, type AudioResamplingAnnotationImpact } from "@/api/endpoints/media"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { isResamplingRateSupportedForCodec, RESAMPLING_RATE_OPTIONS } from "./resamplingOptions"
import { ConfirmDialog } from "./ConfirmDialog"
import "./styles/ResampleAudioDrawer.css"

function annotationImpactMessage(impact: AudioResamplingAnnotationImpact): string {
    const messages: string[] = []
    if (impact.removed_annotation_count > 0) {
        const count = impact.removed_annotation_count
        messages.push(
            `${count} annotation${count === 1 ? "" : "s"} entirely above ${impact.max_frequency_hz} Hz will be permanently removed.`,
        )
    }
    if (impact.clipped_annotation_count > 0) {
        const count = impact.clipped_annotation_count
        messages.push(
            `${count} overlapping annotation${count === 1 ? "" : "s"} will be kept and capped at ${impact.max_frequency_hz} Hz.`,
        )
    }
    return messages.join(" ")
}

export function ResampleAudioDrawer({
    open,
    mediaIds,
    projectId,
    maxTargetSamplingRate,
    selectedAudioCodecs = [],
    onClose,
    onSubmitted,
}: {
    open: boolean
    mediaIds: number[]
    projectId: number | null
    maxTargetSamplingRate?: number
    selectedAudioCodecs?: Array<string | null | undefined>
    onClose: () => void
    onSubmitted: (queueId: number) => void
}) {
    const isDark = useAppStore((state) => state.effectiveTheme === "dark")
    const theme = useAntdBrandConfig(isDark)
    const [rate, setRate] = useState<number | undefined>()
    const [saving, setSaving] = useState(false)
    const [confirmOpen, setConfirmOpen] = useState(false)
    const [preview, setPreview] = useState<{
        key: string
        impact: AudioResamplingAnnotationImpact
    } | null>(null)
    const [previewError, setPreviewError] = useState<string | null>(null)
    const [previewRequestVersion, setPreviewRequestVersion] = useState(0)
    const [checkingPreview, setCheckingPreview] = useState(false)

    const availableRates = RESAMPLING_RATE_OPTIONS.filter((value) => (
        (maxTargetSamplingRate == null || value <= maxTargetSamplingRate) &&
        selectedAudioCodecs.every((codec) => isResamplingRateSupportedForCodec(codec, value))
    ))
    const rateIsAllowed = rate != null && availableRates.some((value) => value === rate)
    const previewKey = open && projectId && rate && rateIsAllowed && mediaIds.length
        ? `${projectId}:${rate}:${mediaIds.join(",")}`
        : null
    const annotationImpact = preview?.key === previewKey ? preview.impact : null
    const previewReady = previewKey != null && annotationImpact != null && !checkingPreview && !previewError
    const impactMessage = annotationImpact ? annotationImpactMessage(annotationImpact) : ""
    const hasAnnotationImpact = Boolean(
        annotationImpact && (
            annotationImpact.removed_annotation_count > 0 ||
            annotationImpact.clipped_annotation_count > 0
        ),
    )
    const rateOptions = availableRates.map((value) => {
        return {
            value,
            label: <span className="resample-audio-rate-option">{value}</span>,
        }
    })

    useEffect(() => {
        if (!open) {
            setRate(undefined)
            setPreview(null)
            setPreviewError(null)
            setConfirmOpen(false)
            return
        }
        if (!projectId || !rate || !rateIsAllowed || !mediaIds.length) {
            setPreview(null)
            setPreviewError(null)
            setCheckingPreview(false)
            return
        }
        let cancelled = false
        setPreview(null)
        setPreviewError(null)
        setCheckingPreview(true)
        mediaApi.createAudioResamplingJob(projectId, {
            media_ids: mediaIds,
            target_sampling_rate_hz: rate,
        }, true).then((response) => {
            if (!cancelled) {
                if (!response.data?.annotation_impact || !previewKey) {
                    throw new Error("Annotation impact preview is unavailable")
                }
                setPreview({ key: previewKey, impact: response.data.annotation_impact })
            }
        }).catch((error) => {
            if (!cancelled) {
                console.error("Failed to preview resampling impact", error)
                setPreview(null)
                setPreviewError("Unable to preview annotation changes. Try again before resampling.")
            }
        }).finally(() => {
            if (!cancelled) {
                setCheckingPreview(false)
            }
        })

        return () => {
            cancelled = true
        }
    }, [open, projectId, rate, rateIsAllowed, mediaIds, previewKey, previewRequestVersion])

    const submit = async () => {
        if (!projectId || !rate || !mediaIds.length || !previewReady) return
        setSaving(true)
        try {
            const response = await mediaApi.createAudioResamplingJob(projectId, {
                media_ids: mediaIds,
                target_sampling_rate_hz: rate,
            })
            const job = response.data
            message.success(`${job.accepted_media_ids.length} recording(s) queued`)
            if (job.rejected.length) message.warning(job.rejected.map((item) => item.message).join("; "))
            if (job.queue_id != null) {
                onSubmitted(job.queue_id)
            }
            onClose()
        } catch (error) {
            console.error("Failed to create resampling job", error)
        } finally {
            setSaving(false)
        }
    }

    return (
        <ConfigProvider theme={theme}>
            <FormDrawer
                title="Resample Recordings"
                className="resample-audio-drawer"
                open={open}
                onClose={onClose}
                placement="right"
                styles={{ wrapper: { width: 480 }, body: { padding: 24 } }}
                extra={
                    <>
                        <Button onClick={onClose}>Close</Button>
                        <Button
                            type="primary"
                            loading={saving || checkingPreview}
                            disabled={!rateIsAllowed || !projectId || !mediaIds.length || !previewReady}
                            onClick={() => setConfirmOpen(true)}
                        >
                            Resample
                        </Button>
                    </>
                }
            >
                <Typography.Paragraph>
                    {mediaIds.length} recording(s) selected. Only compatible lower sample rates are available.
                </Typography.Paragraph>
                <Typography.Paragraph type="secondary">
                    MP3 and OGG recordings are re-encoded and may lose quality.
                </Typography.Paragraph>
                <Form layout="vertical">
                    <Form.Item label="Target Sample Rate (Hz)" required>
                        <Select value={rate} options={rateOptions} onChange={setRate} />
                    </Form.Item>
                </Form>
                {previewError ? (
                    <Alert
                        type="error"
                        showIcon
                        title="Annotation preview failed"
                        description={(
                            <span>
                                {previewError}{" "}
                                <Button size="small" onClick={() => setPreviewRequestVersion((value) => value + 1)}>
                                    Retry
                                </Button>
                            </span>
                        )}
                    />
                ) : null}
                {hasAnnotationImpact && annotationImpact ? (
                    <Alert
                        type="warning"
                        showIcon
                        className="resample-audio-warning-alert"
                        title={<span className="resample-audio-warning-alert__title">Annotations will be adjusted</span>}
                        description={
                            <span className="resample-audio-warning-alert__desc">
                                <span className="resample-audio-warning-alert__count">
                                    {annotationImpact.removed_annotation_count + annotationImpact.clipped_annotation_count} affected annotation
                                    {annotationImpact.removed_annotation_count + annotationImpact.clipped_annotation_count === 1 ? "" : "s"}
                                </span>
                                {annotationImpact.affected_media_count > 0
                                    ? ` on ${annotationImpact.affected_media_count} recording${annotationImpact.affected_media_count === 1 ? "" : "s"}. `
                                    : ". "}
                                {impactMessage}
                            </span>
                        }
                    />
                ) : null}
                <ConfirmDialog
                    open={confirmOpen}
                    onClose={() => setConfirmOpen(false)}
                    title="Replace stored audio files?"
                    message={
                        hasAnnotationImpact
                            ? `Resampling permanently replaces ${mediaIds.length} stored recording${mediaIds.length === 1 ? "" : "s"}. ${impactMessage}`
                            : `Resampling permanently replaces ${mediaIds.length} stored recording${mediaIds.length === 1 ? "" : "s"}.`
                    }
                    confirmLabel="Resample"
                    variant="warning"
                    onConfirm={() => { void submit() }}
                />
            </FormDrawer>
        </ConfigProvider>
    )
}
