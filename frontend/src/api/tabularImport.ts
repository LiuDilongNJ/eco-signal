import { apiClient } from "./client"

export interface ImportRowResult {
    row_number: number
    status: "succeeded" | "skipped" | "failed" | string
    field?: string | null
    reason?: string | null
}

export interface ImportResult {
    source_format: "json" | "delimited_text" | string
    delimiter: string | null
    dry_run: boolean
    total: number
    succeeded: number
    skipped: number
    failed: number
    committed: boolean
    rows: ImportRowResult[]
    global_errors: string[]
}

export interface ImportResponse {
    code: number
    message: string
    data: ImportResult
}

export function emptyImportResult(reason: string): ImportResult {
    return {
        source_format: "delimited_text",
        delimiter: null,
        dry_run: true,
        total: 0,
        succeeded: 0,
        skipped: 0,
        failed: 0,
        committed: false,
        rows: [],
        global_errors: [reason],
    }
}

export async function submitTabularImport(
    endpoint: string,
    file: File,
    dryRun: boolean,
    fields: Record<string, string | number | boolean | null | undefined> = {},
): Promise<ImportResponse> {
    const body = new FormData()
    body.append("file", file)
    body.append("dry_run", String(dryRun))
    Object.entries(fields).forEach(([key, value]) => {
        if (value !== null && value !== undefined && String(value).trim() !== "") {
            body.append(key, String(value))
        }
    })
    return apiClient.post<ImportResponse>(endpoint, body)
}
