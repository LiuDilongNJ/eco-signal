import { useState } from "react"
import { Button, ConfigProvider, Form, Select, Typography, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { mediaApi } from "@/api/endpoints/media"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { RESAMPLING_RATE_OPTIONS } from "./resamplingOptions"
import { ConfirmDialog } from "./ConfirmDialog"
import "./styles/ResampleAudioDrawer.css"

export function ResampleAudioDrawer({ open, mediaIds, projectId, maxTargetSamplingRate, onClose, onSubmitted }: { open: boolean; mediaIds: number[]; projectId: number | null; maxTargetSamplingRate?: number; onClose: () => void; onSubmitted: (queueId: number) => void }) {
    const isDark = useAppStore((state) => state.effectiveTheme === "dark")
    const theme = useAntdBrandConfig(isDark)
    const [rate, setRate] = useState<number | undefined>()
    const [saving, setSaving] = useState(false)
    const [confirmOpen, setConfirmOpen] = useState(false)
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
            onSubmitted(job.queue_id)
            onClose()
        } catch (error) {
            console.error("Failed to create resampling job", error)
        } finally {
            setSaving(false)
        }
    }

    return <ConfigProvider theme={theme}><FormDrawer title="Resample Recordings" open={open} onClose={onClose} placement="right" styles={{ wrapper: { width: 480 }, body: { padding: 24 } }} extra={<><Button onClick={onClose}>Close</Button><Button type="primary" loading={saving} disabled={!rateIsAllowed || !projectId || !mediaIds.length} onClick={() => setConfirmOpen(true)}>Resample</Button></>}>
        <Typography.Paragraph>{mediaIds.length} recording(s) selected. Only lower sample rates are supported. Rates above the lowest selected recording remain visible but are unavailable.</Typography.Paragraph>
        <Typography.Paragraph type="secondary">MP3 and OGG recordings are re-encoded and may lose quality.</Typography.Paragraph>
        <Form layout="vertical"><Form.Item label="Target Sample Rate (Hz)" required><Select value={rate} options={rateOptions} onChange={setRate} /></Form.Item></Form>
        <ConfirmDialog
            open={confirmOpen}
            onClose={() => setConfirmOpen(false)}
            title="Replace stored audio files?"
            message={`Resampling permanently replaces ${mediaIds.length} stored recording${mediaIds.length === 1 ? "" : "s"}.`}
            confirmLabel="Resample"
            variant="warning"
            onConfirm={() => { void submit() }}
        />
    </FormDrawer></ConfigProvider>
}
