import type { CameraLensInfo } from "../../../api/endpoints/cameras"
import type { RecorderMicrophoneInfo } from "../../../api/endpoints/recorders"
import type { SensorCreateBody } from "../../../api/endpoints/sensors"
import { nullableTrimmedText } from "./settingsPayload"

export type SensorFormValues = {
    name?: string
    sensor_type?: "audio" | "photo" | "sensor"
    recorder_id?: number
    microphone_id?: number
    camera_id?: number
    lens_id?: number
    camera_lens_is_default?: boolean
    recorder_microphone_is_default?: boolean
    description?: string
}

export function resolveCameraLensDefault(lenses: CameraLensInfo[], lensId: number): boolean {
    return lenses.find((lens) => lens.lens_id === lensId)?.is_default ?? false
}

export function getUniqueDefaultLensId(lenses: CameraLensInfo[]): number | undefined {
    const defaults = lenses.filter((lens) => lens.is_default)
    return defaults.length === 1 ? defaults[0]?.lens_id : undefined
}

export function resolveRecorderMicrophoneDefault(
    microphones: RecorderMicrophoneInfo[],
    microphoneId: number,
): boolean {
    return microphones.find((mic) => mic.microphone_id === microphoneId)?.is_default ?? false
}

export function getUniqueDefaultMicrophoneId(
    microphones: RecorderMicrophoneInfo[],
): number | undefined {
    const defaults = microphones.filter((mic) => mic.is_default)
    return defaults.length === 1 ? defaults[0]?.microphone_id : undefined
}

export function buildSensorWritePayload(
    values: SensorFormValues,
    cameraLensDefaultTouched: boolean,
    recorderMicrophoneDefaultTouched = false,
): SensorCreateBody {
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
        if (recorderMicrophoneDefaultTouched) {
            payload.recorder_microphone_is_default = values.recorder_microphone_is_default ?? false
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
        if (cameraLensDefaultTouched) {
            payload.camera_lens_is_default = values.camera_lens_is_default ?? false
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
