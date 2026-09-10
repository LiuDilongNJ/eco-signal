import { useEffect, useState } from "react"
import { Button, ConfigProvider, Typography } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { downloadFile } from "@/utils/download"
import { mediaApi, type AudioFileMetadata } from "@/api/endpoints/media"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { LoadingState } from "@/components/ui"
import "./styles/AudioMetadataDrawer.css"

export function AudioMetadataDrawer({ open, mediaId, projectId, onClose }: { open: boolean; mediaId: number | null; projectId: number | null; onClose: () => void }) {
    const isDark = useAppStore((state) => state.effectiveTheme === "dark")
    const theme = useAntdBrandConfig(isDark)
    const [data, setData] = useState<AudioFileMetadata | null>(null)
    const [loading, setLoading] = useState(false)
    const [unavailable, setUnavailable] = useState(false)
    useEffect(() => {
        let active = true
        setData(null)
        setUnavailable(false)
        if (!open || mediaId == null || projectId == null) return () => { active = false }
        setLoading(true)
        void mediaApi.getAudioMetadata(mediaId, projectId)
            .then((result) => { if (active) setData(result) })
            .catch(() => { if (active) setUnavailable(true) })
            .finally(() => { if (active) setLoading(false) })
        return () => { active = false }
    }, [open, mediaId, projectId])
    const renderFields = (title: string, fields: Record<string, unknown>) => <section className="audio-metadata-drawer__section">
        <Typography.Text strong>{title}</Typography.Text>
        {Object.entries(fields).map(([key, value]) => <div className="audio-metadata-drawer__row" key={key}><span>{key}</span><span>{value == null ? "-" : String(value)}</span></div>)}
    </section>
    return <ConfigProvider theme={theme}><FormDrawer title="Audio Metadata" open={open} onClose={onClose} placement="right" styles={{ wrapper: { width: 620 }, body: { padding: 24 } }} extra={<div className="audio-metadata-drawer__footer"><Button onClick={onClose}>Close</Button><Button type="primary" disabled={!data || mediaId == null || projectId == null} onClick={async () => { if (mediaId != null && projectId != null) downloadFile(await mediaApi.downloadAudioMetadata(mediaId, projectId)) }}>Download JSON</Button></div>}>
        {loading ? <LoadingState label="Loading audio metadata..." /> : unavailable ? <Typography.Text type="secondary">Audio metadata is not available</Typography.Text> : data ? <div className="audio-metadata-drawer">
            {renderFields("Source Audio", data.source)}
            {renderFields("Stored Audio", data.stored)}
            <section className="audio-metadata-drawer__section"><Typography.Text strong>Embedded Metadata</Typography.Text>{Object.keys(data.tags).length ? Object.entries(data.tags).map(([namespace, tags]) => <div key={namespace} className="audio-metadata-drawer__tags"><Typography.Text>{namespace}</Typography.Text>{Object.entries(tags).map(([key, values]) => <div className="audio-metadata-drawer__row" key={key}><span>{key}</span><span>{values.map(String).join("\n")}</span></div>)}</div>) : <Typography.Text type="secondary">No embedded metadata</Typography.Text>}</section>
            {data.warnings.length ? <section className="audio-metadata-drawer__section audio-metadata-drawer__warnings"><Typography.Text strong>Warnings</Typography.Text>{data.warnings.map((warning) => <div key={warning}>{warning}</div>)}</section> : null}
        </div> : null}
    </FormDrawer></ConfigProvider>
}
