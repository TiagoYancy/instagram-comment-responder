"""Política de decisão: o que publicar sozinho e o que exigir aprovação humana.

Esta é a peça que implementa o pedido do usuário:
  - modo "approve": tudo vai para uma fila e só publica após aprovação
  - modo "auto": publica 100% sozinho quando confiança e sentimento permitem
  - modo "dry_run": nunca publica (default seguro)
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import (
    ACTION_ESCALATE,
    ACTION_IGNORE,
    ACTION_LIKE_ONLY,
    ACTION_REPLY,
    Settings,
)
from .generator import Draft

# Sentimentos que NUNCA são publicados automaticamente, em nenhum modo.
NEVER_AUTO = {
    "critica",   # discordância pública: risco de imagem
    "spam",      # não se responde spam
}

# Sentimentos liberados para automação total
AUTO_OK = {"elogio", "concordancia", "experiencia", "pergunta", "duvida", "outro"}

DECISION_AUTO_PUBLISH = "auto_publish"
DECISION_NEEDS_APPROVAL = "needs_approval"
DECISION_SKIP = "skip"


@dataclass
class Decision:
    kind: str
    reason: str

    @property
    def publishes_now(self) -> bool:
        return self.kind == DECISION_AUTO_PUBLISH

    @property
    def queues(self) -> bool:
        return self.kind == DECISION_NEEDS_APPROVAL


def decide(draft: Draft, settings: Settings) -> Decision:
    """Decide o destino de um rascunho."""
    mode = settings.approval_mode

    # 1. Ações terminais
    if draft.action == ACTION_IGNORE or draft.sentiment == "spam":
        return Decision(DECISION_SKIP, "ignorado por política (spam/ofensa)")

    if draft.action == ACTION_ESCALATE or draft.sentiment in NEVER_AUTO:
        if mode == "dry_run":
            return Decision(DECISION_SKIP, "dry_run: escalaria para humano")
        return Decision(DECISION_NEEDS_APPROVAL, "sentimento sensível — revisão humana obrigatória")

    # 2. dry_run nunca publica
    if mode == "dry_run":
        return Decision(DECISION_SKIP, "dry_run: não publica")

    # 3. Modo aprovação
    if mode == "approve":
        return Decision(DECISION_NEEDS_APPROVAL, "modo approve: aguarda sua aprovação")

    # 4. Modo automático — barreiras de segurança
    if draft.sentiment not in AUTO_OK:
        return Decision(DECISION_NEEDS_APPROVAL, f"sentimento {draft.sentiment} fora da lista auto")

    if draft.confidence < settings.min_confidence:
        return Decision(
            DECISION_NEEDS_APPROVAL,
            f"confiança {draft.confidence:.2f} < mínimo {settings.min_confidence:.2f}",
        )

    if draft.action == ACTION_REPLY and not draft.text.strip():
        return Decision(DECISION_NEEDS_APPROVAL, "resposta vazia")

    # trava extra: texto com promessa comercial não vai sozinho
    proibidos = ("desconto de", "r$", "por apenas", "promoção", "promocao",
                 "eu garanto", "com certeza fica pronto", "te garanto")
    low = draft.text.lower()
    if any(p in low for p in proibidos):
        return Decision(DECISION_NEEDS_APPROVAL, "texto contém promessa comercial")

    return Decision(DECISION_AUTO_PUBLISH, "modo auto: confiança e sentimento OK")
