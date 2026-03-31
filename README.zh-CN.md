# Open Perplexity 中文说明

Open Perplexity 是一个让别人也能直接使用的本地插件式项目。

更准确地说，它是一个 Python CLI（命令行工具），通过 CDP（Chrome DevTools Protocol，Chrome 调试控制接口）去控制本机已经登录的 Chrome 或 Chromium，然后自动操作 Perplexity 网页。

## 它是什么

这个仓库现在同时支持三种用法：

- 普通 Python 工具
- Codex / OpenClaw 风格插件项目
- 本地 skill 包装器

## 为什么这样做

这样更适合“给别人用”，因为别人不一定在你的目录结构里，也不一定知道原始脚本该怎么跑。

例子：

- 日常例子：把一个中文或英文问题直接发给 Perplexity，并拿回网页回复。
- 自动化例子：把 prompt 写进文件后批量运行。
- Agent 例子：让本地代理工具调用统一命令，而不是直接依赖你个人脚本路径。

## 当前适用范围

目前这个项目先定义为 `只适用于 Linux 桌面环境`。

这句话的意思是：

- 适用于有图形界面（GUI，也就是能正常打开可见浏览器窗口）的 Linux 机器
- 不适用于纯服务器环境，也就是没有桌面界面的 headless server（无头服务器）
- 目前不要宣传成 macOS、Windows 或纯 Linux server 通用工具

例子：

- 适用例子：Ubuntu Desktop
- 适用例子：带 X11 或 Wayland 桌面的 Linux 工作站
- 不适用例子：没有图形界面的 Ubuntu Server

## 快速开始

### 1. 创建虚拟环境

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

或者直接：

```bash
./skills/open-perplexity/bin/setup
```

### 2. 运行

```bash
open-perplexity --prompt "Explain market making in simple English."
```

或者：

```bash
open-perplexity --prompt-file ./prompt.txt --model claude
```

## 目录说明

- [`pyproject.toml`](/Users/fanliang/Downloads/open-perplexity/pyproject.toml): 打包配置
- [`src/open_perplexity/core.py`](/Users/fanliang/Downloads/open-perplexity/src/open_perplexity/core.py): 主要逻辑
- [`src/open_perplexity/cli.py`](/Users/fanliang/Downloads/open-perplexity/src/open_perplexity/cli.py): 命令行入口
- [`/.codex-plugin/plugin.json`](/Users/fanliang/Downloads/open-perplexity/.codex-plugin/plugin.json): 插件元数据
- [`/skills/open-perplexity/SKILL.md`](/Users/fanliang/Downloads/open-perplexity/skills/open-perplexity/SKILL.md): skill 说明

## License 选择

当前继续使用 `MIT` license（宽松开源许可证）最合适。

原因：

- 仓库本来就是 MIT
- 对英文用户和开发者生态最容易理解
- 分发、修改、二次集成门槛低

如果以后你想强调专利授权条款，可以再改成 Apache-2.0，但现在没必要硬切。

## 注意

- 这个工具依赖 Perplexity 网页结构，网页改版后可能要更新选择器。
- 它不是官方 API 封装，而是浏览器自动化。
- 它复用的是你本机浏览器登录态，不会绕过登录。
- 当前发布口径应当是 Linux desktop only，不是 server automation tool。
