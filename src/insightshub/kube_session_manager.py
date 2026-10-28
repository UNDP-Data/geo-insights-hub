import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Dict, List, Optional
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException


logger = logging.getLogger("marimo-kube-manager")


def sanitize_email_label(email: str) -> str:
    """Matches the sanitized owner label used across manifests."""
    return email.lower().replace("@", "-").replace(".", "-")


@dataclass
class KubeMarimoSession:
    session_id: str
    job_name: str
    owner: str  # sanitized email
    status: str  # 'Pending', 'Running', 'Succeeded', 'Failed'
    notebook_path: str
    session_type: str  # run|edit
    hostname: Optional[str] = None
    created_at: Optional[datetime] = None
    active_pods: int = 0


    @property
    def is_alive(self) -> bool:
        return self.status in ("Pending", "Running")

    @property
    def url(self) -> str:
        if self.hostname:
            return f"https://{self.hostname}"
        return f"/session/{self.session_id}"
    def __str__(self):
        return f'{self.job_name} {self.status} owned by {self.owner}'


class KubeMarimoManager:
    def __init__(self, namespace: str = "marimo", poll_interval: float = 4.0):
        self.namespace = namespace
        self.poll_interval = poll_interval
        self._sessions: Dict[str, KubeMarimoSession] = {}
        self._polling_task: Optional[asyncio.Task] = None

        # Load In-Cluster or Local Kubeconfig
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self.batch_v1 = client.BatchV1Api()
        self.core_v1 = client.CoreV1Api()
        self.custom_api = client.CustomObjectsApi()

    async def startup(self):
        """Starts the background polling loop on app boot."""
        logger.info("Starting KubeMarimoManager background polling...")
        self._polling_task = asyncio.create_task(self._poll_loop())

    async def shutdown(self):
        """Cancels background polling on app shutdown."""
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        """Continuously syncs in-memory session registry with Kubernetes."""
        while True:
            try:
                await asyncio.to_thread(self._sync_kubernetes_sessions)
            except Exception as e:
                logger.error(f"Error syncing Kube sessions: {e}")
            await asyncio.sleep(self.poll_interval)

    def _sync_kubernetes_sessions(self):
        """Queries the Kube API for jobs matching app=marimo-worker."""
        try:
            jobs = self.batch_v1.list_namespaced_job(
                namespace=self.namespace,
                label_selector="app=marimo-worker"
            )
        except ApiException as e:
            logger.error(f"Failed to fetch jobs: {e}")
            return

        active_sids = set()

        for job in jobs.items:
            labels = job.metadata.labels or {}
            session_type = job.metadata.name.split('-')[-2] or 'UNK'
            annotations = job.metadata.annotations or {}

            session_id = labels.get("session") or job.metadata.name.replace("marimo-run-", "")
            owner = labels.get("owner", "unknown")
            active_sids.add(session_id)

            # Determine Job lifecycle status
            status = "Pending"
            if job.status.active:
                status = "Running"
            elif job.status.succeeded:
                status = "Succeeded"
            elif job.status.failed:
                status = "Failed"

            # Resolve notebook path and hostname from annotations if present
            notebook_path = annotations.get("marimo.io/notebook-path", "notebook.py")
            hostname = annotations.get("marimo.io/hostname", f"{session_id}.undpgeohub.org")

            session = KubeMarimoSession(
                session_id=session_id,
                job_name=job.metadata.name,
                owner=owner,
                status=status,
                notebook_path=notebook_path,
                hostname=hostname,
                created_at=job.metadata.creation_timestamp,
                active_pods=job.status.active or 0,
                session_type=session_type
            )
            self._sessions[session_id] = session

        # Prune dead sessions that no longer exist in the cluster
        for sid in list(self._sessions.keys()):
            if sid not in active_sids:
                del self._sessions[sid]

    def get_user_sessions(self, user_email: str) -> List[KubeMarimoSession]:
        """Returns sessions belonging strictly to the requested user."""
        sanitized = sanitize_email_label(user_email)
        return [
            s for s in self._sessions.values()
            if s.owner == sanitized
        ]

    async def delete_session(self, session_id: str) -> None:
        """Deletes the Job, Service, and HTTPRoute for a session."""
        session = self._sessions.get(session_id)
        resource_name = session.job_name if session else f"marimo-run-{session_id}"

        await asyncio.to_thread(self._delete_k8s_resources, resource_name, session_id)
        self._sessions.pop(session_id, None)

    def _delete_k8s_resources(self, resource_name: str, session_id: str):
        # 1. Delete Job & cascade to Pods (Background propagation)
        try:
            self.batch_v1.delete_namespaced_job(
                name=resource_name,
                namespace=self.namespace,
                propagation_policy="Background"
            )
            logger.info(f"Deleted Job {resource_name}")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Error deleting Job {resource_name}: {e}")

        # 2. Delete Service
        try:
            self.core_v1.delete_namespaced_service(
                name=resource_name,
                namespace=self.namespace
            )
            logger.info(f"Deleted Service {resource_name}")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Error deleting Service {resource_name}: {e}")

        # 3. Delete Gateway API HTTPRoute
        try:
            self.custom_api.delete_namespaced_custom_object(
                group="gateway.networking.k8s.io",
                version="v1",
                namespace=self.namespace,
                plural="httproutes",
                name=resource_name
            )
            logger.info(f"Deleted HTTPRoute {resource_name}")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Error deleting HTTPRoute {resource_name}: {e}")



manager = KubeMarimoManager(namespace="marimo")