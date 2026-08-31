/// <reference types="vite/client" />

interface ImportMetaEnv {
    readonly VITE_CARTO_BASEMAP_KEY?: string
}

interface ImportMeta {
    readonly env: ImportMetaEnv
}
