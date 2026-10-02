"""Teste de integração do ciclo completo com um cliente falso (sem API real)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ig_responder.client import Comment, GraphError
from ig_responder.config import Settings
from ig_responder.persona import default_persona
from ig_responder.runner import Responder
from ig_responder.store import Store


class FakeClient:
    """Simula a Graph API em memória."""

    def __init__(self, comments, fail_on=None, configured=True):
        self.comments = comments
        self.fail_on = fail_on or set()
        self.published: list[tuple[str, str]] = []
        self.configured = configured

    def list_media(self, limit=25):
        return [{"id": "m1"}]

    def list_comments(self, media_id, limit=100):
        return [c for c in self.comments if c.media_id == media_id]

    def reply(self, comment_id, message):
        if comment_id in self.fail_on:
            raise GraphError(400, "erro simulado da API")
        self.published.append((comment_id, message))
        return {"id": f"reply_{comment_id}"}


def _settings(tmp_path, mode):
    s = Settings()
    s.approval_mode = mode
    s.llm_enabled = False          # determinístico
    s.reply_delay_seconds = 0
    s.max_replies_per_run = 50
    s.db_path = tmp_path / "t.sqlite3"
    s.persona_path = tmp_path / "persona.json"
    default_persona().save(s.persona_path)
    return s


COMENTARIOS = [
    Comment(id="c1", text="Falou tudo! Que verdade 👏", username="ana",
            timestamp="2026-01-01T00:00:00+0000", media_id="m1"),
    Comment(id="c2", text="clique aqui http://spam.com ganhe dinheiro",
            username="spammer", timestamp="2026-01-01T00:00:00+0000", media_id="m1"),
    Comment(id="c3", text="discordo totalmente, papo de quem cobra caro",
            username="critico", timestamp="2026-01-01T00:00:00+0000", media_id="m1"),
]


def test_ciclo_auto_publica_e_ignora(tmp_path):
    s = _settings(tmp_path, "auto")
    fake = FakeClient(COMENTARIOS)
    r = Responder(s, store=Store(s.db_path), client=fake)

    rep = r.ingest()

    assert rep.new_comments == 3
    assert rep.auto_published == 1                      # só o elogio
    assert rep.skipped == 1                             # spam
    assert rep.queued_for_approval == 1                 # crítica
    assert len(fake.published) == 1
    assert fake.published[0][0] == "c1"
    assert fake.published[0][1].startswith("@ana")


def test_ciclo_approve_nao_publica_nada(tmp_path):
    s = _settings(tmp_path, "approve")
    fake = FakeClient(COMENTARIOS)
    r = Responder(s, store=Store(s.db_path), client=fake)

    rep = r.ingest()

    assert fake.published == []                         # nada publicado
    assert rep.auto_published == 0
    assert rep.queued_for_approval == 2                 # elogio + crítica
    assert rep.skipped == 1                             # spam


def test_ciclo_dry_run_nao_publica(tmp_path):
    s = _settings(tmp_path, "dry_run")
    fake = FakeClient(COMENTARIOS)
    r = Responder(s, store=Store(s.db_path), client=fake)

    rep = r.ingest()

    assert fake.published == []
    assert rep.auto_published == 0
    assert rep.skipped == 3                             # tudo ignorado


def test_nao_responde_duas_vezes(tmp_path):
    s = _settings(tmp_path, "auto")
    fake = FakeClient(COMENTARIOS)
    store = Store(s.db_path)
    r = Responder(s, store=store, client=fake)

    r.ingest()
    assert len(fake.published) == 1

    rep2 = r.ingest()                                   # segunda passada
    assert rep2.new_comments == 0                       # nada novo
    assert len(fake.published) == 1                     # não republicou


def test_aprovar_publica_e_marca(tmp_path):
    s = _settings(tmp_path, "approve")
    fake = FakeClient(COMENTARIOS)
    store = Store(s.db_path)
    r = Responder(s, store=store, client=fake)
    r.ingest()

    pend = store.pending()
    assert len(pend) == 2
    alvo = [p for p in pend if p["comment_id"] == "c1"][0]

    ok, info = r.approve(alvo["id"])
    assert ok, info
    assert fake.published[-1][0] == "c1"
    assert store.get_draft(alvo["id"])["state"] == "published"


def test_aprovar_com_texto_editado(tmp_path):
    s = _settings(tmp_path, "approve")
    fake = FakeClient(COMENTARIOS)
    store = Store(s.db_path)
    r = Responder(s, store=store, client=fake)
    r.ingest()

    alvo = [p for p in store.pending() if p["comment_id"] == "c1"][0]
    novo = "@ana Texto reescrito à mão pelo dono da conta. ❤️"
    ok, _ = r.approve(alvo["id"], novo)
    assert ok
    assert fake.published[-1][1] == novo
    assert store.get_draft(alvo["id"])["reply_text"] == novo


def test_rejeitar_nao_publica(tmp_path):
    s = _settings(tmp_path, "approve")
    fake = FakeClient(COMENTARIOS)
    store = Store(s.db_path)
    r = Responder(s, store=store, client=fake)
    r.ingest()

    alvo = store.pending()[0]
    ok, _ = r.reject(alvo["id"], "fora do tom")
    assert ok
    assert store.get_draft(alvo["id"])["state"] == "rejected"
    assert fake.published == []


def test_falha_da_api_marca_failed(tmp_path):
    s = _settings(tmp_path, "auto")
    fake = FakeClient(COMENTARIOS, fail_on={"c1"})
    store = Store(s.db_path)
    r = Responder(s, store=store, client=fake)

    rep = r.ingest()

    assert rep.auto_published == 0
    assert rep.errors == 1
    assert store.stats().get("failed") == 1


def test_aprovar_duas_vezes_falha(tmp_path):
    s = _settings(tmp_path, "approve")
    fake = FakeClient(COMENTARIOS)
    store = Store(s.db_path)
    r = Responder(s, store=store, client=fake)
    r.ingest()

    alvo = [p for p in store.pending() if p["comment_id"] == "c1"][0]
    ok1, _ = r.approve(alvo["id"])
    ok2, msg2 = r.approve(alvo["id"])
    assert ok1 is True
    assert ok2 is False                                 # já publicado
    assert "published" in msg2
    assert len([p for p in fake.published if p[0] == "c1"]) == 1


def test_nao_responde_o_proprio_dono(tmp_path):
    s = _settings(tmp_path, "auto")
    proprio = Comment(id="c9", text="@ana Exatamente!", username="costureira",
                      timestamp="2026-01-01T00:00:00+0000", media_id="m1")
    fake = FakeClient([proprio])
    r = Responder(s, store=Store(s.db_path), client=fake)

    rep = r.ingest()

    assert rep.skipped == 1
    assert fake.published == []


def test_sem_credencial_nao_quebra(tmp_path):
    s = _settings(tmp_path, "auto")
    r = Responder(s, store=Store(s.db_path), client=FakeClient([], configured=False))

    rep = r.ingest()

    assert rep.errors == 1
    assert "credential" in rep.details[0]


def test_troca_de_modo(tmp_path):
    s = _settings(tmp_path, "dry_run")
    store = Store(s.db_path)
    r = Responder(s, store=store, client=FakeClient([]))

    ok, _ = r.set_mode("auto")
    assert ok and s.approval_mode == "auto"
    assert store.get_setting("approval_mode") == "auto"

    ok2, msg = r.set_mode("banana")
    assert ok2 is False
    assert "inválido" in msg
