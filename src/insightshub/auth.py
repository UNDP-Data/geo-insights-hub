import httpx
import logging
from fastapi import Request, Response
from dataclasses import dataclass
from urllib.parse import urlencode
from insightshub.config import settings
import random
import hmac
import base64
import hashlib
from starlette.middleware.base import BaseHTTPMiddleware

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
try:
    # cryptography >= 43.0.0
    from cryptography.hazmat.decrepit.ciphers.modes import CFB
except ImportError:
    # Fallback for older cryptography versions
    from cryptography.hazmat.primitives.ciphers.modes import CFB

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


def user_from_headers(headers:dict[str:str]) -> User:
    """
    Extracts user information from headers to create a User instance.

    Returns:
        User: An instance of the User object or Guest user if headers are missing.
        :param headers:
    """
    h = headers
    token = h.get("x-auth-request-access-token", "")
    email = h.get("x-auth-request-email") or h.get("x-forwarded-email") or User.email
    user = h.get("x-auth-request-user") or h.get("x-forwarded-user") or User.name
    groups_raw = h.get("x-auth-request-groups") or h.get("x-forwarded-groups") or ""
    groups = tuple([g.strip() for g in groups_raw.split(",") if g.strip()])

    return User(name=user, email=email, groups=groups, token=token)





async def authenticateh(url: str, request: Request, response:Response, forward_headers: bool = False) -> User:
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
    user = user_from_headers(headers=response.headers)
    logger.info(f'user {user} is auth {user.is_authenticated}')
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
                    request.state.auth_headers = {
                        "x-auth-request-email": email,
                        "x-auth-request-user": username,
                        "x-auth-request-groups": ','.join(groups),
                        "x-auth-request-access-token": token
                    }

                return User(name=username, email=email, groups=groups, token=token)

        except Exception as e:
            logger.error(f"Auth Service unreachable: {e}")

    return user


def _lz4_decompress_frame(data: bytes) -> bytes:
    """Decompresses an oauth2-proxy LZ4 frame (magic 0x184D2204) in pure Python."""
    if data[:4] != b"\x04\x22\x4d\x18":
        return data
    flg = data[4]
    pos = 6
    if flg & 0x08:  # Content size (8 bytes)
        pos += 8
    if flg & 0x01:  # Dict ID (4 bytes)
        pos += 4
    pos += 1  # Header checksum (1 byte)

    out = bytearray()
    while pos + 4 <= len(data):
        block_size = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4
        if block_size == 0:
            break
        uncompressed = (block_size & 0x80000000) != 0
        block_size &= 0x7FFFFFFF
        block = data[pos:pos + block_size]
        pos += block_size
        if flg & 0x10:  # Block checksum
            pos += 4
        if uncompressed:
            out.extend(block)
        else:
            bpos = 0
            while bpos < len(block):
                token = block[bpos]
                bpos += 1
                lit_len = token >> 4
                if lit_len == 15:
                    while True:
                        b = block[bpos]
                        bpos += 1
                        lit_len += b
                        if b != 255:
                            break
                out.extend(block[bpos:bpos + lit_len])
                bpos += lit_len
                if bpos >= len(block):
                    break
                offset = int.from_bytes(block[bpos:bpos + 2], "little")
                bpos += 2
                match_len = (token & 0x0F) + 4
                if (token & 0x0F) == 15:
                    while True:
                        b = block[bpos]
                        bpos += 1
                        match_len += b
                        if b != 255:
                            break
                for _ in range(match_len):
                    out.append(out[-offset])
    return bytes(out)


def _msgpack_unpack(data: bytes):
    """Minimal pure-Python MessagePack unpacker for oauth2-proxy session maps."""
    pos = 0

    def _read():
        nonlocal pos
        b = data[pos]
        pos += 1
        if b <= 0x7F:
            return b
        if 0x80 <= b <= 0x8F:  # fixmap
            return {_read(): _read() for _ in range(b & 0x0F)}
        if 0x90 <= b <= 0x9F:  # fixarray
            return [_read() for _ in range(b & 0x0F)]
        if 0xA0 <= b <= 0xBF:  # fixstr
            n = b & 0x1F
            s = data[pos:pos + n].decode("utf-8", errors="replace")
            pos += n
            return s
        if b in (0xC0, 0xC2, 0xC3):
            return {0xC0: None, 0xC2: False, 0xC3: True}[b]
        if b in (0xC4, 0xC5, 0xC6):  # bin 8/16/32
            w = 1 << (b - 0xC4)
            n = int.from_bytes(data[pos:pos + w], "big")
            pos += w + n
            return None
        if b in (0xD4, 0xD5, 0xD6, 0xD7, 0xD8):  # fixext 1/2/4/8/16 (e.g. Go time.Time)
            pos += 1 + (1 << (b - 0xD4))
            return None
        if b in (0xC7, 0xC8, 0xC9):  # ext 8/16/32
            w = 1 << (b - 0xC7)
            n = int.from_bytes(data[pos:pos + w], "big")
            pos += w + 1 + n
            return None
        if b in (0xD9, 0xDA, 0xDB):  # str 8/16/32
            w = 1 << (b - 0xD9)
            n = int.from_bytes(data[pos:pos + w], "big")
            pos += w
            s = data[pos:pos + n].decode("utf-8", errors="replace")
            pos += n
            return s
        if b in (0xDC, 0xDD):  # array 16/32
            w = 2 if b == 0xDC else 4
            n = int.from_bytes(data[pos:pos + w], "big")
            pos += w
            return [_read() for _ in range(n)]
        if b in (0xDE, 0xDF):  # map 16/32
            w = 2 if b == 0xDE else 4
            n = int.from_bytes(data[pos:pos + w], "big")
            pos += w
            return {_read(): _read() for _ in range(n)}
        return None

    return _read()


def parse_oauth2_proxy_cookie(
    cookie_val: str,
    cookie_secret: str,
    cookie_name: str = "_oauth2_proxy",
) -> dict | None:
    """Validates HMAC-SHA256, decrypts AES-CFB, and unpacks LZ4+MessagePack cookie."""
    try:
        parts = cookie_val.split("|")
        if len(parts) != 3:
            return None

        b64_payload, timestamp_str, b64_sig = parts

        # 1. Verify HMAC-SHA256 signature (NO pipes in signed message, raw UTF-8 secret)
        pad_sig = b64_sig + "=" * ((4 - len(b64_sig) % 4) % 4)
        expected_sig = base64.urlsafe_b64decode(pad_sig)
        msg = f"{cookie_name}{b64_payload}{timestamp_str}".encode("utf-8")
        computed_sig = hmac.new(cookie_secret.encode("utf-8"), msg, hashlib.sha256).digest()

        if not hmac.compare_digest(expected_sig, computed_sig):
            logger.warning("OAuth2 cookie HMAC signature mismatch.")
            return None

        # 2. AES-CFB Decryption (base64-decoded 24-byte AES-192 key)
        pad_secret = cookie_secret + "=" * ((4 - len(cookie_secret) % 4) % 4)
        try:
            aes_key = base64.urlsafe_b64decode(pad_secret)
            if len(aes_key) not in (16, 24, 32):
                aes_key = cookie_secret.encode("utf-8")
        except Exception:
            aes_key = cookie_secret.encode("utf-8")

        pad_payload = b64_payload + "=" * ((4 - len(b64_payload) % 4) % 4)
        encrypted_bytes = base64.urlsafe_b64decode(pad_payload)
        if len(encrypted_bytes) < 16:
            return None

        iv = encrypted_bytes[:16]
        ciphertext = encrypted_bytes[16:]

        cipher = Cipher(algorithms.AES(aes_key), CFB(iv))
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(ciphertext) + decryptor.finalize()

        # 3. Decompress LZ4 frame & unpack MessagePack map
        raw_msgpack = _lz4_decompress_frame(decrypted_bytes)
        return _msgpack_unpack(raw_msgpack)

    except Exception as e:
        logger.error(f"Failed to decrypt _oauth2_proxy cookie: {e}")
        return None

async def authenticateo(request: Request, forward_headers: bool = False) -> User:
    oauth_cookie = request.cookies.get("_oauth2_proxy")
    if not oauth_cookie:
        return User()

    cookie_secret = getattr(settings, "oauth_cookie_secret", "RfMgU2j3vGrpxEyz2vCJieSlRbdu1AEl")
    session_data = parse_oauth2_proxy_cookie(oauth_cookie, cookie_secret)

    if session_data:
        username = session_data.get("u") or session_data.get("User") or "Guest"
        email = session_data.get("e") or session_data.get("Email") or ""
        token = session_data.get("at") or session_data.get("AccessToken") or ""
        groups = tuple(session_data.get("g") or session_data.get("Groups") or ())
        if forward_headers:
            request.state.auth_headers = {
                "x-auth-request-email": email,
                "x-auth-request-user": username,
                "x-auth-request-groups": ','.join(groups),
                "x-auth-request-access-token": token
            }

        return User(name=username, email=email, groups=groups, token=token)

    return User()


def _save_headers_for_middleware(request: Request, user: User) -> None:
    """Stores user headers in request.state so CustomHeaderMiddleware stamps the browser response."""
    request.state.auth_headers = {
        "x-auth-request-email": user.email,
        "x-auth-request-user": user.name,
        "x-auth-request-groups": ",".join(user.groups),
        "x-auth-request-access-token": user.token,
    }


async def authenticate(
        url: str,
        request: Request,
        response: Response | None = None,
        forward_headers: bool = False,
) -> User:
    """
    Authenticates the user using a 3-tier strategy:
    1. Incoming Request Headers (if injected by reverse proxy)
    2. Local _oauth2_proxy Cookie decryption (0ms latency on consecutive loads)
    3. Remote httpx call to oauth2-proxy /oauth2/auth endpoint (fallback)
    """
    # ---------------------------------------------------------
    # 1. Check incoming REQUEST headers (NOT response.headers!)
    # ---------------------------------------------------------
    user = user_from_headers(headers=request.headers)
    if user.is_authenticated:
        if forward_headers:
            _save_headers_for_middleware(request, user)
        return user

    # ---------------------------------------------------------
    # 2. Check _oauth2_proxy Cookie locally (Fastest for consecutive loads)
    # ---------------------------------------------------------
    oauth_cookie = request.cookies.get("_oauth2_proxy")
    if oauth_cookie:

        try:
            session_data = parse_oauth2_proxy_cookie(oauth_cookie, settings.oauth_cookie_secret)
            if session_data:
                username = session_data.get("u") or session_data.get("User") or "Guest"
                email = session_data.get("e") or session_data.get("Email") or ""
                token = session_data.get("at") or session_data.get("AccessToken") or ""
                groups = tuple(session_data.get("g") or session_data.get("Groups") or ())

                user = User(name=username, email=email, groups=groups, token=token)
                if user.is_authenticated:
                    if forward_headers:
                        _save_headers_for_middleware(request, user)
                    return user
        except Exception as e:
            logger.debug(f"Local cookie parse failed, falling back to httpx: {e}")

    # ---------------------------------------------------------
    # 3. Fallback: Query the remote Auth Service via httpx
    # ---------------------------------------------------------
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            headers = {
                "X-Forwarded-Proto": request.headers.get("x-forwarded-proto", request.url.scheme),
                "X-Forwarded-Host": request.headers.get("x-forwarded-host", request.headers.get("host", "")),
                "X-Forwarded-Uri": request.url.path + (("?" + request.url.query) if request.url.query else ""),
            }
            if ua := request.headers.get("user-agent"):
                headers["User-Agent"] = ua

            auth_resp = await client.get(url, cookies=request.cookies, headers=headers)

            if auth_resp.status_code in (200, 202):
                user = user_from_headers(headers=auth_resp.headers)
                if forward_headers:
                    _save_headers_for_middleware(request, user)
                return user

        except Exception as e:
            logger.error(f"Auth Service unreachable: {e}")

    return User()




class CustomHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 2. Check if authenticate() saved any auth_headers onto request.state
        auth_headers = getattr(request.state, "auth_headers", None)
        if auth_headers:
            for k, v in auth_headers.items():
                response.headers[k] = v

        return response