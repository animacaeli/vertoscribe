"""抖音视频解析与下载（yt-dlp 对抖音已失效，走 Web API + a_bogus 签名）。

流程：分享链接 → 视频 ID → ttwid 游客 cookie → aweme detail API（a_bogus 签名）
→ 无水印直链 → 流式下载。无需登录。

参考实现：douyin_parse 项目（Evil0ctal / JoeanAmier 的 a_bogus 算法，见 _abogus.py）。
"""
from __future__ import annotations

import os
import re

import requests
from urllib.parse import quote, urlencode

from ._abogus import ABogus

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

# 与抖音 Web 端一致的基础请求参数
_BASE_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "pc_client_type": "1",
    "version_code": "190500",
    "version_name": "19.5.0",
    "cookie_enabled": "true",
    "browser_language": "zh-CN",
    "browser_platform": "Win32",
    "browser_name": "Edge",
    "browser_online": "true",
    "engine_name": "Blink",
    "os_name": "Windows",
    "os_version": "10",
    "platform": "PC",
    "screen_width": "1920",
    "screen_height": "1080",
}

_ID_PATTERNS = [
    r"/video/(\d+)",
    r"/aweme/detail/(\d+)",
    r"/note/(\d+)",
    r"(?:video|aweme|note)_id=(\d+)",
]

# 模块级缓存，避免每次下载都注册一遍 ttwid
_ttwid: str | None = None


class DouyinDownloadError(Exception):
    """抖音解析/下载异常，携带用户可读的错误信息。"""


def is_douyin_url(url: str) -> bool:
    """判断链接是否为抖音链接（分享短链或 www.douyin.com 页面）。"""
    return bool(re.search(r"(?:^|\.)douyin\.com|iesdouyin\.com", url.lower()))


def _get_ttwid() -> str:
    """通过字节官方接口注册游客 ttwid cookie（无需登录）。"""
    global _ttwid
    if _ttwid:
        return _ttwid
    try:
        resp = requests.post(
            "https://ttwid.bytedance.com/ttwid/union/register/",
            json={
                "region": "cn",
                "aid": 1768,
                "needFid": False,
                "service": "www.ixigua.com",
                "migrate_info": {"ticket": "", "source": "node"},
                "cbUrlProtocol": "https",
                "union": True,
            },
            timeout=15,
        )
        for cookie in resp.cookies:
            if cookie.name == "ttwid" and cookie.value:
                _ttwid = cookie.value
                return _ttwid
    except requests.RequestException:
        pass
    raise DouyinDownloadError("获取抖音游客凭证（ttwid）失败，请检查网络后重试")


def _build_headers(referer: str) -> dict:
    return {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer,
        "Origin": "https://www.douyin.com",
        "Cookie": f"ttwid={_get_ttwid()}",
    }


def get_video_id(share_url: str) -> str:
    """从分享链接 / 页面链接 / 含链接的分享文本中提取视频 ID。"""
    # 遇到中文字符即截断，避免分享文案中 URL 后紧跟的中文被吞进链接
    url_match = re.search(r"https?://[^\s\u4e00-\u9fff]+", share_url) or re.search(
        r"(?:v\.douyin\.com|douyin\.com)/[^\s\u4e00-\u9fff]+", share_url
    )
    extracted = url_match.group(0) if url_match else share_url.strip()
    if not extracted.startswith("http"):
        extracted = "https://" + extracted

    for pattern in _ID_PATTERNS:
        if match := re.search(pattern, extracted):
            return match.group(1)

    # 短链需要跟随重定向拿到真实地址
    try:
        resp = requests.get(
            extracted,
            headers={"User-Agent": _USER_AGENT, "Referer": "https://www.douyin.com/"},
            allow_redirects=True,
            timeout=15,
        )
        for pattern in _ID_PATTERNS:
            if match := re.search(pattern, resp.url):
                return match.group(1)
        for pattern in _ID_PATTERNS:
            if match := re.search(pattern, resp.text):
                video_id = match.group(1)
                if video_id.isdigit() and len(video_id) >= 15:
                    return video_id
    except requests.RequestException as exc:
        raise DouyinDownloadError(f"访问抖音分享链接失败: {exc}") from exc

    raise DouyinDownloadError("无法从链接中解析出视频 ID，链接可能已失效")


def fetch_aweme_detail(share_url: str) -> dict:
    """调用 aweme detail API，返回 aweme_detail 字典。"""
    video_id = get_video_id(share_url)
    params = _BASE_PARAMS | {"aweme_id": video_id}
    api_url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

    param_str = urlencode(params)
    a_bogus = ABogus().get_value(params)
    signed_url = f"{api_url}?{param_str}&a_bogus={quote(a_bogus, safe='')}"

    referers = dict.fromkeys((
        f"https://www.douyin.com/note/{video_id}" if "/note/" in share_url
        else f"https://www.douyin.com/video/{video_id}",
        f"https://www.douyin.com/note/{video_id}",
        f"https://www.douyin.com/video/{video_id}",
    ))

    def _try_fetch() -> dict | None:
        headers = _build_headers(next(iter(referers), ""))
        for ref in referers:
            headers["Referer"] = ref
            try:
                resp = requests.get(signed_url, headers=headers, timeout=15)
                if resp.status_code == 200 and resp.content:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("status_code") == 0:
                        detail = data.get("aweme_detail")
                        if detail:
                            return detail
            except requests.RequestException:
                continue
        return None

    detail = _try_fetch()
    if detail is None:
        global _ttwid
        if _ttwid:
            # 缓存的 ttwid 可能已过期，刷新后重试一次
            _ttwid = None
            detail = _try_fetch()

    if detail is None:
        raise DouyinDownloadError(
            "抖音视频详情获取失败，视频可能已被删除或设为私密"
        )
    return detail


def get_video_info(share_url: str) -> dict:
    """解析视频，返回 {title, video_url}（无水印直链）。图集类内容暂不支持。"""
    detail = fetch_aweme_detail(share_url)

    if detail.get("images"):
        raise DouyinDownloadError("该链接为图集作品，vertoscribe 仅支持视频内容")

    video = detail.get("video") or {}
    # 不依赖 API 返回顺序，按码率显式降序后取最优
    bit_rates = sorted(
        (br for br in video.get("bit_rate") or [] if isinstance(br, dict)),
        key=lambda br: br.get("bit_rate", 0),
        reverse=True,
    )
    candidates: list[str] = []
    for br in bit_rates:
        candidates.extend((br.get("play_addr") or {}).get("url_list") or [])
    candidates.extend((video.get("play_addr") or {}).get("url_list") or [])

    # playwm → play 即无水印地址
    for url in candidates:
        if url:
            return {
                "title": detail.get("desc") or "",
                "video_url": url.replace("playwm", "play"),
            }

    raise DouyinDownloadError("未能从视频详情中提取到可用的播放地址")


def get_title(share_url: str) -> str:
    """获取视频标题（desc）。"""
    return get_video_info(share_url)["title"] or "douyin_video"


def download_video(share_url: str, output_dir: str) -> str:
    """下载无水印视频到 output_dir/video.mp4，返回绝对路径。"""
    info = get_video_info(share_url)
    out_path = os.path.join(output_dir, "video.mp4")

    resp = requests.get(
        info["video_url"],
        headers={"User-Agent": _USER_AGENT, "Referer": "https://www.douyin.com/"},
        stream=True,
        timeout=60,
    )
    if resp.status_code != 200:
        raise DouyinDownloadError(f"视频下载失败，HTTP {resp.status_code}")

    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            if chunk:
                f.write(chunk)

    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise DouyinDownloadError("视频下载完成但文件为空，请重试")

    return os.path.abspath(out_path)
