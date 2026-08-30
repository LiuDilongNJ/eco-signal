import { apiClient } from "../client"
import type { PagedApiResponse } from "../../types"

/** Matches GET /v1/geo/gadm items: { gid, name } */
export interface GadmOption {
    gid: string
    name: string
    name_zh?: string
}

/** IUCN endpoints use `id`; IHO uses `gid` (string of DB id). */
export interface GenericGeoOption {
    name: string
    id?: number
    gid?: string
}

export type GeoPageParams = {
    search?: string
    page?: number
    page_size?: number
}

export type CoordinateGeoOption = { gid: string; name: string }
export type CoordinateMatches = {
    gadm: {
        status: "matched" | "unmatched" | "ambiguous"
        gadm0: CoordinateGeoOption | null
        gadm1: CoordinateGeoOption | null
        gadm2: CoordinateGeoOption | null
    }
    iho: {
        status: "matched" | "unmatched" | "ambiguous"
        option: CoordinateGeoOption | null
    }
}

export const geoApi = {
    getCoordinateMatches(longitude: number, latitude: number, ignoreUnauthorized?: boolean) {
        return apiClient.get<{ code: number; message?: string; data?: CoordinateMatches }>("/v1/geo/coordinate-matches", {
            params: { longitude, latitude },
            ignoreUnauthorized,
        })
    },
    /** 
     * 获取 GADM 行政区划选项 / Get GADM administrative options
     * @param params - Query parameters
     * @param params.level - integer (Level) 0=Country, 1=Province, 2=City
     * @param params.parent_id - Parent Id (integer) or undefined
     * @param params.search - Search (string) or undefined Keyword search
     */
    getGadmOptions(
        params: GeoPageParams & { level: number; parent_gid?: string },
        ignoreUnauthorized?: boolean,
    ) {
        return apiClient.get<PagedApiResponse<GadmOption[]>>("/v1/geo/gadm", { params, ignoreUnauthorized })
    },

    getIhoOptions(params?: GeoPageParams, ignoreUnauthorized?: boolean) {
        return apiClient.get<PagedApiResponse<GenericGeoOption[]>>("/v1/geo/iho", { params, ignoreUnauthorized })
    },

    getIucnRealms(params?: GeoPageParams, ignoreUnauthorized?: boolean) {
        return apiClient.get<PagedApiResponse<GenericGeoOption[]>>("/v1/geo/iucn-realms", {
            params,
            ignoreUnauthorized,
        })
    },

    getIucnBiomes(params?: GeoPageParams & { realm_id?: number }, ignoreUnauthorized?: boolean) {
        const clean = params
            ? (Object.fromEntries(
                  Object.entries(params).filter(([, v]) => v !== undefined && v !== ""),
                  ) as GeoPageParams & { realm_id?: number })
            : undefined
        return apiClient.get<PagedApiResponse<GenericGeoOption[]>>("/v1/geo/iucn-biomes", {
            params: clean,
            ignoreUnauthorized,
        })
    },

    getIucnFunctionalTypes(params?: GeoPageParams & { biome_id?: number }, ignoreUnauthorized?: boolean) {
        const clean = params
            ? (Object.fromEntries(
                  Object.entries(params).filter(([, v]) => v !== undefined && v !== ""),
                  ) as GeoPageParams & { biome_id?: number })
            : undefined
        return apiClient.get<PagedApiResponse<GenericGeoOption[]>>("/v1/geo/iucn-functional-types", {
            params: clean,
            ignoreUnauthorized,
        })
    },
}
