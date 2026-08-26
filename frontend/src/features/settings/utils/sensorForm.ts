import type { CameraLensInfo } from "../../../api/endpoints/cameras"
import type { SensorCreateBody } from "../../../api/endpoints/sensors"
import { nullableTrimmedText } from "./settingsPayload"

export type SensorFormValues = {
    name?: string
    sensor_type?: "audio" | "photo" | "sensor"
    recorder_id?: number
    microphone_id?: number
    camera_id?: number
    lens_id?: number
    description?: string
}

export function getUniqueDefaultLensId(lenses: CameraLensInfo[]): number | undefined {
    const defaults = lenses.filter((lens) => lens.is_default)
    return defaults.length === 1 ? defaults[0]?.lens_id : undefined
}

export function buildSensorWritePayload(values: SensorFormValues): SensorCreateBody {
    const name = values.name!.trim()
    const description = nullableTrimmedText(values.description)
    if (values.sensor_type === "audio") {
        const payload: SensorCreateBody = {
            name,
            sensor_type: "audio",
            recorder_id: values.recorder_id ?? null,
            microphone_id: values.microphone_id ?? null,
            camera_id: null,
            lens_id: null,
            description,
        }
        return payload
    }
    if (values.sensor_type === "photo") {
        const payload: SensorCreateBody = {
            name,
            sensor_type: "photo",
            camera_id: values.camera_id ?? null,
            lens_id: values.lens_id ?? null,
            recorder_id: null,
            microphone_id: null,
            description,
        }
        return payload
    }
    return {
        name,
        sensor_type: "sensor",
        recorder_id: null,
        microphone_id: null,
        camera_id: null,
        lens_id: null,
        description,
    }
}
