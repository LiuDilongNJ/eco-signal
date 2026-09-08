export interface ProjectCapabilities {
    edit: boolean
    delete: boolean
    link: boolean
}

export interface CollectionCapabilities {
    edit: boolean
    delete: boolean
    set_taxons: boolean
    export_bundle: boolean
}

export interface MediaCapabilities {
    edit: boolean
    delete: boolean
    link: boolean
    assign: boolean
    run_analysis: boolean
    run_ai_models: boolean
    create_annotation: boolean
}

export interface SiteCapabilities {
    edit: boolean
    delete: boolean
    link: boolean
}

export interface AnnotationCapabilities {
    edit: boolean
    delete: boolean
    assign: boolean
    create_review: boolean
}

export interface ReviewCapabilities {
    edit: boolean
    delete: boolean
}

export interface TaskCapabilities { delete: boolean }
export interface IndexLogCapabilities { delete: boolean }
export interface QueueCapabilities { delete: boolean }

export interface UserCapabilities {
    edit: boolean
    delete: boolean
    reset_password: boolean
    manage_permissions: boolean
    set_contributor: boolean
}

export type CapabilityName =
    | keyof ProjectCapabilities
    | keyof CollectionCapabilities
    | keyof MediaCapabilities
    | keyof SiteCapabilities
    | keyof AnnotationCapabilities
    | keyof ReviewCapabilities
    | keyof TaskCapabilities
    | keyof IndexLogCapabilities
    | keyof QueueCapabilities
    | keyof UserCapabilities

export type CapabilityValues = Partial<Record<CapabilityName, boolean>>
