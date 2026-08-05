import { Input as ESInput } from "@/components/ui"
import { useRef, useState, type ChangeEvent } from "react"
import { message } from "@/components/ui"

import { ApiError } from "../../../api/client"
import { emptyCsvImportResult, type CsvImportResponse, type CsvImportResult } from "../../../api/csvImport"
import { CsvImportResultModal } from "../components/CsvImportResultModal"

export function useSettingsCsvImport(
    label: string,
    importCsv: (file: File) => Promise<CsvImportResponse>,
    onSuccess: () => void,
) {
    const inputRef = useRef<HTMLInputElement | null>(null)
    const [importing, setImporting] = useState(false)
    const [instructionsOpen, setInstructionsOpen] = useState(false)
    const [resultOpen, setResultOpen] = useState(false)
    const [result, setResult] = useState<CsvImportResult | null>(null)

    const showResult = (next: CsvImportResult) => {
        setResult(next)
        setResultOpen(true)
    }

    const handleImport = async (event: ChangeEvent<HTMLInputElement>) => {
        const input = event.currentTarget
        const file = input.files?.[0]
        if (!file || importing) return
        if (!file.name.toLowerCase().endsWith(".csv")) {
            message.error("Select a CSV file")
            input.value = ""
            return
        }
        setImporting(true)
        const hide = message.loading(`Importing ${label}...`, 0)
        try {
            const response = await importCsv(file)
            if (response.code !== 0) {
                message.error(response.message || "Import failed")
                showResult(emptyCsvImportResult(response.message || "Import failed"))
                return
            }
            const data = response.data ?? {
                total: 0,
                succeeded: 0,
                skipped: 0,
                failed: 0,
                committed: false,
                rows: [],
                global_errors: ["Import completed without a result payload"],
            }
            showResult(data)
            if (data.succeeded > 0) {
                message.success(`Imported ${data.succeeded} of ${data.total} row(s)`)
            } else {
                message.info(`Import completed: 0 rows written out of ${data.total} row(s)`)
            }
            onSuccess()
        } catch (error) {
            const errorMessage = error instanceof ApiError ? error.message : "Import failed"
            message.error(errorMessage)
            showResult(emptyCsvImportResult(errorMessage))
        } finally {
            hide()
            input.value = ""
            setImporting(false)
        }
    }

    return {
        importing,
        instructionsOpen,
        triggerImport: () => inputRef.current?.click(),
        showInstructions: () => setInstructionsOpen(true),
        hideInstructions: () => setInstructionsOpen(false),
        input: (
            <>
                <ESInput appearance="unstyled" ref={inputRef} type="file" accept=".csv,text/csv" hidden onChange={(event) => void handleImport(event)} />
                <CsvImportResultModal
                    open={resultOpen}
                    label={label}
                    result={result}
                    onClose={() => setResultOpen(false)}
                />
            </>
        ),
    }
}
