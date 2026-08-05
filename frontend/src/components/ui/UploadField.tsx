import { Upload, type UploadProps } from "antd"
import type { ReactNode } from "react"
import { cn } from "@/lib/utils"
import { Label } from "./FormField"

export interface UploadFieldProps extends UploadProps {
    label?: ReactNode
    help?: ReactNode
}

export function UploadField({ label, help, className, children, ...props }: UploadFieldProps) {
    return (
        <div className={cn("es-upload-field", className)}>
            {label ? <Label>{label}</Label> : null}
            <Upload {...props}>{children}</Upload>
            {help ? <div className="es-field-help">{help}</div> : null}
        </div>
    )
}

export function UploadQueue(props: UploadProps) {
    return <Upload className={cn("es-upload-queue", props.className)} listType="text" {...props} />
}
