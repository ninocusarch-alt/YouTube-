# 参与贡献

感谢你愿意帮 Real-time AI Video Companion 变得更好。这是一个持续迭代中的个人项目，任何形式的参与都欢迎：提 Issue、改进文档、补充测试、修复 bug、适配新的 ASR / 翻译模型，或者提出产品想法。

## 开始前

项目由两部分组成：

- `backend/`：Python + FastAPI，负责会话管理、实时 ASR、上下文翻译与问答
- `extension/`：Manifest V3 Chrome 插件，React + TypeScript + Vite，负责音频捕获与交互

基本流程：

```bash
git clone https://github.com/ninocusarch-alt/realtime-ai-video-companion.git
cd realtime-ai-video-companion

# 后端
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 填入你自己的 DASHSCOPE_API_KEY
uvicorn app.main:app --reload --port 8000

# 插件（另开一个终端）
cd extension
pnpm install
pnpm dev                    # 或 pnpm build 后在 chrome://extensions 加载 dist
```

完整说明见 [README.md](README.md) 的「快速开始」章节。

## 环境变量与密钥

- 只在 `backend/.env` 里填真实密钥，该文件已被 `.gitignore` 排除。
- 需要新增配置项时，同步更新 `backend/.env.example`，**只放空值或占位符**。
- 阿里云百炼（DashScope）的 API Key、Workspace Base URL、账号额度和调用费用都由贡献者自行申请与承担。
- 请勿把 `.env`、`*.db`、录音样本、打包产物或任何含个人数据的文件提交到仓库。如果不慎提交过密钥，请先在服务商后台轮换，再联系我们处理历史记录。

## 提交改动

1. 从 `main` 建一个语义化分支，例如 `fix/caption-timeline`、`feat/subtitle-export`。
2. commit message 用简短的一句话说明意图，例如 `fix: 修复暂停后字幕重复回填`。
3. 大改动尽量拆成多个小提交，方便 review 和回退。
4. 发起 PR 时写清楚：改了什么、为什么改、怎么验证、是否影响现有配置或数据格式。

## 验证

- 后端改动：在 `backend/` 下运行 `pytest`，确保现有测试通过；涉及 ASR / 翻译链路的改动请补对应测试。
- 插件改动：运行 `pnpm build`，并在 `chrome://extensions` 里实际加载一次，确认 YouTube 页面上音频捕获与字幕面板正常。
- 涉及界面或实时效果的改动，附上截图或短 GIF 会大幅加快 review。

## 提 Issue

为了让问题更容易复现，建议包含：

- 操作系统、Chrome 版本、Python / Node 版本
- 复现步骤，以及期望行为与实际行为
- 后端日志或浏览器控制台报错（**请先把 API Key、Workspace ID 等敏感信息打码**）
- 出问题的视频链接或场景描述（是否带英文字幕、是否走了 ASR 回退）

## 行为约定

保持友善、就事论事。本项目是学习与技术探索用途，不接受恶意请求、爬取他人数据或绕过平台服务条款的改动。

## 许可

向本项目提交贡献，即表示你同意该贡献以 [MIT License](LICENSE) 一并授权。第三方依赖、模型服务与 SDK 各自遵循其原有许可与服务条款。
