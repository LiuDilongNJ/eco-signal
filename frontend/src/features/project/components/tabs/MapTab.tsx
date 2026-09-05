import { Button as ESButton } from "@/components/ui"
/**
 * MapTab - 地图视图
 *
 * 使用 Leaflet + react-leaflet 展示站点地理位置
 * 包含: 地图视图 + Realm 过滤器 + 站点侧边栏
 */

import { useState, useMemo, useEffect, useRef } from "react"
import { MapContainer, TileLayer, Polygon, useMap } from "react-leaflet"
import L from "leaflet"
import "leaflet/dist/leaflet.css"
import "leaflet.markercluster/dist/leaflet.markercluster.js"
import "leaflet.markercluster/dist/MarkerCluster.css"
import "leaflet.markercluster/dist/MarkerCluster.Default.css"
import { CARTO_ATTRIBUTION, cartoTileUrl } from "@/utils/mapTiles"
import "../../map.css"
import {
    X,
    Mountain,
    SlidersHorizontal,
    ChevronsLeft,
    ChevronDown,
    RotateCcw,
    Maximize,
    Maximize2,
    Minimize2,
    Droplets,
} from "lucide-react"
import { useProjectStore } from "../../stores/useProjectStore"
import { SPHERE_COLORS } from "../../data/constants"
import { sitesApi, type IucnOption, type SiteMapMarker } from "../../../../api/endpoints/sites"
import { mediaApi, type BrowseMediaParams } from "../../../../api/endpoints/media"
import {
    MediaGalleryCard,
    mediaRowToGalleryItem,
    resolveMediaDetailTo,
} from "../media/MediaGalleryCard"
import { CustomScrollArea } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { MediaTypeSegment } from "./MediaTypeSegment"
import { mediaTypeFilterParam, type MediaTypeFilter } from "./mediaTypeFilter"

// ----- Types -----
interface Site {
    id: string
    name: string
    realm: string
    biome: string
    functional_type: string
    center: [number, number]
    polygon: [number, number][]
    ihoPolygons: [number, number][][]
    mediaCount: number
    topography_m: number
    freshwater_depth_m: number | null
    sensors: string[]
}

interface FilterState {
    realm_id: number | null
    biome_id: number | null
    functional_type_id: number | null
}

interface IdName {
    id: number
    name: string
}

/** 地图缩放级别（统一在此调整） */
const DEFAULT_MAP_CENTER: [number, number] = [-3.465, -62.215]
/** MapContainer 初始 zoom；多站点分散过广时不再全球 fitBounds，而用此 zoom flyTo 项目中心 */
const MAP_INITIAL_ZOOM = 6
/** 多站点外包框纬度/经度跨度（度）超过时视为「过散」，避免 fitBounds 缩到全球 */
const MAP_FIT_MAX_LAT_SPAN = 28
const MAP_FIT_MAX_LNG_SPAN = 55
/** 多站点 fitBounds 时允许的最大 zoom，避免视野过窄 */
const MAP_FIT_ALL_MAX_ZOOM = 15
/** 地图上只剩 1 个站点时的 flyTo zoom */
const MAP_FIT_SINGLE_SITE_ZOOM = 10
/** 无有效围栏时 flyTo 中心至少达到的 zoom */
const MAP_SITE_NO_FENCE_MIN_ZOOM = 10
/** 选中站点时，为右侧详情面板预留的最大水平安全偏移（像素）。 */
const MAP_SELECTION_PANEL_GAP_PX = 20
/** 到这个缩放级别后不再聚合，直接拆开站点（过低会导致近距离点“叠在一起”） */
const MAP_DISABLE_CLUSTERING_ZOOM = 16
/** 放大到该级别后显示站点区域 */
const MAP_SHOW_REGION_ZOOM = 11

/** Biome / Group 下拉项圆点（无 realm 色谱时统一用 slate） */
const FILTER_DOT_LIST = "var(--text-muted)"

// ----- 获取 Realm 颜色 -----
function getRealmColor(realm: string): string {
    return (SPHERE_COLORS as Record<string, string>)[realm] ?? "var(--brand)"
}

/** 判断是否为 [[lng,lat], ...] 形式的外环 */
function isLngLatRing(arr: unknown): arr is number[][] {
    if (!Array.isArray(arr) || arr.length === 0) return false
    return arr.every(
        (p) => Array.isArray(p) && typeof p[0] === "number" && typeof p[1] === "number",
    )
}

/** 从可能多层嵌套的 GeoJSON 坐标结构中取出第一个外环 */
function extractGeoJsonOuterRing(coords: unknown): number[][] | null {
    if (!Array.isArray(coords)) return null
    if (isLngLatRing(coords)) return coords
    for (const child of coords) {
        const r = extractGeoJsonOuterRing(child)
        if (r) return r
    }
    return null
}

/** 递归寻找所有 [lng, lat] 点数组（环/区域） */
function extractAllGeoJsonRings(coords: unknown, acc: number[][][] = []): number[][][] {
    if (!Array.isArray(coords)) return acc
    if (isLngLatRing(coords)) {
        acc.push(coords)
        return acc
    }
    for (const child of coords) {
        extractAllGeoJsonRings(child, acc)
    }
    return acc
}

function geometryToLeafletAllRings(coords: unknown): [number, number][][] {
    if (!coords) return []
    const rings = extractAllGeoJsonRings(coords)
    return rings.map(lngLatRingToLeaflet)
}

function lngLatRingToLeaflet(ring: number[][]): [number, number][] {
    return ring.map((pair) => [pair[1]!, pair[0]!] as [number, number])
}

type GeoLocationBlock = {
    center?: { latitude?: number; longitude?: number } | null
    coordinates?: unknown
} | null | undefined

/**
 * 命名字段应为 WGS84：latitude ∈ [-90,90]，longitude ∈ [-180,180]。
 * - 明显反了：纬度槽位超出 ±90（如 117°E 写在 latitude）→ 交换。
 * - 数值都合法但仍反了：如 ~88°E / ~28°N 被写成 latitude=88、longitude=28，会落在北极附近、视野像「在地图边上」。
 */
function normalizeNamedLatLngToLeaflet(lat: number, lng: number): [number, number] {
    const absLat = Math.abs(lat)
    const absLng = Math.abs(lng)

    if (absLat > 90 && absLat <= 180 && absLng <= 90) return [lng, lat]

    if (absLat <= 90 && absLng <= 180) {
        // 高纬槽位 (>87°) + 另一侧像中纬纬度 → 多为把东经误写在 latitude（例：88.57E, 28.54N）
        if (lat > 87 && lat <= 90 && absLng >= 8 && absLng <= 50 && lat > absLng) {
            return [lng, lat]
        }
        return [lat, lng]
    }

    return [lat, lng]
}

/** geometry.point 有合法经纬度时返回 [lat, lng]，供标点专用 */
function geometryPointLatLng(
    geometry: Record<string, unknown> | null | undefined,
): [number, number] | null {
    if (!geometry || typeof geometry !== "object") return null
    const pt = geometry.point as { latitude?: number; longitude?: number } | null | undefined
    if (
        pt != null &&
        typeof pt === "object" &&
        typeof pt.latitude === "number" &&
        typeof pt.longitude === "number" &&
        !Number.isNaN(pt.latitude) &&
        !Number.isNaN(pt.longitude)
    ) {
        return normalizeNamedLatLngToLeaflet(pt.latitude, pt.longitude)
    }
    return null
}

/** 解析 GET /site-map-items 的 center 字段为 Leaflet 用的 [lat, lng] */
function parseSiteMapCenter(
    c: { latitude?: number; longitude?: number; lat?: number; lng?: number } | null | undefined,
): [number, number] | null {
    if (c == null || typeof c !== "object") return null
    const lat = c.latitude ?? c.lat
    const lng = c.longitude ?? c.lng
    if (typeof lat !== "number" || typeof lng !== "number" || Number.isNaN(lat) || Number.isNaN(lng)) {
        return null
    }
    return normalizeNamedLatLngToLeaflet(lat, lng)
}

function mapMarkerToSite(
    m: SiteMapMarker,
    lookups: {
        realmById: Map<number, string>
        biomeById: Map<number, string>
        functionalTypeById: Map<number, string>
    },
): Site {
    const g = (m.geometry ?? {}) as Record<string, unknown>
    const location = g?.location as GeoLocationBlock
    const locationIho = g?.location_iho as GeoLocationBlock

    // 1. 中心点：仅使用 geometry.point（不再做兼容回退）
    const [lat, lng] = geometryPointLatLng(g ?? undefined) ?? [0, 0]

    // 2. 选中区域：优先使用 geometry.location.coordinates
    const clickPolygon = location?.coordinates ? (extractGeoJsonOuterRing(location.coordinates) ? lngLatRingToLeaflet(extractGeoJsonOuterRing(location.coordinates)!) : []) : []

    // 3. IHO 区域：优先使用 geometry.location_iho，备选使用 geometry.iho
    const rawIho = locationIho?.coordinates ?? (g as any)?.iho?.coordinates ?? (g as any)?.location_iho?.coordinates
    const ihoPolygons = rawIho ? geometryToLeafletAllRings(rawIho) : []

    return {
        id: String(m.site_id),
        name: `${m.name?.trim() || `#${m.site_id}`}`,
        realm:
            m.realm_name?.trim() ||
            (m.realm_id != null ? (lookups.realmById.get(m.realm_id) ?? `Realm #${m.realm_id}`) : "-"),
        biome: m.biome_id != null ? (lookups.biomeById.get(m.biome_id) ?? `Biome #${m.biome_id}`) : "-",
        functional_type:
            m.functional_type_id != null
                ? (lookups.functionalTypeById.get(m.functional_type_id) ?? `Group #${m.functional_type_id}`)
                : "-",
        center: [lat, lng],
        polygon: clickPolygon,
        ihoPolygons,
        mediaCount: m.media_count ?? 0,
        topography_m: 0,
        freshwater_depth_m: null,
        sensors: [],
    }
}

/** 圆内数字压缩展示，避免千万级仍占满一行撑破圆环 */
// function formatMarkerCount(n: number): string {
//     const v = Math.max(0, Math.floor(Number.isFinite(n) ? n : 0))
//     if (v < 1000) return String(v)
//     if (v < 1_000_000) return `${Math.floor(v / 1000)}K`
//     if (v < 1_000_000_000) return `${Math.floor(v / 1_000_000)}M`
//     return `${Math.floor(v / 1_000_000_000)}B`
// }

const MARKER_BASE_SIDE = 40
const MARKER_SIDE_STEP = 7
const MARKER_MAX_SIDE = 120
const CLUSTER_SIDE_BOOST = 10

/** 文案越长，Leaflet 图标略放大，圆心与锚点仍居中 */
function markerSidePxForLabel(label: string): number {
    const extra = Math.max(0, label.length - 3)
    return Math.min(MARKER_BASE_SIDE + extra * MARKER_SIDE_STEP, MARKER_MAX_SIDE)
}

// ----- 自定义 Marker 图标 -----
function createSiteIcon(mediaCount: number, color: string) {
    const label = String(mediaCount)
    const side = markerSidePxForLabel(label)
    const ax = Math.round(side / 2)
    return L.divIcon({
        html: `<div class="site-marker-pin site-marker-pin--leaflet" style="--sm-size:${side}px;border-color:${color};color:${color};">
                 <div class="site-marker-val">${label}</div>
               </div>`,
        className: "custom-cluster-icon",
        iconSize: [side, side],
        iconAnchor: [ax, ax],
    })
}

/** 聚合簇：外圈按子标记 realm 数量比例 conic-gradient（与子点同色） */
function createClusterProportionalIcon(
    displayCount: number,
    segments: { color: string; count: number }[],
): L.DivIcon {
    const total = segments.reduce((s, x) => s + x.count, 0)
    if (total <= 0) {
        // 兜底：无分段信息时用统一灰色簇
        const label = String(displayCount)
        const side = Math.min(markerSidePxForLabel(label) + CLUSTER_SIDE_BOOST, MARKER_MAX_SIDE)
        const ax = Math.round(side / 2)
        const html = `<div class="site-marker-cluster site-marker-cluster--leaflet" style="--sm-size:${side}px;background:${FILTER_DOT_LIST};">
        <div class="site-marker-cluster-inner">
          <div class="site-marker-val">${label}</div>
          <div class="site-marker-lbl">MEDIA</div>
        </div>
      </div>`
        return L.divIcon({
            html,
            className: "custom-cluster-icon",
            iconSize: [side, side],
            iconAnchor: [ax, ax],
        })
    }
    let acc = 0
    const stops: string[] = []
    for (const seg of segments) {
        const p0 = (acc / total) * 100
        acc += seg.count
        const p1 = (acc / total) * 100
        stops.push(`${seg.color} ${p0}% ${p1}%`)
    }
    const gradient = `conic-gradient(from 0deg, ${stops.join(", ")})`
    const topSeg = segments.reduce((a, b) => (b.count > a.count ? b : a))
    const glow = `${topSeg.color}66`
    const label = String(displayCount)
    const side = Math.min(markerSidePxForLabel(label) + CLUSTER_SIDE_BOOST, MARKER_MAX_SIDE)
    const ax = Math.round(side / 2)
    const html = `<div class="site-marker-cluster site-marker-cluster--leaflet" style="--sm-size:${side}px;background:${gradient};box-shadow:0 4px 15px ${glow};">
        <div class="site-marker-cluster-inner">
          <div class="site-marker-val">${label}</div>
          <div class="site-marker-lbl">MEDIA</div>
        </div>
      </div>`
    return L.divIcon({
        html,
        className: "custom-cluster-icon",
        iconSize: [side, side],
        iconAnchor: [ax, ax],
    })
}

type MarkerWithSite = L.Marker & { __site?: Site }

/** 点击单个站点标点（无更下层聚合）时，将视图移到该站点围栏，并返回目标缩放级别 */
function fitMapToSiteFence(map: L.Map, site: Site): number {
    const targetZoom = Math.max(map.getZoom(), MAP_SITE_NO_FENCE_MIN_ZOOM)
    // 详情侧栏覆盖在地图上方，飞到中心后再向左平移，避免选中点落在侧栏下面。
    map.once("moveend", () => {
        const panel = document.querySelector<HTMLElement>(".site-sidebar-panel.visible")
        if (!panel) return
        const mapWidth = map.getSize().x
        const panelWidth = panel.getBoundingClientRect().width
        const offset = Math.min(
            mapWidth * 0.25,
            panelWidth / 2 + MAP_SELECTION_PANEL_GAP_PX,
        )
        if (offset > 0) map.panBy([-offset, 0], { duration: 0.25 })
    })
    map.flyTo(site.center, targetZoom, { duration: 0.75 })
    return targetZoom
}

/** Leaflet.markercluster：近距站点合并为聚合圆，点击可展开 / 放大 */
function ClusteredSiteMarkers({
    sites,
    selectedSite,
    onSelectSite,
    selectionZoom,
    onSelectionZoomChange,
    lastSelectionTimeRef,
}: {
    sites: Site[]
    selectedSite: Site | null
    onSelectSite: (site: Site | null) => void
    selectionZoom: number | null
    onSelectionZoomChange: (zoom: number | null) => void
    lastSelectionTimeRef: React.MutableRefObject<number>
}) {
    const map = useMap()
    const clusterRef = useRef<L.MarkerClusterGroup | null>(null)
    const onSelectRef = useRef(onSelectSite)
    onSelectRef.current = onSelectSite
    const selectedSiteRef = useRef(selectedSite)
    selectedSiteRef.current = selectedSite
    const selectionZoomRef = useRef(selectionZoom)
    selectionZoomRef.current = selectionZoom
    const lastClusterClickTimeRef = useRef(0)

    useEffect(() => {
        const mcg = L.markerClusterGroup({
            maxClusterRadius: (zoom: number) => (zoom >= MAP_DISABLE_CLUSTERING_ZOOM - 1 ? 24 : 58),
            disableClusteringAtZoom: MAP_DISABLE_CLUSTERING_ZOOM,
            spiderfyOnMaxZoom: true,
            showCoverageOnHover: false,
            zoomToBoundsOnClick: true,
            chunkedLoading: sites.length > 200,
            chunkDelay: 50,
            iconCreateFunction: (cluster) => {
                const children = cluster.getAllChildMarkers() as MarkerWithSite[]
                let totalMedia = 0
                const realmTally = new Map<string, number>()
                for (const m of children) {
                    const s = m.__site
                    if (s) {
                        totalMedia += s.mediaCount
                        realmTally.set(s.realm, (realmTally.get(s.realm) ?? 0) + 1)
                    }
                }
                const display = totalMedia > 0 ? totalMedia : children.length
                const segments = Array.from(realmTally.entries())
                    .filter(([, n]) => n > 0)
                    .map(([realm, count]) => ({ realm, color: getRealmColor(realm), count }))
                    .sort((a, b) => b.count - a.count || a.realm.localeCompare(b.realm))

                // cluster 图标：不论几种 realm，都用 cluster 样式（数字下方带 MEDIA）
                return createClusterProportionalIcon(
                    display,
                    segments.length > 0
                        ? segments.map(({ color, count }) => ({ color, count }))
                        : [{ color: FILTER_DOT_LIST, count: 1 }],
                )
            },
        })
        clusterRef.current = mcg
        map.addLayer(mcg)

        // 点击聚合簇时只做 zoom/spiderfy，不要误触发子 marker 的选中
        const onClusterClick = (e: any) => {
            lastClusterClickTimeRef.current = Date.now()
            if (e?.originalEvent) {
                e.originalEvent.stopPropagation?.()
                e.originalEvent.preventDefault?.()
            }
        }
        mcg.on("clusterclick", onClusterClick)

        // 监听缩放，如果当前有选中且用户显著缩小了地图（缩小约 2 个层级），则取消选中
        const onZoomEnd = () => {
            const currentZoom = map.getZoom()
            const now = Date.now()
            const activeSite = selectedSiteRef.current
            const activeSelectionZoom = selectionZoomRef.current

            // 只有在非动画期间（点击 1s 后）且缩放级别显著下降时才取消
            if (activeSite && activeSelectionZoom !== null && (now - lastSelectionTimeRef.current > 1000)) {
                if (currentZoom < activeSelectionZoom - 1.5) {
                    onSelectRef.current(null)
                    onSelectionZoomChange(null)
                }
            }
        }
        map.on("zoomend", onZoomEnd)

        return () => {
            map.removeLayer(mcg)
            clusterRef.current = null
            mcg.off("clusterclick", onClusterClick)
            map.off("zoomend", onZoomEnd)
        }
    }, [map, onSelectionZoomChange, lastSelectionTimeRef, sites.length])

    useEffect(() => {
        const mcg = clusterRef.current
        if (!mcg) return
        mcg.clearLayers()

        // 如果有选中站点，则只显示选中站点的 marker
        const sitesToShow = selectedSite ? sites.filter((s) => s.id === selectedSite.id) : sites

        for (const site of sitesToShow) {
            const marker = L.marker(site.center, {
                icon: createSiteIcon(site.mediaCount, getRealmColor(site.realm)),
            }) as MarkerWithSite
            marker.__site = site
            marker.on("click", (e) => {
                // 防止点击事件穿透到地图底层的 click 处理函数
                if (e.originalEvent) {
                    e.originalEvent.stopPropagation()
                    e.originalEvent.preventDefault()
                }

                // 如果刚刚点击过聚合簇（cluster -> spiderfy/zoom），忽略紧随其后的子 marker click
                if (Date.now() - lastClusterClickTimeRef.current < 350) {
                    return
                }
                
                // 如果已经是选中状态且侧边栏可见，则仅再次执行 fitBounds 确保视野对齐，不再触发生态更新
                if (selectedSite?.id === site.id) {
                    fitMapToSiteFence(map, site)
                    return
                }

                // 执行选中
                onSelectRef.current(site)
                lastSelectionTimeRef.current = Date.now()
                const targetZoom = fitMapToSiteFence(map, site)
                onSelectionZoomChange(targetZoom)
            })
            mcg.addLayer(marker)
        }
        mcg.refreshClusters()
    }, [sites, map, selectedSite, onSelectionZoomChange, lastSelectionTimeRef])

    return null
}

function SiteSelectionPolygon({ site }: { site: Site | null }) {
    if (!site) return null
    if (!site.polygon || site.polygon.length < 3) return null
    const color = getRealmColor(site.realm)
    return (
        <Polygon
            positions={site.polygon}
            pathOptions={{
                color,
                weight: 2,
                opacity: 1,
                fillColor: color,
                fillOpacity: 0.2,
            }}
        />
    )
}

function SiteRegionPolygons({
    sites,
    selectedSiteId,
    onSelectSite,
    onSelectionZoomChange,
}: {
    sites: Site[]
    selectedSiteId: string | null
    onSelectSite: (site: Site) => void
    onSelectionZoomChange: (zoom: number | null) => void
}) {
    const map = useMap()
    const [zoom, setZoom] = useState(() => map.getZoom())

    useEffect(() => {
        const onZoomEnd = () => setZoom(map.getZoom())
        map.on("zoomend", onZoomEnd)
        return () => {
            map.off("zoomend", onZoomEnd)
        }
    }, [map])

    // 仅当选中「单个站点 marker」时才显示区域背景（聚合点击/缩放不显示）
    if (!selectedSiteId) return null

    return (
        <>
            {sites
                .filter((site) => site.id === selectedSiteId)
                .filter((site) => site.polygon.length >= 3)
                .map((site) => {
                    const color = getRealmColor(site.realm)
                    const isSelected = selectedSiteId === site.id
                    return (
                        <Polygon
                            key={`site-region-${site.id}`}
                            positions={site.polygon}
                            pathOptions={{
                                color,
                                weight: isSelected ? 2.5 : 1.5,
                                opacity: isSelected ? 1 : 0.75,
                                fillColor: color,
                                fillOpacity: isSelected ? 0.2 : 0.08,
                            }}
                        />
                    )
                })}
        </>
    )
}

function SiteIhoPolygons({ site }: { site: Site | null }) {
    if (!site) return null
    const color = getRealmColor(site.realm)
    return (
        <>
            {site.ihoPolygons.map((ring, idx) => (
                <Polygon
                    key={`site-iho-${site.id}-${idx}`}
                    positions={ring}
                    pathOptions={{
                        color,
                        weight: 2.5,
                        opacity: 0.8,
                        fillColor: color,
                        fillOpacity: 0.12,
                        dashArray: "6, 8",
                        interactive: false,
                    }}
                />
            ))}
        </>
    )
}

function sitesCentroid(sites: Site[]): [number, number] {
    let lat = 0
    let lng = 0
    for (const s of sites) {
        lat += s.center[0]
        lng += s.center[1]
    }
    const n = sites.length
    return [lat / n, lng / n]
}

function boundsSpanTooWide(bounds: L.LatLngBounds): boolean {
    if (!bounds.isValid()) return true
    const sw = bounds.getSouthWest()
    const ne = bounds.getNorthEast()
    const latSpan = ne.lat - sw.lat
    let lngSpan = Math.abs(ne.lng - sw.lng)
    if (lngSpan > 180) lngSpan = 360 - lngSpan
    return latSpan > MAP_FIT_MAX_LAT_SPAN || lngSpan > MAP_FIT_MAX_LNG_SPAN
}

/** 将地图视野恢复到当前筛选结果中的全部站点。 */
function fitMapToAllSites(map: L.Map, sites: Site[]): void {
    if (sites.length === 0) return

    const bounds = L.latLngBounds(sites.map((site) => site.center))
    if (sites.length === 1) {
        map.flyTo(bounds.getCenter(), MAP_FIT_SINGLE_SITE_ZOOM, { duration: 0.8 })
        return
    }

    map.fitBounds(bounds, {
        padding: [50, 50],
        maxZoom: MAP_FIT_ALL_MAX_ZOOM,
        animate: true,
        duration: 0.8,
    })
}

// ----- 自动 FitBounds 组件（会覆盖 MapContainer 的初始 zoom，故多站点逻辑需在此体现） -----
function FitBoundsHelper({
    sites,
    apiCenter,
    projectKey,
}: {
    sites: Site[]
    apiCenter: [number, number] | null
    projectKey: string
}) {
    const map = useMap()
    const prevIdentityRef = useRef<string>("")

    useEffect(() => {
        const sortedIds = [...sites]
            .map((s) => s.id)
            .sort((a, b) => {
                const na = Number(a)
                const nb = Number(b)
                if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb
                return String(a).localeCompare(String(b))
            })
            .join(",")
        const identity = `${projectKey}:${sortedIds}`

        if (sites.length === 0) {
            prevIdentityRef.current = ""
            return
        }

        if (identity === prevIdentityRef.current) return
        prevIdentityRef.current = identity

        fitMapToAllSites(map, sites)
    }, [sites, map, apiCenter, projectKey])

    return null
}

function MapShowAllButton({
    sites,
    onResetSelection,
}: {
    sites: Site[]
    onResetSelection: () => void
}) {
    const map = useMap()

    return (
        <ESButton
            appearance="unstyled"
            type="button"
            className="timeline-show-all-btn map-show-all-btn"
            title="Fit the map to all visible sites"
            aria-label="Show all sites"
            onClick={() => {
                onResetSelection()
                fitMapToAllSites(map, sites)
            }}
        >
            <Maximize size={14} />
            Show All
        </ESButton>
    )
}


// ----- MapTab 主组件 -----
const EMPTY_FILTERS: FilterState = {
    realm_id: null,
    biome_id: null,
    functional_type_id: null,
}

export function MapTab() {
    const project = useProjectStore((s) => {
        if (!s.currentProjectId) return undefined
        return s.projects.find(p => p.id === s.currentProjectId)
    })
    const collection = useProjectStore((s) => {
        if (!s.currentCollectionId) return undefined
        return s.collectionOptions.find(c => c.id === s.currentCollectionId)
    })

    const [isFilterOpen, setIsFilterOpen] = useState(false)
    const [isRealmSelectOpen, setIsRealmSelectOpen] = useState(false)
    const [isBiomeSelectOpen, setIsBiomeSelectOpen] = useState(false)
    const [isGroupSelectOpen, setIsGroupSelectOpen] = useState(false)

    const closeAllFilterDropdowns = () => {
        setIsRealmSelectOpen(false)
        setIsBiomeSelectOpen(false)
        setIsGroupSelectOpen(false)
    }
    const [filterState, setFilterState] = useState<FilterState>(EMPTY_FILTERS)
    const [mediaTypeFilter, setMediaTypeFilter] = useState<MediaTypeFilter>("all")
    const [selectedSite, setSelectedSite] = useState<Site | null>(null)
    const [lastSelectedSite, setLastSelectedSite] = useState<Site | null>(null)
    const [selectionZoom, setSelectionZoom] = useState<number | null>(null)
    const lastMapSelectionTimeRef = useRef(0)

    useEffect(() => {
        if (selectedSite) {
            setLastSelectedSite(selectedSite)
        }
    }, [selectedSite])

    const [mapMarkersRaw, setMapMarkersRaw] = useState<SiteMapMarker[]>([])
    const [mapCenterFromApi, setMapCenterFromApi] = useState<[number, number] | null>(null)
    const [mapDataReady, setMapDataReady] = useState(false)
    const geometryLoadedSiteIdsRef = useRef<Set<number>>(new Set())
    const geometryLoadingSiteIdsRef = useRef<Set<number>>(new Set())
    const [iucnTree, setIucnTree] = useState<IucnOption[]>([])

    const projectIdNum = project?.id != null ? Number(project.id) : NaN
    const collectionIdNum = useMemo(() => {
        if (!collection || collection.id === "" || collection.id === "all") return undefined
        const parsed = Number(collection.id)
        return Number.isNaN(parsed) ? undefined : parsed
    }, [collection])

    const iucnOptions = useMemo(() => {
        const realms: IdName[] = iucnTree.map((r) => ({ id: r.id, name: r.name }))
        const selectedRealm = iucnTree.find((r) => r.id === filterState.realm_id)
        const biomes: IdName[] = selectedRealm
            ? selectedRealm.children.map((b) => ({ id: b.id, name: b.name }))
            : []
        const selectedBiome = selectedRealm?.children.find((b) => b.id === filterState.biome_id)
        const functionalTypes: IdName[] = selectedBiome
            ? selectedBiome.children.map((ft) => ({ id: ft.id, name: ft.name }))
            : []
        return { realms, biomes, functionalTypes }
    }, [iucnTree, filterState.realm_id, filterState.biome_id])

    const iucnLookups = useMemo(() => {
        const realmById = new Map<number, string>()
        const biomeById = new Map<number, string>()
        const functionalTypeById = new Map<number, string>()
        for (const realm of iucnTree) {
            realmById.set(realm.id, realm.name)
            for (const biome of realm.children ?? []) {
                biomeById.set(biome.id, biome.name)
                for (const ft of biome.children ?? []) {
                    functionalTypeById.set(ft.id, ft.name)
                }
            }
        }
        return { realmById, biomeById, functionalTypeById }
    }, [iucnTree])

    useEffect(() => {
        if (!project || Number.isNaN(projectIdNum)) {
            setIucnTree([])
            return
        }
        let cancelled = false
        ;(async () => {
            try {
                const res = await sitesApi.getIucnOptions({
                    project_id: projectIdNum,
                    collection_id: collectionIdNum,
                })
                if (cancelled) return
                if (res.code === 0 || res.code === 200) {
                    setIucnTree(res.data?.realms ?? [])
                }
            } catch (e) {
                console.error("Failed to fetch IUCN options:", e)
                if (!cancelled) setIucnTree([])
            }
        })()
        return () => {
            cancelled = true
        }
    }, [project, projectIdNum, collectionIdNum])

    useEffect(() => {
        if (filterState.realm_id != null && !iucnOptions.realms.some(({ id }) => id === filterState.realm_id)) {
            setFilterState(EMPTY_FILTERS)
        } else if (filterState.biome_id != null && !iucnOptions.biomes.some(({ id }) => id === filterState.biome_id)) {
            setFilterState((prev) => ({ ...prev, biome_id: null, functional_type_id: null }))
        } else if (filterState.functional_type_id != null
            && !iucnOptions.functionalTypes.some(({ id }) => id === filterState.functional_type_id)) {
            setFilterState((prev) => ({ ...prev, functional_type_id: null }))
        }
    }, [filterState, iucnOptions])

    useEffect(() => {
        if (!project || Number.isNaN(projectIdNum)) {
            setMapDataReady(false)
            return
        }
        let cancelled = false
        setMapDataReady(false)
            ; (async () => {
                try {
                    const res = await sitesApi.getMap({
                        project_id: projectIdNum,
                        collection_id: collectionIdNum,
                        media_type: mediaTypeFilterParam(mediaTypeFilter),
                        realm_id: filterState.realm_id ?? undefined,
                        biome_id: filterState.biome_id ?? undefined,
                        functional_type_id: filterState.functional_type_id ?? undefined,
                    }, true)
                    if (cancelled) return
                    if (res.code !== 0 && res.code !== 200) {
                        console.error("Map sites API returned error:", res.message)
                        return
                    }
                    const data = res.data
                    if (!data) return
                    setMapMarkersRaw(data.markers ?? [])
                    geometryLoadedSiteIdsRef.current = new Set()
                    geometryLoadingSiteIdsRef.current = new Set()
                    // data.center：接口返回的地图中心点 [lat, lng]，用于默认视角（与单个 marker 坐标无关）
                    setMapCenterFromApi(parseSiteMapCenter(data.center))
                } catch (e) {
                    console.error("Failed to fetch map sites:", e)
                } finally {
                    if (!cancelled) setMapDataReady(true)
                }
            })()
        return () => {
            cancelled = true
        }
    }, [projectIdNum, collectionIdNum, mediaTypeFilter, filterState.realm_id, filterState.biome_id, filterState.functional_type_id])

    const filteredSites = useMemo(
        () => mapMarkersRaw.map((marker) => mapMarkerToSite(marker, iucnLookups)),
        [mapMarkersRaw, iucnLookups],
    )

    useEffect(() => {
        if (!selectedSite) return
        if (!filteredSites.some((s) => s.id === selectedSite.id)) {
            setSelectedSite(null)
        }
    }, [filteredSites, selectedSite])

    useEffect(() => {
        if (!selectedSite || Number.isNaN(projectIdNum)) return
        const siteId = Number(selectedSite.id)
        if (Number.isNaN(siteId)) return
        if (geometryLoadedSiteIdsRef.current.has(siteId)) return
        if (geometryLoadingSiteIdsRef.current.has(siteId)) return

        let cancelled = false
        geometryLoadingSiteIdsRef.current.add(siteId)
            ; (async () => {
                try {
                    const res = await sitesApi.getMapGeometries(
                        {
                            project_id: projectIdNum,
                            site_ids: [siteId],
                            collection_id: collectionIdNum,
                        },
                        true,
                    )
                    if (cancelled) return
                    if (res.code !== 0 && res.code !== 200) {
                        console.error("Map geometries API returned error:", res.message)
                        return
                    }
                    const geometryItem = res.data?.items?.find((item) => item.site_id === siteId)
                    if (!geometryItem?.geometry) return
                    setMapMarkersRaw((prev) =>
                        prev.map((marker) =>
                            marker.site_id === siteId
                                ? {
                                    ...marker,
                                    geometry: {
                                        point: (geometryItem.geometry as any)?.point ?? marker.geometry?.point ?? null,
                                        location: (geometryItem.geometry as any)?.location ?? null,
                                        location_iho: (geometryItem.geometry as any)?.location_iho ?? null,
                                    },
                                }
                                : marker,
                        ),
                    )
                    geometryLoadedSiteIdsRef.current.add(siteId)
                } catch (e) {
                    console.error("Failed to fetch map geometries:", e)
                } finally {
                    geometryLoadingSiteIdsRef.current.delete(siteId)
                }
            })()

        return () => {
            cancelled = true
            geometryLoadingSiteIdsRef.current.delete(siteId)
        }
    }, [selectedSite, projectIdNum, collectionIdNum])

    useEffect(() => {
        if (!selectedSite) return
        const refreshed = filteredSites.find((site) => site.id === selectedSite.id)
        if (!refreshed) return
        const shouldRefreshSelected =
            refreshed.polygon.length !== selectedSite.polygon.length ||
            refreshed.ihoPolygons.length !== selectedSite.ihoPolygons.length
        if (shouldRefreshSelected) {
            setSelectedSite(refreshed)
            setLastSelectedSite(refreshed)
        }
    }, [filteredSites, selectedSite])

    // 切换项目/collection时关闭侧边栏并重置筛选
    useEffect(() => {
        setSelectedSite(null)
        setLastSelectedSite(null)
        setSelectionZoom(null)
        setFilterState(EMPTY_FILTERS)
        setIsRealmSelectOpen(false)
        setIsBiomeSelectOpen(false)
        setIsGroupSelectOpen(false)
    }, [project?.id, collection?.id])

    const biomeSelectDisabled = filterState.realm_id == null || filterState.realm_id === 0
    const groupSelectDisabled = filterState.biome_id == null || filterState.biome_id === 0

    useEffect(() => {
        if (biomeSelectDisabled) setIsBiomeSelectOpen(false)
    }, [biomeSelectDisabled])

    useEffect(() => {
        if (groupSelectDisabled) setIsGroupSelectOpen(false)
    }, [groupSelectDisabled])

    if (!project) return null

    const mapCenter: [number, number] =
        mapCenterFromApi ??
        (filteredSites.length > 0 ? sitesCentroid(filteredSites) : DEFAULT_MAP_CENTER)

    const selectedRealmName = iucnOptions.realms.find((r) => r.id === filterState.realm_id)?.name
    const selectedBiomeName = iucnOptions.biomes.find((b) => b.id === filterState.biome_id)?.name
    const selectedGroupName = iucnOptions.functionalTypes.find((ft) => ft.id === filterState.functional_type_id)?.name

    return (
        <div className="map-layout">
            {/* Realm 过滤器 */}
            <div className={`map-filter-panel ${isFilterOpen ? "visible" : ""}`}>
                <div className="map-filter-panel-header">
                    <div className="map-filter-panel-title">
                        <SlidersHorizontal size={18} className="filter-icon-svg" />
                        Filters
                    </div>
                    <ESButton appearance="unstyled"
                        className="map-filter-close"
                        title="Close the map filters panel"
                        onClick={() => {
                            closeAllFilterDropdowns()
                            setIsFilterOpen(false)
                        }}
                    >
                        <ChevronsLeft size={16} />
                    </ESButton>
                </div>
                <div className="map-filter-panel-body">
                    <MediaTypeSegment
                        value={mediaTypeFilter}
                        onChange={setMediaTypeFilter}
                        className="map-media-type-segment"
                    />
                    <div className="filter-select-wrapper custom-dropdown-wrapper">
                        <ESButton appearance="unstyled"
                            type="button"
                            className={`filter-select-btn ${isRealmSelectOpen ? 'open' : ''}`}
                            title="Filter sites by ecological realm"
                            onClick={() => {
                                setIsBiomeSelectOpen(false)
                                setIsGroupSelectOpen(false)
                                setIsRealmSelectOpen((o) => !o)
                            }}
                        >
                            <span className="filter-select-value">
                                {filterState.realm_id != null && selectedRealmName ? (
                                    <>
                                        <span
                                            className="filter-dot"
                                            style={{
                                                background: filterState.realm_id === 0
                                                    ? "var(--border-color)"
                                                    : getRealmColor(selectedRealmName),
                                            }}
                                        />
                                        <span className="filter-select-label">{selectedRealmName}</span>
                                    </>
                                ) : filterState.realm_id != null ? (
                                    <span className="filter-select-label">Realm #{filterState.realm_id}</span>
                                ) : (
                                    <span className="filter-select-label">All Realms</span>
                                )}
                            </span>
                            <ChevronDown size={18} className="filter-select-btn-icon" />
                        </ESButton>

                        {isRealmSelectOpen && (
                            <>
                                <div className="dropdown-backdrop" onClick={() => setIsRealmSelectOpen(false)} />
                                <div className="filter-dropdown-menu">
                                    <CustomScrollArea maxHeight={280}>
                                        <ESButton appearance="unstyled"
                                            type="button"
                                            className={`filter-dropdown-item ${filterState.realm_id == null ? 'selected' : ''}`}
                                            onClick={() => {
                                                setFilterState((prev) => ({
                                                    ...prev,
                                                    realm_id: null,
                                                    biome_id: null,
                                                    functional_type_id: null,
                                                }))
                                                setIsRealmSelectOpen(false)
                                            }}
                                        >
                                            <span className="filter-dot" style={{ background: "var(--border-color)" }} />
                                            <span className="filter-dropdown-label">All Realms</span>
                                        </ESButton>
                                        {iucnOptions.realms.map((r) => (
                                            <ESButton appearance="unstyled"
                                                key={r.id}
                                                type="button"
                                                className={`filter-dropdown-item ${filterState.realm_id === r.id ? 'selected' : ''}`}
                                                onClick={() => {
                                                    setFilterState((prev) => ({
                                                        ...prev,
                                                        realm_id: r.id,
                                                        biome_id: null,
                                                        functional_type_id: null,
                                                    }))
                                                    setIsRealmSelectOpen(false)
                                                }}
                                            >
                                                <span
                                                    className="filter-dot"
                                                    style={{ background: r.id === 0 ? "var(--border-color)" : getRealmColor(r.name) }}
                                                />
                                                <span className="filter-dropdown-label">{r.name}</span>
                                            </ESButton>
                                        ))}
                                    </CustomScrollArea>
                                </div>
                            </>
                        )}
                    </div>
                    <div className="filter-select-wrapper custom-dropdown-wrapper">
                        <ESButton appearance="unstyled"
                            type="button"
                            disabled={biomeSelectDisabled}
                            className={`filter-select-btn ${isBiomeSelectOpen ? "open" : ""}`}
                            title={biomeSelectDisabled ? "Select a realm before filtering by biome" : "Filter sites by biome"}
                            onClick={() => {
                                if (biomeSelectDisabled) return
                                setIsRealmSelectOpen(false)
                                setIsGroupSelectOpen(false)
                                setIsBiomeSelectOpen((o) => !o)
                            }}
                        >
                            <span className="filter-select-value">
                                {biomeSelectDisabled ? (
                                    <span className="filter-select-placeholder">Select realm first</span>
                                ) : filterState.biome_id != null && selectedBiomeName ? (
                                    <>
                                        <span
                                            className="filter-dot"
                                            style={{ background: FILTER_DOT_LIST }}
                                        />
                                        <span className="filter-select-label">{selectedBiomeName}</span>
                                    </>
                                ) : filterState.biome_id != null ? (
                                    <span className="filter-select-label">Biome #{filterState.biome_id}</span>
                                ) : (
                                    <span className="filter-select-label">All Biomes</span>
                                )}
                            </span>
                            <ChevronDown size={18} className="filter-select-btn-icon" />
                        </ESButton>
                        {isBiomeSelectOpen && !biomeSelectDisabled && (
                            <>
                                <div className="dropdown-backdrop" onClick={() => setIsBiomeSelectOpen(false)} />
                                <div className="filter-dropdown-menu">
                                    <CustomScrollArea maxHeight={280}>
                                        <ESButton appearance="unstyled"
                                            type="button"
                                            className={`filter-dropdown-item ${filterState.biome_id == null ? "selected" : ""}`}
                                            onClick={() => {
                                                setFilterState((prev) => ({
                                                    ...prev,
                                                    biome_id: null,
                                                    functional_type_id: null,
                                                }))
                                                setIsBiomeSelectOpen(false)
                                            }}
                                        >
                                            <span className="filter-dot" style={{ background: "var(--border-color)" }} />
                                            <span className="filter-dropdown-label">All Biomes</span>
                                        </ESButton>
                                        {iucnOptions.biomes.map((b) => (
                                            <ESButton appearance="unstyled"
                                                key={b.id}
                                                type="button"
                                                className={`filter-dropdown-item ${filterState.biome_id === b.id ? "selected" : ""}`}
                                                onClick={() => {
                                                    setFilterState((prev) => ({
                                                        ...prev,
                                                        biome_id: b.id,
                                                        functional_type_id: null,
                                                    }))
                                                    setIsBiomeSelectOpen(false)
                                                }}
                                            >
                                                <span
                                                    className="filter-dot"
                                                    style={{ background: FILTER_DOT_LIST }}
                                                />
                                                <span className="filter-dropdown-label">{b.name}</span>
                                            </ESButton>
                                        ))}
                                    </CustomScrollArea>
                                </div>
                            </>
                        )}
                    </div>
                    <div className="filter-select-wrapper custom-dropdown-wrapper">
                        <ESButton appearance="unstyled"
                            type="button"
                            disabled={groupSelectDisabled}
                            className={`filter-select-btn ${isGroupSelectOpen ? "open" : ""}`}
                            title={groupSelectDisabled ? "Select a biome before filtering by group" : "Filter sites by functional group"}
                            onClick={() => {
                                if (groupSelectDisabled) return
                                setIsRealmSelectOpen(false)
                                setIsBiomeSelectOpen(false)
                                setIsGroupSelectOpen((o) => !o)
                            }}
                        >
                            <span className="filter-select-value">
                                {groupSelectDisabled ? (
                                    <span className="filter-select-placeholder">Select biome first</span>
                                ) : filterState.functional_type_id != null && selectedGroupName ? (
                                    <>
                                        <span
                                            className="filter-dot"
                                            style={{ background: FILTER_DOT_LIST }}
                                        />
                                        <span className="filter-select-label">{selectedGroupName}</span>
                                    </>
                                ) : filterState.functional_type_id != null ? (
                                    <span className="filter-select-label">Group #{filterState.functional_type_id}</span>
                                ) : (
                                    <span className="filter-select-label">All Groups</span>
                                )}
                            </span>
                            <ChevronDown size={18} className="filter-select-btn-icon" />
                        </ESButton>
                        {isGroupSelectOpen && !groupSelectDisabled && (
                            <>
                                <div className="dropdown-backdrop" onClick={() => setIsGroupSelectOpen(false)} />
                                <div className="filter-dropdown-menu">
                                    <CustomScrollArea maxHeight={280}>
                                        <ESButton appearance="unstyled"
                                            type="button"
                                            className={`filter-dropdown-item ${filterState.functional_type_id == null ? "selected" : ""}`}
                                            onClick={() => {
                                                setFilterState((prev) => ({ ...prev, functional_type_id: null }))
                                                setIsGroupSelectOpen(false)
                                            }}
                                        >
                                            <span className="filter-dot" style={{ background: "var(--border-color)" }} />
                                            <span className="filter-dropdown-label">All Groups</span>
                                        </ESButton>
                                        {iucnOptions.functionalTypes.map((ft) => (
                                            <ESButton appearance="unstyled"
                                                key={ft.id}
                                                type="button"
                                                className={`filter-dropdown-item ${filterState.functional_type_id === ft.id ? "selected" : ""}`}
                                                onClick={() => {
                                                    setFilterState((prev) => ({
                                                        ...prev,
                                                        functional_type_id: ft.id,
                                                    }))
                                                    setIsGroupSelectOpen(false)
                                                }}
                                            >
                                                <span
                                                    className="filter-dot"
                                                    style={{ background: FILTER_DOT_LIST }}
                                                />
                                                <span className="filter-dropdown-label">{ft.name}</span>
                                            </ESButton>
                                        ))}
                                    </CustomScrollArea>
                                </div>
                            </>
                        )}
                    </div>

                    <ESButton appearance="unstyled"
                        className="filter-reset-btn"
                        title="Clear all map filters and show every site"
                        onClick={() => {
                            closeAllFilterDropdowns()
                            setFilterState(EMPTY_FILTERS)
                        }}
                    >
                        <RotateCcw size={14} />
                        Reset
                    </ESButton>
                </div>
            </div>

            <div className={`map-filter-bar ${!isFilterOpen ? "visible" : ""}`}>
                {mapDataReady && filteredSites.length === 0 ? null : (
                    <ESButton appearance="unstyled"
                        className="map-filter-toggle"
                        title="Open map filters"
                        onClick={() => setIsFilterOpen(true)}
                    >
                        <SlidersHorizontal size={20} className="filter-icon-svg" />
                    </ESButton>
                )}
            </div>

            {/* Leaflet Map Container */}
            <div className="map-container-wrapper">
                {mapDataReady ? (
                    filteredSites.length === 0 ? (
                        <EmptyState className="ui-state--page media-state" title="No Data" />
                    ) : (
                    <MapContainer
                        key={String(project.id)}
                        center={mapCenter}
                        zoom={MAP_INITIAL_ZOOM}
                        zoomControl={false}
                        zoomAnimation={false}
                        markerZoomAnimation={false}
                        fadeAnimation={false}
                        style={{ width: "100%", height: "100%" }}
                    >
                        <TileLayer
                            url={cartoTileUrl("light_all")}
                            attribution={CARTO_ATTRIBUTION}
                        />
                        {!selectedSite && <MapShowAllButton
                            sites={filteredSites}
                            onResetSelection={() => {
                                setSelectedSite(null)
                                setSelectionZoom(null)
                                lastMapSelectionTimeRef.current = Date.now()
                            }}
                        />}
                        <FitBoundsHelper
                            sites={filteredSites}
                            apiCenter={mapCenterFromApi}
                            projectKey={String(project.id)}
                        />
                        <SiteRegionPolygons
                            sites={selectedSite ? filteredSites.filter(s => s.id === selectedSite.id) : filteredSites}
                            selectedSiteId={selectedSite?.id ?? null}
                            onSelectSite={(site) => {
                                setSelectedSite(site)
                            }}
                            onSelectionZoomChange={setSelectionZoom}
                        />
                        <SiteIhoPolygons site={selectedSite} />
                        <SiteSelectionPolygon site={selectedSite} />
                        <ClusteredSiteMarkers
                            sites={filteredSites}
                            selectedSite={selectedSite}
                            onSelectSite={setSelectedSite}
                            selectionZoom={selectionZoom}
                            onSelectionZoomChange={setSelectionZoom}
                            lastSelectionTimeRef={lastMapSelectionTimeRef}
                        />
                    </MapContainer>
                    )
                ) : (
                    <LoadingState label="Loading map..." variant="page" size="lg" className="map-loading-state" />
                )}
            </div>
            {/* 站点侧边栏 */}
            {(selectedSite || lastSelectedSite) && (
                <SiteSidebar
                    site={selectedSite || lastSelectedSite!}
                    visible={!!selectedSite}
                    onClose={() => setSelectedSite(null)}
                    mediaTypeFilter={mediaTypeFilter}
                />
            )}
        </div>
    )
}

// ----- SiteSidebar -----
function SiteSidebar({
    site,
    visible,
    onClose,
    mediaTypeFilter,
}: {
    site: Site
    visible: boolean
    onClose: () => void
    mediaTypeFilter: MediaTypeFilter
}) {
    const color = getRealmColor(site.realm)
    const currentProjectId = useProjectStore((s) => s.currentProjectId)
    const currentCollectionId = useProjectStore((s) => s.currentCollectionId)
    const [expanded, setExpanded] = useState(false)
    const [isTransitioning, setIsTransitioning] = useState(false)
    const [mediaRows, setMediaRows] = useState<any[]>([])
    const [mediaLoading, setMediaLoading] = useState(true)
    const [mediaPage, setMediaPage] = useState(1)
    const [mediaTotalPages, setMediaTotalPages] = useState(1)
    const [mediaLoadingMore, setMediaLoadingMore] = useState(false)
    const mediaLoadingMoreRef = useRef(false)

    useEffect(() => {
        const siteId = Number(site.id)
        if (!currentProjectId || Number.isNaN(siteId)) {
            setMediaRows([])
            setMediaLoading(false)
            setMediaPage(1)
            setMediaTotalPages(1)
            return
        }
        let cancelled = false
            ; (async () => {
                setMediaLoading(true)
                try {
                    const params: BrowseMediaParams & { site_id?: number } = {
                        project_id: Number(currentProjectId),
                        view_type: "gallery",
                        site_id: siteId,
                        page: 1,
                        page_size: 50,
                    }
                    if (currentCollectionId && currentCollectionId !== "all" && currentCollectionId !== "") {
                        params.collection_id = Number(currentCollectionId)
                    }
                    const mediaType = mediaTypeFilterParam(mediaTypeFilter)
                    if (mediaType) {
                        params.media_type = mediaType
                    }
                    const res = await mediaApi.browseMedia(params, true)
                    if (cancelled) return
                    if (res.code !== 0 && res.code !== 200) {
                        setMediaRows([])
                        return
                    }
                    setMediaRows(res.data ?? [])
                    const pInfo = (res as any).page_info
                    if (pInfo && typeof pInfo.total_pages === "number") {
                        setMediaTotalPages(Math.max(1, pInfo.total_pages))
                    } else {
                        setMediaTotalPages(1)
                    }
                    setMediaPage(1)
                } catch (e) {
                    console.error("Failed to load site media:", e)
                    if (!cancelled) setMediaRows([])
                } finally {
                    if (!cancelled) setMediaLoading(false)
                }
            })()
        return () => {
            cancelled = true
        }
    }, [site.id, currentProjectId, currentCollectionId, mediaTypeFilter])

    const loadMoreMedia = async () => {
        if (mediaLoadingMoreRef.current) return
        if (mediaLoading) return
        if (mediaPage >= mediaTotalPages) return
        const siteId = Number(site.id)
        if (!currentProjectId || Number.isNaN(siteId)) return

        mediaLoadingMoreRef.current = true
        setMediaLoadingMore(true)
        const nextPage = mediaPage + 1
        try {
            const params: BrowseMediaParams & { site_id?: number } = {
                project_id: Number(currentProjectId),
                view_type: "gallery",
                site_id: siteId,
                page: nextPage,
                page_size: 50,
            }
            if (currentCollectionId && currentCollectionId !== "all" && currentCollectionId !== "") {
                params.collection_id = Number(currentCollectionId)
            }
            const mediaType = mediaTypeFilterParam(mediaTypeFilter)
            if (mediaType) {
                params.media_type = mediaType
            }
            const res = await mediaApi.browseMedia(params, true)
            if (res.code !== 0 && res.code !== 200) return
            const next = res.data ?? []
            setMediaRows((prev) => [...prev, ...next])
            const pInfo = (res as any).page_info
            if (pInfo && typeof pInfo.total_pages === "number") {
                setMediaTotalPages(Math.max(1, pInfo.total_pages))
            }
            setMediaPage(nextPage)
        } catch (e) {
            console.error("Failed to load more site media:", e)
        } finally {
            mediaLoadingMoreRef.current = false
            setMediaLoadingMore(false)
        }
    }

    const handleMediaScroll = (e: React.UIEvent<HTMLDivElement>) => {
        const { scrollTop, scrollHeight, clientHeight } = e.currentTarget
        if (scrollHeight - scrollTop - clientHeight < 120) {
            loadMoreMedia()
        }
    }

    return (
        <div className={`site-sidebar-panel ${expanded ? "site-sidebar-panel--wide" : ""} ${visible ? "visible" : ""}`}>
            <div
                className="site-sidebar-hero"
                style={{ background: color }}
            >
                <div className="site-sidebar-hero-top">
                    <div className="site-sidebar-hero-text">
                        <div className="site-sidebar-hero-title">{site.name}</div>
                        {/* 海拔高度 > 0 才显示 */}
                        {site.topography_m > 0 && (
                            <div className="site-sidebar-hero-sub">
                                <Mountain size={24} strokeWidth={2.5} />
                                <span>{site.topography_m}m</span>
                            </div>
                        )}
                        {/* 水深 > 0 才显示 */}
                        {site.freshwater_depth_m != null && site.freshwater_depth_m > 0 && (
                            <div className="site-sidebar-hero-sub">
                                <Droplets size={24} strokeWidth={2.5} />
                                <span>{site.freshwater_depth_m}m</span>
                            </div>
                        )}
                    </div>
                    <div className="site-sidebar-hero-actions">
                        <ESButton appearance="unstyled"
                            type="button"
                            className="site-sidebar-icon-btn site-sidebar-icon-btn--on-hero"
                            aria-label={expanded ? "Narrow panel" : "Widen panel"}
                            title={expanded ? "Narrow the site details panel" : "Widen the site details panel"}
                            onClick={() => {
                                setIsTransitioning(true)
                                setExpanded((e) => !e)
                                setTimeout(() => setIsTransitioning(false), 300)
                            }}
                        >
                            {expanded ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
                        </ESButton>
                        <ESButton appearance="unstyled"
                            type="button"
                            className="site-sidebar-icon-btn site-sidebar-icon-btn--on-hero"
                            aria-label="Close"
                            title="Close site details"
                            onClick={onClose}
                        >
                            <X size={18} />
                        </ESButton>
                    </div>
                </div>
            </div>

            <div className="site-sidebar-body site-sidebar-body--detail">
                <div className="site-sidebar-fixed-info">
                    <div className="site-sidebar-info-block">
                        <div className="site-sidebar-info-row">
                            <span className="site-sidebar-info-label">Realm</span>
                            <span className="site-sidebar-info-value" style={{ color }}>{site.realm}</span>
                        </div>
                        <div className="site-sidebar-info-divider" />
                        <div className="site-sidebar-info-row">
                            <span className="site-sidebar-info-label">Biome</span>
                            <span className="site-sidebar-info-value">{site.biome}</span>
                        </div>
                        <div className="site-sidebar-info-divider" />
                        <div className="site-sidebar-info-row">
                            <span className="site-sidebar-info-label">Group</span>
                            <span className="site-sidebar-info-value">{site.functional_type}</span>
                        </div>
                    </div>
                </div>

                <CustomScrollArea
                    variant="fill"
                    className="site-sidebar-scroll-area site-sidebar-media-scroll-area"
                    onScroll={handleMediaScroll}
                >
                    <div className="site-sidebar-scroll-content">
                        <div className="site-sidebar-media-section">
                            {(isTransitioning || mediaLoading) ? (
                                <LoadingState label="Loading media..." variant="inline" className="site-sidebar-media-loading" />
                            ) : mediaRows.length === 0 ? (
                                <EmptyState className="ui-state--inline site-sidebar-media-empty" title="No media at this site" />
                            ) : (
                                <>
                                    <ul className="site-sidebar-media-list">
                                        {mediaRows.map((item) => (
                                            <li key={item.media_id ?? item.id} className="site-sidebar-media-list-item">
                                                <MediaGalleryCard
                                                    item={mediaRowToGalleryItem(item)}
                                                    detailTo={currentProjectId ? resolveMediaDetailTo(mediaRowToGalleryItem(item), currentProjectId) : undefined}
                                                    projectId={currentProjectId ? Number(currentProjectId) : null}
                                                    sphere={site.realm}
                                                />
                                            </li>
                                        ))}
                                    </ul>
                                    {mediaLoadingMore ? (
                                        <LoadingState
                                            label="Loading more..."
                                            variant="inline"
                                            size="sm"
                                            className="site-sidebar-media-empty"
                                        />
                                    ) : null}
                                </>
                            )}
                        </div>
                    </div>
                </CustomScrollArea>
            </div>
        </div>
    )
}
