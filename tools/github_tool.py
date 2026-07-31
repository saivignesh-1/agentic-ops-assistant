"""
Tool: get_github_issue
Calls the public GitHub REST API to fetch the live status of an issue.
No auth token required for public repos (rate-limited to 60 req/hr/IP;
set GITHUB_TOKEN env var to raise that limit).
"""
import os
import requests

TOOL_SCHEMA = {
    "name": "get_github_issue",
    "description": (
        "Get the current status, title, labels, and assignees of a GitHub issue "
        "or pull request from a public repository."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "Repository in 'owner/name' form, e.g. 'anthropics/anthropic-sdk-python'",
            },
            "issue_number": {
                "type": "integer",
                "description": "The issue or PR number to look up",
            },
        },
        "required": ["repo", "issue_number"],
    },
}


def run(repo: str, issue_number: int) -> dict:
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        return {"error": f"Network error contacting GitHub: {e}"}

    if resp.status_code == 404:
        return {"error": f"Issue #{issue_number} not found in {repo}"}
    if resp.status_code == 403:
        return {"error": "GitHub API rate limit exceeded. Set GITHUB_TOKEN to raise the limit."}
    if resp.status_code != 200:
        return {"error": f"GitHub API returned {resp.status_code}: {resp.text[:200]}"}

    data = resp.json()
    return {
        "repo": repo,
        "number": issue_number,
        "title": data.get("title"),
        "state": data.get("state"),
        "is_pull_request": "pull_request" in data,
        "labels": [l["name"] for l in data.get("labels", [])],
        "assignees": [a["login"] for a in data.get("assignees", [])],
        "comments": data.get("comments"),
        "html_url": data.get("html_url"),
        "updated_at": data.get("updated_at"),
    }
