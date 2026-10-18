import os
from typing import List, Optional

import requests

from app.logger import logger
from app.tool.search.base import SearchItem, WebSearchEngine


# SerpAPI 的 hl 参数需要完整语言码，短码需映射
_LANG_TO_HL = {
    "zh": "zh-cn",
    "zh-cn": "zh-cn",
    "zh-tw": "zh-tw",
    "en": "en",
    "ja": "ja",
    "ko": "ko",
    "fr": "fr",
    "de": "de",
    "es": "es",
}


class SerpAPISearchEngine(WebSearchEngine):
    """通过 SerpAPI 调用 Google 搜索，避免直接抓取页面。"""

    api_url: str = "https://serpapi.com/search.json"
    timeout: int = 30

    def _get_api_key(self) -> str:
        """从环境变量读取 SerpAPI Key。"""
        for name in ("SERPAPI_API_KEY", "SERP_API_KEY", "SERPAPI_KEY"):
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return ""

    def _normalize_hl(self, lang: Optional[str]) -> Optional[str]:
        """将配置中的语言码转换为 SerpAPI 支持的 hl。"""
        if not lang:
            return None
        key = lang.strip().lower().replace("_", "-")
        return _LANG_TO_HL.get(key, key)

    def perform_search(
        self,
        query: str,
        num_results: int = 10,
        lang: Optional[str] = None,
        country: Optional[str] = None,
        *args,
        **kwargs,
    ) -> List[SearchItem]:
        """
        使用 SerpAPI 执行 Google 搜索。

        Returns:
            按 SearchItem 格式整理后的结果列表。
        """
        api_key = self._get_api_key()
        if not api_key:
            raise RuntimeError(
                "未找到 SerpAPI Key，请设置环境变量 SERPAPI_API_KEY"
            )

        params = {
            "engine": "google",
            "q": query,
            "api_key": api_key,
            "num": max(1, min(int(num_results), 20)),
        }
        hl = self._normalize_hl(lang)
        if hl:
            params["hl"] = hl
        if country:
            params["gl"] = country.strip().lower()

        response = requests.get(self.api_url, params=params, timeout=self.timeout)
        # 尽量把 SerpAPI 返回的业务错误信息带出来，方便排查
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("error") or response.text[:200]
            except Exception:
                detail = response.text[:200]
            raise RuntimeError(
                f"SerpAPI HTTP {response.status_code}: {detail}"
            )

        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"SerpAPI error: {data['error']}")

        organic = data.get("organic_results") or []
        results: List[SearchItem] = []
        for item in organic[:num_results]:
            url = (item.get("link") or "").strip()
            if not url:
                continue
            results.append(
                SearchItem(
                    title=(item.get("title") or "").strip() or url,
                    url=url,
                    description=(item.get("snippet") or "").strip(),
                )
            )

        if not results:
            logger.warning(f"SerpAPI 未返回有效结果，query={query!r}")
        return results
