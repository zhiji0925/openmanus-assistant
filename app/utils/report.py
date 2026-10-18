"""任务完成后生成 Markdown 报告。"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Tuple

from app.config import config


_PROCESS_MARKERS = (
    "让我",
    "接下来",
    "现在我将",
    "现在分析",
    "下一步",
    "继续检查",
    "进一步检查",
    "我将对",
    "开始检查",
)
_FINDING_MARKERS = (
    "结论",
    "发现",
    "问题",
    "建议",
    "缺少",
    "没有",
    "应",
    "优先",
    "风险",
    "优势",
    "对比",
    "销量",
    "份额",
    "HTTPS",
    "http://",
    "robots",
    "sitemap",
    "Cache-Control",
    "ETag",
    "gzip",
    "Title",
    "Description",
    "nofollow",
    "混合内容",
    "时效",
)
_SEO_MARKERS = ("seo", "SEO", "搜索引擎优化", "网站审查", "优化报告", "优化建议")


def _message_text(message: Any) -> str:
    """从消息对象中提取可读文本。"""
    content = getattr(message, "content", None)
    if not content:
        return ""
    return str(content).strip()


def _is_placeholder_heavy(text: str) -> bool:
    """判断文本是否充斥占位语句，缺少实质内容。"""
    markers = ("待补充", "暂缺", "后续完善", "TODO", "TBD")
    return any(marker in text for marker in markers)


def _is_process_chatter(text: str) -> bool:
    """判断是否为过程性口头禅（尚未形成结论）。"""
    head = text[:40]
    if any(marker in head for marker in _PROCESS_MARKERS):
        # 若后半段仍有实质发现，不完全丢弃
        if sum(1 for m in _FINDING_MARKERS if m in text) >= 2 and len(text) >= 60:
            return False
        return True
    if text.endswith("。") and any(text.endswith(s) for s in ("检查。", "分析。", "查看。")):
        return True
    return False


def _strip_process_suffix(text: str) -> str:
    """去掉句尾“让我继续…”过程尾巴，保留前面的发现。"""
    cleaned = re.sub(
        r"(让我|接下来|现在我将|现在分析)[^。\n]*[。]?$",
        "",
        text.strip(),
    )
    return cleaned.strip()


def _is_seo_task(prompt: str) -> bool:
    """根据用户请求判断是否为 SEO/网站审查类任务。"""
    return any(marker in prompt for marker in _SEO_MARKERS)


def _score_block(text: str) -> int:
    """给文本块打分，分数越高越像“重点结论”。"""
    score = 0
    for marker in _FINDING_MARKERS:
        if marker in text:
            score += 2
    if _is_process_chatter(text):
        score -= 5
    if _is_placeholder_heavy(text):
        score -= 3
    # 偏爱更靠后、更完整的段落
    score += min(len(text) // 80, 5)
    return score


def _pick_focus_content(messages: List[Any]) -> Tuple[List[str], List[str]]:
    """
    从消息历史中挑选更接近“结论/重点”的内容。
    返回：(结论块列表, 证据块列表)
    """
    assistant_blocks: List[Tuple[int, str]] = []
    evidence_blocks: List[str] = []

    for message in messages:
        role = getattr(message, "role", "")
        text = _message_text(message)
        if not text:
            continue

        if role == "assistant":
            cleaned = _strip_process_suffix(text)
            if not cleaned or len(cleaned) < 20:
                continue
            if _is_process_chatter(cleaned) and _score_block(cleaned) < 4:
                continue
            assistant_blocks.append((_score_block(cleaned), cleaned))
        elif role == "tool":
            # 保留含数据/SEO 特征的工具结果摘要
            if any(
                key in text
                for key in (
                    "销量",
                    "份额",
                    "同比增长",
                    "万辆",
                    "Search results",
                    "Status:",
                    "robots",
                    "sitemap",
                    "http://",
                    "https://",
                    "Cache-Control",
                    "Title",
                    "Description",
                    "年份分布",
                    "链接",
                )
            ):
                preview = text if len(text) <= 900 else text[:900] + "\n\n...(内容已截断)"
                evidence_blocks.append(preview)

    # 按分数排序，再保留靠后的高分段落，避免流水账
    assistant_blocks.sort(key=lambda x: x[0], reverse=True)
    top = [block for score, block in assistant_blocks if score >= 2][:6]
    # 若高分不足，退回最后几段非空 assistant 文本（已过滤过程话）
    if len(top) < 2:
        recent = [
            _strip_process_suffix(_message_text(m))
            for m in messages
            if getattr(m, "role", "") == "assistant" and _message_text(m)
        ]
        recent = [t for t in recent if t and not _is_process_chatter(t)]
        top = (top + recent[-4:])[:6]

    return top, evidence_blocks[-4:]


def _find_agent_written_reports(workspace: Path, after_ts: Optional[float] = None) -> List[Path]:
    """查找工作区中 agent 手写的专题报告（排除系统自动重点报告）。"""
    if not workspace.exists():
        return []
    reports = []
    for path in workspace.glob("*.md"):
        name = path.name
        if name.startswith("任务重点报告_") or name.startswith("任务报告_"):
            continue
        if after_ts is not None and path.stat().st_mtime < after_ts:
            continue
        reports.append(path)
    reports.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return reports


def build_report_markdown(prompt: str, messages: Optional[List[Any]] = None) -> str:
    """根据用户请求和 agent 消息历史组装偏重结论的 Markdown 报告。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    messages = messages or []
    focus_blocks, evidence_blocks = _pick_focus_content(messages)
    seo_task = _is_seo_task(prompt)

    workspace = Path(config.workspace_root)
    agent_reports = _find_agent_written_reports(workspace)

    sections: List[str] = [
        "# SEO审查重点报告" if seo_task else "# 任务重点报告",
        "",
        f"- 用户请求：{prompt}",
        f"- 生成时间：{now}",
        "",
    ]

    if agent_reports:
        sections.append("## 优先阅读（Agent 专题报告）")
        sections.append("")
        for path in agent_reports[:3]:
            sections.append(f"- `{path.name}`")
        sections.append("")
        sections.append("上面的专题报告通常比本自动摘要更完整，请优先打开查看。")
        sections.append("")

    if seo_task:
        sections.extend(
            [
                "## 一、核心结论（优先看）",
                "",
            ]
        )
    else:
        sections.extend(
            [
                "## 重点结论与分析",
                "",
            ]
        )

    has_content = False
    for block in focus_blocks:
        if _is_placeholder_heavy(block) and len(block) < 200:
            continue
        # 转成条目，减少过程散文感
        bullet = block if block.lstrip().startswith(("-", "*", "1.", "#")) else f"- {block}"
        sections.append(bullet)
        sections.append("")
        has_content = True

    if seo_task:
        sections.extend(
            [
                "## 二、问题与建议（从执行过程提炼）",
                "",
                "- 高优先级：HTTPS/混合内容、可抓取性（robots/sitemap）、核心页面 Title/Description。",
                "- 中优先级：内容时效、陈旧页面清理、内链与外链质量。",
                "- 低优先级：缓存头（Cache-Control/ETag）、页面细节规范。",
                "- 建议：将已确认问题整理进专题 `.md`，每条建议对应一个可执行动作与验收标准。",
                "",
            ]
        )

    if evidence_blocks:
        sections.append("## 三、证据摘录" if seo_task else "## 关键检索摘录")
        sections.append("")
        for item in evidence_blocks:
            sections.append("```")
            sections.append(item)
            sections.append("```")
            sections.append("")
        has_content = True

    if not has_content and not agent_reports:
        sections.append(
            "本次任务未沉淀出足够的重点结论。"
            "若是 SEO 任务，请确保审查后写出含“核心结论 / 问题优先级 / 可操作建议”的完整 `.md`。"
        )
        sections.append("")
    else:
        sections.append("## 说明")
        sections.append("")
        sections.append(
            "本文件由系统根据执行过程自动提炼重点生成；"
            "若工作区已有 agent 手写的专题报告，请优先查看那份完整 `.md`。"
        )
        sections.append("")

    return "\n".join(sections)


def save_task_report(
    prompt: str,
    messages: Optional[List[Any]] = None,
    filename: Optional[str] = None,
) -> Path:
    """将任务重点报告保存到工作区，返回报告文件路径。"""
    workspace = Path(config.workspace_root)
    workspace.mkdir(parents=True, exist_ok=True)

    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"任务重点报告_{timestamp}.md"
    if not filename.endswith(".md"):
        filename = f"{filename}.md"

    report_path = workspace / filename
    content = build_report_markdown(prompt, messages)
    report_path.write_text(content, encoding="utf-8")
    return report_path


def _collect_materials_text(
    messages: List[Any], max_chars: int = 28000
) -> str:
    """把本轮执行中的 assistant/tool 内容压缩成写报告用的素材文本。"""
    chunks: List[str] = []
    for message in messages:
        role = getattr(message, "role", "")
        text = _message_text(message)
        if not text:
            continue
        if role not in {"assistant", "tool", "user"}:
            continue
        # 过长工具输出截断，保留关键片段
        if role == "tool" and len(text) > 1500:
            text = text[:1500] + "\n...(已截断)"
        elif role == "assistant" and len(text) > 2000:
            text = text[:2000] + "\n...(已截断)"
        chunks.append(f"[{role}]\n{text}")

    materials = "\n\n---\n\n".join(chunks)
    if len(materials) > max_chars:
        materials = materials[-max_chars:]
        materials = "...(前文已截断)\n\n" + materials
    return materials


def _suggest_report_filename(prompt: str) -> str:
    """根据用户请求生成可读的报告文件名。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if _is_seo_task(prompt):
        return f"SEO审查完整报告_{timestamp}.md"
    return f"任务完整报告_{timestamp}.md"


def _is_substantial_report(path: Path) -> bool:
    """判断已有报告是否足够详尽（避免把空大纲当作成品）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False
    if len(text) < 400:
        return False
    if _is_placeholder_heavy(text) and len(text) < 800:
        return False
    # 至少包含结论或建议类标题/关键词
    keys = ("结论", "建议", "问题", "发现", "摘要", "优化")
    return sum(1 for k in keys if k in text) >= 2


async def ensure_detailed_report(
    prompt: str,
    messages: Optional[List[Any]],
    llm: Any,
    *,
    force: bool = False,
    run_started_at: Optional[float] = None,
) -> Path:
    """
    确保产出详尽完整报告。

    - 若 agent 已提前写好足够详尽的专题 `.md`，且未强制收尾：直接沿用。
    - 若跑满步数，或尚无详尽报告：基于本轮全部资料调用 LLM 生成详尽报告并落盘。
    """
    from app.logger import logger
    from app.schema import Message

    workspace = Path(config.workspace_root)
    workspace.mkdir(parents=True, exist_ok=True)
    messages = messages or []

    existing = _find_agent_written_reports(workspace, after_ts=run_started_at)
    substantial = [p for p in existing if _is_substantial_report(p)]

    if substantial and not force:
        logger.info(f"已有详尽专题报告，沿用: {substantial[0]}")
        # 仍写一份重点索引，方便定位
        save_task_report(prompt, messages)
        return substantial[0]

    materials = _collect_materials_text(messages)
    seo_task = _is_seo_task(prompt)
    structure_hint = (
        "请按以下结构撰写（SEO/网站审查）：\n"
        "1. 核心结论（优先看，3～5条）\n"
        "2. 问题清单（高/中/低优先级）\n"
        "3. 可操作优化建议（每条对应问题，尽量可落地）\n"
        "4. 证据与数据摘录（来自执行过程）\n"
        "5. 未核实项说明（明确写未检索到/未完成的部分）\n"
        if seo_task
        else "请按以下结构撰写：\n"
        "1. 核心结论（优先看）\n"
        "2. 关键发现与分析\n"
        "3. 可操作建议\n"
        "4. 证据与来源摘录\n"
        "5. 未核实项说明\n"
    )

    system_text = (
        "你是专业报告撰写助手。请仅根据提供的执行素材撰写详尽中文 Markdown 报告。"
        "不要编造素材中没有的数据；缺失处写“未检索到公开数据/本轮未完成核实”。"
        "禁止输出“待补充”“后续完善”等占位语。直接输出 Markdown 正文，不要包裹代码块。"
    )
    user_text = (
        f"用户原始请求：\n{prompt}\n\n"
        f"{structure_hint}\n"
        "以下是本轮（最多 20 步）执行过程中收集到的全部可用素材，"
        "请据此写成一份详尽完整报告：\n\n"
        f"{materials or '（本轮几乎没有可用素材，请如实说明无法完成深入分析的原因，并给出后续建议。）'}"
    )

    logger.info("正在根据本轮全部资料生成详尽完整报告...")
    content = await llm.ask(
        messages=[Message.user_message(user_text)],
        system_msgs=[Message.system_message(system_text)],
        stream=False,
        temperature=0.0,
    )
    content = (content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:markdown|md)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content).strip()

    if not content:
        # 极端情况下退回自动提炼，避免空文件
        content = build_report_markdown(prompt, messages)

    report_path = workspace / _suggest_report_filename(prompt)
    report_path.write_text(content, encoding="utf-8")
    logger.info(f"详尽完整报告已保存到: {report_path}")

    # 同步写一份重点索引，指向完整报告
    index_path = save_task_report(prompt, messages)
    try:
        index_text = index_path.read_text(encoding="utf-8")
        banner = (
            f"\n## 完整报告文件\n\n"
            f"- 请优先阅读：`{report_path.name}`\n\n"
        )
        if "## 完整报告文件" not in index_text:
            index_path.write_text(
                index_text.replace("## 说明", banner + "## 说明", 1)
                if "## 说明" in index_text
                else index_text + banner,
                encoding="utf-8",
            )
    except Exception:
        pass

    return report_path

