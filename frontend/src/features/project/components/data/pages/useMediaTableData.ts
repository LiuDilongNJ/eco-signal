import { useCallback, useEffect, useState } from "react"
import { mediaApi, type MediaListItem } from "../../../../../api/endpoints/media"
import { sitesApi, type SiteOption } from "../../../../../api/endpoints/sites"
import { licensesApi, type LicenseOption } from "../../../../../api/endpoints/licenses"
import { sensorsApi, type SensorOption } from "../../../../../api/endpoints/sensors"
import type { RowData, TableState } from "../DataPageLayout"
import { buildMediaQueryParams } from "./mediaQueryParams"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

export function useMediaTableData(
    mediaType: "audio" | "photo",
    projectId: string | number | null | undefined,
    collectionId: string | number | null | undefined,
) {
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [tableState, setTableState] = useState<TableState | null>(null)
    const [siteOptions, setSiteOptions] = useState<SiteOption[]>([])
    const [licenseOptions, setLicenseOptions] = useState<LicenseOption[]>([])
    const [sensorOptions, setSensorOptions] = useState<SensorOption[]>([])

    useEffect(() => {
        const params: { project_id?: number; collection_id?: number } = {}
        if (projectId) params.project_id = Number(projectId)
        if (collectionId && collectionId !== "all") params.collection_id = Number(collectionId)
        setSiteOptions([])
        licensesApi.getOptions(params)
            .then((response) => setLicenseOptions(response?.data ?? []))
            .catch((error) => console.error("Failed to fetch license options:", error))
        sensorsApi.getOptions(params)
            .then((response) => setSensorOptions(response?.data ?? []))
            .catch((error) => console.error("Failed to fetch sensor options:", error))
    }, [collectionId, projectId])

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            if (!projectId) {
                setRows([])
                setTotalRows(0)
                setSiteOptions([])
                return
            }

            const scope = { projectId, collectionId }
            const [response, siteResponse] = await Promise.all([
                mediaApi.getMedia(buildMediaQueryParams(mediaType, state, scope)),
                sitesApi.getOptions(buildMediaQueryParams(mediaType, state, scope, {
                    includePagination: false,
                    includeSorting: false,
                    includeSiteFilter: false,
                })).catch((error) => {
                    console.error("Failed to fetch site options:", error)
                    return null
                }),
            ])
            const nextSiteOptions = siteResponse?.data ?? []
            setSiteOptions(nextSiteOptions)
            const items = response?.data ?? []
            setRows(items.map((item) => {
                const site = nextSiteOptions.find((option) => option.site_id === item.site_id)
                const license = licenseOptions.find(
                    (option) => option.license_id === item.license_id,
                )
                const sensor = sensorOptions.find(
                    (option) => option.sensor_id === item.sensor_id,
                )
                return {
                    ...item,
                    is_metadata: item.is_metadata === true,
                    site_name: item.site_name?.trim() || site?.name || String(item.site_id || ""),
                    license_name:
                        item.license_name?.trim() ||
                        license?.name ||
                        String(item.license_id || ""),
                    sensor_name:
                        item.sensor_name?.trim() ||
                        sensor?.name ||
                        String(item.sensor_id || ""),
                    recording_gain_db: item.audio_setting?.recording_gain_db,
                    sampling_rate_hz: item.audio_setting?.sampling_rate_hz,
                    bit_depth: item.audio_setting?.bit_depth,
                    channel_num: item.audio_setting?.channel_num,
                    duration_s: item.audio_setting?.duration_s,
                    exposure_ms: item.photo_setting?.exposure_ms,
                    aperture: item.photo_setting?.aperture,
                    iso: item.photo_setting?.iso,
                    uploader_name: item.uploader_name || String(item.uploader_id || ""),
                    creator_name: item.creator_name || String(item.creator_id || ""),
                    hierarchy: Array.isArray(item.hierarchy)
                        ? item.hierarchy.join(" > ")
                        : item.hierarchy,
                } as unknown as RowData
            }))
            setTotalRows(response?.page_info?.total ?? items.length)
        } catch (error) {
            console.error(`Failed to fetch ${mediaType} media:`, error)
        } finally {
            setLoading(false)
        }
    }, [collectionId, licenseOptions, mediaType, projectId, sensorOptions])

    const scheduleTableFetch = useTableFetchScheduler(fetchTableData)

    const handleTableChange = useCallback((state: TableState) => {
        setTableState(state)
        scheduleTableFetch(state)
    }, [scheduleTableFetch])

    const refresh = useCallback(() => {
        if (tableState) handleTableChange(tableState)
    }, [handleTableChange, tableState])

    return {
        rows,
        totalRows,
        loading,
        setLoading,
        tableState,
        siteOptions,
        licenseOptions,
        sensorOptions,
        handleTableChange,
        refresh,
    }
}
