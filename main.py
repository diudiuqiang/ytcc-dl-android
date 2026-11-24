#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ytcc-android — 手机上从 CookieCloud 拉 cookie 并下载国内四站视频。

Kivy 单页界面，所有耗时操作（拉取 cookie / 下载）放后台线程，日志回主线程。
"""
import os
import sys
import json
import threading
import traceback

from kivy.app import App
from kivy.core.text import LabelBase
from kivy.uix.label import Label as KivyLabel
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.checkbox import CheckBox
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.utils import platform

# vendor/yt_dlp 必须进导入路径：APK 内 p4a 只把 source.dir 根加进 sys.path，
# vendor 子目录不会自动可导入。不补这行，下载时 import yt_dlp 直接崩。
_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_HERE, "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import ytcc_core as core

IS_ANDROID = platform == "android"
VERSION = core.__version__

# --- 全局中文字体：Kivy 默认字体无中文字形，手机上会显示成方块 ---
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
FONT_PATH = os.path.join(FONT_DIR, "msyh.ttc")
try:
    LabelBase.register(name="CJK", fn_regular=FONT_PATH)
    # 让所有默认 Label / Button / Spinner / TextInput 统一用中文字体
    KivyLabel.font_name = "CJK"
except Exception:
    pass  # 字体缺失时降级，至少不崩

# ---------------------------------------------------------------------------
# 路径与配置持久化
#   - 下载目录：Android 公共 Download/ytcc-dl（用户可见、可分享）
#   - 配置文件：app 私有目录（p4a 下 __file__ 所在目录可写且随 app 卸载清除）
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if IS_ANDROID:
    from android.permissions import request_permissions, Permission
    request_permissions([Permission.INTERNET, Permission.WRITE_EXTERNAL_STORAGE,
                         Permission.READ_EXTERNAL_STORAGE])
    # p4a 环境：ANDROID_STORAGE 通常指向 /storage/emulated/0；兜底标准路径
    _public = os.environ.get("ANDROID_STORAGE") or "/storage/emulated/0"
    APP_DIR = os.path.join(_public, "Download", "ytcc-dl")
    CFG_PATH = os.path.join(_HERE, "config.json")
else:
    APP_DIR = os.path.join(_HERE, "Downloads")
    CFG_PATH = os.path.join(_HERE, "config.json")

try:
    os.makedirs(APP_DIR, exist_ok=True)
except Exception:
    # 公共目录不可写时退回私有目录，保证至少能下载
    APP_DIR = os.path.join(_HERE, "downloads")
    os.makedirs(APP_DIR, exist_ok=True)


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def save_cfg(d):
    try:
        os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
        with open(CFG_PATH, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
    except Exception:
        pass  # 存不了配置不影响主流程


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def _wrap(widget, pad="8dp"):
    """把 Label 的 text_size 绑定到自身宽度，长中文自动换行而不是被左右裁掉。"""
    def _set(inst, width):
        inst.text_size = (max(width - 8, 1), inst.height or None)
    widget.bind(width=_set)
    return widget


class Root(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding="10dp", spacing="7dp", **kw)
        cfg = load_cfg()

        # 标题：两行分开、左对齐并绑定宽度，避免超宽被裁
        title = _wrap(Label(
            text=f"[b]ytcc-dl 手机版 v{VERSION}[/b]", markup=True,
            font_size="18sp", halign="left", valign="middle",
            size_hint_y=None, height="24dp"))
        self.add_widget(title)
        sub = _wrap(Label(
            text="国内四站 · CookieCloud 拉 cookie · 局域网",
            font_size="12sp", halign="left", valign="middle",
            color=(0.6, 0.6, 0.6, 1), size_hint_y=None, height="18dp"))
        self.add_widget(sub)

        # --- CookieCloud 配置 ---
        # 标签固定列宽 76dp + 文字精简，杜绝「CookieCloud 地址」被切成「ookieCloud 地」
        form = GridLayout(cols=2, spacing="6dp", size_hint_y=None,
                          row_default_height="42dp", row_force_default=True)
        form.bind(minimum_height=form.setter("height"))
        _ti = {"font_name": "CJK"} if Label.font_name == "CJK" else {}

        def _label(text):
            return Label(text=text, font_size="14sp", halign="left", valign="middle",
                         size_hint_x=None, width="76dp")

        form.add_widget(_label("地址"))
        self.host = TextInput(text=cfg.get("host", "http://192.168.31.116:10888"),
                              hint_text="http://192.168.31.116:10888", multiline=False,
                              font_size="14sp", **_ti)
        form.add_widget(self.host)

        form.add_widget(_label("UUID"))
        self.uuid = TextInput(text=cfg.get("uuid", ""), hint_text="CookieCloud UUID",
                              multiline=False, font_size="14sp", **_ti)
        form.add_widget(self.uuid)

        form.add_widget(_label("密码"))
        self.password = TextInput(text=cfg.get("password", ""), hint_text="CookieCloud 密码",
                                  multiline=False, password=True, font_size="14sp", **_ti)
        form.add_widget(self.password)

        form.add_widget(_label("平台"))
        self.platform = Spinner(
            text=cfg.get("platform", "抖音 (Douyin)"),
            values=list(core.PLATFORMS.keys()), font_size="14sp")
        form.add_widget(self.platform)

        form.add_widget(_label("画质"))
        self.quality = Spinner(
            text=cfg.get("quality", "最佳(单流)"),
            values=list(core.QUALITY_PRESETS.keys()), font_size="14sp")
        form.add_widget(self.quality)

        form.add_widget(_label("链接"))
        self.url = TextInput(hint_text="粘贴 v.douyin.com / b23.tv / t.cn 短链均可",
                             multiline=False, font_size="14sp", **_ti)
        form.add_widget(self.url)
        self.add_widget(form)

        # 开关单独一行：CheckBox 固定宽，文字左对齐换行（不再和按钮挤一行）
        opt = BoxLayout(size_hint_y=None, height="28dp", spacing="8dp")
        self.use_cookie = CheckBox(active=True, size_hint_x=None, width="34dp")
        opt.add_widget(self.use_cookie)
        opt.add_widget(_wrap(Label(
            text="拉取并使用 cookie（抖音可免 cookie）", font_size="13sp",
            halign="left", valign="middle", size_hint_x=1)))
        self.add_widget(opt)

        # 两个按钮单独一行，各占一半，size_hint_x 合计=1（原来 1.47 导致重叠）
        btns = BoxLayout(size_hint_y=None, height="46dp", spacing="10dp")
        btn_pull = Button(text="只测试拉取", font_size="14sp", size_hint_x=0.5)
        btn_pull.bind(on_press=lambda _: self.start_pull_only())
        btns.add_widget(btn_pull)
        self.btn_dl = Button(text="开始下载", font_size="14sp", size_hint_x=0.5)
        self.btn_dl.bind(on_press=lambda _: self.start_download())
        btns.add_widget(self.btn_dl)
        self.add_widget(btns)

        # 提示行：路径缩短 + 换行（完整路径写进日志，避免横向溢出）
        hint = _wrap(Label(
            text="保存到 Download/ytcc-dl · 抖音已内置签名补丁，可不勾 cookie 直接下。",
            font_size="11sp", halign="left", valign="top",
            color=(0.6, 0.6, 0.6, 1), size_hint_y=None, height="30dp"))
        self.add_widget(hint)

        # 日志
        self.log_view = TextInput(readonly=True, multiline=True, font_size="13sp",
                                  font_name="CJK" if Label.font_name == "CJK" else "Roboto",
                                  background_color=(0.08, 0.08, 0.1, 1),
                                  foreground_color=(0.85, 0.9, 0.85, 1))
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(self.log_view)
        self.add_widget(scroll)

        self._log(f"ytcc-dl v{VERSION} 就绪（{'Android' if IS_ANDROID else '桌面预览'}）")
        self._log(f"保存目录：{APP_DIR}")
        self._log("首次使用请填 UUID 和密码，点「只测试拉取」验证。")

    # --- 日志线程安全 ---
    def _log(self, msg):
        def _do(_):
            self.log_view.text += f"{msg}\n"
            self.log_view.cursor = (0, len(self.log_view.text))
        Clock.schedule_once(_do, 0)

    def _fields(self):
        return {
            "host": self.host.text.strip(),
            "uuid": self.uuid.text.strip(),
            "password": self.password.text.strip(),
            "platform": self.platform.text,
            "quality": self.quality.text,
        }

    def _save_fields(self):
        save_cfg(self._fields())

    def _busy(self, on):
        def _do(_):
            self.btn_dl.disabled = on
            self.btn_dl.text = "下载中…" if on else "开始下载"
        Clock.schedule_once(_do, 0)

    # --- 拉取测试 ---
    def start_pull_only(self):
        f = self._fields()
        self._save_fields()
        if not all((f["host"], f["uuid"], f["password"])):
            self._log("✗ 请先填写 CookieCloud 地址 / UUID / 密码")
            return
        threading.Thread(target=self._pull_worker, args=(f,), daemon=True).start()

    def _pull_worker(self, f):
        try:
            self._log(f"▶ 测试拉取 {f['host']} …")
            plat = f["platform"]
            conf = core.PLATFORMS.get(plat, {})
            txt, n = core.fetch_cookies(f["host"], f["uuid"], f["password"],
                                        tuple(conf.get("domains", ())))
            self._log(f"✓ 拉取成功：{n} 条 {plat} cookie")
            if n == 0:
                self._log("⚠ 该平台 cookie 为 0：可能是上传时未包含此站域名，或该站本就免 cookie 可下。")
        except Exception as e:
            self._log(f"✗ 拉取失败：{e}")

    # --- 下载 ---
    def start_download(self):
        f = self._fields()
        url = self.url.text.strip()
        ok, msg = core.is_valid_media_url(url)
        if not ok:
            self._log(f"✗ {msg}")
            return
        detected = core.detect_platform(url)
        if detected and detected != f["platform"]:
            self._log(f"ℹ 链接看起来是 {detected}，当前选择 {f['platform']}（按所选平台处理）")
        self._save_fields()
        self._busy(True)
        threading.Thread(target=self._download_worker,
                         args=(f, url, self.use_cookie.active), daemon=True).start()

    def _download_worker(self, f, url, use_cookie):
        cookies_path = None
        try:
            if use_cookie:
                if not all((f["host"], f["uuid"], f["password"])):
                    raise RuntimeError("勾选了使用 cookie，但未填全 CookieCloud 凭据")
                self._log("▶ 拉取 cookie…")
                conf = core.PLATFORMS.get(f["platform"], {})
                txt, n = core.fetch_cookies(f["host"], f["uuid"], f["password"],
                                            tuple(conf.get("domains", ())))
                cookies_path = os.path.join(APP_DIR, "_cookies.txt")
                with open(cookies_path, "w", encoding="utf-8") as fh:
                    fh.write(txt)
                self._log(f"✓ cookie {n} 条")
            else:
                self._log("ℹ 不使用 cookie（免登录模式）")

            fmt = core.build_format(f["quality"])
            self._log(f"▶ 开始下载 [{f['platform']}] [{f['quality']}]\n{fmt}")
            ok, path, err = core.run_download(
                url, cookies_path, APP_DIR, lambda m: self._log(m),
                fmt=fmt, platform=f["platform"])
            if ok:
                size = os.path.getsize(path) / 1024 / 1024 if path else 0
                self._log(f"✓ 完成：{os.path.basename(path)}（{size:.1f} MB）")
                self._log(f"📁 {path}")
            else:
                self._log(f"✗ 失败：{err}")
        except Exception as e:
            self._log(f"✗ 出错：{type(e).__name__}: {e}")
            self._log(traceback.format_exc(limit=3))
        finally:
            if cookies_path and os.path.exists(cookies_path):
                try:
                    os.remove(cookies_path)
                except Exception:
                    pass
            self._busy(False)


class YtccApp(App):
    title = "ytcc-dl 手机版"

    def build(self):
        Window.softinput_mode = "below_target"
        return Root()


if __name__ == "__main__":
    YtccApp().run()
