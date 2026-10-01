"""Garante que a resposta vai no campo de RESPOSTA do comentário.

A ferramenta NUNCA deve publicar um comentário novo no post mencionando a
pessoa. Isso apareceria como um comentário solto na thread, não como resposta
ao comentário dela — e o Instagram não mostraria a conversa encadeada.

O único endpoint de escrita permitido é:
    POST /{ig-comment-id}/replies  {"message": "..."}
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ig_responder.client import Comment, GraphClient
from ig_responder.config import Settings


class RecordingClient(GraphClient):
    """Captura as chamadas em vez de ir à rede."""

    def __init__(self, settings):
        self.s = settings
        self.host = "https://graph.example.com"
        self.version = "v23.0"
        self.calls: list[tuple[str, str, dict | None]] = []

    def _call(self, method, path, params=None, body=None):
        self.calls.append((method, path, body))
        if method == "GET":
            if path.endswith("/comments"):
                return {"data": [{
                    "id": "C1", "text": "Falou tudo! 👏", "username": "ana",
                    "timestamp": "2026-01-01T00:00:00+0000", "like_count": 0,
                }]}
            return {"data": []}
        return {"id": "R1"}


def _settings():
    s = Settings()
    s.access_token = "tok"
    s.ig_user_id = "123"
    return s


def test_resposta_usa_endpoint_replies():
    c = RecordingClient(_settings())
    c.reply("C1", "@ana Exatamente!")
    method, path, body = c.calls[-1]
    assert method == "POST"
    assert path == "/C1/replies"
    assert body == {"message": "@ana Exatamente!"}


def test_nunca_publica_comentario_novo_no_post():
    """Nenhuma chamada de escrita pode ir para /{media}/comments."""
    c = RecordingClient(_settings())
    c.reply("C1", "@ana Exatamente!")
    c.hide("C2")

    for method, path, _ in c.calls:
        if method != "POST":
            continue
        assert "/comments" not in path, (
            f"escrita em endpoint de comentários do post: {method} {path} — "
            "isso criaria um comentário solto em vez de responder"
        )
        assert path.endswith("/replies") or path.count("/") == 1


def test_alvo_e_o_comment_id_do_comentario():
    """O id usado na resposta é o do COMENTÁRIO, não o do post."""
    c = RecordingClient(_settings())
    c.reply("COMMENT_ABC", "oi")
    assert c.calls[-1][1] == "/COMMENT_ABC/replies"


def test_resposta_vazia_recusada():
    c = RecordingClient(_settings())
    with pytest.raises(ValueError):
        c.reply("C1", "   ")


def test_leitura_de_comentarios_usa_o_post_id():
    """GET de comentários usa o media_id — leitura, não escrita."""
    c = RecordingClient(_settings())
    comentarios = c.list_comments("MEDIA_9")
    assert comentarios[0].id == "C1"
    method, path, _ = c.calls[-1]
    assert method == "GET"
    assert path == "/MEDIA_9/comments"


def test_fluxo_completo_sempre_encadeado(tmp_path):
    """Ponta a ponta: toda escrita é uma resposta encadeada a um comentário."""
    from ig_responder.persona import default_persona
    from ig_responder.runner import Responder
    from ig_responder.store import Store

    s = _settings()
    s.approval_mode = "auto"
    s.llm_enabled = False
    s.reply_delay_seconds = 0
    s.db_path = tmp_path / "t.sqlite3"
    s.persona_path = tmp_path / "p.json"
    default_persona().save(s.persona_path)

    c = RecordingClient(s)

    class MediaClient(RecordingClient):
        def list_media(self, limit=25):
            return [{"id": "MEDIA_9"}]

    c = MediaClient(s)
    r = Responder(s, store=Store(s.db_path), client=c)
    r.ingest()

    escritas = [(m, p) for m, p, _ in c.calls if m == "POST"]
    assert escritas, "deveria ter publicado pelo menos uma resposta"
    for method, path in escritas:
        assert path == "/C1/replies", f"escrita inesperada: {method} {path}"
