import uuid
import yaml
from kubernetes import client, config, utils
import asyncio
from nicegui import ui
import textwrap
import logging
import functools
from insightshub.config import settings
from insightshub.auth import User
from urllib.parse import urlparse
logger = logging.getLogger(__name__)




def spawn_marimo_session(
    notebook_path: str,
    mode: str = "run",
    namespace: str = "marimo",
    user: User = None,
    parent_url: str = None,
):
    repo_url = f"https://oauth2:{settings.nb_github_token}@github.com/{settings.nb_github_repo}"
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
      name: placeholder-name
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
            session: placeholder-session
            owner: "{sanitized_email}"
        spec:
          restartPolicy: Never
          volumes:
          - name: session-workspace
            emptyDir: {{}}
          initContainers:
          - name: fetch-notebooks
            image: alpine/git:latest
            command: ["/bin/sh", "-c"]
            args:
            - |
              rm -rf /workspace/* && \
              git clone --no-checkout --depth 1 {repo_url} /workspace && \
              cd /workspace && \
              git sparse-checkout set "{notebook_path}" && \
              git checkout
            volumeMounts:
            - name: session-workspace
              mountPath: /workspace
          containers:
          - name: marimo
            image: insights-hub:latest
            imagePullPolicy: IfNotPresent
            ports:
            - containerPort: 8080
            resources:
              requests:
                memory: "2Gi"
                cpu: "2000m"
              limits:
                memory: "8Gi"
                cpu: "4000m"
            volumeMounts:
            - name: session-workspace
              mountPath: /workspace
    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: placeholder-name
      labels:
        owner: "{sanitized_email}"
    spec:
      selector:
        session: placeholder-session
      ports:
      - port: 80
        targetPort: 8080
    ---
    apiVersion: gateway.networking.k8s.io/v1
    kind: HTTPRoute
    metadata:
      name: placeholder-name
      labels:
        owner: "{sanitized_email}"
    spec:
      parentRefs:
      - name: cluster-gateway
        namespace: default
      hostnames:
      - placeholder-hostname
      rules:
      - matches:
        - path:
            type: PathPrefix
            value: /
        backendRefs:
        - name: placeholder-name
          port: 80
    """)

    job_dict, svc_dict, route_dict = list(yaml.safe_load_all(yaml_template))

    # 1. Configure Job
    job_dict["metadata"]["name"] = resource_name
    job_dict["spec"]["template"]["metadata"]["labels"]["session"] = session_id

    if mode == "edit":
        job_dict["spec"]["template"]["spec"]["containers"][0]["command"] = [
            "python3","-m", "marimohub.mrun", "edit", f"/workspace/{notebook_path}",
            "--host", "0.0.0.0", "--port", "8080", "--headless", "--no-token"
        ]
        # 1. Base session and Git identity variables
        session_env_vars = [
            {"name": "SESSION_ID", "value": session_id},
            {"name": "BRANCH_NAME", "value": session_id},
            {"name": "BASE_BRANCH", "value": "main"},
            {"name": "NOTEBOOK_REL_PATH", "value": notebook_path},
            {"name": "PARENT_HUB_URL", "value": parent_url_str},
            {"name": "HUB_CALLBACK_URL", "value": f"{internal_hub_url}/api/sessions"},
            # Standard Git CLI identity
            {"name": "GIT_AUTHOR_NAME", "value": str(user.name)},
            {"name": "GIT_AUTHOR_EMAIL", "value": str(user.email)},
            {"name": "GIT_COMMITTER_NAME", "value": str(user.name)},
            {"name": "GIT_COMMITTER_EMAIL", "value": str(user.email)},
            # Clean, quote-stripped GitHub credentials from Pydantic settings
            {"name": "NB_GITHUB_TOKEN", "value": settings.nb_github_token},
            {"name": "NB_GITHUB_REPO", "value": settings.nb_github_repo},
        ]



        job_dict["spec"]["template"]["spec"]["containers"][0]["env"] = session_env_vars

    else:
        job_dict["spec"]["template"]["spec"]["containers"][0]["command"] = [
            "marimo", "run", f"/workspace/{notebook_path}",
            "--host", "0.0.0.0", "--port", "8080", "--redirect-console-to-browser"
        ]

    # Submit Job first to acquire the cluster-generated UID
    created_job = batch_v1.create_namespaced_job(namespace=namespace, body=job_dict)
    job_uid = created_job.metadata.uid

    # 2. Build ownerReference pointing to the created Job
    owner_reference = [
        {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "name": resource_name,
            "uid": job_uid,
            "blockOwnerDeletion": True,
            "controller": True,
        }
    ]

    # 3. Configure and create Service
    svc_dict["metadata"]["name"] = resource_name
    svc_dict["metadata"]["ownerReferences"] = owner_reference
    svc_dict["spec"]["selector"]["session"] = session_id

    core_v1.create_namespaced_service(namespace=namespace, body=svc_dict)

    # 4. Configure and create HTTPRoute
    route_dict["metadata"]["name"] = resource_name
    route_dict["metadata"]["ownerReferences"] = owner_reference
    route_dict["spec"]["hostnames"][0] = session_hostname
    route_dict["spec"]["rules"][0]["backendRefs"][0]["name"] = resource_name

    custom_api.create_namespaced_custom_object(
        group="gateway.networking.k8s.io",
        version="v1",
        namespace=namespace,
        plural="httproutes",
        body=route_dict,
    )

    final_url = f"https://{session_hostname}"
    logger.info(f"Provisioned resources for {resource_name} at {final_url} (Job UID: {job_uid})")

    return session_id, final_url

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





async def handle_session_launch(notebook_path: str, mode: str, namespace:str = "marimo", user:User=None,
                                parent_url:str=None):



    # 1. Create a modal dialog that prevents the user from clicking elsewhere
    with ui.dialog().classes('backdrop-blur-sm').props('persistent') as dialog, ui.card().classes(
            'w-full max-w-md p-6'):
        ui.label(f"Preparing {mode.capitalize()} Session").classes('text-xl font-bold mb-6 text-gray-800')

        with ui.row().classes('items-center gap-4 mb-2'):
            spinner = ui.spinner('dots', size='lg', color='primary')
            status_label = ui.label("Provisioning Kubernetes resources...").classes('text-gray-600')
        with ui.row().classes('w-full justify-end gap-2'):
            # The direct link button to open the tab:
            open_link = ui.link('Open Session', '#', new_tab=True).classes(
                'hidden undp-btn--small primary text-white px-4 py-2 rounded no-underline font-medium'
            )

        close_btn = ui.button('Close', on_click=dialog.close).classes('mt-4 hidden')

    dialog.open()
    loop = asyncio.get_event_loop()

    try:
        # 2. Spawn the K8s resources
        # Bind the keyword arguments safely using partial
        spawn_task = functools.partial(
            spawn_marimo_session,
            notebook_path=notebook_path,
            mode=mode,
            user=user,
            parent_url=parent_url

        )

        session_id, target_url = await loop.run_in_executor(None, spawn_task)

        # 3. Smart Polling Loop (Timeout after 60 seconds)
        max_retries = 60
        for _ in range(max_retries):
            await asyncio.sleep(1)  # Yield control back to the UI to keep the spinner animating

            # Ask K8s what the pod is doing
            status = await loop.run_in_executor(None, get_pod_status, session_id, namespace)

            if status == "Ready":
                status_label.set_text("Environment ready! Routing traffic...")
                spinner.classes('hidden')  # Hide spinner
                # Give the Ingress Controller 1.5 seconds to register the new Service IP
                await asyncio.sleep(1.5)

                #ui.navigate.to(target_url, new_tab=True)
                ui.navigate.to(target_url)
                dialog.close()
                return

            elif status == "Error":
                status_label.set_text("Container failed to start.")
                status_label.classes('text-red-500 font-bold')
                spinner.classes('hidden')
                close_btn.classes(remove='hidden')  # Allow user to close dialog
                return

            else:
                # Update the UI with the current K8s phase (e.g., "Allocating node...")
                status_label.set_text(status)

        # 4. Handle Timeout
        status_label.set_text("Timed out waiting for environment.")
        status_label.classes('text-red-500 font-bold')
        spinner.classes('hidden')
        close_btn.classes(remove='hidden')

    except Exception as e:
        # Catch unexpected K8s API errors (e.g., RBAC issues, syntax errors)
        status_label.set_text(f"API Error: {str(e)}")
        status_label.classes('text-red-500 font-bold text-xs')
        spinner.classes('hidden')
        close_btn.classes(remove='hidden')