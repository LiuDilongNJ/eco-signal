import { useEffect, useState } from "react"
import { Alert, Button, ConfigProvider, Form, Select, Typography, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { mediaApi } from "@/api/endpoints/media"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { RESAMPLING_RATE_OPTIONS } from "./resamplingOptions"
import { ConfirmDialog } from "./ConfirmDialog"
import "./styles/ResampleAudioDrawer.css"

export function ResampleAudioDrawer({
    open,
    mediaIds,
    projectId,
    maxTargetSamplingRate,
    onClose,
    onSubmitted,
}: {
    open: boolean
    mediaIds: number[]
    projectId: number | null
    maxTargetSamplingRate?: number
    onClose: () => void
    onSubmitted: (queueId: number) => void
}) {
    const isDark = useAppStore((state) => state.effectiveTheme === "dark")
    const theme = useAntdBrandConfig(isDark)
    const [rate, setRate] = useState<number | undefined>()
    const [saving, setSaving] = useState(false)
    const [confirmOpen, setConfirmOpen] = useState(false)
    const [affectedCount, setAffectedCount] = useState<number>(0)
    const [affectedMediaCount, setAffectedMediaCount] = useState<number>(0)
    const [checkingPreview, setCheckingPreview] = useState(false)

    const rateIsAllowed = rate != null && (maxTargetSamplingRate == null || rate <= maxTargetSamplingRate)
    const rateOptions = RESAMPLING_RATE_OPTIONS.map((value) => {
        const disabled = maxTargetSamplingRate != null && value > maxTargetSamplingRate
        const reason = maxTargetSamplingRate == null
            ? undefined
            : `Unavailable: the selected recordings are at most ${maxTargetSamplingRate} Hz. Resampling cannot increase the sample rate.`
        return {
            value,
            disabled,
            label: (
                <span className="resample-audio-rate-option" title={reason}>
                    <span>{value}</span>
                    {disabled ? <span className="resample-audio-rate-option__reason">Exceeds {maxTargetSamplingRate} Hz</span> : null}
                </span>
            ),
        }
    })

    useEffect(() => {
        if (!open) {
            setRate(undefined)
            setAffectedCount(0)
            setAffectedMediaCount(0)
            return
        }
        if (!projectId || !rate || !rateIsAllowed || !mediaIds.length) {
            setAffectedCount(0)
            setAffectedMediaCount(0)
            return
        }
        let cancelled = false
        setCheckingPreview(true)
        mediaApi.createAudioResamplingJob(projectId, {
            media_ids: mediaIds,
            target_sampling_rate_hz: rate,
        }, true).then((response) => {
            if (!cancelled && response.data) {
                setAffectedCount(response.data.affected_annotation_count ?? 0)
                setAffectedMediaCount(response.data.affected_media_count ?? 0)
            }
        }).catch((error) => {
            if (!cancelled) {
                console.error("Failed to preview resampling impact", error)
                setAffectedCount(0)
                setAffectedMediaCount(0)
            }
        }).finally(() => {
            if (!cancelled) {
                setCheckingPreview(false)
            }
        })

        return () => {
            cancelled = true
        }
    }, [open, projectId, rate, rateIsAllowed, mediaIds])

    const submit = async () => {
        if (!projectId || !rate || !mediaIds.length) return
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

    const maxNyquistFreq = rate ? Math.floor(rate / 2) : 0

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
                            disabled={!rateIsAllowed || !projectId || !mediaIds.length}
                            onClick={() => setConfirmOpen(true)}
                        >
                            Resample
                        </Button>
                    </>
                }
            >
                <Typography.Paragraph>
                    {mediaIds.length} recording(s) selected. Only lower sample rates are supported. Rates above the lowest selected recording remain visible but are unavailable.
                </Typography.Paragraph>
                <Typography.Paragraph type="secondary">
                    MP3 and OGG recordings are re-encoded and may lose quality.
                </Typography.Paragraph>
                <Form layout="vertical">
                    <Form.Item label="Target Sample Rate (Hz)" required>
                        <Select value={rate} options={rateOptions} onChange={setRate} />
                    </Form.Item>
                </Form>
                {affectedCount > 0 ? (
                    <Alert
                        type="warning"
                        showIcon
                        className="resample-audio-warning-alert"
                        title={<span className="resample-audio-warning-alert__title">Annotations will be removed</span>}
                        description={
                            <span className="resample-audio-warning-alert__desc">
                                <span className="resample-audio-warning-alert__count">
                                    {affectedCount} annotation{affectedCount === 1 ? "" : "s"}
                                </span>
                                {affectedMediaCount > 0 ? ` on ${affectedMediaCount} recording${affectedMediaCount === 1 ? "" : "s"}` : ""}{" "}
                                exceed{affectedCount === 1 ? "s" : ""} the new maximum frequency of {maxNyquistFreq} Hz and will be permanently removed upon resampling.
                            </span>
                        }
                    />
                ) : null}
                <ConfirmDialog
                    open={confirmOpen}
                    onClose={() => setConfirmOpen(false)}
                    title="Replace stored audio files?"
                    message={
                        affectedCount > 0
                            ? `Resampling permanently replaces ${mediaIds.length} stored recording${mediaIds.length === 1 ? "" : "s"}. Warning: ${affectedCount} annotation${affectedCount === 1 ? "" : "s"} exceed${affectedCount === 1 ? "s" : ""} the new maximum frequency of ${maxNyquistFreq} Hz and will be permanently removed.`
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

