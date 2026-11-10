import uuid
import yaml
from kubernetes import client, config
import asyncio
from nicegui import ui
import textwrap
import logging
import functools
from insightshub.config import settings
from insightshub.auth import User
from insightshub.gitui import fetch_notebook_source
from urllib.parse import urlparse
import ast
import importlib
import sys
import httpx
import os



logger = logging.getLogger(__name__)





async def verify_package_on_pypi(pkg_name: str) -> bool:
    """Checks if a package name actually exists on PyPI."""
    async with httpx.AsyncClient() as http_client:
        res = await http_client.get(f"https://pypi.org/pypi/{pkg_name}/json", timeout=5.0)
        return res.status_code == 200


async def prompt_user_for_package(failed_import: str) -> str | None:
    """Opens a blocking NiceGUI modal asking the user for the real PyPI package name."""
    with ui.dialog().props('persistent') as prompt_dialog, ui.card().classes('w-full max-w-md p-6 z-50'):
        ui.label("Unresolved Dependency").classes('text-lg font-bold text-amber-600 mb-2')
        ui.markdown(
            f"The import **`{failed_import}`** was detected, but no matching package exists on PyPI. "
            f"Please provide the correct PyPI installation name."
        ).classes('text-sm text-gray-600 mb-4')

        pkg_input = ui.input(
            label="PyPI Package Name",
            placeholder="e.g., opencv-python, pillow, scikit-learn",
            value=failed_import
        ).classes('w-full mb-4').props('autofocus')

        with ui.row().classes('w-full justify-end gap-2'):
            ui.button("Skip", on_click=lambda: prompt_dialog.submit(None)).props('flat color=grey')
            ui.button(
                "Verify & Use",
                on_click=lambda: prompt_dialog.submit(pkg_input.value.strip())
            ).classes('undp-btn--small primary text-white')

    result = await prompt_dialog
    prompt_dialog.delete()
    return result


async def resolve_dependencies_interactively(missing_imports: list[str], status_label: ui.label) -> list[str]:
    """Verifies each missing import against PyPI and prompts the user if any fail."""
    verified_packages = []

    for imp in missing_imports:
        candidate = imp
        while candidate:
            status_label.set_text(f"Verifying package '{candidate}' on PyPI...")
            # Yield to UI so the label updates
            await asyncio.sleep(0.1)

            if await verify_package_on_pypi(candidate):
                verified_packages.append(candidate)
                break
            else:
                candidate = await prompt_user_for_package(candidate)
                if not candidate:
                    logger.warning(f"User skipped unresolved import: {imp}")
                    break

    return verified_packages


import os
import uuid
import yaml
import textwrap
from urllib.parse import urlparse
from kubernetes import client, config


def spawn_marimo_session(
        notebook_path: str,
        mode: str = "run",
        namespace: str = "marimo",
        user: User = None,
        parent_url: str = None,
        missing_packages: list[str] = None,
):
    is_dev = os.getenv("DEV_MODE", "false").lower() == "true"
    worker_image = (
        "insights-hub:latest"
        if is_dev
        else os.environ.get("SPAWNER_IMAGE")
    )

    pull_policy = "IfNotPresent" if is_dev else "Always"
    repo_url = f"https://oauth2:{user.token}@github.com/{settings.nb_github_repo}"
    internal_hub_url = "http://insights-hub-svc.hub.svc.cluster.local"

    config.load_incluster_config()
    k8s_client = client.ApiClient()
    batch_v1 = client.BatchV1Api(k8s_client)
    core_v1 = client.CoreV1Api(k8s_client)
    custom_api = client.CustomObjectsApi(k8s_client)

    parent_url_str = str(parent_url)
    parsed_url = urlparse(parent_url_str)
    host = parsed_url.netloc
    if '.' in host:
        hostname = '.'.join(host.split('.')[-2:])
    else:
        hostname = host

    session_id = uuid.uuid4().hex[:8]
    resource_name = f"marimo-{mode}-{session_id}"
    session_hostname = f"{session_id}.{hostname}"
    sanitized_email = user.email.replace("@", "-").replace(".", "-")

    yaml_template = textwrap.dedent(f"""\
        apiVersion: batch/v1
        kind: Job
        metadata:
          name: {resource_name}
          annotations:
            marimo.io/notebook-path: "{notebook_path}"
            marimo.io/hostname: "{session_hostname}"
        spec:
          activeDeadlineSeconds: 86400
          ttlSecondsAfterFinished: 3600
          template:
            metadata:
              labels:
                app: marimo-worker
                session: {session_id}
                owner: "{sanitized_email}"
            spec:
              restartPolicy: Never
              nodeSelector:
                type: insights
              tolerations:
                - key: "dedicated"
                  operator: "Equal"
                  value: "insights"
                  effect: "NoSchedule"
              volumes:
                # 1. Workspace volume (Empty for now, we will inject PVC or emptyDir in Python)
                - name: session-workspace
                # 2. Heavy Data Volume (Node-local persistence via hostPath)
                - name: session-data
                  hostPath:
                    path: /data/{user.name}
                    type: DirectoryOrCreate
              initContainers:
                - name: fetch-notebooks
                  image: alpine/git:latest
                  command: ["/bin/sh", "-c"]
                  args:
                    - |
                      # CRASH GUARD: Check if repository is already initialized
                      if [ -d "/workspace/.git" ] || [ -f "/workspace/{notebook_path}" ]; then
                        echo "Crash recovery detected: Workspace already exists."
                        echo "Skipping git clone to preserve uncommitted user changes."
                        exit 0
                      fi

                      echo "Initializing fresh workspace..."
                      rm -rf /workspace/*
                      git clone --no-checkout --depth 1 {repo_url} /workspace
                      cd /workspace
                      git sparse-checkout set "{notebook_path}"
                      git checkout
                  volumeMounts:
                    - name: session-workspace
                      mountPath: /workspace
              containers:
                - name: marimo
                  image: {worker_image}
                  imagePullPolicy: {pull_policy}
                  ports:
                    - containerPort: 8080
                  resources:
                    requests:
                      memory: "1Gi"
                      cpu: "500m"
                    limits:
                      memory: "6G"
                      cpu: "3800m"
                  volumeMounts:
                    - name: session-workspace
                      mountPath: /workspace
                    - name: session-data
                      mountPath: /data
        ---
        apiVersion: v1
        kind: PersistentVolumeClaim
        metadata:
          name: {resource_name}-pvc
          labels:
            owner: "{sanitized_email}"
        spec:
          accessModes:
            - ReadWriteOnce
          resources:
            requests:
              storage: 1Gi
        ---
        apiVersion: v1
        kind: Service
        metadata:
          name: {resource_name}
          labels:
            owner: "{sanitized_email}"
        spec:
          selector:
            session: {session_id}
          ports:
            - port: 80
              targetPort: 8080
        ---
        apiVersion: gateway.networking.k8s.io/v1
        kind: HTTPRoute
        metadata:
          name: {resource_name}
          labels:
            owner: "{sanitized_email}"
        spec:
          parentRefs:
            - name: cluster-gateway
              namespace: default
          hostnames:
            - {session_hostname}
          rules:
            - matches:
                - path:
                    type: PathPrefix
                    value: /
              backendRefs:
                - name: {resource_name}
                  port: 80
        """)

    job_dict, pvc_dict, svc_dict, route_dict = list(yaml.safe_load_all(yaml_template))

    if not is_dev:
        job_dict["spec"]["template"]["spec"]["nodeSelector"] = {"type": "insights"}

    # ==========================================
    # DYNAMIC MODE CONFIGURATION
    # ==========================================
    if mode == "edit":
        # Configure Edit Mode (Requires PVC for saving code)
        job_dict["spec"]["template"]["spec"]["volumes"][0]["persistentVolumeClaim"] = {
            "claimName": f"{resource_name}-pvc"}

        job_dict["spec"]["template"]["spec"]["containers"][0]["command"] = [
            "python3", "-m", "marimohub.mrun", "edit", f"/workspace/{notebook_path}",
            "--host", "0.0.0.0", "--port", "8080", "--headless", "--no-token"
        ]
        session_env_vars = [
            {"name": "SESSION_ID", "value": session_id},
            {"name": "BRANCH_NAME", "value": session_id},
            {"name": "BASE_BRANCH", "value": "main"},
            {"name": "NOTEBOOK_REL_PATH", "value": notebook_path},
            {"name": "PARENT_HUB_URL", "value": parent_url_str},
            {"name": "HUB_CALLBACK_URL", "value": f"{internal_hub_url}/api/sessions"},
            {"name": "GIT_AUTHOR_NAME", "value": str(user.name)},
            {"name": "GIT_AUTHOR_EMAIL", "value": str(user.email)},
            {"name": "GIT_COMMITTER_NAME", "value": str(user.name)},
            {"name": "GIT_COMMITTER_EMAIL", "value": str(user.email)},
            {"name": "NB_GITHUB_TOKEN", "value": user.token},
            {"name": "NB_GITHUB_REPO", "value": settings.nb_github_repo},
        ]
    else:
        # Configure Run Mode (Ephemeral code workspace, NO PVC)
        job_dict["spec"]["template"]["spec"]["volumes"][0]["emptyDir"] = {}

        missing_pkgs_str = ",".join(missing_packages) if missing_packages else ""
        session_env_vars = [{"name": "MISSING_PACKAGES", "value": missing_pkgs_str}]

        job_dict["spec"]["template"]["spec"]["containers"][0]["command"] = [
            "python3", "-m", "marimohub.mrun", "run", f"/workspace/{notebook_path}",
            "--host", "0.0.0.0", "--port", "8080", "--redirect-console-to-browser"
        ]

    job_dict["spec"]["template"]["spec"]["containers"][0]["env"] = session_env_vars

    # 1. Submit Job
    created_job = batch_v1.create_namespaced_job(namespace=namespace, body=job_dict)
    job_uid = created_job.metadata.uid

    owner_reference = [{
        "apiVersion": "batch/v1",
        "kind": "Job",
        "name": resource_name,
        "uid": job_uid,
        "blockOwnerDeletion": True,
        "controller": True,
    }]

    # 2. Submit PVC (ONLY if we are in Edit Mode)
    if mode == "edit":
        pvc_dict["metadata"]["ownerReferences"] = owner_reference
        core_v1.create_namespaced_persistent_volume_claim(namespace=namespace, body=pvc_dict)

    # 3. Submit Service
    svc_dict["metadata"]["ownerReferences"] = owner_reference
    core_v1.create_namespaced_service(namespace=namespace, body=svc_dict)

    # 4. Submit HTTPRoute
    route_dict["metadata"]["ownerReferences"] = owner_reference
    custom_api.create_namespaced_custom_object(
        group="gateway.networking.k8s.io",
        version="v1",
        namespace=namespace,
        plural="httproutes",
        body=route_dict,
    )

    final_url = f"https://{session_hostname}"
    logger.info(f"Provisioned resources for {resource_name} at {final_url} (Job UID: {job_uid})")

    return session_id, final_url, resource_name

def get_pod_status(session_id: str, namespace: str = "marimo") -> str:
    """Queries K8s for the pod matching the session_id and returns a human-readable status."""
    core_v1 = client.CoreV1Api()

    # Find the pod we just spawned
    pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=f"session={session_id}")

    if not pods.items:
        return "Creating container..."

    pod = pods.items[0]
    phase = pod.status.phase

    if phase == "Pending":
        return "Allocating node and pulling image..."

    elif phase == "Running":
        # A pod can be 'Running' but not yet 'Ready' to accept traffic
        for condition in pod.status.conditions or []:
            if condition.type == "Ready" and condition.status == "True":
                return "Ready"
        return "Starting Marimo server..."

    elif phase in ["Failed", "Unknown"]:
        return "Error"

    return "Initializing..."


def detect_missing_deps(source_code: str) -> list[str]:
    """Scans notebook source code for imports using AST and returns a list of missing PyPI packages."""
    if not source_code:
        logger.warning("No notebook source code provided to scanner.")
        return []

    logger.info("Scanning notebook source code for imports...")
    imports = set()

    try:
        # Parse the raw string content directly
        tree = ast.parse(source_code)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
    except Exception as e:
        logger.error(f"Failed to parse notebook AST: {e}")
        return []

    packages_to_install = set()
    for pkg in imports:
        if (
            pkg in sys.stdlib_module_names
            or pkg.startswith("_")
        ):
            continue
        try:
            if importlib.util.find_spec(pkg) is not None:
                continue
        except Exception as e:
            logger.error(f'find_spec failed for {pkg}')
        logger.info(f'Detected missing dependency/package {pkg}')
        packages_to_install.add(pkg)

    return packages_to_install


async def handle_session_launch(notebook_path: str, mode: str, namespace: str = "marimo", user: User = None,
                                parent_url: str = None):
    # 0. Create a modal dialog
    with ui.dialog().classes('backdrop-blur-sm').props('persistent') as dialog, ui.card().classes(
            'w-full max-w-md p-6'):
        ui.label(f"Preparing {mode.capitalize()} Session").classes('text-xl font-bold mb-6 text-gray-800')

        with ui.row().classes('items-center gap-4 mb-2'):
            spinner = ui.spinner('dots', size='lg', color='primary')
            status_label = ui.label("Provisioning Kubernetes resources...").classes('text-gray-600')

        with ui.row().classes('w-full justify-end gap-2'):
            open_link = ui.link('Open Session manually', '#', new_tab=True).classes(
                'hidden undp-btn--small primary text-white px-4 py-2 rounded no-underline font-medium'
            )
            close_btn = ui.button('Close', on_click=dialog.close).classes('mt-4 hidden')

    dialog.open()
    loop = asyncio.get_event_loop()

    try:
        source_code = await fetch_notebook_source(notebook_path, user=user)
        missing_packages = detect_missing_deps(source_code)
        verified_packages = []
        if missing_packages:
            status_label.set_text(f'{notebook_path} needs {len(missing_packages)} additional packages...')
            await asyncio.sleep(1)
            verified_packages = await resolve_dependencies_interactively(missing_packages, status_label)
            status_label.set_text(f'{len(verified_packages)} packages verified on pypi...')
            await asyncio.sleep(1)

        spawn_task = functools.partial(
            spawn_marimo_session,
            notebook_path=notebook_path,
            mode=mode,
            user=user,
            parent_url=parent_url,
            missing_packages=verified_packages
        )

        # 1. Unpack all three variables
        session_id, target_url, resource_name = await loop.run_in_executor(None, spawn_task)

        # 2. Build the INTERNAL K8s Service URL (Service routes port 80 -> pod 8080)
        internal_url = f"http://{resource_name}.{namespace}.svc.cluster.local:80"

        max_retries = 90  # 90 seconds total timeout
        pod_is_ready = False

        # 3. Clean Polling Loop
        async with httpx.AsyncClient(verify=False) as client:
            for _ in range(max_retries):
                await asyncio.sleep(1.0)

                # Phase A: Check K8s Pod Status
                if not pod_is_ready:
                    status = await loop.run_in_executor(None, get_pod_status, session_id, namespace)

                    if status == "Ready":
                        pod_is_ready = True
                        status_label.set_text("Environment ready! Waiting for server to boot...")
                    elif status == "Error":
                        status_label.set_text("Container failed to start.")
                        status_label.classes('text-red-500 font-bold')
                        spinner.classes('hidden')
                        close_btn.classes(remove='hidden')
                        return
                    else:
                        status_label.set_text(status)

                # Phase B: Poll the INTERNAL URL
                if pod_is_ready:
                    try:
                        # 1-second timeout so it doesn't freeze the loop
                        response = await client.get(internal_url, timeout=1.0)

                        # Once Marimo binds the port, it will answer the ping
                        if response.status_code in (200, 302, 401, 403):
                            status_label.set_text("Server online! Opening session...")
                            spinner.classes('hidden')
                            await asyncio.sleep(0.5)

                            # Navigate the user to the PUBLIC URL
                            ui.navigate.to(target_url)
                            dialog.close()
                            return
                        else:
                            status_label.set_text(f"Server booting (HTTP {response.status_code})...")

                    except httpx.RequestError:
                        # Connection refused (Marimo process hasn't bound to port 8080 yet)
                        # We just pass and let it try again on the next second!
                        pass

        # 4. Handle Timeout (If Pod never becomes "Ready" OR server never boots in 90 seconds)
        spinner.classes('hidden')
        status_label.set_text("Timed out waiting for the server to answer.")
        status_label.classes('text-red-500 font-bold text-sm')

        close_btn.classes(remove='hidden')
        open_link.props(f'href="{target_url}"')
        open_link.classes(remove='hidden')

    except Exception as e:
        logger.error(f"Launch Error: {e}")
        status_label.set_text(f"API Error: {str(e)}")
        status_label.classes('text-red-500 font-bold text-xs')
        spinner.classes('hidden')
        close_btn.classes(remove='hidden')


