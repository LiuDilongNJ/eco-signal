/**
 * 常量定义
 */

/** Realm → 颜色映射 */
export const SPHERE_COLORS: Record<string, string> = {
    Terrestrial: "#22c55e",
    "Terrestrial-Freshwater": "#14b8a6",
    Freshwater: "#3b82f6",
    "Freshwater-Marine": "#0ea5e9",
    Marine: "#06b6d4",
    "Marine-Terrestrial": "#84cc16",
    "Marine-Freshwater-Terrestrial": "#10b981",
    Subterranean: "#a855f7",
    "Subterranean-Freshwater": "#6366f1",
    "Subterranean-Marine": "#4f46e5",
    Atmospheric: "#f97316",
    Anthroposphere: "#ec4899",
    Unknown: "#94a3b8",
}

/** 默认品牌色 */
export const DEFAULT_BRAND_COLOR = "#83CD20"

/** Tab 标签定义 */
export const TAB_ITEMS = [
    { key: "desc", label: "Description" },
    { key: "summary", label: "Summary" },
    { key: "media", label: "Media" },
    { key: "map", label: "Map" },
    { key: "timeline", label: "Timeline" },
    { key: "data", label: "Data" },
] as const

/** 预定义标签 */
export const PREDEFINED_LABELS = [
    "Aves",
    "Insecta",
    "Chiroptera",
    "Anura",
    "Anthrophony",
    "Geophony",
    "Biophony",
    "Unknown",
]

/** AI 模型配置 */
export const AI_MODELS = [
    {
        id: "birdnet",
        name: "BirdNET",
        desc: "Identify bird species by sound using the BirdNET algorithm.",
        params: [
            { key: "min_conf", label: "Min Confidence", type: "number", default: 0.1 },
            { key: "sensitivity", label: "Sensitivity", type: "number", default: 1.0 },
        ],
    },
    {
        id: "batdetect2",
        name: "BatDetect2",
        desc: "Detect and classify bat echolocation calls.",
        params: [
            { key: "detection_threshold", label: "Detection Threshold", type: "number", default: 0.5 },
        ],
    },
]

/** 声学指数配置 */
export const ACOUSTIC_INDICES = [
    {
        id: "aci",
        name: "Acoustic Complexity Index (ACI)",
        desc: "Measures the variability of sound intensities.",
        params: [
            { key: "min_freq", label: "Min Freq (Hz)", type: "number", default: 0 },
            { key: "max_freq", label: "Max Freq (Hz)", type: "number", default: 22050 },
        ],
    },
    {
        id: "adi",
        name: "Acoustic Diversity Index (ADI)",
        desc: "Measures the diversity of frequency bands.",
        params: [
            { key: "db_threshold", label: "dB Threshold", type: "number", default: -50 },
            { key: "freq_step", label: "Freq Step (Hz)", type: "number", default: 1000 },
        ],
    },
]
