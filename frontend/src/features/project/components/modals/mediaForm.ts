import type { UpdateMediaPayload } from "../../../../api/endpoints/media"
import type { SensorOption } from "../../../../api/endpoints/sensors"

export type EditableMediaKind = "audio" | "photo" | "metadata"

export interface MediaUpdateFormValues extends Record<string, unknown> {
    name?: string | null
    date_time?: { format: (format: string) => string } | null
    site_id?: number | null
    sensor_id?: number | null
    medium?: string | null
    license_id?: number | null
    creator_id?: number | null
    doi?: string | null
    note?: string | null
    recording_gain_db?: string | number | null
    sampling_rate_hz?: string | number | null
    bit_depth?: string | number | null
    channel_num?: string | number | null
    duration_s?: string | number | null
    duty_cycle_recording?: string | number | null
    duty_cycle_period?: string | number | null
}

export const MEDIA_ADD_TITLES = {
    audio: "Add Audio",
    photo: "Add Photos",
} as const

export const MEDIA_EDIT_TITLES: Record<EditableMediaKind, string> = {
    audio: "Edit Audio",
    photo: "Edit Photo",
    metadata: "Edit Metadata",
}

export function resolveEditableMediaKind(mediaType: string | null, isMetadata: boolean): EditableMediaKind {
    if (isMetadata) return "metadata"
    return mediaType === "photo" ? "photo" : "audio"
}

export function filterSensorsForMediaType(
    sensors: SensorOption[],
    mediaType: string | null,
): SensorOption[] {
    const normalizedType = mediaType?.trim().toLowerCase()
    if (normalizedType !== "audio" && normalizedType !== "photo") return []
    return sensors.filter(
        (sensor) => String(sensor.sensor_type ?? "").toLowerCase() === normalizedType,
    )
}

export function formatSensorOptionLabel(sensor: SensorOption): string {
    const name = sensor.name?.trim() || `Sensor #${sensor.sensor_id}`
    const serial = sensor.serial_number?.trim()
    return serial ? `${name} · ${serial}` : name
}

export function buildMediaUpdatePayload(
    values: MediaUpdateFormValues,
    kind: EditableMediaKind,
): UpdateMediaPayload {
    const payload: UpdateMediaPayload = {
        name: values.name,
        date_time: values.date_time ? values.date_time.format("YYYY-MM-DD HH:mm:ss") : null,
        site_id: values.site_id ?? null,
        sensor_id: values.sensor_id ?? null,
        medium: values.medium ?? null,
        license_id: values.license_id ?? null,
        creator_id: values.creator_id ?? null,
        doi: values.doi,
        note: values.note,
    }
    if (kind === "photo") return payload

    const optionalNumber = (value: unknown): number | null => (
        value != null && String(value).trim() !== "" ? Number(value) : null
    )

    if (kind === "audio") {
        // Duty cycle fields are not editable for audio media, so they are omitted
        // to avoid overwriting stored values when the fields are hidden.
        return {
            ...payload,
            recording_gain_db: optionalNumber(values.recording_gain_db),
        }
    }

    // metadata: technical settings have no source file and are user-provided.
    return {
        ...payload,
        recording_gain_db: optionalNumber(values.recording_gain_db),
        sampling_rate_hz: optionalNumber(values.sampling_rate_hz),
        bit_depth: optionalNumber(values.bit_depth),
        channel_num: optionalNumber(values.channel_num),
        duration_s: optionalNumber(values.duration_s),
        duty_cycle_recording: optionalNumber(values.duty_cycle_recording),
        duty_cycle_period: optionalNumber(values.duty_cycle_period),
    }
}
