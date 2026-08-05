import { Button as ESButton, Input as ESInput } from "@/components/ui"
/**
 * EditorModal - 富文本编辑弹窗
 *
 * 使用 TipTap（ProseMirror）替代 document.execCommand，工具栏功能更完整、可维护。
 */

import { useEffect, useMemo, useRef, useState, useCallback } from "react"
import { useEditor, EditorContent } from "@tiptap/react"
import { StarterKit } from "@tiptap/starter-kit"
import { Image } from "@tiptap/extension-image"
import { TextAlign } from "@tiptap/extension-text-align"
import { Placeholder } from "@tiptap/extension-placeholder"
import { TextStyle } from "@tiptap/extension-text-style"
import { Color } from "@tiptap/extension-color"
import { Highlight } from "@tiptap/extension-highlight"
import { message } from "@/components/ui"
import { Modal } from "./Modal"
import { CustomScrollArea } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { filesApi } from "../../../../api/endpoints/files"
import { normalizeRichTextImageSrc, parseRichText } from "@/utils/string"
import {
    Bold,
    Italic,
    Strikethrough,
    Underline,
    Code,
    Heading2,
    Heading3,
    Heading4,
    List,
    ListOrdered,
    IndentIncrease,
    Outdent,
    Quote,
    Minus,
    Link2,
    Link2Off,
    AlignLeft,
    AlignCenter,
    AlignRight,
    AlignJustify,
    Undo2,
    Redo2,
    Highlighter,
    Paintbrush,
    Braces,
    Image as ImageIcon,
    ImagePlus,
} from "lucide-react"

/** 关闭原生图片拖拽，否则 mousedown 被浏览器拖走，缩放把手无法拖动 */
const EditorImage = Image.extend({
    draggable: false,
})

interface EditorModalProps {
    open: boolean
    onClose: () => void
    title?: string
    initialContent?: string
    onSave: (html: string) => void
    /** 上传图片使用的 filesApi 目录（如 projects / collections） */
    imageUploadCategory?: string
}

const PRESET_COLORS = [
    "var(--text-main)",
    "var(--danger)",
    "var(--warning)",
    "var(--warning-strong)",
    "var(--success)",
    "var(--tone-ai-index-a)",
    "var(--link)",
    "var(--tone-ai-primary-a)",
]

export function EditorModal({
    open,
    onClose,
    title = "Edit Description",
    initialContent = "",
    onSave,
    imageUploadCategory = "projects",
}: EditorModalProps) {
    const imageFileRef = useRef<HTMLInputElement>(null)
    const [uploadingImage, setUploadingImage] = useState(false)

    const extensions = useMemo(
        () => [
            StarterKit.configure({
                heading: { levels: [2, 3, 4] },
                link: {
                    openOnClick: false,
                    autolink: true,
                    defaultProtocol: "https",
                    HTMLAttributes: {
                        rel: "noopener noreferrer",
                        target: "_blank",
                    },
                },
            }),
            TextStyle,
            Color,
            TextAlign.configure({
                types: ["heading", "paragraph"],
            }),
            Highlight.configure({
                multicolor: true,
            }),
            Placeholder.configure({
                placeholder: "Write something…",
            }),
            EditorImage.configure({
                inline: false,
                allowBase64: false,
                HTMLAttributes: {
                    class: "editor-content-image",
                },
                /** 选中图片后拖动四角/四边控制点调整大小，尺寸写入 width/height 属性 */
                resize: {
                    enabled: true,
                    directions: [
                        "top",
                        "bottom",
                        "left",
                        "right",
                        "top-left",
                        "top-right",
                        "bottom-left",
                        "bottom-right",
                    ],
                    minWidth: 64,
                    minHeight: 48,
                    alwaysPreserveAspectRatio: true,
                },
            }),
        ],
        []
    )

    const editor = useEditor(
        {
            extensions,
            content: "",
            editable: open,
            shouldRerenderOnTransaction: true,
            editorProps: {
                attributes: {
                    class: "editor-tiptap-content",
                    spellcheck: "false",
                },
            },
        },
        [extensions]
    )

    useEffect(() => {
        if (!editor) return
        editor.setEditable(!!open)
        if (open) {
            editor.commands.setContent(parseRichText(initialContent), { emitUpdate: false })
        }
    }, [editor, open, initialContent])

    const handleSave = () => {
        if (!editor) return
        const html = editor.getHTML()
        onSave(html)
        onClose()
    }

    const run = (fn: () => boolean) => {
        if (!editor) return
        fn()
    }

    const insertImageFromUpload = useCallback(
        async (file: File) => {
            if (!editor) return
            setUploadingImage(true)
            try {
                const res = await filesApi.uploadImage(imageUploadCategory, file)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Image upload failed")
                    return
                }
                const path = res.data.path
                const src = normalizeRichTextImageSrc(path)
                editor.chain().focus().setImage({ src, alt: file.name }).run()
            } catch (e: unknown) {
                const err = e as Error
                message.error(err?.message || "Image upload failed")
            } finally {
                setUploadingImage(false)
            }
        },
        [editor, imageUploadCategory]
    )

    const insertImageFromUrl = useCallback(() => {
        if (!editor) return
        const raw = window.prompt("Image URL (https:// or path starting with /)", "https://")
        if (raw == null) return
        const u = raw.trim()
        if (!u) return
        if (!/^https?:\/\//i.test(u) && !u.startsWith("/")) {
            message.error("Use an http(s) URL or a path starting with /")
            return
        }
        editor.chain().focus().setImage({ src: u, alt: "" }).run()
    }, [editor])

    if (!editor) {
        return (
            <Modal open={open} onClose={onClose} title={title} width="800px">
                <div className="editor-area" style={{ minHeight: 200, opacity: 0.6 }}>
                    <LoadingState label="Loading editor..." variant="page" size="lg" />
                </div>
            </Modal>
        )
    }

    return (
        <Modal
            open={open}
            onClose={onClose}
            title={title}
            width="800px"
            footer={
                <div className="app-modal-footer-actions">
                    <ESButton appearance="unstyled" type="button" className="app-modal-btn cancel" onClick={onClose}>
                        Cancel
                    </ESButton>
                    <ESButton appearance="unstyled" type="button" className="app-modal-btn primary" onClick={handleSave}>
                        Save
                    </ESButton>
                </div>
            }
        >
            <div className="editor-toolbar">
                <div className="editor-toolbar-row">
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("heading", { level: 2 }) ? "active" : ""}`}
                        title="Heading 2"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleHeading({ level: 2 }).run())}
                    >
                        <Heading2 size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("heading", { level: 3 }) ? "active" : ""}`}
                        title="Heading 3"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleHeading({ level: 3 }).run())}
                    >
                        <Heading3 size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("heading", { level: 4 }) ? "active" : ""}`}
                        title="Heading 4"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleHeading({ level: 4 }).run())}
                    >
                        <Heading4 size={15} />
                    </ESButton>
                    <div className="editor-sep" />
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("bold") ? "active" : ""}`}
                        title="Bold"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleBold().run())}
                    >
                        <Bold size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("italic") ? "active" : ""}`}
                        title="Italic"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleItalic().run())}
                    >
                        <Italic size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("underline") ? "active" : ""}`}
                        title="Underline"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleUnderline().run())}
                    >
                        <Underline size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("strike") ? "active" : ""}`}
                        title="Strikethrough"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleStrike().run())}
                    >
                        <Strikethrough size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("code") ? "active" : ""}`}
                        title="Inline code"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleCode().run())}
                    >
                        <Code size={15} />
                    </ESButton>
                    <div className="editor-sep" />
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("bulletList") ? "active" : ""}`}
                        title="Bullet list"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleBulletList().run())}
                    >
                        <List size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("orderedList") ? "active" : ""}`}
                        title="Numbered list"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleOrderedList().run())}
                    >
                        <ListOrdered size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="editor-btn"
                        title="Indent list"
                        disabled={!editor.can().sinkListItem("listItem")}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().sinkListItem("listItem").run())}
                    >
                        <IndentIncrease size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="editor-btn"
                        title="Outdent list"
                        disabled={!editor.can().liftListItem("listItem")}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().liftListItem("listItem").run())}
                    >
                        <Outdent size={15} />
                    </ESButton>
                    <div className="editor-sep" />
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("blockquote") ? "active" : ""}`}
                        title="Quote"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleBlockquote().run())}
                    >
                        <Quote size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("codeBlock") ? "active" : ""}`}
                        title="Code block"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().toggleCodeBlock().run())}
                    >
                        <Braces size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="editor-btn"
                        title="Horizontal rule"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().setHorizontalRule().run())}
                    >
                        <Minus size={15} />
                    </ESButton>
                    <div className="editor-sep" />
                    <ESInput appearance="unstyled"
                        ref={imageFileRef}
                        type="file"
                        accept="image/png,image/jpeg,image/jpg,image/gif,image/webp"
                        className="editor-image-file-input"
                        onChange={(e) => {
                            const f = e.target.files?.[0]
                            e.target.value = ""
                            if (f) void insertImageFromUpload(f)
                        }}
                    />
                    <ESButton appearance="unstyled"
                        type="button"
                        className="editor-btn"
                        title="Insert image (upload)"
                        disabled={uploadingImage}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => imageFileRef.current?.click()}
                    >
                        <ImageIcon size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="editor-btn"
                        title="Insert image from URL"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={insertImageFromUrl}
                    >
                        <ImagePlus size={15} />
                    </ESButton>
                    <div className="editor-sep" />
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("link") ? "active" : ""}`}
                        title="Link"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => {
                            const prev = editor.getAttributes("link").href as string | undefined
                            const url = window.prompt("Link URL", prev || "")
                            if (url === null) return
                            if (url.trim() === "") {
                                editor.chain().focus().extendMarkRange("link").unsetLink().run()
                            } else {
                                editor.chain().focus().extendMarkRange("link").setLink({ href: url.trim() }).run()
                            }
                        }}
                    >
                        <Link2 size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="editor-btn"
                        title="Remove link"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().unsetLink().run())}
                    >
                        <Link2Off size={15} />
                    </ESButton>
                    <div className="editor-sep" />
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive({ textAlign: "left" }) ? "active" : ""}`}
                        title="Align left"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().setTextAlign("left").run())}
                    >
                        <AlignLeft size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive({ textAlign: "center" }) ? "active" : ""}`}
                        title="Align center"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().setTextAlign("center").run())}
                    >
                        <AlignCenter size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive({ textAlign: "right" }) ? "active" : ""}`}
                        title="Align right"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().setTextAlign("right").run())}
                    >
                        <AlignRight size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive({ textAlign: "justify" }) ? "active" : ""}`}
                        title="Justify"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().setTextAlign("justify").run())}
                    >
                        <AlignJustify size={15} />
                    </ESButton>
                    <div className="editor-sep" />
                    <ESButton appearance="unstyled"
                        type="button"
                        className="editor-btn"
                        title="Undo"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().undo().run())}
                        disabled={!editor.can().undo()}
                    >
                        <Undo2 size={15} />
                    </ESButton>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="editor-btn"
                        title="Redo"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().redo().run())}
                        disabled={!editor.can().redo()}
                    >
                        <Redo2 size={15} />
                    </ESButton>
                </div>

                <div className="editor-toolbar-row editor-toolbar-row--secondary">
                    <span className="editor-toolbar-label" title="Text color">
                        <Paintbrush size={14} />
                    </span>
                    {PRESET_COLORS.map((c) => (
                        <ESButton appearance="unstyled"
                            key={c}
                            type="button"
                            className="editor-color-swatch"
                            style={{ backgroundColor: c }}
                            title={c}
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => run(() => editor.chain().focus().setColor(c).run())}
                        />
                    ))}
                    <ESButton appearance="unstyled"
                        type="button"
                        className="editor-btn editor-btn--text"
                        title="Clear text color"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => run(() => editor.chain().focus().unsetColor().run())}
                    >
                        Clear
                    </ESButton>
                    <div className="editor-sep" />
                    <ESButton appearance="unstyled"
                        type="button"
                        className={`editor-btn ${editor.isActive("highlight") ? "active" : ""}`}
                        title="Highlight"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() =>
                            run(() =>
                                editor
                                    .chain()
                                    .focus()
                                    .toggleHighlight({ color: "rgba(250, 204, 21, 0.45)" })
                                    .run()
                            )
                        }
                    >
                        <Highlighter size={15} />
                    </ESButton>
                </div>
            </div>

            <CustomScrollArea className="editor-area-container" maxHeight={400} bodyClassName="editor-area-body">
                <EditorContent editor={editor} />
            </CustomScrollArea>
        </Modal>
    )
}
