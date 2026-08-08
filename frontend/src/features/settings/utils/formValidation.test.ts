import { describe, expect, it } from "vitest"

import {
    optionalOrcidRule,
    taxonHierarchyCreateRule,
    validateOptionalOrcid,
    validateRequiredCoordRange,
    validateRequiredFederationUrl,
} from "./formValidation"

describe("taxon hierarchy validation", () => {
    it("requires at least one hierarchy level", async () => {
        const rule = taxonHierarchyCreateRule({
            getFieldsValue: () => ({}),
        } as never)
        const validate = rule.validator as (rule: unknown, value: unknown) => Promise<void>

        await expect(validate({}, undefined)).rejects.toThrow(
            "Select at least one taxonomy level",
        )
    })

    it("accepts any populated hierarchy level", async () => {
        const rule = taxonHierarchyCreateRule({
            getFieldsValue: () => ({ col_species_id: "species-1" }),
        } as never)
        const validate = rule.validator as (rule: unknown, value: unknown) => Promise<void>

        await expect(validate({}, undefined)).resolves.toBeUndefined()
    })
})

describe("optional ORCID validation", () => {
    it("allows empty values", () => {
        expect(validateOptionalOrcid("")).toBeNull()
        expect(validateOptionalOrcid("   ")).toBeNull()
    })

    it("accepts hyphenated ORCID iDs and ORCID URLs", () => {
        expect(validateOptionalOrcid("0000-0002-1825-0097")).toBeNull()
        expect(validateOptionalOrcid("https://orcid.org/0000-0002-1825-0097")).toBeNull()
        expect(validateOptionalOrcid("0000-0001-5109-3700")).toBeNull()
    })

    it("accepts a correctly formatted value without checksum validation", () => {
        expect(validateOptionalOrcid("0000-0001-4984-5953")).toBeNull()
        expect(validateOptionalOrcid("0000-0002-1825-009X")).toBeNull()
    })

    it("rejects malformed values", () => {
        expect(validateOptionalOrcid("1234")).toBe("Enter a valid ORCID")
        expect(validateOptionalOrcid("0000-0002-1825-009")).toBe("Enter a valid ORCID")
        expect(validateOptionalOrcid("0000-0002-1825-0097-extra")).toBe("Enter a valid ORCID")
    })

    it("exposes a Form rule that mirrors validateOptionalOrcid", async () => {
        const validate = optionalOrcidRule().validator as (
            rule: unknown,
            value: unknown,
        ) => Promise<void>

        await expect(validate({}, "")).resolves.toBeUndefined()
        await expect(validate({}, "0000-0002-1825-0097")).resolves.toBeUndefined()
        await expect(validate({}, "bad")).rejects.toThrow("Enter a valid ORCID")
    })
})

describe("required federation URL validation", () => {
    it("rejects empty values", () => {
        expect(validateRequiredFederationUrl("", "App URL")).toBe("App URL is required")
        expect(validateRequiredFederationUrl("   ", "App URL")).toBe("App URL is required")
    })

    it("accepts HTTP(S) URLs and rejects other schemes", () => {
        expect(validateRequiredFederationUrl(" https://node.example ", "App URL")).toBeNull()
        expect(validateRequiredFederationUrl("file:///tmp/node", "App URL")).toBe("App URL must be a valid URL")
    })
})

describe("required coordinate range validation", () => {
    it("requires coordinates when a public node is being configured", () => {
        expect(validateRequiredCoordRange("", "Latitude", -90, 90)).toBe("Latitude is required")
        expect(validateRequiredCoordRange("  ", "Longitude", -180, 180)).toBe("Longitude is required")
    })

    it("preserves numeric and range validation", () => {
        expect(validateRequiredCoordRange("45.5", "Latitude", -90, 90)).toBeNull()
        expect(validateRequiredCoordRange("181", "Longitude", -180, 180)).toBe(
            "Longitude must be between -180 and 180",
        )
    })
})
