import { describe, expect, it } from "vitest"

import type { TableState } from "../../../project/components/data/DataPageLayout"
import {
    SOUND_COLUMNS,
    SOUND_CSV_TEMPLATE,
    soundListParamsFromTableState,
    soundWritePayload,
} from "../../utils/soundSettingsModel"

describe("SoundSettingsTab configuration", () => {
    it("defines the three management columns without a view-only field", () => {
        expect(SOUND_COLUMNS.map((column) => column.key)).toEqual([
            "sound_id",
            "soundscape_component",
            "sound_type",
        ])
        expect(SOUND_COLUMNS.every((column) => column.filterable && column.sortable)).toBe(true)
    })

    it("maps table filters, pagination, and sorting to management parameters", () => {
        const state: TableState = {
            page: 3,
            pageSize: 25,
            searchQuery: "ignored global search",
            filters: {
                sound_id: "12",
                soundscape_component: "  biophony ",
                sound_type: " birds ",
            },
            sortKey: "sound_type",
            sortDir: "desc",
        }

        expect(soundListParamsFromTableState(state)).toEqual({
            page: 3,
            page_size: 25,
            sound_id: 12,
            soundscape_component: "biophony",
            sound_type: "birds",
            order_by: "sound_type",
            order_dir: "desc",
        })
    })

    it("normalizes write values and provides the exact import template", () => {
        expect(soundWritePayload({ soundscape_component: " biophony ", sound_type: "   " })).toEqual({
            soundscape_component: "biophony",
            sound_type: null,
        })
        expect(SOUND_CSV_TEMPLATE.split("\n")[0]).toBe("soundscape_component,sound_type")
    })
})
