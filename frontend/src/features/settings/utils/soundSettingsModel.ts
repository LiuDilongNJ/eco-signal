import type { ListSoundClassificationParams } from "../../../api/endpoints/soundClassifications"
import type { ColumnDef, TableState } from "../../project/components/data/DataPageLayout"

export const SOUND_COLUMNS: ColumnDef[] = [
    { key: "sound_id", label: "ID", type: "number", width: "96px", sortable: true, filterable: true },
    {
        key: "soundscape_component",
        label: "Soundscape Component",
        type: "text",
        width: "240px",
        sortable: true,
        filterable: true,
    },
    {
        key: "sound_type",
        label: "Sound Type",
        type: "text",
        width: "240px",
        sortable: true,
        filterable: true,
    },
]

export const SOUND_CSV_TEMPLATE = "soundscape_component,sound_type\nbiophony,snapping shrimps\n"

export type SoundFormValues = {
    soundscape_component?: string
    sound_type?: string
}

export function soundWritePayload(values: SoundFormValues) {
    const soundType = values.sound_type?.trim() ?? ""
    return {
        soundscape_component: values.soundscape_component?.trim() ?? "",
        sound_type: soundType === "" ? null : soundType,
    }
}

export function soundOrderByForApi(
    sortKey: string | null,
): NonNullable<ListSoundClassificationParams["order_by"]> {
    if (sortKey === "soundscape_component" || sortKey === "sound_type") return sortKey
    return "sound_id"
}

export function soundListParamsFromTableState(state: TableState): ListSoundClassificationParams {
    return {
        page: state.page,
        page_size: state.pageSize,
        sound_id:
            state.filters.sound_id && String(state.filters.sound_id).trim() !== ""
                ? Number(state.filters.sound_id)
                : undefined,
        soundscape_component: state.filters.soundscape_component?.trim() || undefined,
        sound_type: state.filters.sound_type?.trim() || undefined,
        order_by: soundOrderByForApi(state.sortKey),
        order_dir: state.sortDir === "desc" ? "desc" : "asc",
    }
}
