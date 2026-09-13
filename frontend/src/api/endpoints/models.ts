import { apiClient } from "../client"

export interface MLModelItem {
    model_id: number
    name: string | null
    version: string | null
    description: string | null
    source_url: string | null
    parameter: unknown
}

export const modelsApi = {
    /** 获取AI模型列表及版本 / List AI models with versions */
    getModels() {
        return apiClient.get<{ code: number; message: string; data: MLModelItem[] }>("/v1/models")
    },

    /** 获取单个AI模型详情 / Get AI model detail */
    getModel(modelId: number) {
        return apiClient.get<{ code: number; message: string; data: MLModelItem }>(`/v1/models/${modelId}`)
    },
}
