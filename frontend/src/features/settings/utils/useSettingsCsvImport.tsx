import type { ImportResponse } from "@/api/tabularImport"
import { IMPORT_RESOURCE_CONFIGS, type ImportResourceKey } from "@/features/imports/importConfigs"
import { useTabularImport } from "@/features/imports/useTabularImport"

type SettingsImportKey = Extract<
    ImportResourceKey,
    "sounds" | "taxons" | "cameras" | "lenses" | "microphones" | "recorders"
>

export function useSettingsCsvImport(
    resourceKey: SettingsImportKey,
    submit: (file: File, dryRun?: boolean) => Promise<ImportResponse>,
    onSuccess: () => void,
) {
    const controller = useTabularImport({
        label: IMPORT_RESOURCE_CONFIGS[resourceKey].subject.toLowerCase(),
        config: IMPORT_RESOURCE_CONFIGS[resourceKey],
        submit: (file, dryRun) => submit(file, dryRun),
        onCommitted: onSuccess,
    })

    return {
        importing: controller.importing,
        triggerImport: controller.triggerImport,
        showInstructions: controller.showInstructions,
        input: controller.controls,
    }
}
