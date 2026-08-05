import { apiClient } from "../client"
import type { CsvImportResult } from "../csvImport"
import { getApiData } from "../utils"
import type { ApiResponse, PagedApiResponse } from "../../types"

/** GET /v1/taxons/suggestions 单项 */
export interface TaxonPublic {
    taxon_id: number
    col_species_id?: string | null
    col_genus_id?: string | null
    col_family_id?: string | null
    col_order_id?: string | null
    col_class_id?: string | null
    cached_scientific_name?: string | null
    cached_common_name?: string | null
    taxonomy_source?: string | null
}

/** GET /v1/taxons 管理列表项 */
export interface TaxonListItem {
    taxon_id: number
    cached_scientific_name?: string | null
    cached_common_name?: string | null
    col_species_id?: string | null
    col_genus_id?: string | null
    col_family_id?: string | null
    col_order_id?: string | null
    col_class_id?: string | null
    col_genus_name?: string | null
    col_family_name?: string | null
    col_order_name?: string | null
    col_class_name?: string | null
    col_species_name?: string | null
    taxonomy_source?: string | null
    creation_date: string
    last_synced?: string | null
}

export interface TaxonListQueryParams {
    page?: number
    page_size?: number
    taxon_id?: number
    q?: string
    cached_scientific_name?: string
    cached_common_name?: string
    taxonomy_source?: string
    col_class_id?: string
    col_order_id?: string
    col_family_id?: string
    col_genus_id?: string
    col_species_id?: string
    col_genus_name?: string
    col_family_name?: string
    col_order_name?: string
    col_class_name?: string
    col_species_name?: string
    creation_date_from?: string
    creation_date_to?: string
    last_synced_from?: string
    last_synced_to?: string
    order_by?: string
    order_dir?: "asc" | "desc"
}

export type TaxonCreateBody = {
    cached_common_name?: string | null
    col_species_id?: string | null
    col_genus_id?: string | null
    col_family_id?: string | null
    col_order_id?: string | null
    col_class_id?: string | null
    taxonomy_source?: string | null
}

export type TaxonUpdateBody = TaxonCreateBody
export type TaxonImportResult = CsvImportResult

/** GET /v1/taxons/options — 层级下拉选项 */
export interface TaxonOption {
    id: string
    name: string
}

export interface TaxonOptionsQueryParams {
    rank: "class" | "order" | "family" | "genus" | "species"
    class_id?: string | null
    order_id?: string | null
    family_id?: string | null
    genus_id?: string | null
    q?: string
    page?: number
    page_size?: number
}

/** GET /v1/sound-classifications 单项 */
export interface SoundClassificationPublic {
    sound_id: number
    soundscape_component: string | null
    sound_type: string | null
}

/** GET /v1/animal-sound-types 单项 */
export interface TaxonSoundTypePublic {
    taxon_sound_type_id: number
    name: string
}

function taxonSearchParams(
    q: string | undefined,
    limit: number,
    offset = 0,
): Record<string, string | number> {
    const params: Record<string, string | number> = { limit, offset }
    const t = q?.trim() ?? ""
    if (t !== "") params.q = t
    return params
}

export const taxonsApi = {
    importCsv(file: File) {
        const formData = new FormData()
        formData.append("file", file)
        return apiClient.post<ApiResponse<TaxonImportResult>>("/v1/taxons/imports", formData)
    },
    /** 返回原始封装，便于调用方判断 code */
    listSuggestions(q: string, limit: number = 10, offset = 0) {
        return apiClient.get<ApiResponse<TaxonPublic[]>>("/v1/taxons/suggestions", {
            params: taxonSearchParams(q, limit, offset),
        })
    },

    /** GET /v1/taxons — 解析 data；q 为空或不传时由后端返回默认列表 */
    async listSuggestionsData(
        q: string | undefined,
        limit = 20,
        ignoreUnauthorized?: boolean,
        offset = 0,
    ): Promise<TaxonPublic[]> {
        const res = await apiClient.get<{ code: number; message: string; data: TaxonPublic[] }>(
            "/v1/taxons/suggestions",
            { params: taxonSearchParams(q, limit, offset), ignoreUnauthorized },
        )
        return getApiData(res)
    },

    /** 声景 + 声型下拉数据源；创建标注时第二级选中的 sound_id 写入请求体 */
    async getSoundClassifications(ignoreUnauthorized?: boolean): Promise<SoundClassificationPublic[]> {
        const res = await apiClient.get<{
            code: number
            message: string
            data: SoundClassificationPublic[]
        }>("/v1/sound-classifications", { ignoreUnauthorized })
        return getApiData(res)
    },

    /** 动物发声类型；提交时取选中项 `name` 作为 animal_sound_type */
    async getAnimalSoundTypes(
        params?: {
            taxon_class?: string
            taxon_order?: string
        },
        ignoreUnauthorized?: boolean,
    ): Promise<TaxonSoundTypePublic[]> {
        const res = await apiClient.get<{
            code: number
            message: string
            data: TaxonSoundTypePublic[]
        }>("/v1/animal-sound-types", { params, ignoreUnauthorized })
        return getApiData(res)
    },

    list(params: TaxonListQueryParams) {
        return apiClient.get<PagedApiResponse<TaxonListItem[]>>("/v1/taxons", { params })
    },

    get(taxonId: number) {
        return apiClient.get<{ code: number; message: string; data: TaxonListItem }>(`/v1/taxons/${taxonId}`)
    },

    create(body: TaxonCreateBody) {
        return apiClient.post<{ code: number; message: string; data: TaxonListItem }>("/v1/taxons", body)
    },

    update(taxonId: number, body: TaxonUpdateBody) {
        return apiClient.put<{ code: number; message: string; data: TaxonListItem }>(`/v1/taxons/${taxonId}`, body)
    },

    delete(taxonId: number) {
        return apiClient.delete<{ code: number; message: string }>(`/v1/taxons/${taxonId}`)
    },

    /** GET /v1/taxons/options — 获取层级下拉选项（class/order/family/genus/species） */
    listOptions(params: TaxonOptionsQueryParams) {
        return apiClient.get<PagedApiResponse<TaxonOption[]>>("/v1/taxons/options", { params })
    },

    exportCsv(params?: Pick<TaxonListQueryParams, "order_by" | "order_dir">) {
        return apiClient.download("/v1/taxons/exports", { params })
    },
}

/** 物种层级下拉 → 列表筛选项（value 为本地 taxon_id，供 Reviews 等 taxon_id 筛选） */
export async function fetchSpeciesHierarchyFilterOptions(
    params?: Pick<TaxonOptionsQueryParams, "q" | "page_size">,
): Promise<{ label: string; value: number }[]> {
    const res = await taxonsApi.listOptions({
        rank: "species",
        page_size: params?.page_size ?? 100,
        q: params?.q,
    })
    if (res.code !== 0 && res.code !== 200) {
        return []
    }
    const items = res.data ?? []
    const resolved = await Promise.all(
        items.map(async (opt) => {
            try {
                const list = await taxonsApi.listSuggestionsData(opt.name, 10)
                const match =
                    list.find((t) => t.col_species_id === opt.id) ??
                    list.find((t) => (t.cached_scientific_name ?? "").trim() === opt.name.trim())
                if (!match?.taxon_id) return null
                return { label: opt.name, value: match.taxon_id }
            } catch {
                return null
            }
        }),
    )
    return resolved.filter((x): x is { label: string; value: number } => x != null)
}
