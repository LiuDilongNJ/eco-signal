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

type TemplateFormat = "csv" | "txt" | "json"

function textValue(value: unknown): string {
    if (value === null || value === undefined) return ""
    if (typeof value === "object") return JSON.stringify(value)
    return String(value)
}

function delimitedExample(config: ImportResourceConfig, delimiter: string): string {
    const headers = config.fields.map((item) => item.name)
    return [
        headers.join(delimiter),
        ...[config.example, config.additionalExample].map((example) => (
            headers.map((name) => textValue(example[name])).join(delimiter)
        )),
    ].join("\n")
}

function templateFilename(config: ImportResourceConfig, format: TemplateFormat): string {
    const basename = config.templateFileName.replace(/\.csv$/i, "")
    return `${basename}.${format}`
}

function templateContent(config: ImportResourceConfig, format: TemplateFormat): string {
    if (format === "csv") return config.template
    if (format === "txt") return `${delimitedExample(config, "\t")}\n`
    return `${JSON.stringify([config.example, config.additionalExample], null, 2)}\n`
}

const TEMPLATE_MIME_TYPES: Record<TemplateFormat, string> = {
    csv: "text/csv;charset=utf-8",
    txt: "text/plain;charset=utf-8",
    json: "application/json;charset=utf-8",
}

export function ImportInstructionsDrawer({ config, open, onClose }: ImportInstructionsDrawerProps) {
    const isDark = useAppStore((state) => state.effectiveTheme === "dark")

    const downloadTemplate = (format: TemplateFormat) => {
        downloadFile(
            { blob: new Blob([templateContent(config, format)], { type: TEMPLATE_MIME_TYPES[format] }) },
            templateFilename(config, format),
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
                    <p>Download a template containing the exact accepted fields and two example records.</p>
                    <div
                        className="sound-settings-instructions__downloads"
                        role="group"
                        aria-label="Download import templates"
                    >
                        <Button onClick={() => downloadTemplate("csv")}>Download CSV Template</Button>
                        <Button onClick={() => downloadTemplate("txt")}>Download TXT Template</Button>
                        <Button onClick={() => downloadTemplate("json")}>Download JSON Template</Button>
                    </div>
                </div>
            </CustomScrollArea>
        </DetailDrawer>
    )
}
