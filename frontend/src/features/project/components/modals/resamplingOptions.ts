export const RESAMPLING_RATE_OPTIONS = [
    8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200, 96000,
    176400, 192000, 352800, 384000,
] as const

export function isValidResamplingRate(value: unknown): value is number {
    return typeof value === "number" && Number.isInteger(value) && value >= 8000 && value <= 384000
}
