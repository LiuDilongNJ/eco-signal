import { describe, expect, it } from "vitest"

import { IMPORT_RESOURCE_CONFIGS } from "./importConfigs"

function parseCsvRecord(record: string): string[] {
    const values: string[] = []
    let value = ""
    let quoted = false

    for (let index = 0; index < record.length; index += 1) {
        const character = record[index]
        if (character === '"') {
            if (quoted && record[index + 1] === '"') {
                value += character
                index += 1
            } else {
                quoted = !quoted
            }
        } else if (character === "," && !quoted) {
            values.push(value)
            value = ""
        } else {
            value += character
        }
    }

    values.push(value)
    return values
}

describe("import resource templates", () => {
    it("keeps every template aligned with its accepted field list", () => {
        Object.values(IMPORT_RESOURCE_CONFIGS).forEach((config) => {
            const [header, example, additionalExample] = config.template.trimEnd().split("\n")
            expect(header).toBe(config.fields.map((field) => field.name).join(","))
            expect(example).toBeTruthy()
            expect(parseCsvRecord(example!)).toHaveLength(config.fields.length)
            expect(additionalExample).toBeTruthy()
            expect(parseCsvRecord(additionalExample!)).toHaveLength(config.fields.length)
            expect(config.template.trimEnd().split("\n")).toHaveLength(3)
            expect(config.templateFileName).toMatch(/_template\.csv$/)
        })
    })

    it("restores the audio and photo metadata templates", () => {
        expect(IMPORT_RESOURCE_CONFIGS.audioMetadata.templateFileName).toBe("audio_metadata_template.csv")
        expect(IMPORT_RESOURCE_CONFIGS.photoMetadata.templateFileName).toBe("photo_metadata_template.csv")
        expect(IMPORT_RESOURCE_CONFIGS.audioMetadata.template).toContain("sampling_rate_hz")
        expect(IMPORT_RESOURCE_CONFIGS.photoMetadata.template).toContain("exposure_ms")
    })

    it("provides separate, media-specific annotation templates", () => {
        const audio = IMPORT_RESOURCE_CONFIGS.audioAnnotations
        const photo = IMPORT_RESOURCE_CONFIGS.photoAnnotations

        expect(audio.templateFileName).toBe("audio_annotations_template.csv")
        expect(audio.fields.map((field) => field.name)).toContain("sound_id")
        expect(audio.fields.map((field) => field.name)).not.toContain("object_type")
        expect(audio.fields.find((field) => field.name === "min_x")?.description).toContain("seconds")

        expect(photo.templateFileName).toBe("photo_annotations_template.csv")
        expect(photo.fields.map((field) => field.name)).toContain("object_type")
        expect(photo.fields.map((field) => field.name)).not.toContain("sound_id")
        expect(photo.fields.find((field) => field.name === "min_x")?.description).toContain("pixels")
    })

    it("excludes scoped and generated fields while retaining the user password input", () => {
        const forbidden = ["project_id", "collection_id", "media_type", "uuid", "creation_date", "creator_id", "reviewer_id", "assigner_id"]
        Object.values(IMPORT_RESOURCE_CONFIGS).forEach((config) => {
            const fields = config.fields.map((field) => field.name)
            forbidden.forEach((name) => expect(fields).not.toContain(name))
        })
        expect(IMPORT_RESOURCE_CONFIGS.users.fields.map((field) => field.name)).toContain("password")
    })

    it("uses schema-valid values without environment-specific geography identifiers", () => {
        expect(IMPORT_RESOURCE_CONFIGS.collections.example.sphere).toBe("biosphere")
        expect(IMPORT_RESOURCE_CONFIGS.sites.example.realm_id).toBeNull()
        expect(IMPORT_RESOURCE_CONFIGS.sites.example.biome_id).toBeNull()
        expect(IMPORT_RESOURCE_CONFIGS.sites.example.functional_type_id).toBeNull()
        expect(IMPORT_RESOURCE_CONFIGS.annotations.example.object_type).toBeNull()
        expect(IMPORT_RESOURCE_CONFIGS.annotations.example.taxon_id).toBeNull()
    })
})
