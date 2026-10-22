# 局域网提词器 (LAN Teleprompter)

双端局域网提词器：电脑浏览器做控台（粘稿切段、调字号、上下段），手机全屏看词。**两端的换行逐行一致**——换行不是各端自己算的，而是手机实测后上报，电脑端按同一份断点渲染。

A two-end LAN teleprompter: a desktop browser console (paste script, split into segments, font size, prev/next) and a full-screen phone display. Line breaks are identical on both ends — they are measured on the phone and rendered from the same break list on the console, never computed independently.

## 快速开始

```bash
python server.py --demo     # 首次运行写入演示稿; 不带 --demo 就是空稿
```

- 电脑控台: `http://<本机IP>:8000/pc` —— 粘整篇稿 → 切分并发送; 上一段/下一段; A−/A＋ 字号(两端同步); 预览框按手机实测尺寸与折行逐行还原
- 手机: `http://<本机IP>:8000/` —— 一屏一段不滚动; 底部 ‹上一段 / A− A＋ / 下一段›; ⇄ 镜像; iPhone 可「添加到主屏幕」当 App 用
- 只有标准库，无第三方依赖; 端口默认 8000, 可用环境变量 `TP_PORT` 改
- Windows 可双击 `提词器.bat`(自动探测 Python、自动打印本机 IP)

> 手机上、电脑上看到的是同一个服务端的同一份状态(稿子/段号/字号都存服务端 `state.json`)，任一端操作另一端实时跟上。

## 为什么"换行完全一致"是这个项目最难的部分

iOS 与桌面浏览器的字形推进相差 1~3%，同一段文字在同一宽度下可能差出整整一行。本项目不试图"算准"，而是：

1. 手机页逐字量出每行断点（哪一行从第几个字开始）与每行实际宽度，上报服务端；
2. 电脑控台拿到断点后**逐行渲染，绝不自己折行**；
3. 手机自己同样按这份断点逐行显示 —— 两端同源，换行必然一致；
4. 行尾"贴边字"（距右边不足 2px）保守挪到下一行，避免"量出来的"和"画出来的"差一个字。

细节取舍见 [CHANGELOG.md](CHANGELOG.md)。

## 文件

| 文件 | 作用 |
|---|---|
| `server.py` | 服务端：稿子/段号/字号/手机上报数据，标准库单文件 |
| `index.html` | 手机端页面（横屏一屏一段，支持 PWA 加到主屏） |
| `pc.html` | 电脑控台（切段发送、补发单段、字号、键盘 ↑↓ 换段） |
| `提词器.bat` | Windows 双击启动脚本（自动找 Python、打印地址） |
| `tests/selfcheck.py` | 离线自检：起服务、逐项断言接口行为，退出码非 0 表示失败 |

## 可选：预览字宽更接近手机

手机端用系统字体（PingFang SC），控台预览在 Windows 上回退到微软雅黑，行宽会略有出入（断点不受影响）。想让预览字宽更接近，把本机 `C:\Windows\Fonts\Deng.ttf` 复制到本目录并改名为 `tpfont.ttf` 即可（该文件不进仓库：16MB 且为微软字体）。

## 自检

```bash
python tests/selfcheck.py
```

逐项 OK/FAIL，任何一项失败退出码非 0。测试在临时目录里跑，不会碰你的真实文稿。

## License

MIT — 见 [LICENSE](LICENSE)。
