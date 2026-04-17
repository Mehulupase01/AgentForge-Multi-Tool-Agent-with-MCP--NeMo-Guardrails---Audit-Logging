from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP

ALLOWED_HOSTS = {
    "news.ycombinator.com",
    "hacker-news.firebaseio.com",
    "api.open-meteo.com",
}


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise PermissionError("Only http and https URLs are allowed")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise PermissionError(f"Host not allowed: {parsed.hostname}")


def build_server() -> FastMCP:
    mcp = FastMCP(
        "web_fetch",
        json_response=True,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8102")),
        streamable_http_path="/mcp",
    )

    @mcp.tool()
    async def fetch_url(url: str, max_bytes: int = 100000) -> dict:
        """Fetch an allowlisted URL and return a bounded response body."""
        _validate_url(url)
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url)
        body = response.text[: max_bytes]
        return {
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body": body,
        }

    @mcp.tool()
    async def hacker_news_top(count: int = 10) -> list[dict]:
        """Return the top Hacker News stories."""
        count = max(1, min(count, 25))
        async with httpx.AsyncClient(timeout=20.0) as client:
            ids_response = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
            ids_response.raise_for_status()
            story_ids = ids_response.json()[:count]
            items: list[dict] = []
            for story_id in story_ids:
                story_response = await client.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                )
                story_response.raise_for_status()
                story = story_response.json()
                items.append(
                    {
                        "id": story["id"],
                        "title": story.get("title", ""),
                        "url": story.get("url"),
                        "score": story.get("score", 0),
                    },
                )
        return items

    @mcp.tool()
    async def weather_for(latitude: float, longitude: float) -> dict:
        """Fetch a weather summary from Open-Meteo."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current_weather": "true",
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "UTC",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
        payload = response.json()
        return {
            "current": payload.get("current_weather", {}),
            "daily_max": payload.get("daily", {}).get("temperature_2m_max", [None])[0],
            "daily_min": payload.get("daily", {}).get("temperature_2m_min", [None])[0],
        }

    return mcp


def main() -> None:
    build_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
