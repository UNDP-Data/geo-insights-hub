
"""Site pages. Importing this module registers the routes with NiceGUI."""

from fastapi import Request, Response
import os
from pathlib import Path
from insightshub.layout import standard_page
from insightshub.auth import  page_url
from insightshub import marutil as mu
from insightshub.kubespawner import handle_session_launch
from insightshub.kube_session_manager import manager
import asyncio
from fastapi.responses import RedirectResponse
from urllib.parse import quote
from nicegui import app, ui

from insightshub.config import settings
import json
from insightshub import gitui
import logging
logger = logging.getLogger(__name__)




@ui.page("/")
@ui.page('/apps/{subpath:path}')
async def home(request: Request, response:Response,  subpath: str = "") -> None:

    async with standard_page(title="Apps", request=request, response=response) as user:
        logger.debug(f"User {user}")


        # 1. Traversal protection
        try:
            current_dir = (gitui.NOTEBOOKS_DIR / subpath).resolve()
            current_dir.relative_to(gitui.NOTEBOOKS_DIR.resolve())
        except (ValueError, RuntimeError):
            ui.notify("Invalid path trajectory.", type="negative")
            ui.navigate.to("/")
            return
        logger.debug(f"Current dir {current_dir}")
        can_edit = bool(user and user.is_authenticated)

        # 2. Helper for missing directory / unauthenticated empty state
        def render_auth_prompt(msg: str):
            with ui.column().classes(
                    "w-full max-w-xl mx-auto my-24 p-10 bg-white border-t-2 border-black shadow-sm gap-6 items-center text-center"
            ):
                ui.icon("folder_off", color="negative").classes("text-5xl")
                ui.html(msg).classes("text-sm text-gray-600 leading-relaxed")

                if not can_edit:
                    btn = (
                        ui.button("Sign In", icon="login")
                        .props('color="negative" unelevated')
                        .classes(
                            "font-bold uppercase tracking-wide hover:scale-105 transition-transform px-6 py-2"
                        )
                    )

                    async def go_auth():
                        btn.props(add="loading")
                        await asyncio.sleep(0.1)
                        ui.navigate.to(
                            f"/_auth/bounce?action=start&rd={quote(page_url(request), safe='')}"
                        )

                    btn.on("click", go_auth)

        # 3. Handle directory conditions
        msg = f'The notebooks directory is currently empty on this server. You must be authenticated to check out the <span class="text-red-600 font-bold">{settings.nb_github_repo}</span> workspace.'

        if not current_dir.exists():
            # ui.notify(f"Current dir {current_dir}", type="negative")
            render_auth_prompt(msg)
            if can_edit:
                if await asyncio.to_thread(gitui.sync_repo_task, user=user) and current_dir.exists():
                    ui.navigate.reload()
            return



        if not can_edit:
            if gitui.repo_is_public(settings.nb_github_repo):
                await asyncio.to_thread(gitui.sync_repo_task) # do not return,m co and contineu

            else:
                render_auth_prompt(msg)
                return



        with ui.column().classes('w-full max-w-7xl mx-auto px-6 lg:px-8'):

            # 3. Breadcrumbs / "Back" Navigation
            if subpath:
                parent_path = Path(subpath).parent
                # Navigate back: if parent is '.', go to root '/'
                back_url = '/' if str(parent_path) == '.' else f'/apps/{parent_path}'

                with ui.column().classes('w-full max-w-7xl mx-auto px-6 lg:px-8'):

                    # --- TOP HEADER BAR: Back (Left) | Title (Center/Flow) | New (Right) ---
                    with ui.row().classes('w-full justify-between items-center mb-8'):

                        # 1. Back to Parent Link (Far Left Edge)
                        if subpath:
                            parent_path = Path(subpath).parent
                            back_url = '/' if str(parent_path) == '.' else f'/apps/{parent_path}'
                            back_label = str(parent_path) if str(parent_path) != '.' else 'Apps'
                        else:
                            back_url = '/'
                            back_label = 'Apps'

                        with ui.row().classes('items-center cursor-pointer group').on('click',
                                                                                      lambda: ui.navigate.to(back_url)):
                            ui.icon('arrow_back', color='[#006eb5]').classes(
                                'group-hover:-translate-x-1 transition-transform text-lg')
                            ui.label(f"Back to {back_label}").classes(
                                'text-[#006eb5] font-bold text-xs tracking-widest uppercase ml-1')
                        with ui.column().classes('w-fit mx-auto items-center'):
                            ui.label(current_dir.name.replace('_', ' ').capitalize()).classes(
                                'text-2xl font-bold text-black uppercase tracking-tight whitespace-nowrap'
                            )
                            ui.element('div').classes('w-full h-1 bg-[#006db0] mt-1')

                        # 2. New Button (Far Right Edge)
                        if can_edit:
                            with ui.row():
                                ui.button(
                                    'New',
                                    icon='add',
                                    color='negative',
                                    on_click=lambda e: gitui.open_create_notebook_dialog(
                                        current_subpath=subpath,
                                        user=user,
                                    )
                                ).classes(
                                    'undp-button text-white font-bold py-1.5 px-4 rounded shadow-sm text-sm uppercase tracking-wider')

                                async def handle_manual_sync():
                                    ui.notify("Pulling latest changes from GitHub...", type="info")
                                    # Run the blocking git pull in a background thread
                                    await asyncio.to_thread(gitui.sync_repo_task, user)
                                    ui.notify("Sync complete!", type="positive")
                                    ui.navigate.reload()

                                ui.button(
                                    'Sync',
                                    icon='sync',
                                    color='blue-grey',
                                    on_click=handle_manual_sync
                                ).classes(
                                    'undp-button text-white font-bold py-1.5 px-4 rounded shadow-sm text-sm uppercase tracking-wider')

            # 4. The Grid
            with ui.grid(columns='1fr 1fr 1fr').classes('w-full gap-10 items-stretch'):
                items = [
                    item for item in current_dir.iterdir()
                    if not item.name.startswith('.') and item.name != "__init__.py"
                ]
                items.sort(key=lambda x: (not x.is_dir(), x.name))

                for item in items:
                    rel_path = item.relative_to(gitui.NOTEBOOKS_DIR)
                    name, _ = os.path.splitext(item.name)
                    item_label = name.replace('_', ' ')

                    # ==========================================
                    # FOLDER / APP CARD
                    # ==========================================
                    if item.is_dir():
                        if '__' in item.name:
                            continue

                        with ui.column().classes(
                                'w-full border-t-2 border-black p-3 flex flex-col justify-between h-full '
                                'bg-white hover:bg-[#006eb5] transition-all duration-200 cursor-pointer group hover:scale-102 transition'
                        ).on('click', lambda p=rel_path: ui.navigate.to(f'/apps/{p}')):

                            with ui.column().classes('w-full gap-4'):
                                with ui.row().classes('w-full items-center justify-between -mt-2'):
                                    ui.label('APP').classes(
                                        'text-xs font-bold tracking-wider text-black group-hover:text-white uppercase transition-colors'
                                    )

                                    # Small close icon button below top border
                                    if can_edit:
                                        ui.button(
                                            icon='close',
                                            color="negative",
                                            on_click=lambda e, p=rel_path, n=item.name: gitui.confirm_delete_folder(
                                                folder_path=p, folder_name=n, user=user
                                            )
                                        ).props('flat round dense size=sm') \
                                            .classes(
                                            '-mr-2 text-neutral-400 hover:text-red-600 group-hover:text-white/80 group-hover:hover:text-white transition-colors') \
                                            .tooltip(f'Delete folder {item_label}') \
                                            .on(
                                            'click.stop')  # Stops click from triggering card navigation to /apps/{p}

                                # 2. Headline
                                ui.label(item_label).classes(
                                    'text-2xl font-normal text-black leading-snug capitalize')

                                # # 3. Description
                                # ui.label('Explore notebook collection and analytical workspaces.').classes(
                                #     'text-sm text-gray-700 leading-relaxed'
                                # )

                            # 4. CTA Link
                            with ui.row().classes('items-center gap-1.5 mt-8'):
                                ui.link('Explore', f'/apps/{rel_path}').classes("undp-cta-link")



                    # ==========================================
                    # NOTEBOOK / ARTICLE CARD
                    # ==========================================
                    elif item.suffix == '.py':

                        descr = mu.get_global_metadata(str(item.absolute()))

                        with ui.column().classes(
                                'w-full border-t-2 border-b-1 border-red-500 pt-4 pb-6 flex flex-col justify-between h-full bg-transparent group'
                        ):
                            with ui.column().classes('w-full gap-4'):
                                # 1. Content Tag
                                ui.label('NOTEBOOK').classes(
                                    'text-xs font-bold tracking-wider text-black uppercase')

                                # 2. Headline
                                ui.label(item_label).classes(
                                    'text-2xl font-normal text-black leading-snug capitalize')

                                # 3. Description
                                ui.label(descr or "Interactive analytics and dashboard module.").classes(
                                    'text-sm text-gray-700 leading-relaxed line-clamp-3'
                                )

                            # 4. Action Row
                            with ui.row().classes('items-center gap-4 mt-8'):
                                if can_edit:
                                    # 2 buttons, equal widths
                                    ui.button(
                                        text='Launch',
                                        icon="launch",
                                        on_click=lambda e, p=str(rel_path): handle_session_launch(
                                            notebook_path=p,
                                            mode="run",
                                            user=user,
                                            parent_url=request.url)) \
                                        .props('unelevated') \
                                        .style('min-height: 28px; padding: 0 5px !important;') \
                                        .classes('bg-[#006eb5] text-white font-bold text-xs tracking-wide hover:scale-110 transition') \
                                        .tooltip(f'View as interactive app')


                                    ui.button(
                                        'Edit',
                                        icon="edit",
                                        color="blue-grey",
                                        on_click=lambda e, p=str(rel_path): handle_session_launch(
                                            notebook_path=p,
                                            mode="edit",
                                            user=user,
                                            parent_url=request.url)) \
                                        .props('unelevated') \
                                        .style('min-height: 28px; padding: 0 5px !important;') \
                                        .classes('bg-[#006eb5] text-white font-bold text-xs tracking-wide hover:scale-110 transition') \
                                        .tooltip(f'Edit notebook...')
                                    ui.button(
                                        'Delete',
                                        icon="delete",
                                        color="negative",
                                        on_click=lambda e, p=str(rel_path), n=item_label: gitui.confirm_delete_notebook(
                                            notebook_path=p, notebook_name=n, user=user
                                        )) \
                                        .props('unelevated') \
                                        .style('min-height: 28px; padding: 0 5px !important;') \
                                        .classes('bg-[#006eb5] text-white font-bold text-xs tracking-wide hover:scale-110 transition') \
                                        .tooltip(
                                        f'Delete notebook...')


                                else:

                                    # 1 button, centered in the same max width wrapper
                                    ui.button(
                                        text='Launch',
                                        icon="launch",
                                        on_click=lambda e, p=str(rel_path): handle_session_launch(
                                            notebook_path=p,
                                            mode="run",
                                            user=user,
                                            parent_url=request.url
                                        )
                                        # ).classes('undp-btn--small primary text-white flex-1 w-1/2 capitalize') \
                                    ).classes(
                                    'text-white font-bold py-1.5 px-4 rounded shadow-sm text-sm uppercase tracking-wider hover:scale-110 transition') \
                                    .tooltip(f'View as interactive app')
                                    # .tooltip(f'View as interactive app at {next_uri}')


@ui.page("/settings")
async def app_settings(request: Request, response: Response) -> None:
    async with standard_page(title="Settings", request=request, response=response) as user:
        ui.label('Settings').classes('text-2xl font-bold mb-4')
        ui.label(f'User Email: {user.email}')
        ui.label(f'User token: {user.token}')


        hostname = '.'.join(request.headers.get('host', '').split('.')[-2:])
        ui.label(f'Hostname: {hostname}')

        # Extract and analyze headers
        headers_dict = dict(request.headers)
        token = headers_dict.get("x-auth-request-access-token", "")

        # Display token status visually
        ui.label(f"Token Present: {bool(token)}").classes('font-bold text-lg')
        if token:
            ui.label(f"Token Length: {len(token)}")
            ui.label(f"Token Preview: {token[:10]}...")
        else:
            ui.label("⚠️ Warning: x-auth-request-access-token header is missing!").classes('text-red-500')

        # Display all headers neatly on the UI for inspection
        ui.label('All Request Headers:').classes('font-bold mt-4')
        ui.code(json.dumps(headers_dict, indent=2), language='json')


@ui.page("/sessions")
async def session_manager(request: Request, response: Response) -> None:

    async with standard_page(title="Session manager", request=request, response=response) as user:
        with ui.column().classes('w-full max-w-7xl mx-auto px-6 lg:px-8 gap-6 pb-12'):

            # Header Row
            with ui.row().classes(
                    'w-full justify-between items-center p-4 mb-4 bg-gray-50 border border-gray-200 shadow-sm rounded-lg'):
                with ui.column().classes('gap-0'):
                    ui.label('Active Marimo Sessions').classes('text-xl font-bold text-gray-800')
                    ui.label(f'Owner: {user.email}').classes('text-xs text-gray-500 font-mono')

                with ui.row().classes('items-center gap-2'):
                    ui.button(icon='refresh', on_click=lambda: refresh_list()) \
                        .props('flat round dense color=primary') \
                        .tooltip('Refresh Status') \
                        .classes(' rounded-full hover:scale-110 transition') \
                        .style('border-radius: 50% !important; overflow: hidden;')

                    ui.button(icon='delete_forever', on_click=lambda: kill_all_sessions()) \
                        .props('flat round color=negative') \
                        .tooltip('Delete All Sessions')

            # Session list container
            list_container = ui.column().classes('w-full gap-4')

            async def kill_session(session_id: str):
                await manager.delete_session(session_id)
                ui.notify(f"Terminating cluster session {session_id}...", type='info')
                await asyncio.sleep(0.5)
                refresh_list()

            async def kill_all_sessions():
                user_sessions = manager.get_user_sessions(user.email)
                for s in user_sessions:
                    await manager.delete_session(s.session_id)
                ui.notify("Terminated all user workloads.", type='warning')
                await asyncio.sleep(0.5)
                refresh_list()

            def refresh_list():
                list_container.clear()
                user_sessions = manager.get_user_sessions(user.email)

                if not user_sessions:
                    with list_container:
                        ui.label("No active notebook sessions found for this user.").classes(
                            'text-gray-400 italic mt-4')
                    return

                with list_container:
                    for s in user_sessions:
                        # Status Indicator Color
                        if s.status == "Running":
                            status_color = 'bg-emerald-500'
                        elif s.status == "Pending":
                            status_color = 'bg-amber-500'
                        else:
                            status_color = 'bg-red-500'

                        with ui.card().classes(
                                'w-full p-0 flex flex-row items-center justify-between overflow-hidden bg-white shadow-sm border border-gray-100 rounded-lg'):

                            # Left: Status indicator & details
                            with ui.row().classes('items-center gap-0 w-2/3'):
                                ui.element('div').classes(f'w-5 h-20 {status_color}')

                                with ui.row().classes('items-center gap-4 pl-4 py-2'):
                                    ui.icon('description', color='secondary').classes('text-2xl opacity-80').tooltip('Notebook')

                                    ui.icon(f'{"web" if s.session_type == "run" else "edit_note"}', color='primary').classes('text-2xl opacity-80').props('size="lg"') \
                                    .tooltip(f'{s.session_type.capitalize()} mode')


                                    with ui.column().classes('gap-0'):
                                        ui.label(s.notebook_path).classes('font-bold text-base text-gray-800')

                                        with ui.row().classes('gap-3 items-center mt-1'):
                                            ui.label(f"ID: {s.session_id}").classes(
                                                'text-xs text-gray-500 font-mono bg-gray-100 px-2 py-0.5 rounded')
                                            # ui.label(f"Status: {s.status}").classes(
                                            #     f'text-xs font-bold {"text-emerald-600" if s.status == "Running" else "text-amber-600"}')
                                            ui.label('Status:').classes('text-xs font-bold').tooltip(s.status)
                                            ui.spinner('dots', size='xs') if s.status == 'Running' else ui.icon('block', color='secondary', size='xs')


                                            if s.created_at:
                                                ui.label(f'Created at: {s.created_at.strftime("%Y-%m-%d %H:%M:%S")}').classes(
                                                    'text-xs text-gray-400')

                            # Right: Actions
                            with ui.row().classes('items-center gap-2 pr-6'):
                                # Join Button (Enabled only if Running)
                                join_btn = ui.button('Open', icon='open_in_new',
                                                     on_click=lambda url=s.url: ui.navigate.to(url, new_tab=True)) \
                                    .props('flat color=primary').classes('font-bold tracking-wider')

                                if s.status != "Running":
                                    join_btn.props('disable')
                                    join_btn.tooltip('Session is provisioning...')

                                # Kill Button
                                ui.button(icon='delete_outline', on_click=lambda sid=s.session_id: kill_session(sid)) \
                                    .props('flat round color=negative') \
                                    .tooltip('Delete Kubernetes Session')

            # Initial render
            refresh_list()




@ui.page('/_auth/bounce')
def auth_bounce(action: str, rd: str):
    """Silently clears the cookie and redirects in a single network hop."""
    # 1. Clear the local identity safely via HTTP
    app.storage.browser.pop('user', None)
    app.storage.browser.pop('sync_ident', None)

    # 2. Construct the auth proxy URL
    target_host = settings.public_auth_url
    final_url = f"{target_host}/{action}?rd={quote(rd, safe=':/%?=&')}"
    # 3. Instantly redirect the browser (No UI is rendered)
    return RedirectResponse(final_url)

@ui.page('/datasets')

async def datasets(request:Request, response:Response)->None:

    async with standard_page(title="Datasets", request=request, response=response) as user:
        ui.label(f'Most useful datasets for {user.email}')
