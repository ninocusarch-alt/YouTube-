# Windows EXE 启动器实施计划

> 对应设计：`docs/superpowers/specs/2026-08-07-windows-exe-launcher-design.md`
> 实施目标：用户每次开机后双击一次 EXE，即可直接使用 Chrome 插件，无需安装 Python 或执行 PowerShell 命令。

## 实施原则

- 先测试后实现，每个模块保持单一职责；
- 不改变现有 Chrome 插件与 `127.0.0.1:8000` 的通信协议；
- 不把真实 `.env` 或 API Key 放入源码、测试、日志和发布包；
- 优先完成稳定的 PyInstaller `onedir`，不同时支持 `onefile`；
- 不实现开机自启、Native Messaging、云端部署和安装器。

## 任务 1：建立启动器测试骨架

### 新增文件

- `backend/launcher/__init__.py`
- `backend/tests/test_launcher_config.py`
- `backend/tests/test_launcher_instance.py`
- `backend/tests/test_launcher_server.py`

### 工作内容

1. 为配置路径、密钥保存、单实例、端口判断和服务状态建立测试入口。
2. 测试统一使用临时目录和假 Key，不读取或修改真实 `backend/.env`。
3. 保证现有 12 项后端测试保持通过。

### 验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

第一轮新增测试应因模块尚未实现而失败，确认测试能够捕获缺失行为。

## 任务 2：实现运行目录与配置存储

### 新增文件

- `backend/launcher/runtime_paths.py`
- `backend/launcher/config_store.py`

### 修改文件

- `backend/app/config.py`
- `backend/tests/test_launcher_config.py`

### 工作内容

1. `runtime_paths.py` 区分源码模式与 PyInstaller frozen 模式。
2. frozen 模式以 EXE 所在目录作为运行目录；源码模式默认使用 `backend/`。
3. 支持通过 `VIDEO_COMPANION_ENV_FILE` 显式指定 `.env` 路径。
4. `config_store.py` 提供：
   - 创建缺失的 `.env`；
   - 读取是否已配置 `DASHSCOPE_API_KEY`；
   - 更新单个 Key，同时保留其他配置；
   - 使用临时文件加原子替换保存；
   - 返回掩码值，不返回可直接显示的完整 Key。
5. `get_settings()` 使用明确的环境文件路径，不依赖 PowerShell 当前目录。
6. 保存配置后清理 `get_settings()` 缓存，使后续会话读取新 Key。

### 测试用例

- 源码模式解析到 `backend/.env`；
- frozen 模式解析到 EXE 同级 `.env`；
- `.env` 不存在时从模板创建；
- Key 为空时返回未配置；
- 更新 Key 后其他配置不丢失；
- 日志和返回值不出现完整 Key；
- 写入失败时原文件不损坏。

## 任务 3：实现单实例与端口识别

### 新增文件

- `backend/launcher/single_instance.py`
- `backend/launcher/backend_probe.py`

### 修改文件

- `backend/tests/test_launcher_instance.py`

### 工作内容

1. 使用 Windows Named Mutex 防止同时打开两个启动器窗口。
2. Mutex 名使用固定产品标识，不包含用户 Key 或路径。
3. 对 `127.0.0.1:8000` 进行三态检查：
   - 端口空闲；
   - 本项目后端已运行；
   - 未知程序占用端口。
4. 通过 `/api/health` 的 `ok`、`asr_provider` 等字段识别本项目，不只判断 HTTP 200。
5. 未知程序占用时只提示，不自动结束进程。

### 测试用例

- 第一个 Mutex 成功，第二个识别为重复实例；
- 端口不可连接时返回空闲；
- 正确健康响应识别为本项目；
- 无关 HTTP 响应识别为未知占用；
- 超时和非法 JSON 不导致 GUI 崩溃。

## 任务 4：实现 Uvicorn 服务控制器

### 新增文件

- `backend/launcher/server_controller.py`

### 修改文件

- `backend/app/main.py`
- `backend/tests/test_launcher_server.py`

### 工作内容

1. 定义明确状态：`stopped`、`starting`、`ready`、`stopping`、`failed`。
2. 在后台线程中创建并运行 `uvicorn.Server`，GUI 主线程不阻塞。
3. 启动前执行配置和端口检查。
4. 启动后轮询 `/api/health`，在超时前确认本地服务就绪。
5. 停止时设置 Uvicorn 正常退出标记并等待线程结束。
6. 重启严格执行“停止完成 → 清理配置缓存 → 再启动”。
7. 调整 `app.main` 对 Settings 的使用，避免模块首次导入后永久保留旧 Key。
8. 保留现有 SessionStore 行为，不在本任务引入数据库。

### 测试用例

- 合法配置能够从 stopped 到 ready；
- 配置缺失直接进入 failed，不占用端口；
- 启动超时能够停止残留线程；
- stop 后端口释放；
- restart 能读取更新后的 Key；
- 重复调用 start 不创建第二个线程；
- 现有健康接口和 WebSocket 单元测试继续通过。

## 任务 5：实现 Tkinter 启动器界面

### 新增文件

- `backend/launcher/view_model.py`
- `backend/launcher/main.py`

### 工作内容

1. `view_model.py` 将内部状态和异常映射为用户可理解的中文文案。
2. `main.py` 创建 Tkinter 窗口，包含：
   - 状态指示；
   - 启动、停止、重新启动；
   - 配置 API Key；
   - 打开健康检查；
   - 简化日志区域。
3. 所有后台线程结果通过 Tkinter `after()` 回到主线程更新界面。
4. 首次运行且 Key 缺失时自动打开配置对话框。
5. Key 输入框默认隐藏字符，保存后只显示掩码。
6. 关闭窗口且服务运行时弹出确认，确认后正常停止服务。
7. 重复打开时提示已有实例，而不是静默失败。
8. 浏览器打开健康页使用 Python `webbrowser`，不调用 PowerShell。

### 测试

- 对 `view_model.py` 的状态文案和错误映射做单元测试；
- GUI 主窗口使用人工验收，不在首版引入复杂 UI 自动化框架。

## 任务 6：增加 PyInstaller 配置

### 新增文件

- `backend/launcher_requirements.txt`
- `backend/video_companion.spec`
- `backend/build_launcher.ps1`

### 修改文件

- `.gitignore`

### 工作内容

1. 在启动器专用依赖中固定 PyInstaller 版本。
2. `.spec` 使用 `windowed=True`，避免出现控制台黑框。
3. 收集 Uvicorn、WebSocket、Pydantic Settings 等动态依赖和资源。
4. 输出名称固定为 `VideoCompanionBackend.exe`。
5. 构建产物为：

```text
release/VideoCompanionBackend/
  VideoCompanionBackend.exe
  .env.example
  _internal/
```

6. 构建脚本执行：环境检查、测试、打包、复制模板、凭据扫描和产物清单输出。
7. `.gitignore` 排除 PyInstaller 中间目录、`release/` 和真实 `.env`。
8. 构建脚本只服务开发者；普通用户运行 EXE 时不需要执行脚本。

## 任务 7：更新使用文档

### 修改文件

- `README.md`
- `PROJECT_HANDOFF.md`

### 新增文件

- `release/README-首次使用.txt`（由构建脚本生成或复制）

### 工作内容

1. README 把“双击 EXE”放在普通用户路径首位。
2. PowerShell 启动方式保留在“开发者运行”章节。
3. 首次使用说明控制在五步以内：双击、填 Key、等待就绪、打开 YouTube、点击插件。
4. 交接文档补充启动器架构、构建方式、故障处理和发布产物。
5. 明确窗口关闭后插件不可用，Key 不得分享。

## 任务 8：完整回归与发布验收

### 自动化验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\extension
npm.cmd run build
```

### 源码模式验收

- 现有 Uvicorn 命令仍可运行；
- `/api/health` 正常；
- Chrome 插件仍可建立会话；
- 英文、中文和问答事件协议不变。

### EXE 模式验收

- 删除测试机上的 Python 环境依赖后，EXE 仍可启动；
- 首次运行创建 `.env` 并配置 Key；
- 窗口不出现 PowerShell 黑框；
- 状态达到“服务已就绪”；
- 插件能够收到 `session.ready` 并开始实时识别；
- 重复双击不启动第二个实例；
- 未知程序占用 8000 时不被强制结束；
- 停止、重启和关闭窗口后端口状态正确；
- 发布目录不包含真实 Key；
- 对构建产物执行一次杀毒软件扫描并记录可能的误报。

## 实施顺序与提交建议

建议拆成以下本地提交，便于出现问题时回退：

1. `Test launcher configuration and instance behavior`
2. `Add launcher configuration and single-instance support`
3. `Add managed Uvicorn server controller`
4. `Add Windows launcher interface`
5. `Package Windows backend executable`
6. `Document one-click Windows startup`

在所有自动测试和 EXE 人工验收通过前，不覆盖现有可运行的 `backend/.venv` 和 `extension/dist`，也不删除 PowerShell 启动方式。
