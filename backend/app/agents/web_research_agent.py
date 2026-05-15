import logging

import requests

from app.core.config import settings
from app.rag.schemas import WebResult

logger = logging.getLogger(__name__)


class WebResearchAgent:
    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        provider = settings.web_search_provider.lower().strip()

        if provider == "none":
            return []

        try:
            if provider == "tavily" and settings.tavily_api_key:
                return self._tavily(query, max_results)

            if provider == "serpapi" and settings.serpapi_api_key:
                return self._serpapi(query, max_results)

            if provider == "brave" and settings.brave_api_key:
                return self._brave(query, max_results)

            logger.warning("Web search provider is configured but API key is missing.")
            return []

        except requests.RequestException as error:
            logger.warning("Web search request failed: %s", error)
            return []

        except Exception as error:
            logger.exception("Unexpected web search error: %s", error)
            return []

    def _tavily(self, query: str, max_results: int) -> list[WebResult]:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
            },
            timeout=20,
        )

        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append(
                WebResult(
                    title=item.get("title") or "Untitled",
                    url=item.get("url") or "",
                    summary=item.get("content") or "",
                )
            )

        return results

    def _serpapi(self, query: str, max_results: int) -> list[WebResult]:
        response = requests.get(
            "https://serpapi.com/search.json",
            params={
                "q": query,
                "api_key": settings.serpapi_api_key,
                "num": max_results,
            },
            timeout=20,
        )

        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("organic_results", [])[:max_results]:
            results.append(
                WebResult(
                    title=item.get("title") or "Untitled",
                    url=item.get("link") or "",
                    summary=item.get("snippet") or "",
                )
            )

        return results

    def _brave(self, query: str, max_results: int) -> list[WebResult]:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={
                "q": query,
                "count": max_results,
            },
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": settings.brave_api_key or "",
            },
            timeout=20,
        )

        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("web", {}).get("results", [])[:max_results]:
            results.append(
                WebResult(
                    title=item.get("title") or "Untitled",
                    url=item.get("url") or "",
                    summary=item.get("description") or "",
                )
            )

        return results