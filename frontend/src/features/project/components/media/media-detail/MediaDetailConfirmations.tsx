import { ConfirmDialog } from "../../modals/ConfirmDialog"

export interface ConfirmationContract {
    open: boolean
    onClose: () => void
    onConfirm: () => void | Promise<void>
}

export interface MediaDetailConfirmationsProps {
    selectedDeletion: ConfirmationContract & { count: number }
    annotationExport: ConfirmationContract & { count: number }
    editingDeletion: ConfirmationContract
}

export function MediaDetailConfirmations({
    selectedDeletion,
    annotationExport,
    editingDeletion,
}: MediaDetailConfirmationsProps) {
    return (
        <>
            <ConfirmDialog
                open={selectedDeletion.open}
                onClose={selectedDeletion.onClose}
                title="Delete Records"
                message={`Are you sure you want to delete ${selectedDeletion.count} selected record${selectedDeletion.count === 1 ? "" : "s"}? This action cannot be undone.`}
                confirmLabel="Delete"
                cancelLabel="Cancel"
                variant="danger"
                onConfirm={() => void selectedDeletion.onConfirm()}
            />
            <ConfirmDialog
                open={annotationExport.open}
                onClose={annotationExport.onClose}
                title="Export Records"
                message={`Records to export: ${annotationExport.count.toLocaleString()}. Continue?`}
                confirmLabel="Export"
                cancelLabel="Cancel"
                onConfirm={() => void annotationExport.onConfirm()}
            />
            <ConfirmDialog
                open={editingDeletion.open}
                onClose={editingDeletion.onClose}
                title="Delete Annotation"
                message="Are you sure you want to delete this annotation? This action cannot be undone."
                confirmLabel="Delete"
                cancelLabel="Cancel"
                variant="danger"
                onConfirm={() => void editingDeletion.onConfirm()}
            />
        </>
    )
}
