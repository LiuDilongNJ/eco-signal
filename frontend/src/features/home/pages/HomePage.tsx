import { Button as ESButton, EmptyState, Input as ESInput } from "@/components/ui"
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Swiper, SwiperSlide } from 'swiper/react';
import { Mousewheel, EffectFade } from 'swiper/modules';
import { MapContainer, TileLayer, Marker, useMap } from 'react-leaflet';
import L from 'leaflet';
import {
    Activity, Moon, Sun, Info, LogIn, User, ChevronDown, Settings, LogOut,
    Github, FileText, GraduationCap, Mail, Search, Link as LinkIcon, LayoutDashboard,
    Lock, Unlock, Users, FolderKanban, Library, Mic, Image as ImageIcon, ScanLine, MapPin,
    ChevronLeft, ChevronRight
} from 'lucide-react';

import 'swiper/css';
import 'swiper/css/thumbs';
import 'swiper/css/effect-fade';
import 'leaflet/dist/leaflet.css';
import '../styles/HomePage.css';
import { authUtils, logoutAndRedirectToIndex } from '@/utils/auth';
import { LoginModal } from '@/components/ui';
import type { NetworkNodePublic } from '@/api/endpoints/network';
import { NAV_BAR_ICON_SIZE } from '@/features/project/components/nav/navBarIconSize';
import { CustomScrollArea } from '@/components/ui';
import { useProjectStore } from '@/features/project/stores/useProjectStore';
import { useAppStore } from '@/store/useAppStore';
import {
    openCookiePreferences,
} from '../cookieConsent';

// --- Data ---
const HOME_PAGE_BG =
    'https://images.pexels.com/photos/733090/pexels-photo-733090.jpeg?auto=compress&cs=tinysrgb&w=1600';

/** 首页项目缩略图条：每次箭头横移的缩略图数量（窗口不足时与末尾对齐） */
const THUMB_PAGE = 10;
const THUMB_SLIDE_PX = 60;
const THUMB_SPACE_PX = 20;
const PAGE_NAV_ITEMS = [
    { id: 'home', label: 'Home' },
    { id: 'projects', label: 'Projects' },
    { id: 'network', label: 'Network' },
    { id: 'sponsors', label: 'Sponsors' },
    { id: 'footer', label: 'Footer' },
] as const;
const POWERED_BY_ITEMS = [
    {
        name: 'scikit-maad',
        image: '/images/powered-by/scikit-maad.png',
        href: 'https://scikit-maad.github.io/',
        className: 'powered-by-card--scikit-maad',
    },
    {
        name: 'Leaflet',
        image: '/images/powered-by/leaflet.png',
        href: 'https://leafletjs.com/',
        className: 'powered-by-card--leaflet',
    },
    {
        name: 'BirdNET-Analyzer',
        image: '/images/powered-by/birdnet.png',
        href: 'https://github.com/kahst/BirdNET-Analyzer',
        className: 'powered-by-card--birdnet',
    },
    {
        name: 'batdetect2',
        image: '/images/powered-by/batdetect2.png',
        href: 'https://github.com/macaodha/batdetect2',
        className: 'powered-by-card--batdetect2',
    },
    {
        name: 'RabbitMQ',
        image: '/images/powered-by/rabbitmq.svg',
        href: 'https://www.rabbitmq.com/',
        className: 'powered-by-card--rabbitmq',
    },
] as const;
type MapViewState = {
    center: [number, number];
    zoom: number;
};

function resolveProjectCardId(p: unknown): number | string | null {
    if (!p || typeof p !== 'object') return null;
    const raw = (p as { project_id?: unknown; id?: unknown }).project_id ?? (p as { id?: unknown }).id;
    if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
    if (typeof raw === 'string' && raw.trim() !== '') return raw.trim();
    return null;
}

function findProjectCardIndex(projects: unknown[], id: number | string | null): number {
    if (id == null || projects.length === 0) return -1;
    const idStr = String(id);
    return projects.findIndex((p) => {
        const pid = resolveProjectCardId(p);
        return pid != null && String(pid) === idStr;
    });
}

// Replicate 25 slides for projectSwiper / thumbsSwiper

// --- Custom Components ---

function MapUpdater({
    coords,
    allCoords,
    zoom,
    activePage,
    selectedNodeId,
    savedViewRef,
}: {
    coords: [number, number] | null;
    allCoords: [number, number][];
    zoom: number;
    activePage: number;
    selectedNodeId: number | null;
    savedViewRef: React.MutableRefObject<MapViewState | null>;
}) {
    const map = useMap();
    const prevPageRef = useRef<number | null>(null);
    const prevNodeRef = useRef<number | null>(null);
    const prevCoordsCountRef = useRef(0);

    useEffect(() => {
        if (activePage !== 2) {
            prevPageRef.current = activePage;
            prevCoordsCountRef.current = allCoords.length;
            return;
        }

        const enteringMapPage = prevPageRef.current !== 2;
        const firstMapEntry = prevPageRef.current === null;
        const coordsJustLoaded = prevCoordsCountRef.current === 0 && allCoords.length > 0;
        const nodeChanged =
            prevNodeRef.current !== null &&
            selectedNodeId !== null &&
            prevNodeRef.current !== selectedNodeId;
        const savedView = savedViewRef.current;
        const shouldFitAll =
            allCoords.length > 0 &&
            (firstMapEntry || coordsJustLoaded || (enteringMapPage && !savedView));
        const shouldRestoreSavedView = enteringMapPage && !firstMapEntry && !!savedView && !nodeChanged;
        const shouldFlyToMarker = Boolean(coords && nodeChanged && !shouldFitAll);

        const t = window.setTimeout(() => {
            map.invalidateSize();
            if (shouldFitAll) {
                const bounds = L.latLngBounds(allCoords);
                if (bounds.isValid()) {
                    map.fitBounds(bounds, {
                        padding: [48, 48],
                        maxZoom: 6,
                    });
                }
            } else if (shouldRestoreSavedView && savedView) {
                map.setView(savedView.center, savedView.zoom, { animate: false });
            } else if (shouldFlyToMarker && coords) {
                map.flyTo(coords, zoom, { duration: 1 });
            }
            prevPageRef.current = activePage;
            prevNodeRef.current = selectedNodeId;
            prevCoordsCountRef.current = allCoords.length;
        }, 100);

        return () => window.clearTimeout(t);
    }, [coords, allCoords, map, zoom, activePage, selectedNodeId, savedViewRef]);

    return null;
}

function MapViewPersistence({
    savedViewRef,
    mapPageActive,
}: {
    savedViewRef: React.MutableRefObject<MapViewState | null>;
    mapPageActive: boolean;
}) {
    const map = useMap();

    useEffect(() => {
        const persistView = () => {
            if (!mapPageActive) return;
            const center = map.getCenter();
            savedViewRef.current = {
                center: [center.lat, center.lng],
                zoom: map.getZoom(),
            };
        };

        map.on('moveend zoomend', persistView);
        return () => {
            map.off('moveend zoomend', persistView);
        };
    }, [map, savedViewRef, mapPageActive]);

    return null;
}

/**
 * Leaflet MapContainer freezes options after init; Shift+wheel is handled reliably via native
 * `{ passive:false, capture:true }` on the map pane so Swiper (outer ancestor) never sees the event.
 */
function MapShiftWheelZoom({ mapPageActive }: { mapPageActive: boolean }) {
    const map = useMap();
    useEffect(() => {
        const container = map.getContainer();
        const onWheelCapture = (e: WheelEvent) => {
            if (!mapPageActive || !e.shiftKey) return;
            if (e.ctrlKey || e.metaKey) return;

            const primary =
                Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
            if (primary === 0) return;

            e.preventDefault();
            e.stopPropagation();

            try {
                const cur = map.getZoom();
                const step = primary < 0 ? 1 : -1;
                const nextRaw = cur + step;
                const next = Math.max(map.getMinZoom(), Math.min(map.getMaxZoom(), nextRaw));
                if (next === cur) return;

                const pivot = map.mouseEventToLatLng(e as unknown as MouseEvent);
                map.setZoomAround(pivot, next);
            } catch {
                /* Leaflet may reject some synthetic wheel targets */
            }
        };
        container.addEventListener('wheel', onWheelCapture, { passive: false, capture: true });
        return () => container.removeEventListener('wheel', onWheelCapture, { capture: true });
    }, [map, mapPageActive]);
    return null;
}

const PremiumIcon = (name: string, isSelected: boolean, isLocal: boolean) => L.divIcon({
    className: `premium-marker ${isLocal ? 'premium-marker--local' : 'premium-marker--peer'}${isSelected ? ' marker-selected' : ''}`,
    html: `<div class="marker-label">${name}</div><div class="radar-ring"></div><div class="radar-ring"></div><div class="marker-core"></div>`,
    iconSize: [40, 40]
});

export default function HomePage() {
    const navigate = useNavigate();
    const selectProject = useProjectStore((s) => s.selectProject);
    const currentProjectId = useProjectStore((s) => s.currentProjectId);
    const mainSwiperRef = useRef<any>(null);
    const suppressProjectSlideSyncRef = useRef(false);
    const [activePage, setActivePage] = useState(0);
    const { effectiveTheme, toggleTheme } = useAppStore();

    // Modal / User State
    const [showLogin, setShowLogin] = useState(false);
    /** 首屏同步读 localStorage，避免已登录时先闪「Login」再变成用户名 */
    const [loggedInUser, setLoggedInUser] = useState<string | null>(() => {
        try {
            const token = authUtils.getToken()
            const user = authUtils.getUser()
            return token && user ? user : null
        } catch {
            return null
        }
    });
    const [showUserMenu, setShowUserMenu] = useState(false);

    // Cookie Banner

    // Projects State
    const [thumbsSwiper, setThumbsSwiper] = useState<any>(null);
    const projectSwiperRef = useRef<any>(null);
    const projectChangeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    /** 当前缩略图窗口起始下标（0-based），窗口长度最多 THUMB_PAGE */
    const [thumbPageStart, setThumbPageStart] = useState(0);
    const [currentProjectIdx, setCurrentProjectIdx] = useState(0);
    const [fadingProjectInfo, setFadingProjectInfo] = useState(false);
    const [searchQuery, setSearchQuery] = useState("");
    const [isSearchFocused, setIsSearchFocused] = useState(false);

    // Map State
    const [networkNodes, setNetworkNodes] = useState<NetworkNodePublic[]>([]);
    const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
    const [mapBootstrapReady, setMapBootstrapReady] = useState(false);
    const [statsActive, setStatsActive] = useState(false);
    const savedMapViewRef = useRef<MapViewState | null>(null);

    // Dynamic project data state
    const [projectData, setProjectData] = useState<any[]>([]);
    const [slideBgImages, setSlideBgImages] = useState<string[]>([]);

    const projectDescFingerprint = useMemo(() => {
        const p = projectData[currentProjectIdx] || projectData[0];
        if (!p) return "";
        return `${String(p.description_short ?? "")}|${String(p.description ?? "")}|${String(p.desc ?? "")}`;
    }, [projectData, currentProjectIdx]);

    const mapContainerRef = useRef<HTMLDivElement>(null);
    const searchContainerRef = useRef<HTMLDivElement>(null);

    // --- Effects ---

    /** 去掉首页文档根（html/body）外侧滚动条；Swiper 与内部区域仍可滚动 */
    useEffect(() => {
        const html = document.documentElement
        const body = document.body
        html.classList.add("home-route")
        body.classList.add("home-route")
        return () => {
            html.classList.remove("home-route")
            body.classList.remove("home-route")
        }
    }, [])

    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (searchContainerRef.current && !searchContainerRef.current.contains(e.target as Node)) {
                setIsSearchFocused(false);
            }
        };
        document.addEventListener('click', handleClickOutside);
        return () => document.removeEventListener('click', handleClickOutside);
    }, []);

    useEffect(() => {
        if (activePage === 2) {
            const timer = setTimeout(() => {
                setStatsActive(true);
            }, 100);
            return () => clearTimeout(timer);
        } else {
            setStatsActive(false);
        }
    }, [activePage]);

    useEffect(() => {
        const loadCards = async () => {
            try {
                const { projectsApi } = await import('../../../api/endpoints/projects');
                const res = await projectsApi.getProjectCards();
                if ((res.code === 0 || res.code === 200) && res.data && res.data.length > 0) {
                    setProjectData(res.data);
                    // generate slideBgImages based on the fetched data length
                    const imgs = res.data.map((p: any) => {
                        return p.image_url || p.cover_url || p.picture_url || HOME_PAGE_BG;
                    }) as string[];
                    setSlideBgImages(imgs);
                } else {
                    setProjectData([]);
                    setSlideBgImages([]);
                }
            } catch (err) {
                console.error("Failed to fetch project cards API:", err);
                setProjectData([]);
                setSlideBgImages([]);
            }
        };
        loadCards();
    }, []);

    /** 从 Dashboard 返回首页时，恢复当前选中的项目卡片 */
    useEffect(() => {
        if (projectData.length === 0 || currentProjectId == null) return;
        const idx = findProjectCardIndex(projectData, currentProjectId);
        if (idx < 0) return;

        const n = projectData.length;
        const maxStart = Math.max(0, n - THUMB_PAGE);
        const ideal = Math.min(maxStart, Math.floor(idx / THUMB_PAGE) * THUMB_PAGE);
        setThumbPageStart(ideal);
        setCurrentProjectIdx(idx);

        const swiper = projectSwiperRef.current;
        if (swiper && !swiper.destroyed && swiper.activeIndex !== idx) {
            suppressProjectSlideSyncRef.current = true;
            swiper.slideTo(idx, 0);
            window.requestAnimationFrame(() => {
                suppressProjectSlideSyncRef.current = false;
            });
        }
    }, [projectData, currentProjectId]);

    useEffect(() => {
        return () => {
            if (projectChangeTimerRef.current) {
                clearTimeout(projectChangeTimerRef.current);
            }
        };
    }, []);

    useEffect(() => {
        const loadNetworkMap = async () => {
            try {
                const { networkApi } = await import('../../../api/endpoints/network');
                const nodesResult = await networkApi.getNodes();

                if ((nodesResult.code === 0 || nodesResult.code === 200) && Array.isArray(nodesResult.data) && nodesResult.data.length > 0) {
                    setNetworkNodes(nodesResult.data);
                    const local = nodesResult.data.find((n) => n.is_local);
                    // id 可能为 0（本地节点）；用 ?? 而非 ||，避免把 0 当成缺省
                    setSelectedNodeId(local != null ? local.id : nodesResult.data[0]!.id);
                } else {
                    setNetworkNodes([]);
                    setSelectedNodeId(null);
                }
            } catch (err) {
                console.error("Failed to load network map data:", err);
                setNetworkNodes([]);
                setSelectedNodeId(null);
            } finally {
                setMapBootstrapReady(true);
            }
        };
        loadNetworkMap();
    }, []);

    const thumbCount = slideBgImages.length;
    const maxThumbStart = Math.max(0, thumbCount - THUMB_PAGE);
    const thumbVisible =
        thumbCount === 0 ? 0 : Math.min(THUMB_PAGE, thumbCount);
    const thumbTrackPx =
        thumbVisible > 0
            ? thumbVisible * THUMB_SLIDE_PX + (thumbVisible - 1) * THUMB_SPACE_PX
            : 0;

    useEffect(() => {
        setThumbPageStart((s) => Math.min(s, maxThumbStart));
    }, [maxThumbStart]);

    useEffect(() => {
        if (!thumbsSwiper || thumbsSwiper.destroyed) return;
        thumbsSwiper.slideTo(thumbPageStart, 280);
    }, [thumbPageStart, thumbsSwiper]);

    // --- Handlers ---

    const handleLogout = (e: React.MouseEvent) => {
        e.preventDefault();
        setShowUserMenu(false);
        void logoutAndRedirectToIndex();
    };

    const handleProjectChange = (idx: number) => {
        if (idx === currentProjectIdx) return;
        const n = slideBgImages.length;
        if (n > 0) {
            const maxStart = Math.max(0, n - THUMB_PAGE);
            const ideal = Math.min(
                maxStart,
                Math.floor(idx / THUMB_PAGE) * THUMB_PAGE
            );
            setThumbPageStart(ideal);
        }
        if (projectChangeTimerRef.current) {
            clearTimeout(projectChangeTimerRef.current);
        }
        setFadingProjectInfo(true);
        projectChangeTimerRef.current = setTimeout(() => {
            const nextIdx = projectData.length > 0 ? (idx % projectData.length) : 0;
            setCurrentProjectIdx(nextIdx);
            setFadingProjectInfo(false);
            projectChangeTimerRef.current = null;
            const pid = resolveProjectCardId(projectData[nextIdx]);
            const storeProjectId = useProjectStore.getState().currentProjectId;
            if (pid != null && String(pid) !== String(storeProjectId ?? '')) {
                void selectProject(pid);
            }
        }, 300);
    };

    const handleLogoClick = (e: React.MouseEvent) => {
        e.preventDefault();
        setShowUserMenu(false);
        setIsSearchFocused(false);
        setSearchQuery('');
        const swiper = mainSwiperRef.current;
        if (swiper && !swiper.destroyed) {
            swiper.slideTo(0);
        }
    };

    const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setSearchQuery(e.target.value);
        if (e.target.value.trim().length > 0) {
            setIsSearchFocused(true);
        }
    };

    const handleSearchResultClick = (p: any) => {
        const rawId = p?.project_id ?? p?.id;
        const routeId =
            typeof rawId === "number"
                ? rawId
                : typeof rawId === "string" && rawId.trim() !== ""
                    ? rawId.trim()
                    : null;

        setIsSearchFocused(false);

        if (routeId != null) {
            selectProject(routeId);
            navigate(`/dashboard/${routeId}`);
            return;
        }

        navigate("/dashboard");
    };

    const handleNodeSelect = (nodeId: number) => {
        if (selectedNodeId === nodeId) return;
        setStatsActive(false);
        setTimeout(() => {
            setSelectedNodeId(nodeId);
            setStatsActive(true);
        }, 400); // Wait for fade out
    };

    // --- Derived Data ---

    const mapNodeForCoords =
        (selectedNodeId != null ? networkNodes.find((n) => n.id === selectedNodeId) : undefined) ??
        networkNodes[0];
    const mapLat = mapNodeForCoords?.latitude ?? null;
    const mapLng = mapNodeForCoords?.longitude ?? null;

    const mapCoords = useMemo((): [number, number] | null => {
        if (mapLat != null && mapLng != null) {
            return [mapLat, mapLng];
        }
        return null;
    }, [mapLat, mapLng]);

    const allMapCoords = useMemo(
        () =>
            networkNodes
                .filter((n) => n.latitude != null && n.longitude != null)
                .map((n) => [n.latitude!, n.longitude!] as [number, number]),
        [networkNodes],
    );

    const mapInitialCenter = useMemo<[number, number]>(() => {
        if (mapLat != null && mapLng != null) return [mapLat, mapLng];
        return [48, 6];
    }, [mapLat, mapLng]);

    const project = projectData[currentProjectIdx] || projectData[0];
    const selectedNetworkNode =
        selectedNodeId != null ? networkNodes.find((n) => n.id === selectedNodeId) ?? null : null;
    const nodeStats = selectedNetworkNode?.stats;

    const searchMatches = projectData.filter(p =>
        p.can_access === true && (
            (p.name || p.title || "").toLowerCase().includes(searchQuery.toLowerCase().trim()) ||
            (p.creator || p.author || "").toLowerCase().includes(searchQuery.toLowerCase().trim())
        )
    );

    // 不再用 mock 数据兜底：项目/节点为空时展示空状态，但页面本身保持可用。

    const projectWorkspacePath = (() => {
        const id = project?.project_id;
        if (typeof id === "number" && Number.isFinite(id)) return `/dashboard/${id}`;
        if (typeof id === "string" && /^\d+$/.test(id.trim())) return `/dashboard/${id.trim()}`;
        return "/dashboard";
    })();

    const projectUrlRaw = String(project?.url || "").trim();
    const showProjectExternalLink =
        projectUrlRaw.length > 0 &&
        projectUrlRaw !== "#" &&
        !/^javascript:/i.test(projectUrlRaw);

    const isProjectLocked = project?.public === false || project?.status === "lock";

    const canNavigateProject =
        project?.can_access !== false &&
        project?.can_navigate !== false &&
        project?.status !== "lock" &&
        !(project?.public === false && !loggedInUser);

    const contributorsList: string[] = Array.isArray(project?.contributors)
        ? (project?.contributors as string[]).map((s) => String(s).trim()).filter(Boolean)
        : [];

    return (
        <div className="app-container">
            {/* Navbar */}
            <nav className="home-nav-bar">
                <div className="nav-left">
                    <div className="nav-capsule-box">
                        <a className="nav-logo" href="#" onClick={handleLogoClick}>
                            <div className="logo-icon-box"><Activity size={16} /></div>
                            <span>ecoSignal</span>
                        </a>
                    </div>
                </div>

                <div className="nav-right">
                    <div className="nav-capsule-box">
                        <ESButton appearance="unstyled" className="nav-btn-simple" onClick={toggleTheme} title="Switch Theme">
                            {effectiveTheme === 'dark' ? <Sun size={NAV_BAR_ICON_SIZE} /> : <Moon size={NAV_BAR_ICON_SIZE} />}
                        </ESButton>
                        <div className="nav-divider"></div>

                        <ESButton appearance="unstyled" className="nav-btn-simple" title="Information"><Info size={NAV_BAR_ICON_SIZE} /></ESButton>
                        <div className="nav-divider"></div>

                        {!loggedInUser ? (
                            <div
                                className="user-capsule-btn user-capsule-btn--nav-account"
                                onClick={() => setShowLogin(true)}
                            >
                                <div className="user-avatar-icon"><LogIn size={NAV_BAR_ICON_SIZE} /></div>
                                <span className="user-name-text">Login</span>
                            </div>
                        ) : (
                            <div className={`user-wrapper ${showUserMenu ? 'active' : ''}`}>
                                <div
                                    className="user-capsule-btn user-capsule-btn--nav-account"
                                    onClick={() => setShowUserMenu(!showUserMenu)}
                                >
                                    <div className="user-avatar-icon"><User size={NAV_BAR_ICON_SIZE} /></div>
                                    <span className="user-name-text">{loggedInUser}</span>
                                    <ChevronDown size={NAV_BAR_ICON_SIZE} className="chevron-icon" />
                                </div>
                                <div className="dropdown-menu">
                                    <Link
                                        className="dropdown-item"
                                        to="/dashboard"
                                        onClick={() => setShowUserMenu(false)}
                                    >
                                        <LayoutDashboard size={18} /> Dashboard
                                    </Link>
                                    <div className="dropdown-divider"></div>
                                    <Link
                                        className="dropdown-item"
                                        to="/settings"
                                        onClick={() => setShowUserMenu(false)}
                                    >
                                        <Settings size={18} /> Settings
                                    </Link>
                                    <div className="dropdown-divider"></div>
                                    <Link
                                        to="#"
                                        className="dropdown-item"
                                        onClick={handleLogout}
                                    >
                                        <LogOut size={18} /> Logout
                                    </Link>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </nav>

            {/* Login Modal */}
            <LoginModal
                isOpen={showLogin}
                onClose={() => setShowLogin(false)}
                onSuccess={(username) => setLoggedInUser(username)}
            />

            {/* Vertical Main Swiper */}
            <Swiper
                onSwiper={(swiper) => {
                    mainSwiperRef.current = swiper;
                }}
                direction="vertical"
                slidesPerView={'auto'}
                mousewheel={{ enabled: true, forceToAxis: true }}
                allowTouchMove={false}
                speed={800}
                modules={[Mousewheel]}
                onSlideChange={(swiper) => setActivePage(swiper.activeIndex)}
                className="mainSwiper"
            >
                {/* Slide 1: Home */}
                <SwiperSlide id="page-home">
                    <div className="bg-image"></div>
                    <div className="home-content">
                        <div className="brand-logo"><Activity size={48} /> <span>ecoSignal</span></div>
                        <div className="hero-title">Open-source online<br />platform for ecoacoustics</div>
                        <div className="hero-desc">Use ecoSignal to manage, navigate, visualize, annotate, and analyze soundscape recordings.</div>
                    </div>
                </SwiperSlide>

                {/* Slide 2: Projects */}
                <SwiperSlide id="page-project">
                    <div className="project-fixed-ui">
                        <div className="search-bar" ref={searchContainerRef}>
                            <Search size={28} />
                            <ESInput appearance="unstyled"
                                type="text"
                                value={searchQuery}
                                onChange={handleSearchChange}
                                onFocus={() => { if (searchQuery.trim()) setIsSearchFocused(true); }}
                            />
                            {isSearchFocused && searchQuery.trim() ? (
                                <div className="search-results-dropdown active">
                                    <CustomScrollArea
                                        className="search-results-scroll"
                                        contentFingerprint={`${searchQuery}:${searchMatches.length}`}
                                        maxHeight={300}
                                    >
                                        {searchMatches.length > 0 ? searchMatches.map((p: any) => (
                                            <div key={p.id || p.project_id || p.uuid} className="search-result-item" onClick={() => handleSearchResultClick(p)}>
                                                <div className="search-result-title">{p.name || p.title}</div>
                                                <div className="search-result-meta">by {p.creator || p.author}</div>
                                            </div>
                                        )) : (
                                            <EmptyState className="search-results-empty" title="No Data" />
                                        )}
                                    </CustomScrollArea>
                                </div>
                            ) : null}
                        </div>

                        <div className="info-card" id="info-card-el" onWheel={(e) => e.stopPropagation()}>
                            <div className={`info-content-wrapper ${fadingProjectInfo ? 'fading' : ''}`}>
                                <div className="info-card-header">
                                    <div className="meta-left">{project?.doi ? project.doi : null}</div>
                                    {showProjectExternalLink ? (
                                        <a
                                            href={projectUrlRaw}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="top-link-icon"
                                            title="Project website"
                                        >
                                            <LinkIcon size={18} />
                                        </a>
                                    ) : null}
                                </div>
                                {canNavigateProject ? (
                                    <Link to={projectWorkspacePath} className="project-title">
                                        <h2>{project?.name || project?.title || "No Data"}</h2>
                                    </Link>
                                ) : (
                                    <div className="project-title project-title--disabled">
                                        <h2>{project?.name || project?.title || "No Data"}</h2>
                                    </div>
                                )}
                                <div className="creator-row">
                                    <span className="creator-name">{project?.creator || project?.author || "-"}</span>
                                    <div className={`status-icon ${isProjectLocked ? "locked" : "unlocked"}`}>
                                        {isProjectLocked ? <Lock size={18} /> : <Unlock size={18} />}
                                    </div>
                                </div>
                                <hr />
                                <CustomScrollArea
                                    className="info-card-desc-wrap"
                                    contentFingerprint={projectDescFingerprint}
                                    maxHeight={300}
                                >
                                    <div
                                        className="info-card-desc"
                                        dangerouslySetInnerHTML={{
                                            __html:
                                                project?.description_short ||
                                                project?.description ||
                                                project?.desc ||
                                                "",
                                        }}
                                    />
                                </CustomScrollArea>
                                {contributorsList.length > 0 ? (
                                    <div className="info-card-contributors">
                                        <div className="info-card-contributors-chips">
                                            {contributorsList.map((name, i) => (
                                                <span key={`${name}-${i}`} className="info-card-contributor-chip">
                                                    {name}
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                ) : null}
                                <div className="annotations">
                                    {(project?.annotations || []).map((ann: string, i: number) => (
                                        <span key={`${ann}-${i}`} className="annotation">{ann}</span>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>

                    <Swiper
                        direction="horizontal"
                        onSwiper={(swiper) => {
                            projectSwiperRef.current = swiper;
                        }}
                        onSlideChange={(swiper) => {
                            if (suppressProjectSlideSyncRef.current) return;
                            handleProjectChange(swiper.activeIndex);
                        }}
                        modules={[EffectFade]}
                        effect="fade"
                        fadeEffect={{ crossFade: true }}
                        speed={420}
                        className="projectSwiper"
                    >
                        {slideBgImages.map((img, i) => (
                            <SwiperSlide key={i}>
                                <div className="bg-image" style={{ backgroundImage: `url(${img})` }}></div>
                            </SwiperSlide>
                        ))}
                    </Swiper>

                    <div className="thumbs-container">
                        <div
                            className={`thumbs-button-prev${thumbPageStart <= 0 ? ' thumbs-button-disabled' : ''}`}
                            onClick={() => {
                                if (thumbPageStart <= 0) return;
                                setThumbPageStart((s) => Math.max(0, s - THUMB_PAGE));
                            }}
                            role="button"
                            tabIndex={thumbPageStart <= 0 ? -1 : 0}
                            onKeyDown={(e) => {
                                if (thumbPageStart <= 0) return;
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault();
                                    setThumbPageStart((s) => Math.max(0, s - THUMB_PAGE));
                                }
                            }}
                        >
                            <ChevronLeft size={24} />
                        </div>
                        <Swiper
                            onSwiper={setThumbsSwiper}
                            spaceBetween={THUMB_SPACE_PX}
                            slidesPerView={Math.max(1, thumbVisible)}
                            allowTouchMove={false}
                            className="thumbs-swiper"
                            style={
                                thumbTrackPx > 0
                                    ? { width: thumbTrackPx, flexShrink: 0 }
                                    : undefined
                            }
                        >
                            {slideBgImages.map((img, i) => {
                                const p = projectData[i];
                                const hasRealImage = p && (p.image_url || p.cover_url || p.picture_url);

                                return (
                                    <SwiperSlide
                                        key={i}
                                        className={i === currentProjectIdx ? 'thumb-slide-active' : ''}
                                        style={hasRealImage ? {
                                            backgroundImage: `url(${img})`,
                                            backgroundColor: 'transparent'
                                        } : {
                                            backgroundColor: 'transparent'
                                        }}
                                        onClick={() => {
                                            const swiper = projectSwiperRef.current;
                                            if (!swiper || swiper.destroyed) return;
                                            swiper.slideTo(i);
                                        }}
                                    >
                                        {!hasRealImage && (
                                            <div className="thumb-logo-box">
                                                <Activity size={24} />
                                            </div>
                                        )}
                                    </SwiperSlide>
                                );
                            })}
                        </Swiper>
                        <div
                            className={`thumbs-button-next${thumbPageStart >= maxThumbStart ? ' thumbs-button-disabled' : ''}`}
                            onClick={() => {
                                if (thumbPageStart >= maxThumbStart) return;
                                setThumbPageStart((s) =>
                                    Math.min(maxThumbStart, s + THUMB_PAGE)
                                );
                            }}
                            role="button"
                            tabIndex={thumbPageStart >= maxThumbStart ? -1 : 0}
                            onKeyDown={(e) => {
                                if (thumbPageStart >= maxThumbStart) return;
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault();
                                    setThumbPageStart((s) =>
                                        Math.min(maxThumbStart, s + THUMB_PAGE)
                                    );
                                }
                            }}
                        >
                            <ChevronRight size={24} />
                        </div>
                    </div>
                </SwiperSlide>

                {/* Slide 3: Map */}
                <SwiperSlide id="page-map">
                    <div className="map-brand-overlay">
                        <div className="map-brand-text"><span>ecoSignal</span> Network</div>
                    </div>
                    {nodeStats ? (
                        <div className={`stats-container ${statsActive ? 'active' : ''}`}>
                            <div className="stat-card">
                                <div className="stat-icon"><Users size={22} /></div>
                                <div className="stat-info"><div className="label">Users</div><div className="value">{nodeStats.users}</div></div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-icon"><FolderKanban size={22} /></div>
                                <div className="stat-info"><div className="label">Projects</div><div className="value">{nodeStats.projects}</div></div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-icon"><Library size={22} /></div>
                                <div className="stat-info"><div className="label">Collections</div><div className="value">{nodeStats.collections}</div></div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-icon"><Mic size={22} /></div>
                                <div className="stat-info"><div className="label">Audios</div><div className="value">{nodeStats.audios}</div></div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-icon"><ImageIcon size={22} /></div>
                                <div className="stat-info"><div className="label">Photos</div><div className="value">{nodeStats.photos}</div></div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-icon"><ScanLine size={22} /></div>
                                <div className="stat-info"><div className="label">Annotations</div><div className="value">{nodeStats.annotations}</div></div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-icon"><MapPin size={22} /></div>
                                <div className="stat-info"><div className="label">Sites</div><div className="value">{nodeStats.sites}</div></div>
                            </div>
                        </div>
                    ) : (
                        <div className={`stats-container ${statsActive ? 'active' : ''}`}>
                            <div className="stat-card">
                                <div className="stat-icon stat-icon--empty"><Info size={22} /></div>
                                <div className="stat-info">
                                    <div className="label">Network</div>
                                    <div className="value">No Data</div>
                                </div>
                            </div>
                        </div>
                    )}

                    <div
                        className="swiper-no-swiping"
                        ref={mapContainerRef}
                        style={{ width: '100%', height: '100%' }}
                    >
                        {mapBootstrapReady ? (
                            <MapContainer
                                center={mapInitialCenter}
                                zoom={5.5}
                                zoomControl={false}
                                attributionControl={false}
                                scrollWheelZoom={false}
                                id="map-pane"
                                style={{ width: '100%', height: '100%' }}
                            >
                                <MapShiftWheelZoom mapPageActive={activePage === 2} />
                                <MapViewPersistence
                                    savedViewRef={savedMapViewRef}
                                    mapPageActive={activePage === 2}
                                />
                                <TileLayer url="https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png" />
                                <TileLayer url="https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png" opacity={0.7} />
                                {networkNodes
                                    .filter(
                                        (n) => n.latitude != null && n.longitude != null
                                    )
                                    .map((n) => (
                                        <Marker
                                            key={n.id}
                                            position={[n.latitude!, n.longitude!]}
                                            icon={PremiumIcon(n.name, selectedNodeId === n.id, n.is_local)}
                                            eventHandlers={{
                                                click: () => handleNodeSelect(n.id),
                                                mouseover: (e) => {
                                                    e.target.getElement()?.classList.add('marker-hover');
                                                },
                                                mouseout: (e) => {
                                                    e.target.getElement()?.classList.remove('marker-hover');
                                                },
                                            }}
                                        />
                                    ))}
                                <MapUpdater
                                    coords={mapCoords}
                                    allCoords={allMapCoords}
                                    zoom={6}
                                    activePage={activePage}
                                    selectedNodeId={selectedNodeId}
                                    savedViewRef={savedMapViewRef}
                                />
                            </MapContainer>
                        ) : null}
                    </div>
                </SwiperSlide>

                {/* Slide 4: Sponsors */}
                <SwiperSlide id="page-sponsors">
                    <div className="aurora-bg">
                        <div className="aurora-blob"></div>
                        <div className="aurora-blob"></div>
                    </div>
                    <div className="sponsors-wrapper">
                        <div className="sponsors-header">
                            <h2 className="main-title">Sponsored <span>By</span></h2>
                            <p className="sponsors-desc">
                                Our research is made possible through the generous support of leading academic institutions and environmental organizations.
                            </p>
                        </div>
                        <div className="logo-grid">
                            <a
                                className="sponsor-card sponsor-card--inrae"
                                href="https://www.inrae.fr/en"
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label="Visit the INRAE website"
                            >
                                <img src="/images/sponsors/inrae.png" alt="INRAE" />
                            </a>
                            <a
                                className="sponsor-card sponsor-card--cnrs"
                                href="https://www.cnrs.fr/en"
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label="Visit the CNRS website"
                            >
                                <img src="/images/sponsors/cnrs.png" alt="CNRS" />
                            </a>
                        </div>
                        <div className="powered-by-section">
                            <h3 className="powered-by-title">Powered <span>By</span></h3>
                            <div className="powered-by-grid">
                                {POWERED_BY_ITEMS.map((item) => (
                                    <a
                                        key={item.name}
                                        className={`powered-by-card ${item.className}`}
                                        href={item.href}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        aria-label={`Visit the ${item.name} website`}
                                    >
                                        <img src={item.image} alt={item.name} />
                                    </a>
                                ))}
                            </div>
                        </div>
                    </div>
                </SwiperSlide>

                {/* Slide 5: Footer */}
                <SwiperSlide id="page-footer">
                    <div className="footer-content">
                        <div className="footer-logo"><span>ecoSignal</span></div>
                        <p>&copy; 2025 ecoSignal. All rights reserved.</p>
                        <div className="footer-resource-links">
                            <a href="#" className="pill-btn"><Github size={18} /> GitHub</a>
                            <a href="https://f1000research.com/articles/9-1224/v3" target="_blank" rel="noopener noreferrer" className="pill-btn"><FileText size={18} /> F1000Research</a>
                            <a href="https://scholar.google.com/scholar?cites=5906516760297568833&as_sdt=2005&sciodt=0,5&hl=en" target="_blank" rel="noopener noreferrer" className="pill-btn"><GraduationCap size={18} /> Scholar</a>
                            <a href="mailto:contact@ecosignal.org" className="pill-btn"><Mail size={18} /> Contact Us</a>
                        </div>
                        <div className="footer-actions">
                            <ESButton appearance="unstyled"
                                type="button"
                                className="footer-action-btn"
                                onClick={() => navigate("/privacy-policy")}
                            >
                                Privacy Policy
                            </ESButton>
                            <ESButton appearance="unstyled"
                                type="button"
                                className="footer-action-btn"
                                onClick={openCookiePreferences}
                            >
                                Manage Cookies
                            </ESButton>
                        </div>
                    </div>
                </SwiperSlide>
            </Swiper>

            <div className="page-jump-nav" aria-label="Page navigation">
                {PAGE_NAV_ITEMS.map((item, index) => (
                    <ESButton appearance="unstyled"
                        key={item.id}
                        type="button"
                        className={`page-jump-nav__item${activePage === index ? ' page-jump-nav__item--active' : ''}`}
                        title={item.label}
                        aria-label={item.label}
                        onClick={() => {
                            const swiper = mainSwiperRef.current;
                            if (!swiper || swiper.destroyed) return;
                            swiper.slideTo(index);
                        }}
                        aria-current={activePage === index ? 'page' : undefined}
                    >
                        <span className="page-jump-nav__dot" aria-hidden />
                        <span className="page-jump-nav__label">{item.label}</span>
                    </ESButton>
                ))}
            </div>
        </div>
    );
}
