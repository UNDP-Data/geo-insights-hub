"""Site pages. Importing this module registers the routes with NiceGUI."""

from fastapi import Request, Response
import os
from pathlib import Path
from insightshub.layout import standard_page
from insightshub import marutil as mu
from insightshub.kubespawner import handle_session_launch
from insightshub.kube_session_manager import manager
import asyncio
from fastapi.responses import RedirectResponse
from urllib.parse import quote
from nicegui import app, ui
from insightshub.config import settings



BASE_DIR = Path(__file__).parent.parent.parent.resolve()
NOTEBOOKS_DIR = (BASE_DIR / "notebooks").resolve()
os.environ['NOTEBOOKS_DIR'] = str(NOTEBOOKS_DIR)


@ui.page("/")
@ui.page('/apps/{subpath:path}')
async def home(request: Request, response:Response,  subpath: str = "") -> None:

    async with (standard_page(title="Apps", request=request, response=response) as user):

        # 1. Identify if user has Edit rights (authenticated users)
        can_edit = user.is_authenticated

        # 2. Resolve the directory to scan
        current_dir = (NOTEBOOKS_DIR / subpath).resolve()
        # Security: Prevent escaping the root directory
        if not str(current_dir).startswith(str(NOTEBOOKS_DIR)) or not current_dir.exists():
            ui.notify("Directory not found", type='negative')
            return ui.navigate.to('/')


        with ui.column().classes('w-full max-w-7xl mx-auto px-6 lg:px-8'):

            # 3. Breadcrumbs / "Back" Navigation
            if subpath:
                parent_path = Path(subpath).parent
                # Navigate back: if parent is '.', go to root '/'
                back_url = '/' if str(parent_path) == '.' else f'/apps/{parent_path}'

                with ui.row().classes('items-center mb-6 cursor-pointer group').on('click',
                                                                                   lambda: ui.navigate.to(back_url)):
                    ui.icon('arrow_back', color='[#006db0]').classes('group-hover:-translate-x-1 transition-transform')
                    ui.label(f"Back to {parent_path if str(parent_path) != '.' else 'Apps'}").classes(
                        'text-[#006db0] font-bold text-xs tracking-widest uppercase')
            # 4. The Grid
            with ui.grid(columns='1fr 1fr 1fr').classes('w-full gap-10 items-stretch'):
                items = [
                    item for item in current_dir.iterdir()
                    if not item.name.startswith('.') and item.name != "__init__.py"
                ]
                items.sort(key=lambda x: (not x.is_dir(), x.name))

                for item in items:
                    rel_path = item.relative_to(NOTEBOOKS_DIR)
                    name, _ = os.path.splitext(item.name)
                    item_label = name.replace('_', ' ')

                    # ==========================================
                    # FOLDER / APP CARD
                    # ==========================================
                    if item.is_dir():
                        if '__' in item.name:
                            continue

                        with ui.column().classes(
                                'w-full border-t-2 border-black p-6 flex flex-col justify-between h-full '
                                'bg-white hover:bg-[#006eb5] transition-all duration-200 cursor-pointer group hover:scale-102 transition'
                        ).on('click', lambda p=rel_path: ui.navigate.to(f'/apps/{p}')):

                            with ui.column().classes('w-full gap-4'):
                                # 1. Content Tag
                                ui.label('APP').classes('text-xs font-bold tracking-wider text-black uppercase ')

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
                        # marimo_slug = str(rel_path).replace('.py', '').replace(os.sep, '/').strip('/')
                        # next_uri = f'/apps/{marimo_slug}'
                        descr = mu.get_global_metadata(str(item.absolute()))

                        with ui.column().classes(
                                'w-full border-t-2 border-black pt-4 pb-6 flex flex-col justify-between h-full bg-transparent group'
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
                                        on_click=lambda e, p=str(rel_path): handle_session_launch(
                                            notebook_path=p,
                                            mode="run",
                                            user=user,
                                            parent_url=request.url
                                        )
                                    ).classes('undp-btn--small primary text-white flex-1 w-1/2 capitalize') \
                                        .tooltip(f'View as interactive app')
                                        #.tooltip(f'View as interactive app at {next_uri}')

                                    ui.button(
                                        'Edit',
                                        color="secondary",
                                        on_click=lambda e, p=str(rel_path): handle_session_launch(
                                            notebook_path=p,
                                            mode="edit",
                                            user=user,
                                            parent_url=request.url
                                        )
                                    ).classes('undp-btn--small secondary text-white flex-1 w-1/2 capitalize') \
                                        .tooltip(
                                        f'Edit notebook...')

                                else:

                                    # 1 button, centered in the same max width wrapper
                                    ui.button(
                                        text='Launch',
                                        on_click=lambda e, p=str(rel_path): handle_session_launch(
                                            notebook_path=p,
                                            mode="run",
                                            user=user,
                                            parent_url=request.url
                                        )
                                    ).classes('undp-btn--small primary text-white flex-1 w-1/2 capitalize') \
                                        .tooltip(f'View as interactive app')
            # # 4. The Grid
            # with ui.grid(columns='1fr 1fr 1fr').classes('w-full gap-8'):
            #     # Filter: No hidden files, no __init__.py
            #     items = [
            #         item for item in current_dir.iterdir()
            #         if not item.name.startswith('.') and item.name != "__init__.py"
            #     ]
            #     # Sort: Folders first, then files
            #     items.sort(key=lambda x: (not x.is_dir(), x.name))
            #
            #     for item in items:
            #
            #         rel_path = item.relative_to(NOTEBOOKS_DIR)
            #         name, _ = os.path.splitext(item.name)
            #         item_label = name.replace('_', ' ')
            #
            #         if item.is_dir():
            #             if '__' in item.name: continue
            #             # --- FOLDER CARD ---
            #             with ui.card().classes(
            #                     'undp-card bg-white h-full flex flex-col justify-between cursor-pointer border border-gray-200 hover:border-[#006eb5] transition-all'
            #             ).on('click', lambda p=rel_path: ui.navigate.to(f'/notebooks/{p}')):
            #
            #                 with ui.column().classes('gap-3 w-full'):
            #                     # Category tag placed at top with icon
            #                     with ui.row().classes('items-center gap-2'):
            #                         ui.icon('insights', size='18px', color='[#006eb5]')
            #                         ui.label('App').classes(
            #                             'text-xs font-bold tracking-widest uppercase text-[#006eb5]')
            #
            #                     # Bold black title
            #                     ui.label(item_label).classes(
            #                         'text-xl font-bold text-black tracking-tight leading-snug capitalize')
            #
            #                 # Subtle UNDP-style arrow link indicator at bottom
            #                 with ui.row().classes('w-full justify-end items-center mt-6 pt-4 border-t border-gray-100'):
            #                     ui.icon('east', size='18px', color='[#006eb5]').classes(
            #                         'hover:translate-x-1 transition-transform')
            #
            #         elif item.suffix == '.py':
            #             # --- NOTEBOOK CARD ---
            #             with ui.card().classes('undp-card p-0 overflow-hidden bg-white'):
            #                 # Green accent for notebooks
            #                 ui.element('div').classes('w-full h-1 bg-green-500')
            #                 with ui.column().classes('p-8 w-full'):
            #                     with ui.row().classes('items-center gap-2 mb-2'):
            #                         ui.icon('dashboard', color='[#006db0]').classes('text-2xl')
            #                         ui.label('Notebook').classes(
            #                             'text-[#006db0] text-sm font-bold tracking-widest uppercase')
            #                     ui.label(item_label).classes('text-xl font-bold text-gray-700 capitalize')
            #
            #                     # Fetch metadata (description) from the file
            #                     descr = mu.get_global_metadata(str(item.absolute()))
            #                     ui.label(descr or "No description available.").classes(
            #                         'text-sm mb-6 text-gray-500 line-clamp-2 h-10')
            #                     # Standard slug: 'folder/name'
            #                     marimo_slug = str(rel_path).replace('.py', '').replace(os.sep, '/').strip('/')
            #
            #                     # Calculate relative path jump to root (../../ etc)
            #                     # This ensures links work regardless of folder depth
            #                     #depth = str(rel_path).count('/')
            #                     #r = "../" * (depth + 1)
            #                     next_uri = f'/apps/{marimo_slug}'
            #                     with ui.row().classes('w-full justify-center mt-auto'):
            #                         # This wrapper defines the “middle” area and width budget for buttons
            #                         with ui.row().classes('w-full max-w-[360px] gap-2 flex-nowrap'):
            #                             if can_edit:
            #                                 # 2 buttons, equal widths
            #                                 ui.button(
            #                                     'Launch',
            #                                     on_click=lambda s=marimo_slug, : ui.navigate.to(next_uri)
            #                                 ).classes('undp-btn primary text-white flex-1 w-1/2 capitalize') \
            #                                     .tooltip(f'View as interactive app at {next_uri}')
            #
            #                                 ui.button(
            #                                     'Edit',
            #                                     on_click=lambda s=marimo_slug,: ui.navigate.to(f'/edit/open/{s}')
            #                                 ).props(f'color="{UNDP_RED}"') \
            #                                     .classes('undp-btn text-white flex-1 w-1/2 capitalize') \
            #                                     .tooltip(
            #                                     f'Open in Editor mode (Spawns kernel) to /edit/open/{marimo_slug}')
            #
            #                             else:
            #
            #                                 # 1 button, centered in the same max width wrapper
            #                                 ui.button(
            #                                     'Launch',
            #                                     on_click=lambda: ui.navigate.to(next_uri)
            #                                 ).classes('undp-btn primary text-white justify w-[180px] capitalize') \
            #                                     .tooltip(f'View as interactive app at {next_uri}')


@ui.page("/settings")
async def app_settings(request: Request, response: Response) -> None:

    async with standard_page(title="Settings", request=request, response=response) as user:
        ui.label('Settings')
        ui.label(f'{user.email}')
        hostname = '.'.join(request.headers.get('host').split('.')[-2:])

        ui.label(f'{hostname}')


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

    # 2. Construct the auth proxy URL
    target_host = settings.public_auth_url
    final_url = f"{target_host}/{action}?rd={quote(rd, safe=':/%?=&')}"

    # 3. Instantly redirect the browser (No UI is rendered)
    return RedirectResponse(final_url)