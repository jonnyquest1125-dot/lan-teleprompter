#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线自检: 在临时目录起服务, 逐项断言接口行为。任何一项失败退出码非 0。
不读不写真实文稿(state.json 落在临时目录)。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "server.py")
PORT = 8099
BASE = "http://127.0.0.1:%d" % PORT

passed, failed = [], []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print("%s %s %s" % ("OK  " if cond else "FAIL", name, detail))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def fetch_raw(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return r.status, r.read().decode("utf-8", "replace")


def post(path, obj):
    data = json.dumps(obj, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def main():
    tmp = tempfile.mkdtemp(prefix="lan-tp-test-")
    env = dict(os.environ, TP_PORT=str(PORT), TP_STATE=os.path.join(tmp, "state.json"))
    proc = subprocess.Popen([sys.executable, os.path.abspath(SERVER)],
                            cwd=tmp, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                code, d = get("/api/state?c=test")
                break
            except Exception:
                time.sleep(0.25)
        else:
            check("服务能起", False)
            shutil.rmtree(tmp, ignore_errors=True)
            return 1
        check("服务能起", code == 200 and d.get("ok") == 1)

        code, html = fetch_raw("/")
        check("手机页 GET /", code == 200 and "提词器" in html)
        code, html = fetch_raw("/pc")
        check("控台页 GET /pc", code == 200)

        code, d = post("/api/script", {"text": "第一段。\n\n第二段。\n\n第三段。", "mode": "replace", "c": "test"})
        check("发稿切段(空行分3段)", d.get("ok") == 1 and d.get("total") == 3 and d.get("idx") == 0)

        code, d = post("/api/script", {"text": "补发的一段。", "mode": "append", "c": "test"})
        check("补发单段并跳到它", d.get("total") == 4 and d.get("idx") == 3)

        code, d = post("/api/next", {"delta": 1, "c": "test"})
        check("越界保护(末段再next不越界)", d.get("idx") == 3)
        code, d = post("/api/next", {"delta": -1, "c": "test"})
        check("上一段", d.get("idx") == 2)

        code, d = post("/api/goto", {"idx": 0, "c": "test"})
        check("跳段", d.get("idx") == 0)

        fs0 = d.get("fs")
        code, d = post("/api/font", {"delta": 4, "c": "test"})
        check("字号+4", d.get("fs") == fs0 + 4)
        code, d = post("/api/font", {"fs": 72, "c": "test"})
        check("字号上限 72", d.get("fs") == 72)
        code, d = post("/api/font", {"fs": 8, "c": "test"})
        check("字号下限 16", d.get("fs") == 16)

        code, d = post("/api/clear", {})
        check("清空", d.get("total") == 0)

        code, d = get("/api/full?c=test")
        check("full 带 lan/segwraps 字段", d.get("ok") == 1 and "lan" in d)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d OK, %d FAIL" % (len(passed), len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
