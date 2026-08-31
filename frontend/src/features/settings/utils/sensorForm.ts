import type { SensorCreateBody } from "../../../api/endpoints/sensors"
import { nullableTrimmedText } from "./settingsPayload"

export type SensorFormValues = {
    name?: string
    serial_number?: string
    sensor_type?: "audio" | "photo" | "sensor"
    recorder_id?: number
    microphone_id?: number
    camera_id?: number
    lens_id?: number
    description?: string
}

export function buildSensorWritePayload(values: SensorFormValues): SensorCreateBody {
    const name = values.name!.trim()
    const description = nullableTrimmedText(values.description)
    const serial_number = nullableTrimmedText(values.serial_number)
    if (values.sensor_type === "audio") {
        const payload: SensorCreateBody = {
            name,
            sensor_type: "audio",
            recorder_id: values.recorder_id ?? null,
            microphone_id: values.microphone_id ?? null,
            camera_id: null,
            lens_id: null,
            description,
            serial_number,
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
            serial_number,
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
        serial_number,
    }
}
