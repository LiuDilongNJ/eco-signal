import { forwardRef, type ForwardedRef, type InputHTMLAttributes, type LabelHTMLAttributes, type ReactElement, type ReactNode, type RefAttributes, type TextareaHTMLAttributes } from "react"
import {
    Checkbox as AntCheckbox,
    DatePicker as AntDatePicker,
    Form as AntForm,
    Input as AntInput,
    InputNumber as AntInputNumber,
    Radio as AntRadio,
    Switch as AntSwitch,
} from "antd"
import type { FormItemProps, InputProps as AntInputProps, InputRef } from "antd"
import { cn } from "@/lib/utils"

export type { FormInstance, RuleObject } from "antd/es/form"

export interface FormFieldProps extends Omit<FormItemProps, "help"> {
    help?: ReactNode
    error?: ReactNode
}

export function FormField({ className, help, error, validateStatus, ...props }: FormFieldProps) {
    return (
        <AntForm.Item
            className={cn("es-form-field", className)}
            help={error ?? help}
            validateStatus={error ? "error" : validateStatus}
            {...props}
        />
    )
}

export interface LabelProps extends LabelHTMLAttributes<HTMLLabelElement> {
    required?: boolean
}

export function Label({ children, required, className, ...props }: LabelProps) {
    return (
        <label className={cn("es-field-label", className)} {...props}>
            {children}
            {required ? <span className="es-field-label__required" aria-hidden="true">*</span> : null}
        </label>
    )
}

export function Help({ children }: { children: ReactNode }) {
    return <div className="es-field-help">{children}</div>
}

export function Error({ children }: { children: ReactNode }) {
    return <div className="es-field-error" role="alert">{children}</div>
}

type NativeInputProps = InputHTMLAttributes<HTMLInputElement> & { appearance: "unstyled" }
export type InputProps = AntInputProps

interface NativeInputComponent {
    (props: NativeInputProps & RefAttributes<HTMLInputElement>): ReactElement
}

function InputAdapter(
    props: AntInputProps | NativeInputProps,
    ref: ForwardedRef<InputRef | HTMLInputElement>,
) {
    if ("appearance" in props && props.appearance === "unstyled") {
        const { appearance: _appearance, className, ...nativeProps } = props
        void _appearance
        return (
            <input
                ref={ref as ForwardedRef<HTMLInputElement>}
                className={cn("es-input-unstyled", className)}
                {...nativeProps}
            />
        )
    }
    const { className, ...antProps } = props as AntInputProps
    return (
        <AntInput
            ref={ref as ForwardedRef<InputRef>}
            className={cn("es-input", className)}
            {...antProps}
        />
    )
}

type AntTextareaProps = React.ComponentProps<typeof AntInput.TextArea>
type NativeTextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { appearance: "unstyled" }
export type TextareaProps = AntTextareaProps

export function Textarea(props: AntTextareaProps): React.ReactElement
export function Textarea(props: NativeTextareaProps): React.ReactElement
export function Textarea(props: AntTextareaProps | NativeTextareaProps) {
    if ("appearance" in props && props.appearance === "unstyled") {
        const { appearance: _appearance, className, ...nativeProps } = props
        void _appearance
        return <textarea className={cn("es-textarea-unstyled", className)} {...nativeProps} />
    }
    const { className, ...textareaProps } = props as AntTextareaProps
    return <AntInput.TextArea className={cn("es-textarea", className)} {...textareaProps} />
}

function PasswordInput({ className, ...props }: React.ComponentProps<typeof AntInput.Password>) {
    return <AntInput.Password className={cn("es-input", "es-input-password", className)} {...props} />
}

function SearchInput({ className, ...props }: React.ComponentProps<typeof AntInput.Search>) {
    return <AntInput.Search className={cn("es-input", "es-input-search", className)} {...props} />
}

export const Input = Object.assign(forwardRef(InputAdapter), {
    Password: PasswordInput,
    Search: SearchInput,
    TextArea: Textarea,
}) as NativeInputComponent & typeof AntInput
function InputNumberAdapter({ className, ...props }: React.ComponentProps<typeof AntInputNumber>) {
    return <AntInputNumber className={cn("es-input-number", className)} {...props} />
}

function DatePickerAdapter({ className, ...props }: React.ComponentProps<typeof AntDatePicker>) {
    return <AntDatePicker className={cn("es-date-picker", className)} {...props} />
}

function RangePickerAdapter({ className, ...props }: React.ComponentProps<typeof AntDatePicker.RangePicker>) {
    return <AntDatePicker.RangePicker className={cn("es-date-picker", "es-date-range-picker", className)} {...props} />
}

export const InputNumber = InputNumberAdapter as typeof AntInputNumber
export const DatePicker = Object.assign(DatePickerAdapter, AntDatePicker, {
    RangePicker: RangePickerAdapter,
}) as typeof AntDatePicker

function CheckboxAdapter({ className, ...props }: React.ComponentProps<typeof AntCheckbox>) {
    return <AntCheckbox className={cn("es-checkbox", className)} {...props} />
}

function RadioAdapter({ className, ...props }: React.ComponentProps<typeof AntRadio>) {
    return <AntRadio className={cn("es-radio", className)} {...props} />
}

function SwitchAdapter({ className, ...props }: React.ComponentProps<typeof AntSwitch>) {
    return <AntSwitch className={cn("es-switch", className)} {...props} />
}

export const Checkbox = Object.assign(CheckboxAdapter, { Group: AntCheckbox.Group }) as typeof AntCheckbox
export const Radio = Object.assign(RadioAdapter, { Group: AntRadio.Group, Button: AntRadio.Button }) as typeof AntRadio
export const RadioGroup = AntRadio.Group
export const Switch = SwitchAdapter as typeof AntSwitch

function FormAdapter(props: React.ComponentProps<typeof AntForm>) {
    const { className, ...formProps } = props
    return <AntForm className={cn("es-form", className)} {...formProps} />
}

export const Form = Object.assign(FormAdapter, {
    Item: FormField,
    List: AntForm.List,
    ErrorList: AntForm.ErrorList,
    Provider: AntForm.Provider,
    useForm: AntForm.useForm,
    useFormInstance: AntForm.useFormInstance,
    useWatch: AntForm.useWatch,
}) as typeof AntForm

export const FormRoot = Form
