export interface CsvImportRowResult {
    row_number: number
    status: "succeeded" | "skipped" | "failed" | string
    field?: string | null
    reason?: string | null
}

export interface CsvImportResult {
    total: number
    succeeded: number
    skipped: number
    failed: number
    committed: boolean
    rows: CsvImportRowResult[]
    global_errors: string[]
}

export interface CsvImportResponse {
    code: number
    message: string
    data?: CsvImportResult | null
}

export function emptyCsvImportResult(reason: string): CsvImportResult {
    return {
        total: 0,
        succeeded: 0,
        skipped: 0,
        failed: 0,
        committed: false,
        rows: [],
        global_errors: [reason],
    }
}
