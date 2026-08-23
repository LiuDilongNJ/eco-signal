import { describe, expect, it } from "vitest"

import { IMPORT_RESOURCE_CONFIGS } from "./importConfigs"

describe("import resource templates", () => {
    it("keeps every template aligned with its accepted field list", () => {
        Object.values(IMPORT_RESOURCE_CONFIGS).forEach((config) => {
            const [header, example] = config.template.trimEnd().split("\n")
            expect(header).toBe(config.fields.map((field) => field.name).join(","))
            expect(example).toBeTruthy()
            expect(config.templateFileName).toMatch(/_template\.csv$/)
        })
    })

    it("restores the audio and photo metadata templates", () => {
        expect(IMPORT_RESOURCE_CONFIGS.audioMetadata.templateFileName).toBe("audio_metadata_template.csv")
        expect(IMPORT_RESOURCE_CONFIGS.photoMetadata.templateFileName).toBe("photo_metadata_template.csv")
        expect(IMPORT_RESOURCE_CONFIGS.audioMetadata.template).toContain("sampling_rate_hz")
        expect(IMPORT_RESOURCE_CONFIGS.photoMetadata.template).toContain("exposure_ms")
    })

    it("excludes scoped and generated fields while retaining the user password input", () => {
        const forbidden = ["project_id", "collection_id", "media_type", "uuid", "creation_date", "creator_id", "reviewer_id", "assigner_id"]
        Object.values(IMPORT_RESOURCE_CONFIGS).forEach((config) => {
            const fields = config.fields.map((field) => field.name)
            forbidden.forEach((name) => expect(fields).not.toContain(name))
        })
        expect(IMPORT_RESOURCE_CONFIGS.users.fields.map((field) => field.name)).toContain("password")
    })
})
