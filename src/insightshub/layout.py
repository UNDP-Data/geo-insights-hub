import asyncio
import dataclasses
from insightshub import utils
from nicegui import ui, app
from pathlib import Path
from fastapi import Request, Response
from insightshub.auth import User, authenticate, page_url
from insightshub.config import settings
from contextlib import asynccontextmanager
import logging
from urllib.parse import quote
from pydantic import SecretStr


logger = logging.getLogger(__name__)


UNDP_BLUE = "#006eb5"
UNDP_RED = "#d12800"
STATIC_DIR = Path(__file__).parent / "static"
ASSETS = "/static/undp"
REPO_URL = "https://github.com/UNDP-Data/geo-careatlas"

NAV_ITEMS = [
    ("Apps", "/"),
    ("Settings", "/settings"),
    ("Docs", "/docs"),

]

FOOTER_LINKS = [
    ("About UNDP", "https://www.undp.org/about-us"),
    ("Terms of use", "https://www.undp.org/copyright-terms-use"),
    ("Source code", REPO_URL),
]

def _is_external(url: str) -> bool:
    return url.startswith("http")


def _is_active(path: str, current: str) -> bool:
    if _is_external(path):
        return False
    return current == path if path == "/" else current.startswith(path)


def _link(label: str, url: str) -> ui.link:
    return ui.link(label, url, new_tab=_is_external(url))

def _img(src: str, alt: str) -> ui.element:
    return ui.element("img").props(f'src="{src}" alt="{alt}"')


def _asset_url(name: str) -> str:
    """URL of a static file, versioned by its modification time.

    Checked on every render so an edited file gets a new URL even when the
    server has not restarted, and browsers never serve a stale cached copy.
    """
    version = int((STATIC_DIR / name).stat().st_mtime)
    return f"/static/{name}?v={version}"


def _account(request: Request, user: User | None) -> None:
    is_authenticated = user.is_authenticated
    target_host = settings.public_auth_url
    rd = page_url(request)

    # Dynamically determine the action based on auth status
    action = "sign_out" if is_authenticated else "start"
    final_url = f"{target_host}/{action}?rd={quote(rd, safe=':/%?=&')}"

    with ui.row().classes("items-center gap-1"):
        # --- 1. MANAGEMENT ICONS (Placed first so they appear on the left) ---
        # Session Manager Icon
        ui.button(icon='dns').props('color="secondary" size="lg"') \
            .props('flat round dense') \
            .classes('rounded-full hover:scale-110 transition') \
            .style('border-radius: 50% !important; overflow: hidden;') \
            .tooltip('Session Manager') \
            .on('click', lambda: ui.navigate.to('/sessions'))


        if is_authenticated:
            # System Settings Icon
            ui.button(icon='tune').props('color="secondary" size="lg"') \
                .props('flat round dense') \
                .classes(' rounded-full hover:scale-110 transition') \
                .style('border-radius: 50% !important; overflow: hidden;') \
                .tooltip('System Settings') \
                .on('click', lambda: ui.navigate.to('/settings'))

            # Subtle vertical divider (Now placed between settings and the identity button)
            ui.element('div').classes('w-[1px] h-6 bg-gray-300 mx-1')

        # --- 2. THE IDENTITY BUTTON (Placed last so it appears on the right) ---
        with ui.element('div'):
            identity_btn = ui.button(icon='account_circle') \
                .props(f'flat round dense color="{"blue" if is_authenticated else "secondary"}" size="lg"') \
                .classes(' rounded-full hover:scale-110 transition') \
                .style('border-radius: 50% !important; overflow: hidden;') \
                .tooltip(f'Connected as {user.email}' if is_authenticated else f'Sign In {user.name} with email: {user.email}')

            async def go_auth():
                logger.info(f'Going to {action} {final_url}')
                identity_btn.props('loading icon=sync')
                identity_btn.classes(add='animate-spin')
                await asyncio.sleep(.1)
                safe_rd = quote(rd, safe='')

                asyncio.create_task(asyncio.to_thread(utils.sync_repo_task, user))
                ui.navigate.to(f"/_auth/bounce?action={action}&rd={safe_rd}")

            identity_btn.on('click', go_auth)




def _hamburger() -> None:
    with ui.element("button").classes("undp-hamburger") \
            .props('type="button" aria-label="Open menu" aria-expanded="false" aria-controls="undp-mobile-nav"') \
            .on("click", js_handler="() => undpToggleNav()"):
        for position in ("top", "middle", "bottom"):
            ui.element("span").classes(f"undp-hamburger__line undp-hamburger__line--{position}")


def load_theme() -> None:
    ui.colors(primary=UNDP_BLUE, secondary=UNDP_RED)
    ui.add_head_html(
        f'<link rel="stylesheet" href="{_asset_url("theme.css")}">'
        f'<script src="{_asset_url("nav.js")}"></script>'
    )

def _header_old(request: Request, user: User | None ) -> None:
    current = request.url.path

    with ui.header().classes("undp-header"):
        with ui.element("div").classes("undp-header__inner"):
            with ui.link(target="/").classes("undp-header__logo"):
                _img(f"{ASSETS}/undp-logo-blue.svg", "UNDP logo")
            with ui.link(target="/").classes("undp-site-title"):
                ui.label(settings.header_label).classes("undp-site-title__region")
                ui.label(settings.app_name).classes("undp-site-title__name")

            with ui.element("nav").classes("undp-menu gt-sm"):
                for label, url in NAV_ITEMS:
                    link = _link(label, url).classes("undp-menu__link")
                    if _is_active(url, current):
                        link.classes("undp-menu__link--active").props('aria-current="page"')

            with ui.element("div").classes("undp-header__actions"):
                with ui.element("div").classes("gt-sm"):
                    _account(request, user)
                _hamburger()
        #_mobile_nav(request, user, current)


def _header(request: Request, user: User | None) -> None:
    current = request.url.path

    with ui.header().classes("undp-header"):
        # The inner container only manages TWO children: Left side vs Right side
        with ui.element("div").classes("undp-header__inner").style(
                "display: flex; align-items: center; justify-content: space-between; width: 100%;"):

            # ==========================================
            # 1. LEFT WRAPPER (Brand + Menu locked together)
            # ==========================================
            with ui.element("div").style("display: flex; align-items: center;"):

                # A. The Brand (Logo + Title)
                with ui.link(target="/").classes("undp-header__logo"):
                    _img(f"{ASSETS}/undp-logo-blue.svg", "UNDP logo")
                with ui.link(target="/").classes("undp-site-title"):
                    ui.label(settings.header_label).classes("undp-site-title__region")
                    ui.label(settings.app_name).classes("undp-site-title__name")

                # B. The Menu
                # Use margin-left to push the menu further to the right away from the Brand.
                # Because it's locked in this wrapper, it will NEVER move when you log in/out.
                with ui.element("nav").classes("undp-menu gt-sm").style(
                        "margin-left: 8rem !important; display: flex; gap: 2rem;"):
                    for label, url in NAV_ITEMS:
                        link = _link(label, url).classes("undp-menu__link")
                        if _is_active(url, current):
                            link.classes("undp-menu__link--active").props('aria-current="page"')

            # ==========================================
            # 2. RIGHT WRAPPER (Actions)
            # ==========================================
            # This can grow or shrink as much as it wants; it won't affect the Left Wrapper.
            with ui.element("div").classes("undp-header__actions").style("display: flex; align-items: center;"):
                with ui.element("div").classes("gt-sm"):
                    _account(request, user)
                _hamburger()

def _footer() -> None:
    with ui.footer(fixed=False).classes("undp-footer"):
        with ui.element("div").classes("undp-footer__inner"):
            with ui.element("div").classes("undp-footer__top"):
                with ui.element("div").classes("undp-footer__brand"):
                    with ui.link(target="https://www.undp.org", new_tab=True).classes("undp-footer__logo"):
                        _img(f"{ASSETS}/undp-logo-white.svg", "UNDP logo")
                    ui.html("United Nations<br>Development Programme").classes("undp-footer__name")
                # with ui.element("div").classes("undp-footer__social"):
                #     for name, url, icon in SOCIAL_LINKS:
                #         with ui.link(target=url, new_tab=True).props(f'aria-label="{name}" title="{name}"'):
                #             _img(f"{ASSETS}/{icon}", name)

            with ui.element("div").classes("undp-footer__bottom"):
                ui.label("© United Nations Development Programme").classes("undp-footer__copyright")
                with ui.element("nav").classes("undp-footer__links"):
                    for label, url in FOOTER_LINKS:
                        _link(label, url).classes("undp-footer__link")


def page_title(title: str) -> None:
    with ui.column().classes("gap-2"):
        ui.element("div").classes("undp-title__bar")
        ui.label(title).classes("undp-title")

@asynccontextmanager
async def standard_page(title: str = None, request: Request = None, response: Response = None):
    """A reusable layout with a header, main content area, and footer."""

    # 1. Always try extracting/authenticating fresh from the current request first
    user = await authenticate(url=settings.private_auth_url, request=request, forward_headers=True)

    # 2. If the current request gave us a valid authenticated user, update browser storage
    if user.is_authenticated:
        app.storage.browser['user'] = dataclasses.asdict(user)

    else:
        # 3. If current request is a Guest, check if we have a valid cached user in browser storage
        cached_data = app.storage.browser.get('user')
        if cached_data:
            cached_user = User(**cached_data)
            if cached_user.is_authenticated:
                user = cached_user


    load_theme()
    _header(request=request, user=user)
    with ui.column().classes("undp-container undp-main"):
        yield user
    _footer()