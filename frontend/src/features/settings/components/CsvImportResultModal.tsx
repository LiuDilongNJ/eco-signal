import { Button as ESButton } from "@/components/ui"
import { AlertTriangle, CheckCircle2, CircleX, Info, SkipForward } from "lucide-react"
import { Modal } from "../../project/components/modals/Modal"
import type { CsvImportResult, CsvImportRowResult } from "../../../api/csvImport"
import "./style/settings-forms.css"

interface CsvImportResultModalProps {
    open: boolean
    label: string
    result: CsvImportResult | null
    onClose: () => void
}

function statusLabel(status: CsvImportRowResult["status"]): string {
    if (status === "succeeded") return "Success"
    if (status === "skipped") return "Skipped"
    if (status === "failed") return "Failed"
    return status
}

function statusClass(status: CsvImportRowResult["status"]): string {
    if (status === "succeeded") return "csv-import-result__status csv-import-result__status--success"
    if (status === "skipped") return "csv-import-result__status csv-import-result__status--skipped"
    if (status === "failed") return "csv-import-result__status csv-import-result__status--failed"
    return "csv-import-result__status"
}

export function CsvImportResultModal({
    open,
    label,
    result,
    onClose,
}: CsvImportResultModalProps) {
    if (!result) return null

    const committedRows = result.succeeded
    const hasErrors = result.failed > 0 || result.global_errors.length > 0

    return (
        <Modal
            open={open}
            onClose={onClose}
            title={`${label} Import Result`}
            width="760px"
            footer={
                <div className="app-modal-footer-actions">
                    <ESButton appearance="unstyled" className="app-modal-btn primary" onClick={onClose}>
                        Close
                    </ESButton>
                </div>
            }
        >
            <div className="csv-import-result">
                <div className={`csv-import-result__outcome ${hasErrors ? "is-warning" : "is-success"}`}>
                    {hasErrors ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
                    <div>
                        <strong>
                            {committedRows > 0
                                ? `${committedRows} row(s) written successfully.`
                                : "0 rows were written."}
                        </strong>
                        {!result.committed && committedRows === 0 ? (
                            <span>No data was written.</span>
                        ) : null}
                    </div>
                </div>

                <div className="csv-import-result__summary" aria-label="Import summary">
                    <div><span>Total rows</span><strong>{result.total}</strong></div>
                    <div><span>Success</span><strong>{result.succeeded}</strong></div>
                    <div><span>Skipped</span><strong>{result.skipped}</strong></div>
                    <div><span>Failed</span><strong>{result.failed}</strong></div>
                </div>

                {result.global_errors.length > 0 ? (
                    <div className="csv-import-result__global-errors">
                        {result.global_errors.map((error, index) => (
                            <div key={`${index}-${error}`}>
                                <Info size={14} />
                                <span>{error}</span>
                            </div>
                        ))}
                    </div>
                ) : null}

                <div className="csv-import-result__rows-title">
                    <strong>Row details</strong>
                    <span>{result.rows.length} reported row(s)</span>
                </div>
                <div className="csv-import-result__rows">
                    {result.rows.length === 0 ? (
                        <div className="csv-import-result__empty">
                            <Info size={16} />
                            <span>No data rows were found in the file.</span>
                        </div>
                    ) : (
                        result.rows.map((row) => (
                            <div className="csv-import-result__row" key={row.row_number}>
                                <span className="csv-import-result__row-number">Row {row.row_number}</span>
                                <span className={statusClass(row.status)}>
                                    {row.status === "succeeded" ? <CheckCircle2 size={13} /> : null}
                                    {row.status === "skipped" ? <SkipForward size={13} /> : null}
                                    {row.status === "failed" ? <CircleX size={13} /> : null}
                                    {statusLabel(row.status)}
                                </span>
                                <span className="csv-import-result__field">{row.field || "—"}</span>
                                <span className="csv-import-result__reason">{row.reason || "—"}</span>
                            </div>
                        ))
                    )}
                </div>
            </div>
        </Modal>
    )
}
