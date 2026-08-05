import type { ReactNode } from "react"

export function renderRequiredLabel(label: ReactNode): ReactNode {
    return (
        <>
            {label}
            <span className="form-drawer-required-suffix" aria-hidden="true">*</span>
        </>
    )
}

export function renderRequiredMark(
    label: ReactNode,
    info: { required: boolean },
): ReactNode {
    return info.required ? renderRequiredLabel(label) : label
}
