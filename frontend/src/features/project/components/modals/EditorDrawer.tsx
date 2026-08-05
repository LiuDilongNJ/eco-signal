import { Button as ESButton } from "@/components/ui"
import { useState, useRef, useEffect } from "react"
import { Button, Space, ConfigProvider, Tooltip, theme as antdTheme } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import {
    Bold,
    Italic,
    Underline,
    List,
    ListOrdered,
    Link2,
    Heading2,
    AlignLeft,
    AlignCenter,
} from "lucide-react"
import { useAppStore } from "@/store/useAppStore"
import { parseRichText } from "@/utils/string"
import "./styles/EditorDrawer.css"

interface EditorDrawerProps {
    open: boolean
    onClose: () => void
    title?: string
    initialContent?: string
    onSave: (html: string) => void
}

export function EditorDrawer({
    open,
    onClose,
    title = "Edit Description",
    initialContent = "",
    onSave,
}: EditorDrawerProps) {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const [content, setContent] = useState(initialContent)
    const editorRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (open) {
            const decoded = parseRichText(initialContent)
            setContent(decoded)
            // Ensure editor matches initial content when opened
            if (editorRef.current) {
                editorRef.current.innerHTML = decoded
            }
        }
    }, [open, initialContent])

    const exec = (cmd: string, value?: string) => {
        document.execCommand(cmd, false, value)
        editorRef.current?.focus()
    }

    const handleSave = () => {
        const html = editorRef.current?.innerHTML ?? content
        onSave(html)
        onClose()
    }

    const toolbarButtons = [
        { icon: Heading2, cmd: "formatBlock", val: "h2", title: "Heading" },
        { icon: Bold, cmd: "bold", title: "Bold" },
        { icon: Italic, cmd: "italic", title: "Italic" },
        { icon: Underline, cmd: "underline", title: "Underline" },
        { icon: null, cmd: "sep" },
        { icon: List, cmd: "insertUnorderedList", title: "Bullet List" },
        { icon: ListOrdered, cmd: "insertOrderedList", title: "Numbered List" },
        { icon: null, cmd: "sep" },
        { icon: AlignLeft, cmd: "justifyLeft", title: "Align Left" },
        { icon: AlignCenter, cmd: "justifyCenter", title: "Align Center" },
        { icon: null, cmd: "sep" },
        { icon: Link2, cmd: "link", title: "Insert Link" },
    ]

    return (
        <ConfigProvider
            theme={{
                algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
                token: {
                    colorPrimary: "var(--brand)",
                }
            }}
        >
            <FormDrawer
                closable={false}
                maskClosable={false}
                title={title}
                placement="right"
                open={open}
                onClose={onClose}
                extra={
                    <Space>
                        <Button onClick={onClose} size="middle">Cancel</Button>
                        <Button
                            type="primary"
                            onClick={handleSave}
                            size="middle"
                            style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
                        >
                            Save
                        </Button>
                    </Space>
                }
                styles={{
                    wrapper: {
                        width: 420,
                    },
                    header: {
                        background: "var(--bg-surface)",
                        borderBottom: `1px solid ${isDark ? "var(--border-color)" : "var(--border-light)"}`,
                        padding: "16px 24px",
                    },
                    body: {
                        background: "var(--bg-surface)",
                        padding: 0,
                        overflow: "hidden",
                    },
                    footer: {
                        background: "var(--bg-surface)",
                        borderTop: `1px solid ${isDark ? "var(--border-color)" : "var(--border-light)"}`,
                    },
                }}
            >
                <CustomScrollArea variant="fill">
                    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "20px" }}>
                        {/* Toolbar */}
                        <div className="editor-toolbar-container">
                            {toolbarButtons.map((btn, i) => {
                                if (btn.cmd === "sep") return <div key={i} className="editor-sep-item" />
                                const Icon = btn.icon!
                                return (
                                    <Tooltip key={i} title={btn.title} mouseEnterDelay={0.5}>
                                        <ESButton appearance="unstyled"
                                            className="editor-btn"
                                            onMouseDown={(e) => e.preventDefault()}
                                            onClick={() => {
                                                if (btn.cmd === "link") {
                                                    const url = prompt("Enter URL:")
                                                    if (url) exec("createLink", url)
                                                } else if (btn.val) {
                                                    exec(btn.cmd, btn.val)
                                                } else {
                                                    exec(btn.cmd)
                                                }
                                            }}
                                        >
                                            <Icon size={18} />
                                        </ESButton>
                                    </Tooltip>
                                )
                            })}
                        </div>

                        {/* Editor Area */}
                        <div
                            ref={editorRef}
                            className={`editor-area ${isDark ? 'editor-area-dark' : 'editor-area-light'}`}
                            contentEditable
                            dangerouslySetInnerHTML={{ __html: parseRichText(initialContent) }}
                            onInput={() => setContent(editorRef.current?.innerHTML ?? "")}
                            spellCheck={false}
                        />
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
