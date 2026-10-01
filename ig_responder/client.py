"""Cliente da Instagram Graph API (comentários e respostas).

Suporta os dois modos de login da Meta:
  - Instagram API with Instagram Login  -> graph.instagram.com
  - Instagram API with Facebook Login   -> graph.facebook.com

Endpoints usados:
  GET  /{ig-user-id}/media                 lista posts
  GET  /{ig-media-id}/comments             lista comentários de um post
  GET  /{ig-comment-id}/replies            lista respostas de um comentário
  POST /{ig-comment-id}/replies?message=   responde um comentário
  POST /{ig-comment-id}?hide=true          esconde um comentário
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .config import Settings


class GraphError(RuntimeError):
    def __init__(self, status: int, payload: str):
        super().__init__(f"HTTP {status}: {payload[:400]}")
        self.status = status
        self.payload = payload


@dataclass
class Comment:
    id: str
    text: str
    username: str
    timestamp: str
    like_count: int = 0
    parent_id: str | None = None
    media_id: str | None = None


class GraphClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.host = settings.llm_base_url and None  # placeholder, sobrescrito abaixo
        self.host = None  # definido pelo from_settings
        self._set_host()

    def _set_host(self) -> None:
        from .config import GRAPH_HOST, GRAPH_VERSION
        self.host = GRAPH_HOST
        self.version = GRAPH_VERSION

    # ------------------------------------------------------------- helpers
    @property
    def configured(self) -> bool:
        return bool(self.s.access_token and self.s.ig_user_id)

    def _url(self, path: str) -> str:
        path = path if path.startswith("/") else "/" + path
        return f"{self.host}/{self.version}{path}"

    def _call(self, method: str, path: str, params: dict | None = None,
              body: dict | None = None) -> dict:
        params = dict(params or {})
        params["access_token"] = self.s.access_token
        url = self._url(path) + "?" + urllib.parse.urlencode(params)

        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise GraphError(e.code, e.read().decode("utf-8", "replace")) from e
        except urllib.error.URLError as e:
            raise GraphError(0, f"rede: {e}") from e

    # ---------------------------------------------------------------- read
    def list_media(self, limit: int = 25) -> list[dict]:
        out: list[dict] = []
        path = f"/{self.s.ig_user_id}/media"
        params = {
            "fields": "id,caption,media_type,permalink,timestamp,comments_count",
            "limit": min(limit, 100),
        }
        while len(out) < limit:
            page = self._call("GET", path, params)
            out.extend(page.get("data", []))
            nxt = (page.get("paging") or {}).get("next")
            if not nxt or len(out) >= limit:
                break
            # próxima página já vem com token embutido
            url = nxt
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                page = json.loads(r.read().decode("utf-8"))
            out.extend(page.get("data", []))
            nxt = (page.get("paging") or {}).get("next")
            if not nxt:
                break
            path, params = "", {}
            break  # paginação simples: uma volta basta para o caso de uso
        return out[:limit]

    def list_comments(self, media_id: str, limit: int = 100) -> list[Comment]:
        path = f"/{media_id}/comments"
        params = {
            "fields": "id,text,username,timestamp,like_count,parent_id",
            "limit": min(limit, 100),
        }
        page = self._call("GET", path, params)
        out = [
            Comment(
                id=d.get("id", ""),
                text=d.get("text", ""),
                username=d.get("username", ""),
                timestamp=d.get("timestamp", ""),
                like_count=int(d.get("like_count") or 0),
                parent_id=d.get("parent_id"),
                media_id=media_id,
            )
            for d in page.get("data", [])
        ]
        return out

    def list_replies(self, comment_id: str) -> list[Comment]:
        page = self._call("GET", f"/{comment_id}/replies",
                          {"fields": "id,text,username,timestamp,like_count"})
        return [
            Comment(
                id=d.get("id", ""), text=d.get("text", ""),
                username=d.get("username", ""), timestamp=d.get("timestamp", ""),
                like_count=int(d.get("like_count") or 0),
            )
            for d in page.get("data", [])
        ]

    # --------------------------------------------------------------- write
    def reply(self, comment_id: str, message: str) -> dict:
        """Publica uma resposta. Retorna {'id': ...}."""
        if not message.strip():
            raise ValueError("mensagem vazia")
        return self._call("POST", f"/{comment_id}/replies", body={"message": message})

    def hide(self, comment_id: str, hide: bool = True) -> dict:
        return self._call("POST", f"/{comment_id}",
                          body={"hide": "true" if hide else "false"})

    def like(self, comment_id: str) -> dict:
        """A API pública da Meta não expõe 'curtir comentário'.

        Mantido como ponto de extensão explícito — falha de forma clara em vez
        de silenciosamente fingir sucesso.
        """
        raise NotImplementedError(
            "A Instagram Graph API não oferece endpoint para curtir comentários. "
            "Use action=ignore ou action=reply."
        )
