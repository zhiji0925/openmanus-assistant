OpenManus 二次开发版 - 简要说明
================================

本仓库为 OpenManus 本地二次开发版本。详细介绍见 README.md / README_zh.md。


【别人下载后的操作】
--------------------

环境要求：
  - Python 3.12 或更高版本
  - Windows / macOS / Linux

一、创建并激活虚拟环境（推荐）

  Windows PowerShell：
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1

  macOS / Linux：
    python3 -m venv .venv
    source .venv/bin/activate

二、安装依赖

    pip install -r requirements.txt

三、配置 API（必须）

  1. 复制示例配置：
       Windows：
         copy config\config.example.toml config\config.toml
       macOS / Linux：
         cp config/config.example.toml config/config.toml

  2. 编辑 config/config.toml，填写自己的 LLM 配置，例如：
       [llm]
       model = "你的模型名"
       base_url = "你的 API 地址"
       api_key = "你的密钥"

       [llm.vision]
       model = "你的视觉模型名"
       base_url = "你的 API 地址"
       api_key = "你的密钥"

  说明：
  - config/config.toml 含密钥，默认不随仓库提交，每人需自行创建。
  - 如使用 Daytona，再在 [daytona] 中填写 daytona_api_key。

四、可选：浏览器自动化

    playwright install

五、启动项目

  普通版：
    python main.py

  MCP 工具版：
    python run_mcp.py

  多智能体版：
    python run_flow.py

启动后在终端输入任务提示即可。

六、可选：数据分析 / 图表可视化智能体

  1. 在 config/config.toml 中设置：
       [runflow]
       use_data_analysis_agent = true

  2. 安装 Node.js（建议 18+），并执行：
       cd app/tool/chart_visualization
       npm install

  更细步骤见：app/tool/chart_visualization/README_zh.md

常见问题：
  - ModuleNotFoundError：确认已激活 .venv，并已执行 pip install -r requirements.txt
  - API 报错：检查 config.toml 中 model / base_url / api_key 是否正确
  - 不要提交自己的 config/config.toml 和 .env 到公开仓库
