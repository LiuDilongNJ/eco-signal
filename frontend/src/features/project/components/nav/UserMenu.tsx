import { Button as ESButton } from "@/components/ui"
/**
 * UserMenu - 用户头像 + 下拉菜单
 */

import { useState, useEffect } from "react"
import { User, Settings, LogOut, ChevronDown, LogIn, LayoutDashboard } from "lucide-react"
import { Link } from "react-router-dom"
import { DropdownMenu, LoginModal } from "@/components/ui"
import type { MenuProps } from "@/components/ui"
import { StableText } from "@/components/ui"
import { authUtils, logoutAndRedirectToIndex } from "@/utils/auth"
import { NAV_BAR_ICON_SIZE } from "./navBarIconSize"

export function UserMenu() {
    const [showLoginModal, setShowLoginModal] = useState(false)
    const [loggedInUser, setLoggedInUser] = useState<string | null>(null)

    useEffect(() => {
        // 同步当前登录状态
        const syncAuth = () => {
            const user = authUtils.getUser()
            setLoggedInUser(user ?? null)
        }
        syncAuth()

        // 监听全局登录/登出事件（LoginModal、登出按钮等任意入口触发）
        window.addEventListener("eco-auth-change", syncAuth)

        return () => {
            window.removeEventListener("eco-auth-change", syncAuth)
        }
    }, [])

    const handleLogout = () => {
        void logoutAndRedirectToIndex()
    }

    const menuItems: MenuProps["items"] = [
        { key: "dashboard", label: <Link className="dropdown-item" to="/dashboard"><LayoutDashboard size={18} /><StableText>Dashboard</StableText></Link> },
        { type: "divider" },
        { key: "settings", label: <Link className="dropdown-item" to="/settings"><Settings size={18} /><StableText>Settings</StableText></Link> },
        { type: "divider" },
        { key: "logout", label: <span className="dropdown-item"><LogOut size={18} /><StableText>Logout</StableText></span> },
    ]

    if (!loggedInUser) {
        return (
            <div className="user-wrapper">
                <ESButton appearance="unstyled"
                    type="button"
                    className="user-capsule-btn user-capsule-btn--nav-user"
                    onClick={() => setShowLoginModal(true)}
                >
                    <div className="user-avatar-icon">
                        <LogIn size={NAV_BAR_ICON_SIZE} />
                    </div>
                    <StableText className="user-name-text">Login</StableText>
                </ESButton>
                <LoginModal
                    isOpen={showLoginModal}
                    onClose={() => setShowLoginModal(false)}
                    onSuccess={(username) => setLoggedInUser(username)}
                />
            </div>
        )
    }

    return (
        <div className="user-wrapper">
            <DropdownMenu
                items={menuItems}
                placement="bottomRight"
                overlayClassName="user-dropdown-menu"
                onItemClick={({ key }) => {
                    if (key === "logout") handleLogout()
                }}
            >
            <ESButton appearance="unstyled"
                type="button"
                className="user-capsule-btn user-capsule-btn--nav-user"
            >
                <div className="user-avatar-icon">
                    <User size={NAV_BAR_ICON_SIZE} />
                </div>
                <StableText className="user-name-text">{loggedInUser || "Guest"}</StableText>
                <ChevronDown size={NAV_BAR_ICON_SIZE} className="chevron-icon" />
            </ESButton>
            </DropdownMenu>
        </div>
    )
}
