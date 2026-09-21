"""GitHub 저장소 어댑터. 자막 검수를 저장소의 브랜치와 PR로 합니다.

쓰기는 `allow_write`가 켜져 있어야 합니다(설정 `R4_GITHUB_REVIEW_ENABLED`).
**기본 브랜치에는 쓰지 않고, 병합하지 않습니다.** 병합은 사람이 합니다.

돌아오는 파일은 남이 고친 글입니다. 크기를 먼저 보고, 폴더·다른 인코딩·깨진 글자는
읽지 않고 막습니다. 내용 검사는 `pipeline.review`가 합니다.

시험은 `client`에 대역을 넣습니다(`httpx.MockTransport`).
"""

from __future__ import annotations

import base64
from urllib.parse import quote

import httpx

from pipeline.review import MAX_FILE_BYTES

DEFAULT_API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"


class GitHubError(RuntimeError):
    pass


def require_write(enabled: bool) -> None:
    if not enabled:
        raise GitHubError("GitHub 검수가 꺼져 있습니다. R4_GITHUB_REVIEW_ENABLED를 켜세요.")


class GitHubRepository:
    def __init__(
        self,
        token: str,
        repository: str,
        *,
        client: httpx.Client,
        allow_write: bool = False,
        api_url: str = DEFAULT_API_URL,
    ):
        owner, _, name = repository.partition("/")
        if not owner or not name or "/" in name:
            raise ValueError("저장소는 'owner/repo' 모양이어야 합니다.")
        self.owner, self.name = owner, name
        self.token, self.client, self.allow_write = token, client, allow_write
        self.api_url = api_url.rstrip("/")

    @property
    def base(self) -> str:
        return f"{self.api_url}/repos/{quote(self.owner)}/{quote(self.name)}"

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        return self.client.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
            },
            timeout=30,
            **kwargs,
        )

    @staticmethod
    def _ok(response: httpx.Response, what: str) -> None:
        if response.status_code >= 400:
            raise GitHubError(f"GitHub {what} 실패: HTTP {response.status_code}")

    def branch_sha(self, branch: str) -> str | None:
        """브랜치가 가리키는 커밋. 없으면 None입니다."""
        response = self._request("GET", f"{self.base}/git/ref/heads/{quote(branch, safe='/')}")
        if response.status_code == 404:
            return None
        self._ok(response, "브랜치 조회")
        return response.json()["object"]["sha"]

    def create_branch(self, branch: str, sha: str) -> None:
        require_write(self.allow_write)
        response = self._request(
            "POST", f"{self.base}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha}
        )
        # 422는 이미 있다는 뜻입니다. 다시 만들지 않고 그대로 씁니다.
        if response.status_code == 422:
            return
        self._ok(response, "브랜치 만들기")

    def file(self, path: str, ref: str) -> tuple[str, str] | None:
        """(글자, 파일 sha). 없으면 None입니다."""
        response = self._request("GET", f"{self.base}/contents/{quote(path)}", params={"ref": ref})
        if response.status_code == 404:
            return None
        self._ok(response, "파일 읽기")
        data = response.json()
        if isinstance(data, list):
            raise GitHubError(f"{path}는 파일이 아니라 폴더입니다.")
        if int(data.get("size") or 0) > MAX_FILE_BYTES:
            raise GitHubError(f"{path}가 너무 큽니다({data.get('size')}바이트).")
        if data.get("encoding") != "base64":
            raise GitHubError(f"{path}를 읽을 수 없습니다(인코딩 {data.get('encoding')!r}).")
        raw = base64.b64decode(data["content"])
        if len(raw) > MAX_FILE_BYTES:
            raise GitHubError(f"{path}가 너무 큽니다({len(raw)}바이트).")
        try:
            return raw.decode("utf-8"), str(data["sha"])
        except UnicodeDecodeError as exc:
            raise GitHubError(f"{path}가 UTF-8이 아닙니다. 그대로 저장해 주세요.") from exc

    def put_file(self, path: str, branch: str, text: str, message: str) -> str | None:
        """파일을 그 브랜치에 씁니다. 내용이 같으면 **커밋하지 않고** None입니다."""
        require_write(self.allow_write)
        existing = self.file(path, branch)
        body = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if existing is not None:
            if existing[0] == text:
                return None
            body["sha"] = existing[1]
        response = self._request("PUT", f"{self.base}/contents/{quote(path)}", json=body)
        self._ok(response, "파일 쓰기")
        return str(response.json()["commit"]["sha"])

    def open_pull_request(self, branch: str, base: str, title: str, body: str) -> tuple[int, str]:
        """이 브랜치의 열린 PR이 있으면 그것을, 없으면 새로 만들어 (번호, 주소)를 돌려줍니다."""
        require_write(self.allow_write)
        found = self._request(
            "GET",
            f"{self.base}/pulls",
            params={"head": f"{self.owner}:{branch}", "state": "open"},
        )
        self._ok(found, "PR 조회")
        rows = found.json()
        if rows:
            return int(rows[0]["number"]), str(rows[0]["html_url"])
        response = self._request(
            "POST",
            f"{self.base}/pulls",
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        self._ok(response, "PR 만들기")
        data = response.json()
        return int(data["number"]), str(data["html_url"])

    def pull_request(self, number: int) -> dict:
        response = self._request("GET", f"{self.base}/pulls/{number}")
        self._ok(response, "PR 조회")
        data = response.json()
        return {
            "number": int(data["number"]),
            "state": data.get("state"),
            "merged": bool(data.get("merged")),
            "head_sha": (data.get("head") or {}).get("sha"),
        }
