"""思想孵化机 - 联网搜索服务

提供基于DuckDuckGo的免费网络搜索能力，让Agent可以获取实时信息减少幻觉。
"""
import re
import logging
import httpx
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# DuckDuckGo HTML搜索的URL
DDG_HTML_URL = "https://html.duckduckgo.com/html/"
# DuckDuckGo即时回答API
DDG_API_URL = "https://api.duckduckgo.com/"


class WebSearchService:
    """网络搜索服务"""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
        return self._client

    async def search(self, query: str, num_results: int = 5) -> List[Dict]:
        """搜索网络，返回结果列表

        Returns:
            [{"title": str, "snippet": str, "url": str}, ...]
        """
        results = []
        try:
            results = await self._search_ddg_html(query, num_results)
        except Exception as e:
            logger.warning(f"DuckDuckGo HTML搜索失败: {e}")

        if not results:
            try:
                results = await self._search_ddg_api(query, num_results)
            except Exception as e:
                logger.warning(f"DuckDuckGo API搜索失败: {e}")

        return results

    async def _search_ddg_html(self, query: str, num_results: int = 5) -> List[Dict]:
        """通过DuckDuckGo HTML页面搜索（最可靠的方式）"""
        data = {"q": query, "b": ""}
        resp = await self.client.post(DDG_HTML_URL, data=data)
        resp.raise_for_status()

        results = []
        html = resp.text

        # 解析搜索结果
        result_blocks = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )

        for url, title, snippet in result_blocks[:num_results]:
            # 清理HTML标签
            title = re.sub(r'<[^>]+>', '', title).strip()
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()
            # DuckDuckGo的URL可能需要解码
            if 'uddg=' in url:
                import urllib.parse
                url = urllib.parse.unquote(url.split('uddg=')[1].split('&')[0])
            if title and snippet:
                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": url,
                })

        return results

    async def _search_ddg_api(self, query: str, num_results: int = 5) -> List[Dict]:
        """通过DuckDuckGo Instant Answer API搜索"""
        params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
        resp = await self.client.get(DDG_API_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        results = []

        # 综合结果
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", query),
                "snippet": data["AbstractText"],
                "url": data.get("AbstractURL", ""),
            })

        # 相关话题
        for topic in data.get("RelatedTopics", [])[:num_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:80],
                    "snippet": topic.get("Text", ""),
                    "url": topic.get("FirstURL", ""),
                })

        return results[:num_results]

    def format_search_results(self, results: List[Dict], query: str = "") -> str:
        """将搜索结果格式化为Agent可读的文本"""
        if not results:
            return f"未找到关于「{query}」的搜索结果。"

        lines = [f"【联网搜索结果: {query}】"]
        for i, r in enumerate(results, 1):
            lines.append(f"\n{i}. {r['title']}")
            lines.append(f"   {r['snippet']}")
            if r.get('url'):
                lines.append(f"   来源: {r['url']}")
        lines.append("\n请参考以上搜索结果进行讨论，注意区分事实与观点。")

        return "\n".join(lines)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


# 全局单例
web_search = WebSearchService()
