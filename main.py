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
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.checkbox import CheckBox
from kivy.uix.widget import Widget
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


# 私用：地址写死，省得每次手填；换 NAS 时改这一行重新编译即可。
COOKIECLOUD_HOST = "http://192.168.31.116:10888"


class MaskedPassword(FloatLayout):
    """密码展示/编辑控件：默认星号遮挡只露后两位，点一下切明文编辑，回车/失焦切回。

    ★ v2 修复（真机反馈"点密码框弹填充框、松手就没"）：旧实现用 Button.on_press +
    remove/add widget 切换，Android 上会触发系统自动填充弹窗且与焦点事件重入打架。
    新实现把「只读显示框」和「明文输入框」两个 TextInput 始终叠放在界面里，
    只用 opacity/disabled 切换，绝不 add/remove；显示框用 on_touch_down 主动拦截
    触摸后切到编辑态并聚焦，不会再弹系统填充框。

    明文只存在内存与本地 config.json（自动拉 cookie 必需）；遮挡只作用于界面。
    """
    def __init__(self, value="", **kw):
        super().__init__(**kw)
        self._value = value or ""
        self._editing = False
        _box = {"font_size": "14sp", "multiline": False,
                "size_hint": (1, 1), "pos_hint": {"x": 0, "y": 0},
                "padding": ["8dp", "8dp", "10dp", "10dp"]}

        # 显示态：只读，展示遮挡串；on_touch_down 主动接管触摸切编辑态
        self.display = TextInput(text=self._masked(), readonly=True, **_box)
        self.display.bind(on_touch_down=self._on_display_touch)
        self.add_widget(self.display)

        # 编辑态：明文输入，初始隐藏且禁用；始终在 widget 树里不移除
        self.editor = TextInput(text=self._value, opacity=0, disabled=True, **_box)
        self.editor.bind(on_text_validate=self._end_edit)
        self.editor.bind(focus=self._on_focus)
        self.add_widget(self.editor)

    @property
    def text(self):
        # 编辑中实时返回输入框内容，非编辑态返回已保存值
        return self.editor.text if self._editing else self._value

    def _masked(self):
        v = self._value
        if not v:
            return "点击设置密码"
        if len(v) <= 2:
            return "*" * len(v)
        return "*" * (len(v) - 2) + v[-2:]

    def _on_display_touch(self, inst, touch):
        if self._editing or not inst.collide_point(*touch.pos):
            return False
        # 拦截显示框的触摸，切到编辑态：显示框隐藏、明文框显示并聚焦全选
        self._editing = True
        self.editor.text = self._value
        self.display.opacity = 0
        self.display.disabled = True
        self.editor.opacity = 1
        self.editor.disabled = False
        self.editor.focus = True
        self.editor.select_all()
        return True  # 消费触摸，避免继续传给下层触发填充框

    def _on_focus(self, instance, has_focus):
        if self._editing and not has_focus:
            # 失焦（点了别处）切回遮挡态，延迟一帧避免事件重入
            Clock.schedule_once(lambda _: self._end_edit(), 0)

    def _end_edit(self, *args):
        if not self._editing:
            return
        self._value = self.editor.text.strip()
        self._editing = False
        self.display.text = self._masked()
        self.editor.opacity = 0
        self.editor.disabled = True
        self.editor.focus = False
        self.display.disabled = False
        self.display.opacity = 1


class Root(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=0, spacing=0, **kw)
        cfg = load_cfg()

        # ★ 关键：整个界面套一层 ScrollView。软键盘用 resize 模式弹出时窗口整体
        # 缩小，用户可上下滚动到任意输入框/按钮；表单固定高度不再随 minimum_height
        # 抖动，杜绝"输 UUID 时字符和输入框对不上、会跳"。
        outer = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        page = BoxLayout(orientation="vertical", padding="10dp", spacing="7dp",
                         size_hint_y=None)
        page.bind(minimum_height=page.setter("height"))
        outer.add_widget(page)
        self._page = page
        self.add_widget(outer)

        # 顶部状态栏留白：Kivy 在 Android 默认把内容画到状态栏下面，
        # 标题会被系统时间/信号/电量盖住。加一段透明占位把内容顶下来。
        if IS_ANDROID:
            page.add_widget(Widget(size_hint_y=None, height="26dp"))

        # 标题：两行分开、左对齐并绑定宽度，避免超宽被裁
        title = _wrap(Label(
            text=f"[b]ytcc-dl 手机版 v{VERSION}[/b]", markup=True,
            font_size="18sp", halign="left", valign="middle",
            size_hint_y=None, height="24dp"))
        page.add_widget(title)
        sub = _wrap(Label(
            text="国内四站 · CookieCloud 拉 cookie · 局域网",
            font_size="12sp", halign="left", valign="middle",
            color=(0.6, 0.6, 0.6, 1), size_hint_y=None, height="18dp"))
        page.add_widget(sub)

        # --- CookieCloud 配置 ---
        # 标签固定列宽 76dp + 文字精简，杜绝「CookieCloud 地址」被切成「ookieCloud 地」
        form = GridLayout(cols=2, spacing="6dp", size_hint_y=None,
                          row_default_height="46dp", row_force_default=True)
        form.bind(minimum_height=form.setter("height"))
        _ti = {"font_name": "CJK"} if Label.font_name == "CJK" else {}
        # 输入框垂直居中留白，文字不顶在框上沿（截图里 UUID 顶格的根因）
        _ti_pad = {"padding": ["8dp", "8dp", "12dp", "12dp"]}

        def _label(text):
            return Label(text=text, font_size="14sp", halign="left", valign="middle",
                         size_hint_x=None, width="76dp")

        form.add_widget(_label("地址"))
        host_view = _wrap(Label(
            text=COOKIECLOUD_HOST, font_size="14sp", halign="left", valign="middle",
            color=(0.75, 0.85, 1, 1)))
        form.add_widget(host_view)

        form.add_widget(_label("UUID"))
        self.uuid = TextInput(text=cfg.get("uuid", ""), hint_text="CookieCloud UUID",
                              multiline=False, font_size="14sp", **_ti, **_ti_pad)
        form.add_widget(self.uuid)

        form.add_widget(_label("密码"))
        self.password = MaskedPassword(value=cfg.get("password", ""))
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
                             multiline=False, font_size="14sp", **_ti, **_ti_pad)
        form.add_widget(self.url)
        page.add_widget(form)

        # 开关单独一行：CheckBox 固定宽，文字左对齐换行（不再和按钮挤一行）
        opt = BoxLayout(size_hint_y=None, height="28dp", spacing="8dp")
        self.use_cookie = CheckBox(active=True, size_hint_x=None, width="34dp")
        opt.add_widget(self.use_cookie)
        opt.add_widget(_wrap(Label(
            text="拉取并使用 cookie（抖音可免 cookie）", font_size="13sp",
            halign="left", valign="middle", size_hint_x=1)))
        page.add_widget(opt)

        # 两个按钮单独一行，各占一半，size_hint_x 合计=1（原来 1.47 导致重叠）
        btns = BoxLayout(size_hint_y=None, height="46dp", spacing="10dp")
        btn_pull = Button(text="只测试拉取", font_size="14sp", size_hint_x=0.5)
        btn_pull.bind(on_press=lambda _: self.start_pull_only())
        btns.add_widget(btn_pull)
        self.btn_dl = Button(text="开始下载", font_size="14sp", size_hint_x=0.5)
        self.btn_dl.bind(on_press=lambda _: self.start_download())
        btns.add_widget(self.btn_dl)
        page.add_widget(btns)

        # 提示行：路径缩短 + 换行（完整路径写进日志，避免横向溢出）
        hint = _wrap(Label(
            text="保存到 Download/ytcc-dl · 抖音已内置签名补丁，可不勾 cookie 直接下。",
            font_size="11sp", halign="left", valign="top",
            color=(0.6, 0.6, 0.6, 1), size_hint_y=None, height="30dp"))
        page.add_widget(hint)

        # 日志：固定高度（不再 size_hint=1 抢占剩余空间），放外层 ScrollView 内
        self.log_view = TextInput(readonly=True, multiline=True, font_size="13sp",
                                  font_name="CJK" if Label.font_name == "CJK" else "Roboto",
                                  background_color=(0.08, 0.08, 0.1, 1),
                                  foreground_color=(0.85, 0.9, 0.85, 1),
                                  size_hint_y=None, height="170dp")
        page.add_widget(self.log_view)

        self._log(f"ytcc-dl v{VERSION} 就绪（{'Android' if IS_ANDROID else '桌面预览'}）")
        self._log(f"保存目录：{APP_DIR}")
        self._log("地址已固定；首次填 UUID，点密码框输入后点「只测试拉取」验证。")

    # --- 日志线程安全 ---
    def _log(self, msg):
        def _do(_):
            self.log_view.text += f"{msg}\n"
            self.log_view.cursor = (0, len(self.log_view.text))
        Clock.schedule_once(_do, 0)

    def _fields(self):
        return {
            "host": COOKIECLOUD_HOST,
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
        # resize：软键盘弹出时缩小窗口而不是平移，配合外层 ScrollView 让内容
        # 可滚动，输入框位置稳定不再跳动（below_target 在部分机型会反复平移抖动）
        Window.softinput_mode = "resize"
        return Root()


if __name__ == "__main__":
    YtccApp().run()
