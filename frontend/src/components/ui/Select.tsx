import { Select as AntSelect, type SelectProps as AntSelectProps } from "antd"
import type { RefAttributes, SelectHTMLAttributes } from "react"
import { cn } from "@/lib/utils"

type NativeSelectProps = SelectHTMLAttributes<HTMLSelectElement> & { appearance: "unstyled" }
export type SelectProps<ValueType = unknown> = AntSelectProps<ValueType>

interface NativeSelectComponent {
    (props: NativeSelectProps & RefAttributes<HTMLSelectElement>): React.ReactElement
}

function SelectAdapter(props: AntSelectProps<unknown> | NativeSelectProps) {
    if ("appearance" in props && props.appearance === "unstyled") {
        const { appearance: _appearance, className, ...nativeProps } = props
        void _appearance
        return <select className={cn("es-select-unstyled", className)} {...nativeProps} translate="no" />
    }
    const { className, ...antProps } = props as AntSelectProps<unknown>
    // Ant Select forwards native DOM attributes, although its public props omit `translate`.
    const translationSafeProps = { ...antProps, translate: "no" } as AntSelectProps<unknown>
    return <AntSelect className={cn("es-select", className)} {...translationSafeProps} />
}

export const Select = Object.assign(SelectAdapter, {
    Option: AntSelect.Option,
    OptGroup: AntSelect.OptGroup,
}) as NativeSelectComponent & typeof AntSelect

export function Combobox<ValueType = unknown>({ className, ...props }: AntSelectProps<ValueType>) {
    const translationSafeProps = { ...props, translate: "no" } as AntSelectProps<ValueType>

    return (
        <AntSelect<ValueType>
            className={cn("es-combobox", className)}
            showSearch
            optionFilterProp="label"
            {...translationSafeProps}
        />
    )
}
