import socket
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def request_bytes(request, timeout=60, interval=0, attempts=3):
    """Serial requests; retry temporary failures without printing secrets."""
    for attempt in range(attempts):
        if interval:
            time.sleep(interval)
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError("HTTP {}：请检查接口地址、权限和请求配置".format(exc.code)) from None
            delay = 2 ** (attempt + 1)
            retry_after = exc.headers.get("Retry-After", "")
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                try:
                    delay = max(delay, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError):
                    pass
            if attempt == attempts - 1:
                raise RuntimeError("HTTP {}：重试后仍失败，稍后可继续运行".format(exc.code)) from None
            time.sleep(min(delay, 60))
        except (URLError, TimeoutError, socket.timeout):
            if attempt == attempts - 1:
                raise RuntimeError("网络请求失败或超时，稍后可继续运行") from None
            time.sleep(2 ** (attempt + 1))
