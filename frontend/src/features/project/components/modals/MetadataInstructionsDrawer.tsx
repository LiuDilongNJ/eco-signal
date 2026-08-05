import { Button } from "@/components/ui"
import { DetailDrawer } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { downloadFile } from "@/utils/download"
import { useAppStore } from "@/store/useAppStore"
import {
    SETTINGS_DRAWER_BODY_PADDING,
    SETTINGS_DRAWER_WIDTH_STANDARD,
    SettingsDrawerTitle,
    getSettingsStageDrawerStyles,
} from "@/features/settings/components/settingsDrawerUi"
import "@/features/settings/components/style/sound-settings.css"

interface MetadataInstructionsDrawerProps {
    open: boolean
    mediaType?: "audio" | "photo"
    onClose: () => void
}

const AUDIO_FIELDS = [
    { key: "date_time", desc: "format: YYYY-MM-DD HH:MM:SS, local time" },
    { key: "duration_s", desc: "duration of recording in seconds" },
    { key: "sampling_rate_hz", desc: "numeric value in Hz" },
    { key: "name", desc: "optional, limited to 40 characters" },
    { key: "bit_depth", desc: "optional, integer" },
    { key: "channel_num", desc: "optional, integer" },
    { key: "duty_cycle_recording", desc: "duration of duty-cycled recordings in seconds" },
    { key: "duty_cycle_period", desc: "duration of cycle, recording plus pause, in seconds" },
]

const PHOTO_FIELDS = [
    { key: "date_time", desc: "format: YYYY-MM-DD HH:MM:SS, local time" },
    { key: "name", desc: "optional, limited to 40 characters" },
    { key: "exposure_ms", desc: "optional, numeric exposure time in milliseconds" },
    { key: "aperture", desc: "optional, numeric F value" },
    { key: "iso", desc: "optional, integer" },
]

export function MetadataInstructionsDrawer({ open, mediaType = "audio", onClose }: MetadataInstructionsDrawerProps) {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const fields = mediaType === "photo" ? PHOTO_FIELDS : AUDIO_FIELDS
    const subject = mediaType === "photo" ? "Photo meta-data" : "Recording meta-data"

    const handleDownloadTemplate = () => {
        const header = fields.map((field) => field.key).join(",")
        downloadFile(
            { blob: new Blob([`${header}\n`], { type: "text/csv;charset=utf-8" }) },
            `${mediaType}_metadata_template.csv`,
        )
    }

    return (
        <DetailDrawer
            rootClassName="csv-upload-instructions-drawer"
            maskClosable={false}
            closable={false}
            title={<SettingsDrawerTitle>View Instructions</SettingsDrawerTitle>}
            open={open}
            onClose={onClose}
            placement="right"
            destroyOnClose
            styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_STANDARD)}
            extra={<Button type="primary" onClick={onClose}>Close</Button>}
        >
            <CustomScrollArea variant="fill">
                <div className="sound-settings-instructions" style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                    <p>{subject} can be uploaded with a CSV containing the following columns:</p>
                    <div className="sound-settings-instructions__rules">
                        {fields.map((field) => (
                            <div key={field.key}>
                                <strong>{field.key}</strong> ({field.desc})
                            </div>
                        ))}
                    </div>
                    <p>
                        You can download a{" "}
                        <Button type="link" className="sound-settings-instructions__download" onClick={handleDownloadTemplate}>
                            template CSV file
                        </Button>{" "}
                        to fill in your data.
                    </p>
                </div>
            </CustomScrollArea>
        </DetailDrawer>
    )
}
