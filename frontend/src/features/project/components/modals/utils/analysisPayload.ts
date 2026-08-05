import type {
    BatDetectParams,
    BirdNETLocale,
    BirdNETParams,
    RunAnalysisRequest,
} from "../../../../../api/endpoints/analysis"

export interface AnalysisPayloadValues {
    projectId: number
    mediaIds: number[]
    birdnet: {
        enabled: boolean
        minConf: number | null
        overlap: number | null
        sensitivity: number | null
        sfThresh: number | null
        locale: BirdNETLocale
        topN: number | null
    }
    batdetect: {
        enabled: boolean
        threshold: number | null
        chunkSize: number | null
    }
    insects: {
        enabled: boolean
        windowSize: number | null
        strideLength: number | null
    }
    merge: {
        enabled: boolean
        maxGap: number | null
        keepMerged: boolean
    }
}

export function buildRunAnalysisPayload(values: AnalysisPayloadValues): RunAnalysisRequest {
    const payload: RunAnalysisRequest = {
        project_id: values.projectId,
        media_ids: values.mediaIds,
        merge: {
            is_merged: values.merge.enabled,
            max_gap: values.merge.maxGap || 0,
            keep_merged: values.merge.keepMerged,
        },
    }

    if (values.birdnet.enabled) {
        const birdnet: BirdNETParams = {
            sensitivity: values.birdnet.sensitivity ?? 1,
            min_conf: values.birdnet.minConf ?? 0.1,
            overlap: values.birdnet.overlap ?? 0,
            sf_thresh: values.birdnet.sfThresh ?? 0.03,
            locale: values.birdnet.locale,
        }
        if (values.birdnet.topN !== null) birdnet.top_n = values.birdnet.topN
        payload.birdnet = birdnet
    }

    if (values.batdetect.enabled) {
        const batdetect: BatDetectParams = {
            detection_threshold: values.batdetect.threshold ?? 0.3,
        }
        batdetect.chunk_size = values.batdetect.chunkSize ?? 2
        payload.batdetect = batdetect
    }

    if (values.insects.enabled) {
        payload.insects = {
            window_size: values.insects.windowSize ?? 4,
            stride_length: values.insects.strideLength ?? 4,
        }
    }

    return payload
}
