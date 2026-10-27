import httpx
import logging
from fastapi import Request
from dataclasses import dataclass
from urllib.parse import urlencode
from insightshub.config import settings
import random

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class User:
    """Represents an application user."""
    name: str = 'Guest'
    email: str = ''
    token:str = ''
    groups: tuple[str, ...] = ()


    def __post_init__(self):
        if not self.email:
            # Use object.__setattr__ to bypass frozen=True restrictions during initialization
            random_suffix = random.randint(0, 10000)
            object.__setattr__(self, 'email', f"{self.name.lower()}{random_suffix}@ran.dom")

    @property
    def display_name(self) -> str:
        """Returns the user's name if available, otherwise defaults to email."""
        return self.name or self.email

    @property
    def is_authenticated(self) -> bool:
        """Checks if the user is authenticated (not a default Guest)."""
        return bool(self.name != 'Guest' and self.email and self.token)



def page_url(request: Request) -> str:
    """
    Constructs the absolute URL of the current page as seen by the browser.

    Args:
        request (Request): The incoming FastAPI request.

    Returns:
        str: The full absolute URL including scheme, host, path, and query parameters.
    """
    path = request.url.path
    if request.url.query:
        path += f"?{request.url.query}"

    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    return f"{scheme}://{host}{path}"


def sign_in_url(request: Request) -> str:
    """
    Generates the sign-in URL, appending a redirect back to the current page.

    Args:
        request (Request): The incoming FastAPI request.

    Returns:
        str: The authentication start URL with a redirect parameter.
    """
    return f"{settings.public_auth_url}/start?{urlencode({'rd': page_url(request)})}"


def sign_out_url(request: Request) -> str:
    """
    Generates the sign-out URL, appending a redirect back to the current page.

    Args:
        request (Request): The incoming FastAPI request.

    Returns:
        str: The authentication sign-out URL with a redirect parameter.
    """
    return f"{settings.public_auth_url}/sign_out?{urlencode({'rd': page_url(request)})}"


def user_from_headers(request: Request) -> User:
    """
    Extracts user information from request headers to create a User instance.

    Args:
        request (Request): The incoming FastAPI request.

    Returns:
        User: An instance of the User object or Guest user if headers are missing.
    """
    h = request.headers
    token = h.get("x-auth-request-access-token", "")
    email = h.get("x-auth-request-email") or h.get("x-forwarded-email") or User.email
    user = h.get("x-auth-request-user") or h.get("x-forwarded-user") or User.name
    groups_raw = h.get("x-auth-request-groups") or h.get("x-forwarded-groups") or ""
    groups = tuple([g.strip() for g in groups_raw.split(",") if g.strip()])

    return User(name=user, email=email, groups=groups, token=token)





async def authenticate(url: str, request: Request, forward_headers: bool = False) -> User:
    """
    Asynchronously verifies authentication by checking headers first, then querying an auth service.

    Args:
        url (str): The URL of the authentication validation service.
        request (Request): The incoming FastAPI request.
        forward_headers (bool, optional): If True, injects auth headers back into
                                          the request scope upon successful validation.
                                          Defaults to False.

    Returns:
        User: An authenticated User instance if successful, otherwise a default Guest user.
    """
    user = user_from_headers(request=request)
    if user.is_authenticated:
        return user

    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            headers = {
                "X-Forwarded-Proto": request.headers.get("x-forwarded-proto", request.url.scheme),
                "X-Forwarded-Host": request.headers.get("x-forwarded-host", request.headers.get("host", "")),
                "X-Forwarded-Uri": request.url.path + (("?" + request.url.query) if request.url.query else ""),

            }
            ua = request.headers.get("user-agent")
            if ua:
                headers["User-Agent"] = ua

            response = await client.get(url, cookies=request.cookies, headers=headers)

            if response.status_code in (200, 202):
                token = response.headers.get("x-auth-request-access-token", "")
                email = response.headers.get("x-auth-request-email", "")
                groups_raw = response.headers.get("x-auth-request-groups", "")
                groups = tuple([g.strip() for g in groups_raw.split(",")] if groups_raw else [])
                username = response.headers.get("x-auth-request-user", "Guest")

                if forward_headers:
                    auth_headers = {
                        "x-auth-request-email": response.headers.get("x-auth-request-email", "Guest"),
                        "x-auth-request-user": response.headers.get("x-auth-request-user", ""),
                        "x-auth-request-groups": response.headers.get("x-auth-request-groups", ""),
                        "x-auth-request-access-token": token
                    }
                    current_headers = dict(request.headers)
                    current_headers.update(auth_headers)
                    request.scope["headers"] = [
                        (k.lower().encode("latin-1"), v.encode("latin-1"))
                        for k, v in current_headers.items()
                    ]
                    if hasattr(request, "_headers"):
                        delattr(request, "_headers")

                return User(name=username, email=email, groups=groups, token=token)

        except Exception as e:
            logger.error(f"Auth Service unreachable: {e}")

    return User()