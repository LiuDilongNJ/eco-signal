import { Input as ESInput, message } from "@/components/ui"
import { ApiError } from "@/api/client"
import { emptyImportResult, type ImportResponse, type ImportResult } from "@/api/tabularImport"
import { CsvImportResultModal } from "@/features/settings/components/CsvImportResultModal"
import { useRef, useState, type ChangeEvent } from "react"

import { ImportInstructionsDrawer } from "./ImportInstructionsDrawer"
import type { ImportResourceConfig } from "./importConfigs"

type ImportSubmitResponse = Omit<ImportResponse, "data"> & { data?: ImportResult | null }

interface UseTabularImportOptions {
    label: string
    config: ImportResourceConfig
    submit: (file: File, dryRun: boolean) => Promise<ImportSubmitResponse>
    onCommitted: () => void
}

export function useTabularImport({ label, config, submit, onCommitted }: UseTabularImportOptions) {
    const inputRef = useRef<HTMLInputElement | null>(null)
    const [importing, setImporting] = useState(false)
    const [instructionsOpen, setInstructionsOpen] = useState(false)
    const [resultOpen, setResultOpen] = useState(false)
    const [result, setResult] = useState<ImportResult | null>(null)
    const [selectedFile, setSelectedFile] = useState<File | null>(null)

    const clearTransientState = () => {
        setSelectedFile(null)
        setResult(null)
        setResultOpen(false)
        if (inputRef.current) inputRef.current.value = ""
    }

    const showFailure = (reason: string) => {
        setResult(emptyImportResult(reason))
        setResultOpen(true)
    }

    const handleImport = async (event: ChangeEvent<HTMLInputElement>) => {
        const input = event.currentTarget
        const file = input.files?.[0]
        if (!file || importing) return
        if (!/\.(csv|txt|json)$/i.test(file.name)) {
            message.error("Select a CSV, TXT, or JSON file")
            input.value = ""
            return
        }

        setImporting(true)
        setSelectedFile(file)
        setResult(null)
        const hide = message.loading(`Validating ${label}...`, 0)
        try {
            const response = await submit(file, true)
            if (response.code !== 0 && response.code !== 200) {
                const reason = response.message || "Import validation failed"
                message.error(reason)
                showFailure(reason)
                return
            }
            const data = response.data ?? emptyImportResult("Import validation completed without a result payload")
            setResult(data)
            setResultOpen(true)
            if (data.failed > 0 || data.global_errors.length > 0) {
                message.warning("Validation completed with errors")
            }
        } catch (error) {
            const reason = error instanceof ApiError ? error.message : "Import validation failed"
            message.error(reason)
            showFailure(reason)
        } finally {
            hide()
            input.value = ""
            setImporting(false)
        }
    }

    const confirmImport = async () => {
        if (!selectedFile || !result || result.failed > 0 || result.global_errors.length > 0) return
        setImporting(true)
        const hide = message.loading(`Importing ${label}...`, 0)
        try {
            const response = await submit(selectedFile, false)
            const data = response.data ?? emptyImportResult(response.message || "Import failed")
            if (!data.committed || data.failed > 0 || data.global_errors.length > 0) {
                setResult(data)
                message.error(response.message || "Import was not committed")
                return
            }
            message.success(`Imported ${data.succeeded} of ${data.total} row(s)`)
            clearTransientState()
            onCommitted()
        } catch (error) {
            message.error(error instanceof ApiError ? error.message : "Import failed")
        } finally {
            hide()
            setImporting(false)
        }
    }

    return {
        importing,
        triggerImport: () => inputRef.current?.click(),
        showInstructions: () => setInstructionsOpen(true),
        controls: (
            <>
                <ESInput
                    appearance="unstyled"
                    ref={inputRef}
                    type="file"
                    accept=".csv,.txt,.json,text/csv,text/plain,application/json"
                    hidden
                    onChange={(event) => void handleImport(event)}
                />
                <CsvImportResultModal
                    open={resultOpen}
                    label={label}
                    result={result}
                    onClose={clearTransientState}
                    onConfirm={() => void confirmImport()}
                    confirming={importing}
                />
                <ImportInstructionsDrawer
                    config={config}
                    open={instructionsOpen}
                    onClose={() => setInstructionsOpen(false)}
                />
            </>
        ),
    }
}
