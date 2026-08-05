export function nullableTrimmedText(value: string | null | undefined): string | null {
    const trimmed = value?.trim() ?? ""
    return trimmed === "" ? null : trimmed
}

export function requiredTrimmedText(value: string | null | undefined): string {
    return value?.trim() ?? ""
}

export function buildRecorderWritePayload(values: { name?: string; version?: string; brand?: string }) {
    return {
        name: requiredTrimmedText(values.name),
        version: nullableTrimmedText(values.version),
        brand: nullableTrimmedText(values.brand),
    }
}

export function buildMicrophoneWritePayload(values: {
    name?: string
    microphone_element?: string
    sensitivity?: number | null
    signal_to_noise_ratio?: number | null
}) {
    return {
        name: requiredTrimmedText(values.name),
        microphone_element: nullableTrimmedText(values.microphone_element),
        sensitivity: values.sensitivity ?? null,
        signal_to_noise_ratio: values.signal_to_noise_ratio ?? null,
    }
}

export function buildCameraWritePayload(values: { name?: string; version?: string; brand?: string }) {
    return {
        name: requiredTrimmedText(values.name),
        version: nullableTrimmedText(values.version),
        brand: nullableTrimmedText(values.brand),
    }
}

export function buildLensWritePayload(values: {
    name?: string
    focal_length?: string
    max_aperture?: string
    brand?: string
}) {
    return {
        name: requiredTrimmedText(values.name),
        focal_length: nullableTrimmedText(values.focal_length),
        max_aperture: nullableTrimmedText(values.max_aperture),
        brand: nullableTrimmedText(values.brand),
    }
}
