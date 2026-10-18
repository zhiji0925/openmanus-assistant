import argparse
import asyncio
import time

from app.agent.manus import Manus
from app.logger import logger
from app.utils.report import ensure_detailed_report, save_task_report


async def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="运行 Manus agent")
    parser.add_argument(
        "--prompt", type=str, required=False, help="输入给 agent 的提示"
    )
    args = parser.parse_args()

    # 创建并初始化 Manus agent
    agent = await Manus.create()
    prompt = ""
    run_started_at = time.time()
    try:
        # 如果提供了命令行提示，则使用它；否则询问用户输入
        prompt = args.prompt if args.prompt else input("请输入你的提示: ")
        if not prompt.strip():
            logger.warning("提供的提示为空。")
            return

        logger.warning("正在处理你的请求...")
        await agent.run(prompt)
        logger.info("请求处理完成。")

        # 资料够可提前结束；若一直排查到满步数，则用本轮全部资料让 LLM 生成详尽完整报告
        messages = agent.memory.messages if getattr(agent, "memory", None) else []
        reached_max = bool(getattr(agent, "reached_max_steps", False))
        report_path = await ensure_detailed_report(
            prompt,
            messages,
            agent.llm,
            force=reached_max,  # 满 20 轮：必须按已收集资料生成完整报告
            run_started_at=run_started_at,
        )
        logger.info(f"报告已保存到: {report_path}")
    except KeyboardInterrupt:
        logger.warning("操作被中断。")
        # 中断时也尽量根据已有资料生成报告
        if prompt.strip() and getattr(agent, "memory", None):
            try:
                report_path = await ensure_detailed_report(
                    prompt,
                    agent.memory.messages,
                    agent.llm,
                    force=True,
                    run_started_at=run_started_at,
                )
                logger.info(f"中断前的报告已保存到: {report_path}")
            except Exception:
                report_path = save_task_report(prompt, agent.memory.messages)
                logger.info(f"中断前的过程报告已保存到: {report_path}")
    finally:
        # 确保在退出前清理 agent 资源
        await agent.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
