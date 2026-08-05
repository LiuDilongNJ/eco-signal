/**
 * Project 模块类型定义
 */

/** 贡献者 */
export interface Contributor {
  user_id?: number
  name: string
  role?: string | null
  email?: string | null
  orcid?: string | null
  /** 接口返回的贡献角色（优先展示） */
  contribution_role?: string | null
  avatar?: string
}

/** Collection */
export interface Collection {
  id: number
  name: string
  /** 当前用户是否可管理（选项接口） */
  can_manage?: boolean
  creator: string
  date: string
  description: string
  image: string
  stats: CollectionStats
  contributors: Contributor[]
  taxons?: TaxonEntry[]
}

/** Collection 统计 */
export interface CollectionStats {
  audios: string | number
  annotations: number
  sites: number
}

/** 项目统计 */
export interface ProjectStats {
  users: number
  collections_or_projects: number
  audios: string | number
  photos: string | number
  annotations: number
  sites: number
}

/** 项目 */
export interface Project {
  id: number
  name: string
  /** 当前用户是否可管理该项目（选项接口） */
  can_manage?: boolean
  creator: string
  date: string
  doi: string
  externalUrl: string
  description: string
  image: string
  collections: Collection[]
  stats: ProjectStats
  contributors: Contributor[]
}

/** 站点 */
export interface Site {
  id: string
  name: string
  lat: number
  lng: number
  realm: string
  biome: string
  functionalType: string
  collectionId: number
  collectionName: string
  media: SiteMedia[]
  color: string
}

/** 站点媒体 */
export interface SiteMedia {
  filename: string
  src: string
}

/** 媒体项 */
export interface MediaItem {
  id: string
  filename: string
  src: string
  type: "audio" | "image"
  size: string
  duration?: string
  date: string
  site: string
  collection: string
  collectionId: number
}

/** Taxon 条目 */
export interface TaxonEntry {
  id: string
  name: string
  rank: string
  notes?: string
}

/** DB Schema 列定义 */
export interface SchemaColumn {
  key: string
  label: string
  type: "text" | "number" | "boolean" | "select" | "textarea" | "file" | "richtext"
  readonly?: boolean
  readonlyOnUpdate?: boolean
  hiddenInForm?: boolean
  options?: string[] | { value: string; label: string }[]
  filterType?: "select" | "range"
  dependentKey?: string
  dependentOptions?: Record<string, string[]>
}

/** DB Schema 表定义 */
export interface SchemaTable {
  label: string
  icon: string
  pk: string
  columns: SchemaColumn[]
}

/** Tab 名称 */
export type TabName = "desc" | "summary" | "media" | "map" | "timeline" | "data"
