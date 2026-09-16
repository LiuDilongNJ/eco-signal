export const RESAMPLING_RATE_OPTIONS = [
    8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000,
    176400, 192000, 352800, 384000,
] as const

export const OPUS_RESAMPLING_RATE_OPTIONS = [8000, 12000, 16000, 24000, 48000] as const
export const MP3_RESAMPLING_RATE_OPTIONS = [8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000] as const
const VORBIS_MAX_SAMPLING_RATE = 200000

export function isResamplingRateSupportedForCodec(codec: string | null | undefined, rate: number): boolean {
    switch (codec?.toLowerCase()) {
        case "opus":
            return OPUS_RESAMPLING_RATE_OPTIONS.includes(rate as typeof OPUS_RESAMPLING_RATE_OPTIONS[number])
        case "mp3":
            return MP3_RESAMPLING_RATE_OPTIONS.includes(rate as typeof MP3_RESAMPLING_RATE_OPTIONS[number])
        case "vorbis":
            return rate <= VORBIS_MAX_SAMPLING_RATE
        default:
            return true
    }
}

export function isValidResamplingRate(value: unknown): value is number {
    return typeof value === "number" && Number.isInteger(value) && value >= 8000 && value <= 384000
}
