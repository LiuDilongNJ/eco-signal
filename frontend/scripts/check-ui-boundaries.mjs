import { execFileSync } from "node:child_process"
import { readdirSync, readFileSync } from "node:fs"
import path from "node:path"

const projectRoot = process.cwd()
const gitRoot = execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8" }).trim()
const gitPrefix = `${path.relative(gitRoot, projectRoot).split(path.sep).join("/")}/`.replace(/^\.\/$/, "")
const restrictedAntComponents = new Set([
    "Button", "Checkbox", "DatePicker", "Drawer", "Dropdown", "Empty", "Form", "Input",
    "InputNumber", "Menu", "Modal", "Pagination", "Popover", "Radio", "Select", "Skeleton",
    "Spin", "Switch", "Table", "Tooltip", "Upload",
])
const adapterFiles = new Set([
    "src/providers/AppProviders.tsx",
    "src/styles/antdTheme.ts",
    "src/features/project/hooks/useAntdBrandConfig.ts",
])
const runtimeRoots = ["src/components", "src/features", "src/store"]

function git(args) {
    return execFileSync("git", args, {
        cwd: gitRoot,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
    }).trim()
}

function hasWorkingChanges() {
    return Boolean(git(["status", "--porcelain", "--", `${gitPrefix}src`]))
}

function resolveBase() {
    if (process.env.UI_BOUNDARY_BASE) return process.env.UI_BOUNDARY_BASE
    if (hasWorkingChanges()) return "HEAD"
    try {
        git(["rev-parse", "HEAD^"])
        return "HEAD^"
    } catch {
        return "HEAD"
    }
}

function readBase(base, repoPath) {
    try {
        return git(["show", `${base}:${repoPath}`])
    } catch {
        return ""
    }
}

function importedAntComponents(source) {
    const names = new Map()
    const importPattern = /import\s+(?:type\s+)?\{([\s\S]*?)\}\s+from\s+["']antd["']/g
    for (const match of source.matchAll(importPattern)) {
        for (const part of (match[1] ?? "").split(",")) {
            const [original, local = original] = part.trim().split(/\s+as\s+/)
            if (original && restrictedAntComponents.has(original)) names.set(original, local)
        }
    }
    return names
}

function rawControlCounts(source) {
    const counts = new Map()
    for (const tag of ["button", "input", "textarea", "select", "label"]) {
        counts.set(tag, (source.match(new RegExp(`<${tag}\\b`, "g")) ?? []).length)
    }
    return counts
}

function walkRuntime(directory) {
    return readdirSync(path.join(projectRoot, directory), { withFileTypes: true }).flatMap((entry) => {
        const relative = `${directory}/${entry.name}`
        return entry.isDirectory() ? walkRuntime(relative) : [relative]
    })
}

const base = resolveBase()
const changed = new Set([
    ...git(["diff", "--name-only", base, "--", `${gitPrefix}src`]).split("\n"),
    ...git(["ls-files", "--others", "--exclude-standard", "--", `${gitPrefix}src`]).split("\n"),
].filter(Boolean))
const violations = []

const compatSource = readFileSync(path.join(projectRoot, "src/components/ui/AntCompat.ts"), "utf8")
const compatValueExport = compatSource.match(/export\s*\{([\s\S]*?)\}\s*from\s*["']antd["']/)?.[1] ?? ""
for (const part of compatValueExport.split(",")) {
    const component = part.trim().split(/\s+as\s+/)[0]
    if (restrictedAntComponents.has(component)) {
        violations.push(`src/components/ui/AntCompat.ts: audited ${component} must be exported by a semantic adapter`)
    }
}

const governedComponentCss = readFileSync(path.join(projectRoot, "src/styles/components.css"), "utf8")
const governedLiteralColors = governedComponentCss.match(/#[0-9a-f]{3,8}\b|rgba?\([^)]*\)/gi) ?? []
if (governedLiteralColors.length) {
    violations.push(`src/styles/components.css: use --es-* tokens instead of literal colors (${governedLiteralColors.join(", ")})`)
}

for (const localPath of runtimeRoots.flatMap(walkRuntime)) {
    if (!/\.tsx?$/.test(localPath) || /\.(test|spec)\.tsx?$/.test(localPath)) continue
    if (localPath.startsWith("src/components/ui/")) continue
    const source = readFileSync(path.join(projectRoot, localPath), "utf8")
    if (/from\s+["']antd["']/.test(source)) {
        violations.push(`${localPath}: imports Ant Design directly`)
    }
    if (/from\s+["']antd\//.test(source) || /from\s+["']@rc-component\//.test(source)) {
        violations.push(`${localPath}: imports Ant Design implementation internals directly`)
    }
    if (/from\s+["']@\/components\/ui\//.test(source)) {
        violations.push(`${localPath}: bypasses the @/components/ui public entry`)
    }
    for (const [tag, count] of rawControlCounts(source)) {
        if (count > 0) violations.push(`${localPath}: contains ${count} raw <${tag}> control(s)`)
    }
}

for (const repoPath of changed) {
    const localPath = gitPrefix && repoPath.startsWith(gitPrefix) ? repoPath.slice(gitPrefix.length) : repoPath
    if (!/\.tsx?$/.test(localPath) || localPath.startsWith("src/components/ui/")) continue
    let current = ""
    try {
        current = readFileSync(path.join(projectRoot, localPath), "utf8")
    } catch {
        continue
    }
    const previous = readBase(base, repoPath)

    if (!adapterFiles.has(localPath)) {
        const beforeImports = importedAntComponents(previous)
        const currentImports = importedAntComponents(current)
        for (const [component, localName] of currentImports) {
            if (!beforeImports.has(component)) {
                violations.push(`${localPath}: new direct Ant Design ${component} import`)
                continue
            }

            const beforeLocalName = beforeImports.get(component) ?? component
            const beforeUsage = (previous.match(new RegExp(`<${beforeLocalName}\\b`, "g")) ?? []).length
            const currentUsage = (current.match(new RegExp(`<${localName}\\b`, "g")) ?? []).length
            if (currentUsage > beforeUsage) {
                violations.push(`${localPath}: adds ${currentUsage - beforeUsage} direct Ant Design <${component}> usage(s)`)
            }
        }
    }

    const beforeControls = rawControlCounts(previous)
    for (const [tag, count] of rawControlCounts(current)) {
        if (count > (beforeControls.get(tag) ?? 0)) {
            violations.push(`${localPath}: adds ${count - (beforeControls.get(tag) ?? 0)} raw <${tag}> control(s)`)
        }
    }
}

if (violations.length) {
    console.error("UI boundary check failed. Use @/components/ui adapters:\n")
    for (const violation of violations) console.error(`- ${violation}`)
    process.exit(1)
}

console.log(`UI boundary check passed against ${base}.`)
