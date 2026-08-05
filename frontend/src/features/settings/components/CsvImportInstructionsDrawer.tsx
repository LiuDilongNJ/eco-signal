import { Button } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { DetailDrawer } from "@/components/ui"
import { downloadFile } from "@/utils/download"
import type { SettingsCsvImportConfig } from "../utils/settingsCsvImportConfig"
import {
    SETTINGS_DRAWER_BODY_PADDING,
    SETTINGS_DRAWER_WIDTH_STANDARD,
    SettingsDrawerTitle,
    getSettingsStageDrawerStyles,
} from "./settingsDrawerUi"
import "./style/sound-settings.css"

interface CsvImportInstructionsDrawerProps {
    config: SettingsCsvImportConfig
    isDark: boolean
    open: boolean
    onClose: () => void
}

export function CsvImportInstructionsDrawer({ config, isDark, open, onClose }: CsvImportInstructionsDrawerProps) {
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
            title={<SettingsDrawerTitle>CSV Upload Instructions</SettingsDrawerTitle>}
            open={open}
            maskClosable={false}
            onClose={onClose}
            destroyOnClose
            styles={getSettingsStageDrawerStyles(isDark, SETTINGS_DRAWER_WIDTH_STANDARD)}
            extra={<Button type="primary" onClick={onClose}>Close</Button>}
        >
            <CustomScrollArea variant="fill">
                <div className="sound-settings-instructions" style={{ padding: SETTINGS_DRAWER_BODY_PADDING }}>
                    <p>{config.subject} data can be uploaded with a CSV containing the following columns:</p>
                    <div className="sound-settings-instructions__rules">
                        {config.fields.map((field) => (
                            <div key={field.name}>
                                <strong>{field.name}</strong> ({field.rules}) - {field.description}
                            </div>
                        ))}
                    </div>
                    <p>
                        You can download a{" "}
                        <Button type="link" className="sound-settings-instructions__download" onClick={downloadTemplate}>
                            template CSV file
                        </Button>{" "}
                        to fill in your data.
                    </p>
                </div>
            </CustomScrollArea>
        </DetailDrawer>
    )
}
