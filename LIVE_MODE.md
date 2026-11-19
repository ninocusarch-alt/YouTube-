# 跨境直播模式（Live Mode）增量改造说明

> 基于原项目 `Real-time AI Video Companion v0.4.0` 就地扩展，**没有重写、没有删除原有 YouTube / Chrome 插件链路**。
> 目标场景：人在国外、打外服、说英语，把英文实时翻成中文字幕给国内直播观众。

## 1. 这次改动的核心判断

原后端 `/ws/sessions/{id}` 本来就同时支持两种输入：

- `audio.append` —— 16 kHz 单声道 PCM（base64），`input_mode='audio'` 时拉起千问实时 ASR（语言 `en`）
- `caption.segment` —— YouTube 字幕文本

断句、千问翻译、`chat.ask` Agent 问答、阶段小结、SQLite 历史全都在后端复用。
所以改造的实质是**替换"谁送音频、谁显示字幕"**，翻译 / 问答 / 断句逻辑未改。
唯一新增的后端改动是 ASR **协议适配层**（见第 8 节）：本机专属实例用的是
DashScope Streaming 协议，原代码只支持 OpenAI Realtime，实跑时发现整个音频识别
链路是静默失效的，现已按模型自动切换。

```
麦克风 ┐
       ├→ WASAPI 采集 → 20ms PCM → LiveAudioBridge（冒充原 Chrome 扩展）
系统声音┘                              │ audio.append
                                       ▼
                    原有 /ws/sessions/{id}（ASR → 断句 → 翻译 → 问答/小结）
                                       │ transcript.translation
                                       ▼
                              LiveHub + CaptionState
                       ┌──────────────┴──────────────┐
              /ws/live/overlay                 /ws/live/console
              OBS 透明字幕叠层                主播控制台（含 Agent 问答）
```

EXE 启动器新增一个按钮「▶ 开启跨境直播模式」，与原有「安装 / 更新 Chrome 插件」并列；点它会：
确保本地服务已启动 → `POST /api/live/start` → 打开主播控制台 → 日志里打印 OBS 叠层地址。
真实采集失败（没设备 / 没装驱动 / 没配 API Key）时会弹窗询问是否改用**演示模式**，不会把界面卡死。

## 2. 与上一版（已删除的独立项目）的差别

| | 上一版 LiveBridge | 这一版 |
|---|---|---|
| 形态 | 从零新建独立项目 | 原插件 / EXE 上增量改造 |
| AI 管线 | 自己重写一套 | **完全复用原后端** |
| 音源假设 | 外文队友→中文观众，主播说中文，只采 Discord | **主播自己说英语，麦克风是主音源**，系统声音可选 |
| 问答 | 新写 | 复用原 `chat.ask` → qwen-plus，放在主播端 |
| 观众端 | 独立 overlay | OBS Browser Source，字幕烧录进推流画面 |

观众端只收「一次成型的中文整行」；主播端保留双语记录、术语上下文、问答与审核。

## 3. 文件清单

**新增**（`backend/app/live/`）

| 文件 | 作用 |
|---|---|
| `pcm.py` | 48k/44.1k 立体声 → 16k 单声道、20 ms 分帧、两路混音、能量 VAD 静音门控、mock 音源（纯标准库） |
| `devices.py` | WASAPI 麦克风 / loopback 设备枚举与采集；非 Windows 或缺库时降级 |
| `caption.py` | 字幕状态机：只放行 final 整行、发布延迟队列、去重、撤回、一键隐藏、AI 角标、SRT |
| `hub.py` | 单例广播中心：两条 WS、演示注入、`chat.ask` 转发、指标 |
| `bridge.py` | 本地 WS 客户端：冒充扩展发 `audio.append`，收上游事件喂 hub |
| `routes.py` | `/api/live/*` REST + `/ws/live/overlay` + `/ws/live/console` + `/live` 静态挂载 |

**新增前端**（`backend/live/web/`）：`overlay.html/css/js`（透明叠层、断线重连、最多 2 行）、`console.html/css/js`（音源矩阵、设备选择、发布延迟、隐藏/撤回、P50/P95 与成本、Agent 问答、SRT 导出、OBS 地址）。

**新增验证**：`backend/tests/test_live.py`（19 项）、`backend/scripts/live_smoke.py`（14 项离线端到端）、
`scripts/live_probe.py`（API 连通性探针，不打印密钥）、`scripts/live_realtest.py`（真实 API 13 项）、
`scripts/live_realvoice.py`（真实英文语音闭环）、`scripts/live_loopback_e2e.py`（扬声器 → OBS 字幕全闭环）、
`scripts/asr_raw_probe.py`（ASR 原始事件诊断）。

> 测试用的 `edge-tts` / `miniaudio` 只用于生成英文测试音频，**未加入生产依赖**，打包不需要。

**修改**（除 ASR 适配外均为小改动）

- `app/main.py`：+2 行挂载 `mount_live(app)`；ASR 实例化改为 `create_asr_agent(settings)`
- `app/config.py`：识别 `DASHSCOPE_BASE_URL`（此前被静默忽略）、按模型推导 ASR 端点、新增 `QWEN_ASR_PROTOCOL` / `QWEN_ASR_VAD_THRESHOLD`
- `app/services/agents.py`：`session.update` 补必填 `event_id` 并去掉非法 `model`、支持 `.text` 实时事件、把裸 `CLIENT_ERROR` 纳入错误检测；新增 `QwenStreamingASRAgent`（run-task / 二进制 PCM / result-generated）与 `create_asr_agent` 工厂
- `launcher/key_validator.py`：Key 校验也走同一协议工厂
- `launcher/native_ui.py`：新增 `ID_LIVE` 按钮、启停编排、演示模式回退、日志与提示文案
- `launcher/server_controller.py` + `launcher/backend_probe.py`：端口统一读 `VIDEO_COMPANION_PORT`（默认仍 8000），避免采集桥连错服务
- `requirements.txt` / `launcher_requirements.txt`：Windows 可选 `PyAudioWPatch`
- `video_companion.spec`：条件收集 `pyaudiowpatch`
- `build_launcher.ps1` / `build_installer.ps1`：把 `live/web` 复制进 release 与安装包 payload
- `installer/main.py`：自检清单加入 6 个静态页文件；安装完成提示改为双模式说明

## 4. 快速验证（不消耗 API 额度）

```bash
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -v       # 76 项
# 端口由 VIDEO_COMPANION_PORT 统一给 uvicorn、采集桥、启动器和页面使用（默认 8000）
set VIDEO_COMPANION_PORT=8010
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8010
set LIVE_SMOKE_PORT=8010
.venv\Scripts\python.exe scripts\live_smoke.py                  # 14 项（mock）

# 真实联调（会调用 API、短暂打开麦克风/扬声器，只用于验证）
set VIDEO_COMPANION_ENV_FILE=<已安装目录>\.env
set SESSION_DATABASE_PATH=<backend>\data\realtest.db
set LIVE_REALTEST_PORT=8010
.venv\Scripts\python.exe scripts\live_realtest.py              # 13 项（真实 API）
.venv\Scripts\python.exe scripts\live_realvoice.py            # 英文语音 → 中文译文
.venv\Scripts\python.exe scripts\live_loopback_e2e.py         # 扬声器 → OBS 字幕
```

> 上面用 8010 是因为本机 8000 已被已安装的旧版 EXE 占用，可在不打断它的情况下并列验证。

演示模式也可从控制台或 EXE 按钮进入：`/api/live/start {"mock": true}`，
再 `POST /api/live/inject {"source_text": "We should rotate mid."}` 看字幕上屏。

## 5. 怎么真正用上（重要）

本机**已安装并正在运行** `VideoCompanionBackend.exe`（占用 8000 端口），那是旧版，没有新按钮。
源码改动不会自动生效，二选一：

1. **重新打包安装**（推荐，替换现有 EXE）
   ```powershell
   cd backend
   powershell -NoProfile -ExecutionPolicy Bypass -File build_installer.ps1
   ```
   产出 `release/installer/VideoCompanionSetup.exe`。先退出正在运行的旧版主程序，再运行安装器；
   安装器会保留 `.env`（API Key）和 `data`（历史记录）。
2. **直接从源码运行**：先退出旧版 EXE 释放 8000，再
   `.venv\Scripts\python.exe launcher\main.py`。

配置千问 API Key 后（启动器「配置 API Key」按钮），点「▶ 开启跨境直播模式」：
默认只采**麦克风**（主播英语）；要连队友/游戏声音一起翻，在控制台勾「系统声音」，两路会混音进同一识别会话，ASR 费用不变、但杂音风险上升。

OBS：来源 → 浏览器 → URL 填 `http://127.0.0.1:8000/live/overlay.html?font=34&bottom=12`，
把「自定义 CSS」里的 `background-color` 整行删掉即可透明。字幕随画面一起推流，不需要和平台延迟对齐。

## 6. 已知边界与风险

- **真实千问链路已联调**（2026-11-18）：用安装目录里的真实 `.env` 跑通了翻译、Agent 问答、ASR、
  真实麦克风与 OBS 字幕上屏，详见第 8 节。唯一未覆盖的是**多人真实对局语音**的识别可用率。
- **人在国外 → 调国内 API**：当前 `.env` 指向华北2 北京专属实例，跨境 RTT 与链路波动会叠加到字幕延迟，需实测试播；必要时评估国际地域或本地 ASR。
- **系统声音串音**：loopback 会收到浏览器 / OBS 里播放的任何声音。中文解说、观众语音、翻译朗读若进入 loopback，会被当成英语误识别。默认关闭。
- **多人抢话 / 游戏音效 / 黑话**：靠低置信度不上屏（当前仅 final 整行 + 未翻译过滤）、发布延迟队列和一键撤回兜底；术语表与热词尚未接入。
- **进程级 loopback 未做**：目前是设备级采集（或 VB-Cable / VoiceMeeter 虚拟声卡），要只抓 Discord/游戏进程需 M2 的 Process Loopback API。
- **合规**：《人工智能生成合成内容标识办法》2025-09-01 已施行，叠层默认带「AI 实时翻译」角标，请勿关闭；队友语音需事先告知同意；原始音频不落盘；只采系统音频输出，不读游戏内存，避开反作弊边界。
- **成本**：`qwen-audio-3.1-asr-flash-streaming` 按输入音频 / 输出文本 Token 计费（不是按时长），
  单价以控制台为准；翻译另计。实测 4 秒采集经 VAD 门控只上传 1.14 秒音频，静音时段能显著省钱。
  用真实账单复核每小时成本，不要套用旧模型的「元/秒」估算。
- **ASR 长连接保活**：直播里长时间静音时，采集端 VAD 会停止送帧；已开启 `heartbeat`，
  但仍建议连续试播 2 小时验证连接不会超时断开。

## 7. 建议的下一步

真实 API Key 与端到端闭环已经验证（第 8 节）。剩下只能靠**真实对局试播**回答三件事：
**多人抢话时的英文识别可用率、连续 2 小时的 P50/P95 与断线率、每小时实际账单**。
控制台已经把这三项埋点做好了。

## 8. 实跑验证记录（2026-11-18）

### 8.1 环境与一个致命发现

本机已安装目录的 `.env` 指向**百炼 MaaS 专属实例**，配置为
`DASHSCOPE_BASE_URL=https://ws-…cn-beijing.maas.aliyuncs.com/compatible-mode/v1`、
`QWEN_ASR_MODEL=qwen-audio-3.1-asr-flash-streaming`、`QWEN_TRANSLATION_MODEL=qwen3.8-flash`。
探针实测：

| 组合 | 结果 |
|---|---|
| 公共端点 + `qwen-plus` | HTTP 403，免费额度耗尽 |
| 公共 / 专属端点 + `qwen3.8-flash` | OK，1.6–1.9 s |
| 默认 `qwen3-asr-flash-realtime` | WebSocket 直接断开 |
| 专属端点 + `qwen-audio-3.1-asr-flash-streaming` | 握手 OK，但 `session.update` 被拒 |

**根因**：`qwen-audio-3.1-asr-flash-streaming` 用的是 DashScope Streaming 协议
（`/api-ws/v1/inference` + `run-task` + WebSocket 二进制 PCM 帧 + `result-generated`），
而原项目只实现了 OpenAI Realtime 协议（`/api-ws/v1/realtime` + `session.update` + JSON base64）。
服务端对每条消息都回 `{"code":"CLIENT_ERROR","message":"parse parameters failed"}`，
原解析器又不认识这种不带 `type` 的错误，于是**握手成功但永远不出字幕**，属于静默失效。
另外 `DASHSCOPE_BASE_URL` 此前被 `extra='ignore'` 直接丢弃。

### 8.2 修复

- `config.py`：识别 `DASHSCOPE_BASE_URL`、按模型自动推导 `/api-ws/v1/inference`、
  新增 `QWEN_ASR_PROTOCOL`（auto / realtime / streaming）与 `QWEN_ASR_VAD_THRESHOLD`。
- `agents.py`：Realtime 分支补必填 `event_id`、去掉非法的 `input_audio_transcription.model`、
  支持 `.text` 实时事件、把裸 `CLIENT_ERROR` 和 `transcription.failed` 纳入错误检测；
  新增 `QwenStreamingASRAgent`（`run-task` → 等 `task-started` → 二进制帧 → `result-generated` → `finish-task`），
  由 `create_asr_agent()` 按模型选择。原有 Realtime 模型行为不变。
- `main.py` / `launcher/key_validator.py`：改用工厂，Key 校验也走正确协议。

### 8.3 实测结果（全部真实 API，非 mock）

| 项目 | 结果 |
|---|---|
| 单元测试 | **76/76**（原 45 + 直播 19 + 协议回归 12） |
| 离线端到端冒烟 | **14/14** |
| 真实 API 链路 | **13/13**；翻译 626 / 1520 ms，Agent 问答 2.3 s，译文含游戏术语 |
| 真实英文语音闭环 | TTS 语音 → ASR → 断句 → **「我们应该先换线」**，端到端 3.28 s |
| 直播模式全闭环 | 扬声器播放 → WASAPI loopback（366 帧，上传 182 帧 / 3.64 s）→ ASR → 真实翻译 → OBS `caption.show` **「我们应该在对方抱团推进前转线中路」**，端到端 **5.25 s**，字幕发布 P50/P95 = 910 ms |
| 真实麦克风 | 5 麦克风 / 2 loopback，4 秒采 195 帧，VAD 门控丢弃 70 帧，无错误、干净停止 |

服务用 `VIDEO_COMPANION_ENV_FILE` 指向真实 `.env`、`SESSION_DATABASE_PATH` 指向隔离测试库，
**没有污染安装目录里的历史数据库**；测试期间短暂打开过麦克风与扬声器（音频送 ASR，按 Token 计费，量极小）。

### 8.4 仍未验证

- 真实**多人**外服对局语音（TTS 是单人朗读）、口音、游戏音效、抢话与游戏黑话识别率。
- 连续 2 小时长播的 ASR 连接稳定性与真实账单（VAD 长时间不送帧时的心跳保活）。
- 人在境外到华北2 北京专属实例的跨境 RTT 抖动。

复现命令见第 4 节；`scripts/live_probe.py` 可随时检查当前 Key / 端点 / 模型组合是否可用，
它不会打印密钥。

## 9. 重新打包与安装（2026-11-18 17:03 完成）

### 9.1 命令

```powershell
cd backend
powershell -NoProfile -ExecutionPolicy Bypass -File build_installer.ps1
```

脚本会依次：跑全部单测 → `pip install -r launcher_requirements.txt`（PyInstaller 6.22.3）
→ 构建 `VideoCompanionBackend.exe` → 复制 `live/web/*`、`.env.example`、`FIRST_RUN.txt`
→ 凭据扫描 → 组装无凭据 payload（含 `extension/dist` 与 `live/web` 六个文件）
→ 再跑单测 → 构建 `VideoCompanionSetup.exe` → 运行安装器自检。

产物：

| 文件 | 说明 |
|---|---|
| `release/VideoCompanionBackend/VideoCompanionBackend.exe` | 带直播按钮的主程序（7.3 MB，另有 `_internal`、`live/web`） |
| `release/installer/VideoCompanionSetup.exe` | 一键安装器（28 MB，内嵌完整 payload） |

> 安装器是 GUI 程序（`runw.exe`），从 PowerShell / Bash 调用时**取不到真实退出码**；
> 校验打包内容请用 `PyInstaller.archive.readers.CArchiveReader` 读归档 TOC，
> 或直接启动安装后的 EXE 验证（见 9.3）。

### 9.2 安装到桌面

`VideoCompanionSetup.exe` 是交互式（弹窗询问是否开机自启、会检查 8000 端口）。
无人值守覆盖安装用项目自带 `installer.install_engine.install_payload` 的等价脚本：

```bash
cd backend
set VIDEO_COMPANION_BACKUP_DIR=<安装目录的完整备份路径>
.venv\Scripts\python.exe scripts\silent_install.py
```

它保留 `.env` 与 `data`，刷新 `Uninstall.exe`，并把安装器原本会清掉的
`.env.bak-*` / `_internal.bak-*` 还原回去。桌面与开始菜单快捷方式指向固定路径，
覆盖后**自动生效，无需重建**。

本次安装前已完整备份到：
`%TEMP%\VideoCompanion-prebuild-backup-20261118-165334`（166 MB / 1,941 个文件）。

### 9.3 安装后验证（真实 EXE，端口 8000）

```bash
cd backend
.venv\Scripts\python.exe scripts\verify_installed_exe.py
```

实测结果：

- Win32 窗口枚举到 **8 个按钮**，原有 7 个全部保留，新增 `▶ 开启跨境直播模式`。
- `/api/health`、`/api/live/status`、`/live/overlay.html`、`/live/console.html` 全部 200。
- `/api/health` 正确报告 `asr_provider=qwen-streaming`、`asr_model=qwen-audio-3.1-asr-flash-streaming`、
  `translation_model=qwen3.8-flash`（读的是安装目录里原有的真实 `.env`）。
- 冻结版 mock 端到端：`/api/live/start` → `/api/live/inject` → `on_air=1, published=1`，
  字幕「我们应该在对方包夹之前先转中路。」→ `/api/live/stop` 干净回到 idle。

### 9.4 打包过程中额外修复

- `app/main.py`：`/api/health` 的 `asr_provider` 原先写死 `qwen-realtime`，与专属实例实际使用的
  DashScope Streaming 协议不符；改为按 `settings.asr_is_streaming` 输出。
- `launcher/backend_probe.py`：`classify_health_payload` 原先只认 `qwen-realtime`，直接改 health
  会让启动器把自己的后端判成「端口被占用」；改为接受 `qwen-realtime` / `qwen-streaming` 两种，并补 2 项测试。
- 单测从 76 增至 **78**，两轮打包均全通过。

### 9.5 使用

双击桌面 `Real-time AI Video Companion`，第二行右侧即「▶ 开启跨境直播模式」。
点击后会自动确保服务已启动、开启本机音频采集、打开主播控制台，并在运行记录里打印
OBS 叠层地址（`http://127.0.0.1:8000/live/overlay.html`）。再点一次变成「■ 停止跨境直播模式」即停止。
真实采集失败会弹窗询问是否改用不消耗 API 的演示模式。

---

## 10. 点击按钮后窗口消失：崩溃定位与修复（2026-11-18 17:08）

### 10.1 现象与证据

用户点击「▶ 开启跨境直播模式」后无可见反馈，随后整个 EXE 窗口消失。
Windows 事件日志给出确证，不是最小化、也不是托盘化，而是**进程崩溃退出**：

```
17:08:25  Application Error (ID 1000)
出错应用程序：VideoCompanionBackend.exe
出错模块：ntdll.dll    异常代码：0xc0000374 (STATUS_HEAP_CORRUPTION)
出错进程 ID：0xB4C4
17:08:30 / 17:08:35  Windows Error Reporting APPCRASH (StackHash_5408)
```

用户随后在 17:08:45 重新双击了桌面快捷方式，所以窗口又出现了一次。

### 10.2 根因

`0xc0000374` 是原生堆损坏，Python 层无法捕获，因此没有任何 traceback / 弹窗，窗口直接消失。
触发路径是**一次点击里「服务刚就绪 → 立刻开真实采集」的时序竞争**：

- `app/live/devices.py` 原先每次 `list_devices()` / `device_info()` / `capture_frames()`
  都各自 `pyaudio.PyAudio()` 并在结束时 `manager.terminate()`。
- 设备枚举跑在 uvicorn 的 event loop 线程，采集流跑在 `LiveCapture-*` 子线程；
  `routes.start` 返回时还会再调一次 `cached_devices()`。
- PortAudio 的 `Pa_Initialize` / `Pa_Terminate` **不是线程安全的引用计数**，
  一个线程 terminate、另一个线程同时 initialize，在冻结版 EXE 里直接破坏堆。
- 单独先启动服务、隔几秒再调 `/api/live/start` 不复现（时序错开），所以打包前的验证没抓到。

另一个独立问题是「没反应」本身：`launcher/native_ui.py` 的 `_toggle_live()` 原先是
`if not self.busy: self._run_task(...)`。EXE 启动后 0.4 s 会自动启动服务，此时 `busy=True`，
用户在这一两秒内点按钮会被**静默丢弃**，既不排队也不提示。

### 10.3 修复

- `app/live/devices.py`：改为**进程级单例** `PyAudio()` + `threading.RLock`，
  所有枚举与采集共用同一句柄，全程不再 `terminate()`；`capture_frames` 的
  `finally` 只关闭自己的 stream。设备枚举、建流、关流都在锁内串行。
- `launcher/native_ui.py`：
  - 点击后立刻把按钮改成「⏳ 等待服务就绪… / ⏳ 正在启动跨境直播…」并写运行记录；
  - `busy` 期间的点击进入 `live_queued`，等服务动作结束后自动重放，不再静默丢失；
  - 结果回来时先恢复按钮再弹任何模态框，避免卡在「正在启动…」。
- `scripts/verify_live_click.py`：新增回归脚本，模拟「启动 EXE → 立刻点击」这一条会崩的路径。

### 10.4 验证（修复后重新打包的冻结版 EXE，端口 8000）

- 单测 **78/78** 通过。
- 完整点击路径：按钮立即显示「⏳ 等待服务就绪…」→「⏳ 正在启动跨境直播…」→
  「■ 停止跨境直播模式」，2.5 s 内 `mode=live` 且 `frames_captured>0`，窗口全程未消失。
- 连续 **4 轮** `/api/live/stop` + `/api/live/start(真实采集)`：
  `frames_captured` 151 → 238 → 326 → 413，`frames_sent` 137 → 214 → 283 → 362，
  `last_error` 全为空。
- `/api/health`、`/api/live/status`、`/live/overlay.html`、`/live/console.html` 全部 200；
  Win32 枚举 8 个按钮仍在。
- 修复后 10 分钟内事件日志**无新增** VideoCompanionBackend 崩溃记录。

### 10.5 交付物

- 桌面快捷方式指向的
  `%LOCALAPPDATA%\Programs\RealTimeAIVideoCompanion\VideoCompanionBackend.exe`
  已替换为修复版（7,632,707 字节），`.env`、`data`、历史备份均未改动。
- 旧 EXE 备份：`%TEMP%\VideoCompanionBackend.exe.bak-20261118-1724`。
- `release/installer/VideoCompanionSetup.exe` 已用同一份 payload 重打包，
  `--self-test` 通过；归档内嵌 EXE 与新构建 EXE 的 SHA-256 完全一致，
  `payload/live/web/*` 6 个文件齐全。
- 由于打包版是单进程（Win32 窗口 + uvicorn + 音频采集同处一个进程），
  原生层若再次崩溃仍会带走窗口；如后续再出现 `0xc0000374`，下一步应把
  WASAPI 采集隔离到独立子进程，让主窗口与后端服务不受影响。

---

## 11. 桌面原生悬浮字幕窗 + 双音源修复（需求纠偏）

### 11.1 需求纠偏

用户明确：**不要网页版 / OBS 浏览器源**，要的是类似 Chrome 插件那种盖在画面上的
**桌面悬浮字幕窗**，直播时直接被观众看到；同时反馈「本机声音和麦克风好像识别不了」。

### 11.2 音频诊断

- 实测电平：麦克风安静环境 RMS ≈ 0.001–0.002；系统 WASAPI loopback 播放英文语音时
  p90 ≈ 0.109。链路本身是通的（播放 `data/tts_en.wav` 约 4 s 后出中文字幕）。
- 真正原因：`LiveConfig` 默认 `source_system=False`（**只开麦克风**），固定 VAD 门限
  `0.008` 对低电平麦克风几乎全被 gate 掉，界面又没有任何输入反馈，所以看起来「识别不了」。

修复：

- `app/live/caption.py`：默认 `source_microphone=True` **且** `source_system=True`。
- `app/live/pcm.py`：`EnergyVAD` 改为自适应噪声基线 + 自动增益，避免低电平麦克风被整段丢弃。
- `app/live/bridge.py`：混流时把两路 RMS 写入 `hub.metrics['levels']`。
- `launcher/native_ui.py`：主窗口新增「输入电平 麦:▮▮▯▯▯ 系:▮▮▮▯▯」实时条。

### 11.3 桌面悬浮字幕窗

- 新增 `launcher/caption_overlay.py`：Win32 分层窗口
  (`WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`)，
  圆角深色半透明面板、绿色「AI 实时翻译 · English → 中文」标识、双行白色描边中文大字、
  英文原文小字、右上双路电平条。可拖动，右键菜单切换极简 / OBS 色键黑底 / 隐藏 / 字号。
- `app/live/hub.py` 新增 `register_local_overlay_sink()`：桌面浮层与 OBS 浏览器源收到
  **同一批** `caption.*` 事件，完全不需要浏览器或网页。
- 主窗口新增 3 个复选框：麦克风 / 系统声音 / 桌面字幕浮层；开启直播自动显示浮层，
  停止时隐藏；**不再自动打开网页控制台**。
- OBS 里用「显示器采集」即可拍到浮层；也可右键切到色键黑底，用色度键抠背景。

### 11.4 打包后才暴露的关键 bug：WNDCLASSEXW 重复定义

`native_ui.py` 与 `caption_overlay.py` 各自定义了一份 `WNDCLASSEXW`，并各自给同一个
`user32.RegisterClassExW` 设置 `argtypes`。第二个模块用「另一份但布局相同」的结构覆盖后，
窗口类注册在 WM_CREATE 内抛 `ctypes.ArgumentError`；windowed 版 PyInstaller 会静默吞掉该异常，
结果是浮层不出现、连主窗口的「运行记录」编辑框也没创建出来。

修复：抽出 `launcher/win32_types.py`，统一提供 `LRESULT` / `WNDPROC` / `WNDCLASSEXW` / `RECT`，
两个模块共享同一类型；其余 GDI 调用统一走 `gdi32.SetTextColor` / `gdi32.SetBkMode`。

### 11.5 验证（冻结版 EXE，端口 8000）

- 单测 **82/82** 通过（新增 4 个浮层 / 默认音源用例）。
- 源码层：`import launcher.native_ui` 后再 `CaptionOverlay.create()` 能正常注册窗口类。
- `scripts/verify_desktop_overlay.py` 全流程：主窗口 11 个按钮/复选框 + 运行记录编辑框齐全；
  点击「开启跨境直播模式」后浮层窗口可见、无浏览器被打开；`mic=True, system=True`；
  `levels={'microphone': 0.0, 'system': 0.1091}`；播放英文语音 **4.0 s** 出中文字幕
  「我们应该在它们坍塌前进行旋转」。
- 音源 / 浮层开关实测：系统声音 False → True 生效；浮层 显示 → 隐藏 → 显示 生效。
- 事件日志近 20 分钟**无新增** VideoCompanionBackend 崩溃；EXE 进程稳定 (PID 39064)。
- 截图：`overlay_preview.png`（静态样例）、`overlay_live_preview2.png`（真实运行画面）。

### 11.6 交付物与遗留

- 桌面快捷方式指向的 EXE 已替换为 `release/rebuild3`（7,650,905 字节），
  `.env`、`data`、历史备份未动；旧版备份 `%TEMP%\VideoCompanionBackend.exe.bak-20261118-1810`。
- `release/installer/VideoCompanionSetup.exe` 用同一 payload 重打包（29,324,536 字节），
  `--self-test` 退出码 0；`CArchiveReader` 确认内嵌 EXE 与新 EXE 的 SHA-256 一致
  (`a2d76ccc050b3d02…`)；冻结 PYZ 含 `launcher.win32_types` / `launcher.caption_overlay`
  / `launcher.native_ui` / `app.live.*`。
- 新脚本：`scripts/verify_desktop_overlay.py`、`scripts/capture_overlay_window.py`。
- 未覆盖：真人对话麦克风（只有环境底噪电平，无真人语音样本）、连续 2 小时长播、
  境外到华北 2 的 RTT 与真实账单；单进程架构的原生崩溃风险仍存在。

---

## 12. 开播约 20 秒后字幕静默停摆（保活帧 + 会话自愈）

### 12.1 现象与定位

第 11 节验证通过后，把 EXE 放着继续跑，发现 `last_error` 变成
`音频上行失败：ConnectionClosedOK: received 1000 (OK); then sent 1000 (OK)`，
`frames_sent` 停在 838、`asr_seconds` 冻结在 16.76 s，但 `frames_captured` 仍在涨 ——
**采集还活着，上游已经死了**，观众看到的是字幕再也不更新。

用 `scripts/asr_stream_probe.py` 直连千问 Streaming ASR 打印原始事件：

- 连续送 PCM 帧时，`task-started` → 多次 `result-generated` → 句子 5.35 s 判定
  `sentence_end=true`；之后继续送 35 s 静音帧，连接仍存活，55.34 s 收到服务端
  `heartbeat`，直到客户端 65 s 主动关闭都没有 `task-finished`。
- 结论：**服务端在长时间收不到音频时会结束 ASR 任务**。旧 `bridge._mix_loop()` 的
  本地 VAD 把静音帧全部 `frames_gated` 掉，安静房间 = 上行长时间零数据。

链路放大：千问结束任务 → `QwenStreamingASRAgent.transcript_events()` 在
`task-finished` 返回 → `app/main.py` 的 `asyncio.wait(..., FIRST_COMPLETED)`
让整个会话 WS 处理器退出并 `websocket.close()` → bridge 的 `_send_loop()` 抛
`ConnectionClosedOK` 后直接 `return`，且**没有任何重连**。

### 12.2 修复

`app/live/bridge.py`：

- **静音尾包 + 稀疏保活**：语音结束后 1.6 s 内仍按 20 ms 节拍送零帧（让服务端 VAD
  正常判定句尾），之后每 0.2 s 送一个 20 ms 静音帧；新增
  `frames_keepalive` 指标。上行不再出现长时间空窗，且只增加约 10% 的 ASR 音频量。
- **会话监督器** `_session_supervisor()`：把「建会话 / 收发循环」包成可重连单元。
  任一收发任务结束就在 0.4 s 后重建会话（指数退避至 4 s），采集线程、混流循环、
  桌面字幕浮层全部不重启；重连时清空过期音频缓冲，并同步更新 `hub.session_id`。
  新增 `reconnects` 指标，重连成功后清空 `last_error`。
- `start()` 通过 `_session_ready` 等首个会话就绪，API Key / 上游故障仍按硬失败抛出，
  启动器照旧能提示切换演示模式。
- `app/live/hub.py`：把 `obs_hint` 改成桌面浮层用法（显示器采集 / 色键黑底），
  并在 metrics 里预置 `frames_keepalive` / `reconnects`。

### 12.3 验证（最终冻结版，60 秒静音长跑）

`scripts/verify_live_longrun.py 60`：

| 时刻 | frames_sent | frames_keepalive | reconnects | last_error |
| --- | --- | --- | --- | --- |
| 10 s | 500 | 95 | 0 | 空 |
| 20 s | 642 | 177 | 0 | 空 |
| 30 s | 689 | 224 | 0 | 空 |
| 40 s | 735 | 270 | 0 | 空 |
| 50 s | 798 | 313 | 0 | 空 |
| 60 s | 1032 | 454 | 0 | 空 |

- 第一次英文语音 1.5 s 出中文字幕；**静音 60 s 后第二次英文语音 3.6 s 再次出中文字幕**。
- 全程 `frames_sent` 163 → 1153 持续增长、`reconnects=0`、`last_error=''`、
  `segments=4`，说明保活帧已足够，监督器作为兜底未触发。
- 同时 `scripts/verify_desktop_overlay.py` 再次通过：11 个控件齐全、点击后浮层可见、
  双音源默认开启、真实 EN→ZH 字幕 3.5 s。
- 单测 **84/84**（新增静音保活、会话重连 2 个用例）；近 15 分钟事件日志无崩溃，
  EXE PID 44756 稳定。

### 12.4 最终交付物（取代 11.6 中的版本号）

- 桌面 EXE：`release/rebuild4/VideoCompanionBackend/VideoCompanionBackend.exe`
  **7,653,958 字节**，已覆盖安装目录；上一版备份
  `%TEMP%\VideoCompanionBackend.exe.bak-20261118-1827`。
- 安装器：`release/installer/VideoCompanionSetup.exe` **29,328,064 字节**，
  `--self-test` 退出码 0；内嵌 EXE 与新 EXE SHA-256 一致
  (`38f358d2761e05ed…`)，`payload/live/web/*` 6 个文件齐全。
- 新增脚本：`scripts/asr_stream_probe.py`、`scripts/verify_live_longrun.py`、
  `scripts/capture_overlay_window.py`、`scripts/verify_desktop_overlay.py`。
- 仍建议后续把 WASAPI 采集隔离成独立子进程，彻底消除单进程原生崩溃风险。

## 13. 浮层外观回归第一版插件（2026-11-19）

用户反馈桌面浮层「太丑了」。根因是方向做反了：第 11 节做成了黑底 + 32px 白色描边大字的电影字幕条，
而 Chrome 插件 `extension/src/content.ts` 的 `.floating-panel` 实际是**浅色卡片**。
本次按该 CSS 1:1 重绘 `launcher/caption_overlay.py`。

### 13.1 视觉规范对照

| 项 | 插件 CSS | 桌面浮层 |
| --- | --- | --- |
| 底色 | `rgba(255,255,255,.96)` + `backdrop-filter: blur(14px)` | 纯白不透明（Win32 分层窗口无法模糊，半透明会让桌面文字透出来显脏） |
| 边框 / 圆角 | `1px rgba(20,27,23,.12)` / `14px` | 1px `#e1e5e2` / `CreateRoundRectRgn` 14px + `CS_DROPSHADOW` |
| 头部 | 48px、`#e7eae8` 分隔线、8px 绿色状态点 + 光晕 | 同；标题 `Video Companion` 14px/700，副标题 `实时翻译中 · English → 中文` 10px `#8b918e` |
| 头部按钮 | `↺  −  ×` 透明图标按钮 | 同，且可点击（收起 / 复位 / 隐藏） |
| 强调色 | `#19a66a` / `#16875a` / `#087b4c` | 同，用于状态点、正在听、最新记录左边 3px 竖条 |
| 实时行 | `.live`：绿色 `正在听` + 16px 英文 + `#f7f8f7` 底 | 同，右侧加两条极细音源电平（直播排障用） |
| 记录列表 | 英文 `#191d1a` 在上、译文 `#68706b` 在下；最新一条 `#f0f9f5` + `#cbe9da` 边框 | 同，最近 2 条，最新一条译文加深加粗以便观众看清 |
| 正文字号 | `--content-size: 17px`（可调 14–22） | 默认 17px，右键可调 12–30 |
| 字体 | Inter / Segoe UI / PingFang SC / Microsoft YaHei | 英文 Segoe UI、中文 Microsoft YaHei UI |

### 13.2 顺带修掉的三个「显得糙」的问题

- `CreateFontW` 原来用 `charset=134` + `quality=3 (NONANTIALIASED)`：小字锯齿、英文被映射到中文字体。
  改为 `DEFAULT_CHARSET` + `CLEARTYPE_QUALITY(5)`，10–17px 文字明显变清晰。
- 旧配置 `font_size=32` 是深色大字条的量纲，直接套到白卡片会撑爆布局。
  `_load()` 用 `theme` 字段作 schema 标记：旧配置首次加载自动把字号重置为 17。
- 冻结版 EXE 的 popup 会被 shell 重定位到屏幕外（实测 `GetWindowRect` 得到 `x=-509`，
  窗口 `IsWindowVisible=1` 但屏幕上完全看不到）。`show()` 现在每次都调 `_place_window()`
  强制摆回可见范围并置顶；`WM_EXITSIZEMOVE` 改用真实窗口矩形记忆位置，不再解析 `WM_MOVE` 的有符号 lParam。

### 13.3 保留的能力

右键菜单新增「切换：插件白卡片 / 深色字幕条」；深色条（原黑底大字）与 OBS 色键黑底仍可用，
适合浅色卡片会挡住游戏画面的场景。收起、字号 ±、显示英文原文、拖动、位置持久化都保留。
默认回到插件白卡片。

### 13.4 验证与交付

- 单测 **86/86**（新增 `CaptionCardThemeTests`：默认 light/17px/940px、旧配置字号迁移）。
- 源码同进程渲染截图 `overlay_card_clear.png`；真实 EXE 截图 `overlay_exe_card_full.png`。
- `scripts/verify_desktop_overlay.py` 在冻结版上通过：11 个控件齐全、点击后浮层可见、
  `mic=True, system=True`、真实英文语音 **3.5 s** 出中文字幕、无浏览器窗口弹出。
- 4 个端点全 200；`last_error=''`；近 30 分钟事件日志无崩溃。
- 桌面 EXE `release/rebuild6/…/VideoCompanionBackend.exe` **7,661,364 B** 已覆盖安装目录，
  旧版备份 `%TEMP%\VideoCompanionBackend.exe.bak-20261119-0349`。
- 安装器 `release/installer/VideoCompanionSetup.exe` **29,335,320 B**，`--self-test` = 0，
  内嵌 EXE 与新 EXE SHA-256 一致 `530521c76b0c9f68…`，`payload/live/web/*` 6 个文件齐全。
- `.env` 与 `data` 未改动。已知的边界：真人麦克风语音、连续 2 小时长播、境外到华北 2 的
  RTT 与真实账单仍未实测；单进程原生崩溃风险仍在。

**注意**：插件的 `.floating-panel` 用 `backdrop-filter: blur(14px)`，Win32 分层窗口做不到，
因此浅色卡片做成完全不透明；若觉得挡画面，右键切到深色字幕条或按 `−` 收起成单行。
