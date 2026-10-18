import time
from typing import Optional

from daytona_sdk import (
    CreateSandboxFromImageParams,
    Daytona,
    DaytonaConfig,
    Resources,
    Sandbox,
    SandboxState,
    SessionExecuteRequest,
)

from app.config import config
from app.utils.logger import logger

# 条件初始化 Daytona 客户端
daytona: Optional[Daytona] = None

daytona_settings = config.daytona
if daytona_settings and daytona_settings.daytona_api_key:
    logger.info("Initializing Daytona sandbox configuration")
    daytona_config = DaytonaConfig(
        api_key=daytona_settings.daytona_api_key,
        server_url=daytona_settings.daytona_server_url,
        target=daytona_settings.daytona_target,
    )

    logger.info("Daytona API key configured successfully")
    if daytona_config.server_url:
        logger.info(f"Daytona server URL set to: {daytona_config.server_url}")
    if daytona_config.target:
        logger.info(f"Daytona target set to: {daytona_config.target}")

    try:
        daytona = Daytona(daytona_config)
        logger.info("Daytona client initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize Daytona client: {e}")
        daytona = None
else:
    logger.info("Daytona configuration not found or API key not provided. Daytona features will be disabled.")


def _check_daytona_initialized():
    """检查 Daytona 客户端是否已初始化"""
    if daytona is None:
        raise RuntimeError("Daytona client is not initialized. Please configure daytona_api_key in config.toml")


async def get_or_start_sandbox(sandbox_id: str):
    """根据 ID 检索沙箱，检查其状态，如果需要则启动它。"""

    _check_daytona_initialized()
    logger.info(f"Getting or starting sandbox with ID: {sandbox_id}")

    try:
        sandbox = daytona.get(sandbox_id)

        # 检查沙箱是否需要启动
        if (
            sandbox.state == SandboxState.ARCHIVED
            or sandbox.state == SandboxState.STOPPED
        ):
            logger.info(f"Sandbox is in {sandbox.state} state. Starting...")
            try:
                daytona.start(sandbox)
                # 等待沙箱初始化
                # sleep(5)
                # 启动后刷新沙箱状态
                sandbox = daytona.get(sandbox_id)

                # 重启时在会话中启动 supervisord
                start_supervisord_session(sandbox)
            except Exception as e:
                logger.error(f"Error starting sandbox: {e}")
                raise e

        logger.info(f"Sandbox {sandbox_id} is ready")
        return sandbox

    except Exception as e:
        logger.error(f"Error retrieving or starting sandbox: {str(e)}")
        raise e


def _relax_browser_api_startup(sandbox: Sandbox) -> None:
    """避免镜像启动时访问 Google 失败导致 8003 服务退出。

    whitezxj/sandbox 的 browser_api 会在 FastAPI 启动阶段打开 Google。
    沙箱网络访问 Google 会报 ERR_QUIC_PROTOCOL_ERROR，启动函数再把异常抛出，
    uvicorn 直接退出，8003 端口始终没有监听。
    """
    remote_path = "/app/browser_api.py"
    try:
        raw = sandbox.fs.download_file(remote_path)
    except Exception as e:
        logger.warning(f"无法读取沙箱浏览器启动脚本 {remote_path}: {e}")
        return

    text = raw.decode("utf-8")
    original = text
    replacements = (
        (
            'await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=30000)',
            'await page.goto("about:blank", wait_until="domcontentloaded", timeout=30000)',
        ),
        (
            "await page.goto('https://www.google.com', wait_until='domcontentloaded', timeout=30000)",
            "await page.goto('about:blank', wait_until='domcontentloaded', timeout=30000)",
        ),
        (
            'raise RuntimeError(f"Browser initialization failed: {str(e)}")',
            'print(f"Browser initialization failed, keep server running: {e}")',
        ),
    )
    for old, new in replacements:
        text = text.replace(old, new)

    if text == original:
        logger.info("沙箱浏览器启动脚本无需修改")
        return

    sandbox.fs.upload_file(text.encode("utf-8"), remote_path)
    logger.info("已调整沙箱浏览器启动逻辑：首页改为 about:blank，初始化失败不再退出服务")


def start_supervisord_session(sandbox: Sandbox):
    """在会话中启动 supervisord。"""
    _check_daytona_initialized()
    # 必须在 supervisord 拉起 browser_api 之前改脚本，否则 8003 会因启动失败退出
    _relax_browser_api_startup(sandbox)
    session_id = "supervisord-session"
    try:
        logger.info(f"Creating session {session_id} for supervisord")
        sandbox.process.create_session(session_id)

        # 执行 supervisord 命令
        sandbox.process.execute_session_command(
            session_id,
            SessionExecuteRequest(
                command="exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf",
                var_async=True,
            ),
        )
        logger.info("Waiting for supervisord and browser automation service to start...")
        time.sleep(25)  # 等待 supervisord 启动

        # 等待浏览器自动化服务就绪（最多等待 60 秒）
        max_wait = 60
        wait_interval = 5
        waited = 0
        service_ready = False

        while waited < max_wait:
            try:
                # 检查服务是否可用
                check_cmd = "curl -s -f http://localhost:8003/api > /dev/null 2>&1 && echo 'READY' || echo 'NOT_READY'"
                response = sandbox.process.exec(check_cmd, timeout=10)
                # NOT_READY 中包含 READY，必须按整行判断，否则会在服务未就绪时提前结束等待
                output = (response.result or "").strip()
                if output == "READY":
                    service_ready = True
                    logger.info(f"Browser automation service is ready after {waited} seconds")
                    break
                logger.info(f"Browser automation service not ready yet: {output}")
            except Exception as e:
                logger.debug(f"Service check attempt {waited}s failed: {e}")

            time.sleep(wait_interval)
            waited += wait_interval
            logger.debug(f"Waiting for browser automation service... ({waited}/{max_wait}s)")

        if not service_ready:
            logger.warning(
                f"Browser automation service may not be ready after {max_wait} seconds. "
                "It may still be starting up. Subsequent browser operations may fail."
            )

        logger.info(f"Supervisord started in session {session_id}")
    except Exception as e:
        logger.error(f"Error starting supervisord session: {str(e)}")
        raise e


def create_sandbox(password: str, project_id: str = None):
    """创建配置了所有必需服务并正在运行的新沙箱。"""

    _check_daytona_initialized()
    if daytona_settings is None:
        raise RuntimeError("Daytona settings not configured")

    logger.info("Creating new Daytona sandbox environment")
    logger.info("Configuring sandbox with browser-use image and environment variables")

    labels = None
    if project_id:
        logger.info(f"Using sandbox_id as label: {project_id}")
        labels = {"id": project_id}

    params = CreateSandboxFromImageParams(
        image=daytona_settings.sandbox_image_name,
        public=True,
        labels=labels,
        env_vars={
            "CHROME_PERSISTENT_SESSION": "true",
            "RESOLUTION": "1024x768x24",
            "RESOLUTION_WIDTH": "1024",
            "RESOLUTION_HEIGHT": "768",
            "VNC_PASSWORD": password,
            "ANONYMIZED_TELEMETRY": "false",
            "CHROME_PATH": "",
            "CHROME_USER_DATA": "",
            "CHROME_DEBUGGING_PORT": "9222",
            "CHROME_DEBUGGING_HOST": "localhost",
            "CHROME_CDP": "",
        },
        resources=Resources(
            cpu=2,
            memory=4,
            disk=5,
        ),
        auto_stop_interval=15,
        auto_archive_interval=24 * 60,
    )

    # 创建沙箱
    sandbox = daytona.create(params)
    logger.info(f"Sandbox created with ID: {sandbox.id}")

    # 为新沙箱在会话中启动 supervisord
    start_supervisord_session(sandbox)

    logger.info(f"Sandbox environment successfully initialized")
    return sandbox


async def delete_sandbox(sandbox_id: str):
    """根据 ID 删除沙箱。"""
    _check_daytona_initialized()
    logger.info(f"Deleting sandbox with ID: {sandbox_id}")

    try:
        # 获取沙箱
        sandbox = daytona.get(sandbox_id)

        # 删除沙箱
        daytona.delete(sandbox)

        logger.info(f"Successfully deleted sandbox {sandbox_id}")
        return True
    except Exception as e:
        logger.error(f"Error deleting sandbox {sandbox_id}: {str(e)}")
        raise e
