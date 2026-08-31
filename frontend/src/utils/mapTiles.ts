const CARTO_BASEMAP_KEY = import.meta.env.VITE_CARTO_BASEMAP_KEY?.trim()

export const CARTO_ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'

export function cartoTileUrl(style: string): string {
    const baseUrl = `https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png`
    return CARTO_BASEMAP_KEY
        ? `${baseUrl}?key=${encodeURIComponent(CARTO_BASEMAP_KEY)}`
        : baseUrl
}
