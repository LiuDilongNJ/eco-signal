import type { FormInstance, RuleObject } from "@/components/ui"
import { validateOptionalHttpUrl } from "../../project/utils/urlValidation"

export { renderRequiredLabel } from "@/components/ui"

export const COL_HIERARCHY_FIELDS = [
    "col_class_id",
    "col_order_id",
    "col_family_id",
    "col_genus_id",
    "col_species_id",
] as const

export const FFT_VALID_VALUES = new Set([128, 256, 512, 1024, 2048, 4096])

export function federationUrlRule(fieldLabel: string): RuleObject {
    return {
        validator: async (_, value) => {
            const error = validateOptionalHttpUrl(value, fieldLabel)
            if (error) throw new Error(error)
        },
    }
}

export function taxonHierarchyCreateRule(form: FormInstance): RuleObject {
    return {
        validator: async () => {
            const values = form.getFieldsValue([...COL_HIERARCHY_FIELDS])
            const hasAny = COL_HIERARCHY_FIELDS.some((key) => {
                const value = values[key]
                return value != null && value !== ""
            })
            if (!hasAny) {
                throw new Error("Select at least one taxonomy level (class through species)")
            }
        },
    }
}

export function validateRequiredEmail(email: string): string | null {
    const trimmed = email.trim()
    if (!trimmed) return "Email is required"
    if (trimmed.length > 100) return "Email must be at most 100 characters"
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
        return "Enter a valid email address"
    }
    return null
}

export function validateRequiredName(name: string): string | null {
    const trimmed = name.trim()
    if (!trimmed) return "Name is required"
    if (trimmed.length > 100) return "Name must be at most 100 characters"
    return null
}

/** ORCID iD format: 0000-0000-0000-000X (hyphenated). */
const ORCID_ID_PATTERN = /^(\d{4}-){3}\d{3}[\dX]$/

function normalizeOrcidInput(orcid: string): string {
    let value = orcid.trim()
    value = value.replace(/^https?:\/\/(www\.)?orcid\.org\//i, "")
    return value.toUpperCase()
}

export function validateOptionalOrcid(orcid: string): string | null {
    const trimmed = orcid.trim()
    if (!trimmed) return null
    if (trimmed.length > 100) return "ORCID must be at most 100 characters"

    const normalized = normalizeOrcidInput(trimmed)
    if (!ORCID_ID_PATTERN.test(normalized)) {
        return "Enter a valid ORCID"
    }
    return null
}

export function optionalOrcidRule(): RuleObject {
    return {
        validator: async (_, value) => {
            const error = validateOptionalOrcid(String(value ?? ""))
            if (error) throw new Error(error)
        },
    }
}

export function validateHexColor(color: string): string | null {
    const trimmed = color.trim()
    if (!trimmed) return null
    if (trimmed.length !== 7 || !trimmed.startsWith("#") || !/^#[0-9A-Fa-f]{6}$/.test(trimmed)) {
        return "Color must be a hex value like #RRGGBB"
    }
    return null
}

export function validatePasswordField(value: string, label: string): string | null {
    if (!value) return `Please enter ${label}`
    if (value.length < 8) return `${label} must be at least 8 characters`
    if (value.length > 128) return `${label} must be at most 128 characters`
    return null
}

export function validateFederationUrl(value: string, label: string): string | null {
    return validateOptionalHttpUrl(value, label)
}

export function validateRequiredFederationUrl(value: string, label: string): string | null {
    const trimmed = value.trim()
    if (!trimmed) return `${label} is required`
    return validateOptionalHttpUrl(trimmed, label)
}

export function validateOptionalCoord(value: string, label: string): string | null {
    const trimmed = value.trim()
    if (!trimmed) return null
    const n = Number(trimmed)
    if (!Number.isFinite(n)) return `${label} must be a valid number`
    return null
}

export function validateOptionalCoordRange(value: string, label: string, min: number, max: number): string | null {
    const numberError = validateOptionalCoord(value, label)
    if (numberError) return numberError
    const trimmed = value.trim()
    if (!trimmed) return null
    const n = Number(trimmed)
    if (n < min || n > max) {
        return `${label} must be between ${min} and ${max}`
    }
    return null
}

export function validateRequiredCoordRange(value: string, label: string, min: number, max: number): string | null {
    if (!value.trim()) return `${label} is required`
    return validateOptionalCoordRange(value, label, min, max)
}

export function validateFftSize(value: string): string | null {
    const trimmed = value.trim()
    if (!trimmed) return "FFT window size is required"
    const n = Number(trimmed)
    if (!Number.isInteger(n) || !FFT_VALID_VALUES.has(n)) {
        return "FFT window size must be one of 128, 256, 512, 1024, 2048, or 4096"
    }
    return null
}
