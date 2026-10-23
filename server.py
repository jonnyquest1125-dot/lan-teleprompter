#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提词器服务端 (标准库, 无第三方依赖)

  手机  http://<本机IP>:8000        看台词, 一点一屏, 不滚动
  电脑  http://127.0.0.1:8000/pc    控制台: 粘整篇切段 / 补发单段 / 上下段

设计要点:
  - 台词存在服务端 state.json, 不再只存手机浏览器 localStorage
  - 手机端每 1.2s 拉一次 /api/state, 电脑一按发送, 手机自动换词(手动刷新也有效)
  - 换段由服务端统一记 idx, 手机和电脑同时按也不会跳段或乱序
"""
import json
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.environ.get("TP_STATE", os.path.join(ROOT, "state.json"))
DATA_DIR = os.path.dirname(os.path.abspath(STATE_FILE))   # 运行期数据跟 state.json 放同一个目录
VPX_FILE = os.path.join(DATA_DIR, "vpx.json")         # 手机上报的布局数据, 落盘防丢
WRAPS_FILE = os.path.join(DATA_DIR, "wraps.json")     # 手机预计算的每段折行, 落盘防丢
CAMPOS_FILE = os.path.join(DATA_DIR, "campos.json")   # 镜头框: 手机报来的当前几行 + 框的实测几何
PORT = int(os.environ.get("TP_PORT", "8000"))

DEFAULT_FS = 32          # 手机显示字号, 16-72
FS_STEP = 4
APP_VER = "2026-10-24-cambox14"      # 页面版本: 手机/电脑页面对不上就自己刷新, 免得跑旧 JS

# 镜头框(camera box): 手机屏上只露几行、每行约 10 个字, 落在镜头那一点, 上下留暗色上下文
# 两端共用同一份配置: on 开关 / n 每行目标字数 / dx,dy 位置微调 / seq+cmd 控台发来的翻屏命令
CAM_DEFAULT = {"on": 0, "n": 10, "dx": 0, "dy": 0, "seq": 0, "cmd": ""}


def clamp_fs(v):
    try:
        v = int(v)
    except Exception:
        v = DEFAULT_FS
    return max(16, min(72, v))


def clamp_cam(src):
    """镜头框配置(两端共用): 开关/字数/位置偏移/命令序号, 范围在这里兜住。"""
    c = dict(CAM_DEFAULT)
    if isinstance(src, dict):
        for k in ("on", "n", "dx", "dy", "seq"):
            if k in src:
                try:
                    c[k] = int(src[k])
                except Exception:
                    pass
        if isinstance(src.get("cmd"), str):
            c["cmd"] = src["cmd"][:8]
    c["on"] = 1 if c["on"] else 0
    c["n"] = max(4, min(20, c["n"]))
    c["dx"] = max(-500, min(500, c["dx"]))
    c["dy"] = max(-400, min(400, c["dy"]))
    c["seq"] = max(0, c["seq"])
    return c


def lan_ip():
    """本机局域网 IP: 用来在控台上给出手机能打开的地址(不能给 127.0.0.1)。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))          # 不发包, 只借路由表选出口网卡
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


LAN_IP = lan_ip()

_lock = threading.Lock()
_state = {"segs": [], "idx": 0, "rev": 1, "fs": DEFAULT_FS, "cam": dict(CAM_DEFAULT)}
_last_seen = {}
# 手机自报的可视区(CSS px): 预览按它来, 才是"和手机完全一样"的尺寸
_vp = {"w": 844, "h": 390}
_vpx = {}          # 手机报上来的详细尺寸/量到的元素尺寸
_campos = {}       # 镜头框: 手机报来的当前几行 + 框的实测几何(控台照这个画)
_shot = {"data": b"", "v": 0}   # (已停用)手机 canvas 截图, iOS 上不准
_wraps = {}        # 手机预先算好的每段折行: idx -> {wh, wraps, lws}


def report_vp(qs):
    try:
        w = int(qs.get("w") or 0)
        h = int(qs.get("h") or 0)
    except Exception:
        return
    if 200 <= w <= 4000 and 200 <= h <= 4000:
        _vp["w"], _vp["h"] = w, h


# ---------- 状态 ----------
def load_state():
    global _state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        segs = [s for s in (d.get("segs") or []) if isinstance(s, str) and s.strip()]
        idx = int(d.get("idx") or 0)
        rev = int(d.get("rev") or 1)
        fs = clamp_fs(d.get("fs", DEFAULT_FS))
        _state = {"segs": segs, "idx": max(0, min(idx, max(0, len(segs) - 1))), "rev": rev, "fs": fs,
                  "cam": clamp_cam(d.get("cam"))}
    except Exception:
        _state = {"segs": [], "idx": 0, "rev": 1, "fs": DEFAULT_FS, "cam": dict(CAM_DEFAULT)}

    for path, target in ((VPX_FILE, _vpx), (WRAPS_FILE, _wraps), (CAMPOS_FILE, _campos)):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                target.clear()
                target.update(d)
        except Exception:
            pass


def save_json(path, obj):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def save_state():
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        sys.stderr.write("[warn] 状态写盘失败: %s\n" % e)


def split_segs(text):
    """空行优先分段; 没有空行时一行一段。"""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t:
        return []
    blocks = [b.strip() for b in re.split(r"\n[ \t]*\n", t) if b.strip()]
    if len(blocks) >= 2:
        return blocks
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
    return lines if lines else [t]


def cur_text():
    s = _state["segs"]
    if not s:
        return ""
    return s[_state["idx"]]


def public_state():
    s = _state["segs"]
    return {
        "ok": 1,
        "rev": _state["rev"],
        "idx": _state["idx"],
        "total": len(s),
        "text": cur_text(),
        "fs": _state["fs"],
        "ver": APP_VER,
        "vp": {"w": _vp["w"], "h": _vp["h"]},
        "shotv": _shot["v"],
        "cam": _state["cam"],
        "campos": _campos,
        "updated": int(time.time()),
    }


def full_state():
    d = public_state()
    d["segs"] = _state["segs"]
    d["lan"] = LAN_IP
    d["vpx"] = _vpx
    sw = _wraps.get(_state["idx"])
    if sw:
        d["segwraps"] = sw          # 当前段的折行(手机预先算的), 电脑端直接用
    d["port"] = PORT
    # 手机/电脑在线判定: 10s 内有过请求
    now = time.time()
    d["online"] = {k: (now - v < 10) for k, v in _last_seen.items()}
    return d


# ---------- HTTP ----------
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".ico": "image/x-icon",
    ".ttf": "font/ttf",
    ".woff2": "font/woff2",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "Teleprompter/2.1"
    protocol_version = "HTTP/1.1"

    # 轮询请求太频繁, 不刷日志; 只记其它请求, 出现手机 IP 即可证明真通
    def log_message(self, fmt, *args):
        try:
            line = fmt % args
        except Exception:
            return
        if "/api/state" in line:
            return
        sys.stderr.write("[%s] %s\n" % (self.client_address[0], line))
        sys.stderr.flush()

    # --- 工具 ---
    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except Exception:
                pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    def _file(self, rel):
        path = os.path.normpath(os.path.join(ROOT, rel))
        if not path.startswith(ROOT) or not os.path.isfile(path):
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    def _touch(self, who):
        if who:
            _last_seen[str(who)] = time.time()

    # --- GET ---
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path

        if p in ("/", "/index.html"):
            self._touch("phone")
            return self._file("index.html")
        if p in ("/pc", "/pc/"):
            self._touch("pc")
            return self._file("pc.html")

        if p == "/api/state":
            qs = {}
            for kv in u.query.split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    qs[k] = v
            who = qs.get("c")
            if who:
                self._touch(who)
                if who == "phone":
                    report_vp(qs)      # 手机每 1.2s 报一次自己真实的可视区
            with _lock:
                return self._json(public_state())
        if p == "/api/shot.png":
            data, v = _shot["data"], _shot["v"]
            if not data:
                return self._send(404, "no shot yet", "text/plain; charset=utf-8")
            self._send(200, data, "image/png")
            return

        if p == "/api/full":
            if "c=" in u.query:
                self._touch(u.query.split("c=", 1)[1].split("&")[0])
            with _lock:
                return self._json(full_state())

        return self._file(p.lstrip("/"))

    def do_HEAD(self):
        self.do_GET()

    # --- POST ---
    def do_POST(self):
        p = urlparse(self.path).path
        body = self._read_json()

        with _lock:
            if p == "/api/script":
                text = body.get("text") or ""
                mode = body.get("mode") or "replace"
                if mode == "append":
                    one = text.strip()
                    if one:
                        _state["segs"].append(one)
                        _state["idx"] = len(_state["segs"]) - 1
                else:
                    segs = split_segs(text)
                    if not segs:
                        return self._json({"ok": 0, "err": "空稿"}, 400)
                    _state["segs"] = segs
                    _state["idx"] = 0
                _state["rev"] += 1
                save_state()
                self._touch(body.get("c") or "pc")
                return self._json(full_state())

            if p == "/api/next":
                segs = _state["segs"]
                if segs:
                    d = int(body.get("delta") or 1)
                    _state["idx"] = max(0, min(len(segs) - 1, _state["idx"] + d))
                    _state["rev"] += 1
                    save_state()
                self._touch(body.get("c") or "pc")
                return self._json(public_state())

            if p == "/api/vp":
                _vpx.update(body)      # 合并, 不清空: wraps 只在变化时才发, 不能被冲掉
                try:
                    w, h = int(body.get("iw") or 0), int(body.get("ih") or 0)
                    if 200 <= w <= 4000 and 200 <= h <= 4000:
                        _vp["w"], _vp["h"] = w, h
                except Exception:
                    pass
                save_json(VPX_FILE, _vpx)
                return self._json({"ok": 1})

            if p == "/api/cam":
                c = dict(_state["cam"])
                for k in ("on", "n", "dx", "dy"):
                    if k in body:
                        c[k] = body[k]
                if body.get("cmd"):        # 控台按「下一屏/上一屏」: 手机轮询时读到就翻
                    c["cmd"] = str(body["cmd"])
                    c["seq"] = int(c.get("seq") or 0) + 1
                _state["cam"] = clamp_cam(c)
                save_state()
                self._touch(body.get("c") or "pc")
                return self._json(public_state())

            if p == "/api/campos":
                _campos.clear()
                _campos.update({k: v for k, v in body.items() if k != "c"})
                save_json(CAMPOS_FILE, _campos)
                return self._json({"ok": 1})

            if p == "/api/wraps":
                try:
                    i = int(body.get("idx"))
                    _wraps[i] = {"wh": body.get("wh"), "wraps": body.get("wraps") or [],
                                 "lws": body.get("lws") or [], "wstamp": body.get("wstamp")}
                    save_json(WRAPS_FILE, _wraps)
                except Exception:
                    pass
                return self._json({"ok": 1})

            if p == "/api/shot":
                url = body.get("png") or ""
                if "," in url:
                    try:
                        import base64 as _b64
                        _shot["data"] = _b64.b64decode(url.split(",", 1)[1])
                        _shot["v"] += 1
                    except Exception:
                        pass
                return self._json({"ok": 1, "v": _shot["v"]})

            if p == "/api/font":
                if "fs" in body:
                    _state["fs"] = clamp_fs(body.get("fs"))
                else:
                    try:
                        delta = int(body.get("delta") or FS_STEP)
                    except Exception:
                        delta = FS_STEP
                    _state["fs"] = clamp_fs(_state["fs"] + delta)
                _state["rev"] += 1
                save_state()
                self._touch(body.get("c") or "pc")
                return self._json(public_state())

            if p == "/api/goto":
                segs = _state["segs"]
                if segs:
                    i = int(body.get("idx") or 0)
                    _state["idx"] = max(0, min(len(segs) - 1, i))
                    _state["rev"] += 1
                    save_state()
                self._touch(body.get("c") or "pc")
                return self._json(public_state())

            if p == "/api/del":
                segs = _state["segs"]
                i = int(body.get("idx") or 0)
                if 0 <= i < len(segs):
                    segs.pop(i)
                    if _state["idx"] >= len(segs):
                        _state["idx"] = max(0, len(segs) - 1)
                    _state["rev"] += 1
                    save_state()
                return self._json(full_state())

            if p == "/api/clear":
                _state["segs"] = []
                _state["idx"] = 0
                _state["rev"] += 1
                save_state()
                return self._json(full_state())

            if p == "/api/ping":
                self._touch(body.get("c") or "")
                return self._json({"ok": 1, "ts": time.time()})

        return self._json({"ok": 0, "err": "unknown api"}, 404)



DEMO_SEGS = [
    "这是局域网提词器的演示稿。手机横屏看词，电脑控台切段。",
    "电脑浏览器打开 /pc：粘贴整篇稿子，按空行切成段，调字号。",
    "手机打开首页：一屏一段，上下段切换，两端换行逐行一致。",
]


def main():
    load_state()
    if "--demo" in sys.argv and not _state["segs"]:
        _state["segs"] = [str(x) for x in DEMO_SEGS]
        _state["idx"] = 0
        _state["rev"] += 1
        save_state()
        sys.stderr.write("[demo] 已写入演示稿, 打开页面即可看到效果。\n")
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)

    srv.daemon_threads = True
    sys.stderr.write("提词器服务已启动  端口 %d  根目录 %s\n" % (PORT, ROOT))
    sys.stderr.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
