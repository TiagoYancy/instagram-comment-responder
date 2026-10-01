"""Orquestração: busca comentários, gera respostas, decide e publica."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .client import GraphClient, GraphError
from .config import ACTION_LIKE_ONLY, ACTION_REPLY, Settings
from .generator import LLMClient, generate, personalize
from .persona import Persona
from .policy import (
    DECISION_AUTO_PUBLISH,
    DECISION_NEEDS_APPROVAL,
    decide,
)
from .sentiment import classify
from .store import Store


@dataclass
class RunReport:
    scanned_posts: int = 0
    scanned_comments: int = 0
    new_comments: int = 0
    auto_published: int = 0
    queued_for_approval: int = 0
    skipped: int = 0
    errors: int = 0
    details: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [
            f"posts varridos ......... {self.scanned_posts}",
            f"comentários lidos ...... {self.scanned_comments}",
            f"comentários novos ...... {self.new_comments}",
            f"publicados sozinho ..... {self.auto_published}",
            f"na fila de aprovação ... {self.queued_for_approval}",
            f"ignorados .............. {self.skipped}",
            f"erros .................. {self.errors}",
        ]
        if self.details:
            lines.append("")
            lines.extend(self.details[:40])
        return "\n".join(lines)


class Responder:
    def __init__(self, settings: Settings, store: Store | None = None,
                 client: GraphClient | None = None, persona: Persona | None = None):
        self.s = settings
        self.store = store or Store(settings.db_path)
        self.client = client or GraphClient(settings)
        self.persona = persona or Persona.load(settings.persona_path)
        self.llm = LLMClient(settings)

    # -------------------------------------------------------------- ingest
    def ingest(self, media_limit: int = 10, comment_limit: int = 50) -> RunReport:
        """Lê posts e comentários da API e guarda os inéditos."""
        rep = RunReport()
        if not self.client.configured:
            rep.errors += 1
            rep.details.append("credential ausente: defina IG_ACCESS_TOKEN e IG_USER_ID")
            return rep

        try:
            media = self.client.list_media(limit=media_limit)
        except GraphError as e:
            rep.errors += 1
            rep.details.append(f"erro listando posts: {e}")
            return rep

        rep.scanned_posts = len(media)
        for m in media:
            mid = m.get("id", "")
            try:
                comments = self.client.list_comments(mid, limit=comment_limit)
            except GraphError as e:
                rep.errors += 1
                rep.details.append(f"erro lendo comentários de {mid}: {e}")
                continue
            for c in comments:
                rep.scanned_comments += 1
                if self.store.seen(c.id):
                    continue
                sent = classify(c.text)
                self.store.save_comment(c, sent, media_id=mid)
                rep.new_comments += 1

                # pula comentários do próprio dono
                if c.username and self.persona.handle.strip("@").lower() == c.username.lower():
                    rep.skipped += 1
                    continue

                draft = generate(self.persona, sent, c.username, c.text, self.s, self.llm)
                draft = personalize(draft, self.persona, c.username)
                draft.comment_id = c.id
                decision = decide(draft, self.s)
                draft_id = self.store.save_draft(draft, decision, media_id=mid)

                if decision.kind == DECISION_NEEDS_APPROVAL:
                    rep.queued_for_approval += 1
                    rep.details.append(
                        f"⏳ @{c.username} [{sent.label} {sent.confidence:.2f}] "
                        f"-> fila: {decision.reason}")
                elif decision.kind == DECISION_AUTO_PUBLISH:
                    ok, info = self.publish(draft)
                    if ok:
                        rep.auto_published += 1
                        rep.details.append(f"✅ @{c.username} [{sent.label}] publicado: {draft.text[:70]}")
                    else:
                        rep.errors += 1
                        rep.details.append(f"❌ @{c.username} falha ao publicar: {info}")
                else:
                    # ignorado: sai da fila, não deve ficar pendente de aprovação
                    self.store.set_state(draft_id, "skipped", error=decision.reason)
                    rep.skipped += 1
                    rep.details.append(f"⏭️  @{c.username} [{sent.label}] ignorado: {decision.reason}")

                # ritmo humano entre publicações
                if decision.kind == DECISION_AUTO_PUBLISH and self.s.reply_delay_seconds > 0:
                    time.sleep(self.s.reply_delay_seconds + random.uniform(0, 4))

                if rep.auto_published >= self.s.max_replies_per_run:
                    rep.details.append("limite de respostas por execução atingido")
                    return rep
        return rep

    # ------------------------------------------------------------- publish
    def publish(self, draft) -> tuple[bool, str]:
        row = None
        for r in self.store.pending(limit=500):
            if r["comment_id"] == draft.comment_id:
                row = r
                break
        draft_id = row["id"] if row else None

        if draft.action == ACTION_LIKE_ONLY:
            if draft_id:
                self.store.set_state(draft_id, "skipped",
                                     error="like-only: API não expõe curtir comentário")
            return True, "like_only (nada publicado)"
        if draft.action != ACTION_REPLY or not draft.text.strip():
            if draft_id:
                self.store.set_state(draft_id, "skipped", error="sem texto")
            return True, "nada a publicar"

        try:
            res = self.client.reply(draft.comment_id, draft.text)
        except (GraphError, ValueError) as e:
            if draft_id:
                self.store.mark_failed(draft_id, str(e))
            return False, str(e)

        if draft_id:
            self.store.mark_published(draft_id, str(res.get("id", "")))
        return True, str(res.get("id", ""))

    # ------------------------------------------------------------- aprovar
    def approve(self, draft_id: int, text: str | None = None) -> tuple[bool, str]:
        row = self.store.get_draft(draft_id)
        if not row:
            return False, f"rascunho {draft_id} não encontrado"
        if row["state"] not in ("pending", "failed"):
            return False, f"rascunho {draft_id} está em estado {row['state']}"

        final = (text if text is not None else row["reply_text"] or "").strip()
        if not final:
            return False, "texto vazio — edite antes de aprovar"

        try:
            res = self.client.reply(row["comment_id"], final)
        except (GraphError, ValueError) as e:
            self.store.mark_failed(draft_id, str(e))
            return False, str(e)

        self.store.conn.execute("UPDATE drafts SET reply_text=? WHERE id=?", (final, draft_id))
        self.store.conn.commit()
        self.store.set_state(draft_id, "approved", decided_at=None)
        self.store.mark_published(draft_id, str(res.get("id", "")))
        return True, str(res.get("id", ""))

    def reject(self, draft_id: int, reason: str = "") -> tuple[bool, str]:
        row = self.store.get_draft(draft_id)
        if not row:
            return False, f"rascunho {draft_id} não encontrado"
        self.store.set_state(draft_id, "rejected", error=reason[:300] or None)
        return True, "rejeitado"

    def set_mode(self, mode: str) -> tuple[bool, str]:
        from .config import APPROVAL_MODES
        mode = mode.strip().lower()
        if mode not in APPROVAL_MODES:
            return False, f"modo inválido. use: {', '.join(APPROVAL_MODES)}"
        self.store.set_setting("approval_mode", mode)
        self.s.approval_mode = mode
        return True, f"modo agora é '{mode}'"
