from __future__ import annotations
import base64
import html
import json
import mimetypes
import re
import sys
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any
import requests


PROMPT = """cat and a dog """  #promt


IMAGE_SOURCE = " " # Image link or path 
MODEL = "Kuvu 1.0" #model 
RESOLUTION = "720p"  #4k #1080p #720p
ASPECT_RATIO = "1:1"  #16:9  #9:16 #1:1  #4:3  #3:4
DURATION = 4  #4 #6 #8 #10 #15  

MAIL_API = "https://api.mail.tm"
KUVU_API = "https://kuvu.ai"
KUVU_HOME = f"{KUVU_API}/home"
REQUEST_TIMEOUT = 20
MAIL_WAIT_LIMIT = 600
VIDEO_WAIT_LIMIT = 1800
POLL_DELAY = 5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)

RESET = "\033[0m"
CYAN = "\033[38;5;81m"
BLUE = "\033[38;5;111m"
PURPLE = "\033[38;5;141m"
GREEN = "\033[38;5;114m"
YELLOW = "\033[38;5;221m"
RED = "\033[38;5;203m"
DIM = "\033[2m"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

KUVU_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "no-cache",
    "content-type": "application/json",
    "origin": KUVU_API,
    "pragma": "no-cache",
    "sec-ch-ua": '"Chromium";v="139", "Not;A=Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": USER_AGENT,
}


class WorkflowError(RuntimeError):
    pass


def request_json(session: requests.Session, method: str, url: str, **kwargs: Any) -> Any:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    response = session.request(method, url, **kwargs)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise WorkflowError(f"Invalid JSON response from {url}") from exc


def image_data(value: str) -> str:
    value = value.strip()
    if value.startswith(("http://", "https://", "data:image/")):
        return value
    path = Path(value).expanduser()
    if not path.is_file():
        raise WorkflowError(f"Image file was not found: {path}")
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type or not mime_type.startswith("image/"):
        raise WorkflowError(f"Unsupported image file: {path}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def video_options() -> dict[str, Any]:
    images = []
    if IMAGE_SOURCE.strip():
        images.append(image_data(IMAGE_SOURCE))
    if not PROMPT.strip():
        raise WorkflowError("PROMPT cannot be empty")
    return {
        "prompt": PROMPT.strip(),
        "model": MODEL,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration": DURATION,
        "return_last_frame": False,
        "generationType": "",
        "enableFallback": False,
        "enableTranslation": False,
        "input": {"images": images, "videos": [], "audios": []},
    }


def mailbox_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"accept": "application/json", "user-agent": USER_AGENT})
    return session


def create_mailbox(session: requests.Session) -> tuple[str, str]:
    domains = request_json(session, "GET", f"{MAIL_API}/domains?page=1")
    domains = domains if isinstance(domains, list) else domains.get("hydra:member", [])
    active = next((item.get("domain") for item in domains if item.get("isActive")), None)
    if not active:
        raise WorkflowError("No active service domain is available")
    address = f"kuvu{uuid.uuid4().hex[:16]}@{active}"
    password = f"{uuid.uuid4().hex}Aa1!"
    account = request_json(
        session,
        "POST",
        f"{MAIL_API}/accounts",
        json={"address": address, "password": password},
    )
    account_id = account.get("id")
    token_data = request_json(
        session,
        "POST",
        f"{MAIL_API}/token",
        json={"address": address, "password": password},
    )
    token = token_data.get("token")
    if not account_id or not token:
        raise WorkflowError("Could not initialize the secure session")
    session.headers.update({"authorization": f"Bearer {token}"})
    return address, str(account_id)


def normalize(value: str) -> str:
    for _ in range(3):
        value = html.unescape(value)
        value = urllib.parse.unquote(value)
        value = value.replace("\\/", "/").replace("\\", "")
    return value


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(strings(item))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(strings(item))
        return result
    return []


def magic_link(value: Any) -> str | None:
    for item in strings(value):
        match = re.search(
            r"https?://(?:www\.)?kuvu\.ai/api/auth/magic-link/verify\?token=[^\s\"'<>,)\\]+",
            normalize(item),
        )
        if match:
            return match.group(0).rstrip(".;")
    return None


def wait_for_link(session: requests.Session, account_id: str) -> str:
    del account_id
    started = time.monotonic()
    seen: set[str] = set()
    check = 0
    while time.monotonic() - started < MAIL_WAIT_LIMIT:
        payload = request_json(session, "GET", f"{MAIL_API}/messages?page=1")
        messages = payload if isinstance(payload, list) else payload.get("hydra:member", [])
        for summary in messages:
            message_id = summary.get("id")
            if not message_id or message_id in seen:
                continue
            seen.add(message_id)
            message = request_json(session, "GET", f"{MAIL_API}/messages/{message_id}")
            link = magic_link(message)
            if link:
                print()
                return link
        elapsed = int(time.monotonic() - started)
        frame = SPINNER[check % len(SPINNER)]
        print(f"\r{CYAN}{frame} Preparing secure session... {elapsed}s{RESET}", end="", flush=True)
        check += 1
        time.sleep(POLL_DELAY)
    print()
    raise WorkflowError("The secure session could not be prepared in time")


def request_login(address: str) -> None:
    response = requests.post(
        f"{KUVU_API}/api/auth/sign-in/magic-link",
        headers={**KUVU_HEADERS, "referer": f"{KUVU_API}/signin?from=%2Fhome"},
        json={"email": address, "callbackURL": KUVU_HOME},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise WorkflowError("The service returned an invalid login response") from exc
    if not payload.get("status"):
        raise WorkflowError("The login request was rejected")


def authenticated_session(link: str) -> requests.Session:
    session = requests.Session()
    response = session.get(
        link,
        headers={**KUVU_HEADERS, "referer": f"{KUVU_API}/"},
        allow_redirects=True,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    token = session.cookies.get("__Secure-better-auth.session_token")
    if not token:
        raise WorkflowError("Could not create the authenticated session")
    session.headers.update(
        {
            **KUVU_HEADERS,
            "referer": KUVU_HOME,
            "cookie": f"__Secure-better-auth.session_token={token}",
        }
    )
    return session


def submit(session: requests.Session, options: dict[str, Any]) -> tuple[str, str]:
    payload = {
        **options,
        "videoPrompt": options["prompt"],
        "videoModel": options["model"],
        "quality": options["resolution"],
        "aspectRatio": options["aspect_ratio"],
    }
    data = request_json(
        session,
        "POST",
        f"{KUVU_API}/api/ai-video/text-to-video/gen",
        json=payload,
    )
    try:
        return str(data["taskId"]), str(data["request"])
    except (KeyError, TypeError) as exc:
        raise WorkflowError("The generation request was not accepted") from exc


def wait_for_video(session: requests.Session, task_id: str, request_id: str) -> str:
    payload = {
        "taskId": task_id,
        "taskIds": [task_id],
        "request": request_id,
        "finalize": True,
    }
    started = time.monotonic()
    check = 0
    while time.monotonic() - started < VIDEO_WAIT_LIMIT:
        data = request_json(
            session,
            "POST",
            f"{KUVU_API}/api/ai-video/text-to-video/get",
            json=payload,
        )
        status = data.get("status") if isinstance(data, dict) else None
        elapsed = int(time.monotonic() - started)
        if status == "SUCCESS":
            print(f"\n{GREEN}Completed in {elapsed}s{RESET}")
            return data.get("videoUrl", "")
        if status == "RUNNING":
            frame = SPINNER[check % len(SPINNER)]
            print(f"\r{YELLOW}{frame} Generating video... {elapsed}s{RESET}", end="", flush=True)
            check += 1
            time.sleep(POLL_DELAY)
            continue
        raise WorkflowError(data.get("errorMessage", "Video generation failed"))
    raise WorkflowError("Video generation exceeded the time limit")


def run() -> None:
    options = video_options()
    print(f"{BLUE}Starting video generation {SPINNER[0]}{RESET}")
    session = mailbox_session()
    address, account_id = create_mailbox(session)
    request_login(address)
    link = wait_for_link(session, account_id)
    kuvu = authenticated_session(link)
    task_id, request_id = submit(kuvu, options)
    result = wait_for_video(kuvu, task_id, request_id)
    print(f"{GREEN}Video URL:{RESET} {result}")


def main() -> None:
    try:
        run()
    except (requests.RequestException, WorkflowError, KeyboardInterrupt) as exc:
        print(f"\n{RED}Error: {exc}{RESET}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
