#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ytcc-android 核心逻辑：CookieCloud 拉取 + 短链解析 + yt-dlp 下载。

与桌面版 ytcc_dl.py 同源，但为 Android 精简：
  - 无 tkinter / DPAPI / Windows 路径 / 代理 / deno / ffmpeg 重编码
  - AES 解密用纯 Python（pure_aes），避免 p4a 编译 cryptography
  - 只下国内四站：B站 / 抖音 / 微博 / 小红书
  - 单流直出 mp4（format=best[ext=mp4]/best），无 ffmpeg 合并 → APK 更轻更稳
"""

import os
import re
import json
import base64
import hashlib
import urllib.request
import urllib.parse

import pure_aes

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# 平台配置（与桌面版同域名表，去掉海外三站）
# ---------------------------------------------------------------------------
PLATFORMS = {
    "B站 (Bilibili)": {
        "domains": ("bilibili.com", "b23.tv"),
        "need_cookie": False,
        "note": "公开视频免登录；高清需 cookie",
        "extra_opts": {"http_headers": {"Referer": "https://www.bilibili.com/"}},
    },
    "抖音 (Douyin)": {
        "domains": ("douyin.com", "v.douyin.com"),
        "need_cookie": False,
        "note": "已内置 x-secsdk 签名补丁，免 cookie 可下",
    },
    "微博 (Weibo)": {
        "domains": ("weibo.com", "weibo.cn", "t.cn"),
        "need_cookie": False,
        "note": "公开视频免登录；支持 t.cn 短链",
    },
    "小红书 (Xiaohongshu)": {
        "domains": ("xiaohongshu.com", "xhslink.com", "xhslink.cn"),
        "need_cookie": False,
        "note": "部分内容需 cookie；支持 xhslink 短链",
    },
}

PLATFORM_HOST_HINTS = {
    "bilibili.com": "B站 (Bilibili)", "b23.tv": "B站 (Bilibili)",
    "douyin.com": "抖音 (Douyin)", "v.douyin.com": "抖音 (Douyin)",
    "weibo.com": "微博 (Weibo)", "weibo.cn": "微博 (Weibo)", "t.cn": "微博 (Weibo)",
    "xiaohongshu.com": "小红书 (Xiaohongshu)",
    "xhslink.com": "小红书 (Xiaohongshu)", "xhslink.cn": "小红书 (Xiaohongshu)",
}

SHORT_LINK_HOSTS = {"t.cn", "v.douyin.com", "xhslink.com", "xhslink.cn"}

QUALITY_PRESETS = {
    "1080p": "best[height<=1080][ext=mp4]/best[height<=1080]/best",
    "720p": "best[height<=720][ext=mp4]/best[height<=720]/best",
    "最佳(单流)": "best[ext=mp4]/best",
    "仅音频": "bestaudio/best",
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _host_of(url):
    try:
        return urllib.parse.urlparse(url or "").netloc.lower()
    except Exception:
        return ""


def _domain_matches(key, domains):
    k = (key or "").lower()
    for d in domains:
        d = d.lower()
        if k == d or k.endswith("." + d):
            return True
    return False


def detect_platform(url):
    host = _host_of(url)
    if not host:
        return None
    for h, plat in PLATFORM_HOST_HINTS.items():
        if host == h or host.endswith("." + h):
            return plat
    return None


def is_valid_media_url(url):
    s = (url or "").strip()
    if not s:
        return False, "链接不能为空"
    if re.match(r'^[A-Za-z]:[\\/]', s):
        return False, "这看起来是本地文件路径，不是视频链接"
    if s.lower().startswith("file:"):
        return False, "不支持 file:// 协议，请粘贴网页视频地址"
    if not re.match(r'^https?://', s, re.I):
        return False, "链接必须以 http:// 或 https:// 开头"
    return True, ""


def build_format(quality):
    return QUALITY_PRESETS.get(quality, QUALITY_PRESETS["最佳(单流)"])


# ---------------------------------------------------------------------------
# CookieCloud：拉取 + 纯 Python 解密
# ---------------------------------------------------------------------------
def evp_bytes_to_key(passphrase, salt, key_len=32, iv_len=16):
    dtot, d = b"", b""
    while len(dtot) < key_len + iv_len:
        d = hashlib.md5(d + passphrase + salt).digest()
        dtot += d
    return dtot[:key_len], dtot[key_len:key_len + iv_len]


def fetch_cookies(host, uuid, password, domains):
    """从 CookieCloud 拉密文、解密，返回指定域名的 Netscape cookie 文本和条数。

    Android 上 CookieCloud 走局域网（如 http://192.168.31.116:10888），
    必须强制直连，不能走系统代理。domain 严格按边界匹配。
    """
    host = (host or "").rstrip("/")
    if not host or not uuid or not password:
        raise RuntimeError("请填写完整的 CookieCloud 地址、UUID 和密码")
    url = f"{host}/get/{uuid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=25) as r:
            raw = r.read()
    except Exception as e:
        raise RuntimeError(
            f"连不上 CookieCloud（{type(e).__name__}: {e}）。"
            f"请确认手机和 NAS 在同一 WiFi，且地址可在手机浏览器打开：{url}") from e
    try:
        resp = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"CookieCloud 返回的不是合法 JSON：{e}") from e
    enc = resp.get("encrypted")
    if not enc:
        raise RuntimeError(f"CookieCloud 响应缺少 encrypted 字段：{list(resp.keys())}")
    data = base64.b64decode(enc)
    if data[:8] != b"Salted__":
        raise RuntimeError("CookieCloud 数据不是 OpenSSL Salted__ 格式")
    salt, ct = data[8:16], data[16:]
    keystr = hashlib.md5((uuid + "-" + password).encode()).hexdigest()[:16]
    key, iv = evp_bytes_to_key(keystr.encode("utf-8"), salt)
    plain = pure_aes.cbc_decrypt(ct, key, iv)
    pad = plain[-1] if plain else 0
    if pad < 1 or pad > 16 or pad > len(plain):
        raise RuntimeError("解密失败：填充非法（UUID 或密码错误？）")
    plain = plain[:-pad]
    try:
        payload = json.loads(plain.decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"解密后不是合法 JSON：{e}") from e
    cookie_data = payload.get("cookie_data", {})

    def clean(s):
        return "" if s is None else str(s).replace("\t", " ").replace("\n", " ").replace("\r", " ")

    lines = ["# Netscape HTTP Cookie File"]
    count = 0
    for dom, cookies in cookie_data.items():
        if not _domain_matches(dom, domains):
            continue
        for c in cookies:
            name = clean(c.get("name", ""))
            if not name:
                continue
            value = clean(c.get("value", ""))
            path = clean(c.get("path", "/")) or "/"
            secure = "TRUE" if c.get("secure") else "FALSE"
            exp = c.get("expirationDate") or c.get("expires") or c.get("expiry") or 0
            try:
                exp = int(float(exp))
            except Exception:
                exp = 0
            domain = clean(c.get("domain") or dom)
            if not domain.startswith("."):
                domain = "." + domain
            lines.append(f"{domain}\tFALSE\t{path}\t{secure}\t{exp}\t{name}\t{value}")
            count += 1
    return "\n".join(lines) + "\n", count


# ---------------------------------------------------------------------------
# 短链解析（与桌面版同源，国内四站）
# ---------------------------------------------------------------------------
def _unwrap_weibo_passport(url):
    try:
        p = urllib.parse.urlparse(url or "")
        if "passport.weibo.com" in p.netloc:
            real = urllib.parse.parse_qs(p.query).get("url", [None])[0]
            if real:
                return real
    except Exception:
        pass
    return url


def _is_xhs_note(url):
    try:
        p = urllib.parse.urlparse(url or "")
        return "xiaohongshu.com" in p.netloc and ("/explore/" in url or "/discovery/item/" in url)
    except Exception:
        return False


def _extract_redirect_path(url):
    try:
        p = urllib.parse.urlparse(url or "")
        for key in ("redirectPath", "redirect_url", "target_url"):
            cand = urllib.parse.parse_qs(p.query).get(key, [None])[0]
            if cand:
                cand = urllib.parse.unquote(cand)
                if _is_xhs_note(cand):
                    return cand
        m = re.search(r'(?:redirectPath|redirect_url|target_url)=(https?%3A%2F%2F[^&\s]+)', url or "")
        if m:
            cand = urllib.parse.unquote(m.group(1))
            if _is_xhs_note(cand):
                return cand
    except Exception:
        pass
    return None


def _ensure_xhs_www(url):
    try:
        p = urllib.parse.urlparse(url or "")
        if p.netloc.lower() == "xiaohongshu.com":
            return urllib.parse.urlunparse(p._replace(netloc="www.xiaohongshu.com"))
    except Exception:
        pass
    return url


def _normalize_douyin(url):
    """把 iesdouyin.com/share/video/<id> 等分享页归一化成 DouyinIE 认的标准链接。"""
    try:
        p = urllib.parse.urlparse(url or "")
        m = re.search(r"/(?:share/)?video/(\d+)", p.path)
        if m and ("douyin.com" in p.netloc):
            # 标准 douyin.com/video 只换 host（保留查询串）；iesdouyin share 页重建干净链接
            if p.netloc.lower().endswith("douyin.com") and "/share/" not in p.path:
                return urllib.parse.urlunparse(p._replace(netloc="www.douyin.com"))
            return f"https://www.douyin.com/video/{m.group(1)}"
    except Exception:
        pass
    return url


def resolve_short_url(url, timeout=20):
    if not url or _host_of(url) not in SHORT_LINK_HOSTS:
        return None
    try:
        # 抖音短链必须用桌面 UA：实测 Android UA 会 302 到 iesdouyin.com/share/video/<id>
        # （补丁版 DouyinIE 不认），Windows UA 才给标准 douyin.com/video/<id>。
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as r:
            final = _unwrap_weibo_passport(r.geturl())
            if final and final.rstrip("/") != url.rstrip("/"):
                redir = _extract_redirect_path(final)
                result = _ensure_xhs_www(redir or final)
                return _normalize_douyin(result)
            body = r.read().decode("utf-8", "ignore")
            m = re.search(r'content=["\']\s*\d+;\s*url=([^"\']+)', body, re.I)
            if m:
                cand = urllib.parse.urljoin(url, m.group(1))
                return _normalize_douyin(_ensure_xhs_www(_extract_redirect_path(cand) or cand))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------
def run_download(url, cookies_path, out_dir, log_fn, fmt=None, platform=None):
    """调用 vendor 的 yt-dlp 下载。返回 (ok, 最终文件路径, 错误信息)。

    Android 简化：无 ffmpeg 合并、无重编码、无代理。format 优先单流 mp4，
    保证产出即 mp4，无需后处理。抖音签名补丁已在 vendor/yt_dlp 内。
    """
    import yt_dlp

    os.makedirs(out_dir, exist_ok=True)
    _state = {"last": -1.0}

    def progress_hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            pct = (got / total * 100) if total else 0.0
            if pct - _state["last"] >= 5.0 or pct >= 100:
                _state["last"] = pct
                spd = (d.get("speed") or 0) / 1024 / 1024
                log_fn(f"{pct:5.1f}%  {spd:.1f} MB/s")
        elif d.get("status") == "finished":
            log_fn("下载完成，正在保存…")

    # 短链先解析成真链
    resolved = resolve_short_url(url)
    if resolved and resolved != url:
        log_fn(f"短链解析：{url} → {resolved}")
        url = resolved

    ydl_opts = {
        "outtmpl": os.path.join(out_dir, "%(title).80s.%(ext)s"),
        "format": fmt or QUALITY_PRESETS["最佳(单流)"],
        "quiet": True,
        "no_warnings": True,
        "retries": 10,
        "fragment_retries": 10,
        "cookiefile": cookies_path if cookies_path and os.path.exists(cookies_path) else None,
        "progress_hooks": [progress_hook],
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 14; Find X9 Pro) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        },
    }
    conf = PLATFORMS.get(platform, {})
    for k, v in (conf.get("extra_opts") or {}).items():
        if k == "http_headers" and isinstance(v, dict):
            ydl_opts["http_headers"].update(v)
        else:
            ydl_opts[k] = v

    final = None
    err = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            for rd in reversed(info.get("requested_downloads") or []):
                fp = rd.get("filepath")
                if fp and os.path.exists(fp):
                    final = fp
                    break
            if not final:
                import glob
                title = info.get("title", "video")
                cands = [c for c in glob.glob(os.path.join(out_dir, title + ".*"))
                         if c.lower().endswith((".mp4", ".mkv", ".webm"))]
                final = cands[-1] if cands else None
        if not final:
            err = "下载完成但找不到输出文件"
        return final is not None, final, err
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"
