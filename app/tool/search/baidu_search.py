from typing import List
from urllib.parse import urljoin

from baidusearch.baidusearch import search

from app.tool.search.base import SearchItem, WebSearchEngine

BAIDU_BASE_URL = "https://www.baidu.com"


def _normalize_baidu_url(url: str) -> str:
    """补全百度返回的相对路径，例如 /s?wd=xxx。"""
    if not url:
        return ""
    url = str(url).strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return urljoin(BAIDU_BASE_URL, url)


class BaiduSearchEngine(WebSearchEngine):
    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        百度搜索引擎。

        返回根据 SearchItem 模型格式化的结果。
        """
        raw_results = search(query, num_results=num_results)

        # 将原始结果转换为 SearchItem 格式
        results = []
        for i, item in enumerate(raw_results):
            if isinstance(item, str):
                # 如果只是 URL
                results.append(
                    SearchItem(
                        title=f"Baidu Result {i+1}",
                        url=_normalize_baidu_url(item),
                        description=None,
                    )
                )
            elif isinstance(item, dict):
                # 如果是包含详细信息的字典
                results.append(
                    SearchItem(
                        title=item.get("title", f"Baidu Result {i+1}"),
                        url=_normalize_baidu_url(item.get("url", "")),
                        description=item.get("abstract", None),
                    )
                )
            else:
                # 尝试直接获取属性
                try:
                    results.append(
                        SearchItem(
                            title=getattr(item, "title", f"Baidu Result {i+1}"),
                            url=_normalize_baidu_url(getattr(item, "url", "")),
                            description=getattr(item, "abstract", None),
                        )
                    )
                except Exception:
                    # 回退到基本结果
                    results.append(
                        SearchItem(
                            title=f"Baidu Result {i+1}",
                            url=_normalize_baidu_url(str(item)),
                            description=None,
                        )
                    )

        return [item for item in results if item.url]
