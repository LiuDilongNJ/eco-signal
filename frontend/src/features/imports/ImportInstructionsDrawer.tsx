import { Button, CustomScrollArea, DetailDrawer } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import { downloadFile } from "@/utils/download"
import {
    SETTINGS_DRAWER_BODY_PADDING,
    SETTINGS_DRAWER_WIDTH_STANDARD,
    SettingsDrawerTitle,
    getSettingsStageDrawerStyles,
} from "@/features/settings/components/settingsDrawerUi"
import "@/features/settings/components/style/sound-settings.css"

import type { ImportResourceConfig } from "./importConfigs"

interface ImportInstructionsDrawerProps {
    config: ImportResourceConfig
    open: boolean
    onClose: () => void
}

function textValue(value: unknown): string {
    if (value === null || value === undefined) return ""
    if (typeof value === "object") return JSON.stringify(value)
    return String(value)
}

function delimitedExample(config: ImportResourceConfig, delimiter: string): string {
    const headers = config.fields.map((item) => item.name)
    return [
        headers.join(delimiter),
        headers.map((name) => textValue(config.example[name])).join(delimiter),
    ].join("\n")
}

export function ImportInstructionsDrawer({ config, open, onClose }: ImportInstructionsDrawerProps) {
    const isDark = useAppStore((state) => state.effectiveTheme === "dark")

    const downloadTemplate = () => {
        downloadFile(
            { blob: new Blob([config.template], { type: "text/csv;charset=utf-8" }) },
            config.templateFileName,
        )
    }

    return (
        <DetailDrawer
            rootClassName="csv-upload-instructions-drawer"
            closable={false}
            title={<SettingsDrawerTitle>Data Import Instructions</SettingsDrawerTitle>}
            open={open}
            maskClosable={false}
            onClose={onClose}
            destroyOnClose
            styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_STANDARD)}
            extra={<Button type="primary" onClick={onClose}>Close</Button>}
        >
            <CustomScrollArea variant="fill">
                <div className="sound-settings-instructions" style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                    <p>{config.subject} data can be uploaded as CSV, delimited TXT, or a JSON object array.</p>
                    <div className="sound-settings-instructions__rules">
                        {config.fields.map((item) => (
                            <div key={item.name}>
                                <strong>{item.name}</strong> ({item.rules}) - {item.description}
                            </div>
                        ))}
                    </div>
                    <p>
                        Download a{" "}
                        <Button type="link" className="sound-settings-instructions__download" onClick={downloadTemplate}>
                            template CSV file
                        </Button>{" "}
                        containing the exact accepted headers and one example row.
                    </p>
                    <strong>CSV example</strong>
                    <pre className="sound-settings-instructions__code">{config.template.trimEnd()}</pre>
                    <strong>Delimited TXT examples</strong>
                    <p>TXT files may use Tab, semicolon, or pipe delimiters. The same delimiter must be used consistently.</p>
                    <pre className="sound-settings-instructions__code">{delimitedExample(config, "\t")}</pre>
                    <pre className="sound-settings-instructions__code">{delimitedExample(config, ";")}</pre>
                    <pre className="sound-settings-instructions__code">{delimitedExample(config, "|")}</pre>
                    <strong>JSON example</strong>
                    <pre className="sound-settings-instructions__code">{JSON.stringify([config.example], null, 2)}</pre>
                </div>
            </CustomScrollArea>
        </DetailDrawer>
    )
}
