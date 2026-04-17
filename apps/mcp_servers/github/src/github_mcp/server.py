from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

GITHUB_API = "https://api.github.com"


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def build_server(token: str | None = None) -> FastMCP:
    github_token = token or os.getenv("GITHUB_TOKEN")
    if not github_token:
        raise RuntimeError("GITHUB_TOKEN is required to start the github MCP server")

    mcp = FastMCP(
        "github",
        json_response=True,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8104")),
        streamable_http_path="/mcp",
    )

    @mcp.tool()
    async def list_user_repos(username: str, limit: int = 10) -> list[dict]:
        """List public repositories for a GitHub user."""
        async with httpx.AsyncClient(timeout=20.0, headers=_headers(github_token)) as client:
            response = await client.get(
                f"{GITHUB_API}/users/{username}/repos",
                params={"per_page": max(1, min(limit, 50)), "sort": "updated"},
            )
            response.raise_for_status()
        return [
            {
                "name": repo["name"],
                "full_name": repo["full_name"],
                "private": repo["private"],
                "html_url": repo["html_url"],
            }
            for repo in response.json()
        ]

    @mcp.tool()
    async def search_issues(repo: str, query: str, state: str = "open", limit: int = 10) -> list[dict]:
        """Search issues in a repository."""
        search_query = f"repo:{repo} is:issue state:{state} {query}".strip()
        async with httpx.AsyncClient(timeout=20.0, headers=_headers(github_token)) as client:
            response = await client.get(
                f"{GITHUB_API}/search/issues",
                params={"q": search_query, "per_page": max(1, min(limit, 50))},
            )
            response.raise_for_status()
        return [
            {
                "number": issue["number"],
                "title": issue["title"],
                "state": issue["state"],
                "html_url": issue["html_url"],
            }
            for issue in response.json().get("items", [])
        ]

    @mcp.tool()
    async def get_repo(owner: str, name: str) -> dict:
        """Fetch repository metadata from GitHub."""
        async with httpx.AsyncClient(timeout=20.0, headers=_headers(github_token)) as client:
            response = await client.get(f"{GITHUB_API}/repos/{owner}/{name}")
            response.raise_for_status()
        repo = response.json()
        return {
            "id": repo["id"],
            "full_name": repo["full_name"],
            "description": repo.get("description"),
            "private": repo["private"],
            "stargazers_count": repo.get("stargazers_count", 0),
            "html_url": repo["html_url"],
        }

    return mcp


def main() -> None:
    build_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
