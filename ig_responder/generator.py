"""Geração da resposta no estilo do dono da conta.

Duas estratégias:
  1. LLM (OpenAI-compatible, ex. Hermes API server) com o system prompt da persona.
  2. Fallback determinístico (templates da persona) quando não há LLM disponível.
"""
from __future__ import annotations

import json
import random
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import (
    ACTION_ESCALATE,
    ACTION_IGNORE,
    ACTION_LIKE_ONLY,
    ACTION_REPLY,
    Settings,
)
from .persona import Persona
from .sentiment import Sentiment


@dataclass
class Draft:
    comment_id: str
    comment_text: str
    author: str
    sentiment: str
    sentiment_confidence: float
    text: str
    action: str
    confidence: float
    motivo: str
    engine: str  # "llm" | "template"

    def as_row(self) -> dict:
        return {
            "comment_id": self.comment_id,
            "author": self.author,
            "comment": self.comment_text,
            "sentiment": self.sentiment,
            "sentiment_conf": self.sentiment_confidence,
            "text": self.text,
            "action": self.action,
            "confidence": self.confidence,
            "motivo": self.motivo,
            "engine": self.engine,
        }


# ------------------------------------------------------------------- LLM
class LLMClient:
    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.llm_enabled and self.s.llm_base_url)

    def complete(self, system: str, user: str) -> str | None:
        if not self.enabled:
            return None
        payload = {
            "model": self.s.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "temperature": 0.7,
        }
        req = urllib.request.Request(
            self.s.llm_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.s.llm_api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.s.llm_timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError) as e:
            print(f"[llm] indisponível: {type(e).__name__}: {e}")
            return None


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------- templates
_TEMPLATES: dict[str, list[str]] = {
    "elogio": [
        "Que bom que fez sentido para você, {nome}! Valorizar esse trabalho é essencial. ❤️",
        "Fico feliz demais com isso, {nome}! É exatamente sobre isso que eu falo por aqui. ❤️",
        "Obrigado, {nome}! Você entendeu a mensagem: nosso trabalho tem valor. ✂️",
    ],
    "concordancia": [
        "Exatamente, {nome}! Mais peças representam mais tempo e mais responsabilidade.",
        "Concordo, {nome}! O serviço tem valor e não pode ser tratado como favor. ❤️",
        "É isso mesmo, {nome}! Desconto não pode virar obrigação.",
    ],
    "experiencia": [
        "{nome}, que relato importante! 👏 Você está no caminho certo: valorizar o próprio tempo muda tudo. Como está sendo essa virada no seu ateliê?",
        "Isso, {nome}! 👏 Quando a gente para de dar desconto, sobra mais para a gente. Percebeu diferença no faturamento?",
    ],
    "duvida": [
        "{nome}, comece cobrando o valor cheio na primeira proposta e não justifique o preço. Me chama no direct que eu te passo um roteiro. ✂️",
        "{nome}, anota o custo do seu tempo antes de orçar. Se quiser, me chama no direct que a gente ajusta isso junto. ✂️",
    ],
    "pergunta": [
        "{nome}, me chama no direct que eu te respondo com prazer! 😊",
        "{nome}, boa pergunta! Me manda um direct que eu te explico direitinho. ✂️",
    ],
    "critica": [
        "Entendo seu ponto, {nome}! O que eu defendo é que cada profissional saiba o custo do próprio tempo. ❤️",
    ],
}


# Tokens que não são nome de pessoa — aparecem em handles de ateliê
_GENERICOS = {
    "costureira", "costureiras", "atelie", "atelier", "ateliers", "modista",
    "oficial", "ofc", "by", "arte", "artes", "costura", "costuras", "croche",
    "bordado", "moda", "store", "loja", "shop", "studio", "estudio", "criacoes",
    "ajustes", "confeccao", "customizacao", "personalizados", "the", "real",
    "grupo", "clube", "cursos", "curso", "aula", "aulas", "dicas", "canal",
    "oficial1", "oficiall", "ofc1", "page", "of", "meu", "minha", "sou",
}


def _primeiro_nome(author: str) -> str:
    """Extrai um vocativo plausível de um handle do Instagram.

    'costureira_ana' -> 'Ana'      'atelie_maria' -> 'Maria'
    'joana.lima'     -> 'Joana'    'rosa.m_costuras_' -> 'Rosa'
    """
    import re as _re
    import unicodedata as _ud

    h = (author or "").strip().lstrip("@")
    partes = [p for p in _re.split(r"[._\-\d]+", h) if p]
    if not partes:
        return ""

    def limpo(p: str) -> str:
        p = _ud.normalize("NFKD", p)
        return "".join(c for c in p if not _ud.combining(c)).lower()

    candidatos = [p for p in partes if limpo(p) not in _GENERICOS and len(p) >= 2]
    if not candidatos:
        candidatos = [p for p in partes if len(p) >= 2]
    if not candidatos:
        return ""

    # Handles começam pelo nome da pessoa ('joana.lima', 'rosa.costuras') ou
    # por uma palavra genérica de ateliê ('atelie_maria', 'costureira_ana').
    if limpo(partes[0]) not in _GENERICOS and len(partes[0]) >= 2:
        nome = partes[0]
    else:
        nome = candidatos[0]
    return nome[:1].upper() + nome[1:].lower() if nome.isalpha() else nome


def template_reply(persona: Persona, sent: Sentiment, author: str, comment: str) -> Draft | None:
    nome = _primeiro_nome(author) or "costureira"

    if sent.label == "spam":
        return None
    if sent.label == "critica":
        txt = random.choice(_TEMPLATES["critica"]).format(nome=nome)
        return _mk(sent, author, comment, txt, ACTION_ESCALATE, 0.6,
                   "crítica exige revisão humana")
    tpls = _TEMPLATES.get(sent.label) or _TEMPLATES["concordancia"]
    txt = random.choice(tpls).format(nome=nome)
    # a confiança do template acompanha a confiança da classificação:
    # um comentário claramente elogioso não deveria ir para a fila só por
    # não haver LLM ligado.
    conf = round(min(0.95, 0.50 + sent.confidence * 0.45), 3)
    return _mk(sent, author, comment, txt, ACTION_REPLY, conf, "template da persona")


def _mk(sent: Sentiment, author: str, comment: str, txt: str,
        action: str, conf: float, motivo: str, engine: str = "template") -> Draft:
    return Draft(
        comment_id="", comment_text=comment, author=author,
        sentiment=sent.label, sentiment_confidence=sent.confidence,
        text=txt, action=action, confidence=conf, motivo=motivo, engine=engine,
    )


# ------------------------------------------------------------------ gerar
def generate(
    persona: Persona,
    sent: Sentiment,
    author: str,
    comment: str,
    settings: Settings,
    llm: LLMClient | None = None,
) -> Draft:
    """Gera um rascunho de resposta para um comentário."""
    llm = llm or LLMClient(settings)

    # spam/ofensa: nunca gasta LLM
    if sent.label == "spam":
        d = _mk(sent, author, comment, "", ACTION_IGNORE, 0.95, "spam/ofensa detectado")
        return d

    if llm.enabled:
        user = (
            f"Comentário de @{author or 'seguidora'}:\n\"{comment}\"\n\n"
            f"Classificação automática do sentimento: {sent.label} "
            f"(confiança {sent.confidence})\n\n"
            "Escreva a resposta no meu estilo."
        )
        raw = llm.complete(persona.system_prompt(), user)
        parsed = _extract_json(raw or "")
        if parsed and isinstance(parsed.get("texto"), str):
            action = parsed.get("acao") or ACTION_REPLY
            if action not in (ACTION_REPLY, ACTION_LIKE_ONLY, ACTION_IGNORE, ACTION_ESCALATE):
                action = ACTION_REPLY
            try:
                conf = float(parsed.get("confianca", 0.7))
            except (TypeError, ValueError):
                conf = 0.7
            texto = parsed["texto"].strip()
            if action == ACTION_IGNORE:
                texto = ""
            if action in (ACTION_REPLY, ACTION_LIKE_ONLY) and not texto:
                action = ACTION_LIKE_ONLY if action == ACTION_REPLY else action
            return Draft(
                comment_id="", comment_text=comment, author=author,
                sentiment=sent.label, sentiment_confidence=sent.confidence,
                text=texto, action=action, confidence=round(conf, 3),
                motivo=str(parsed.get("motivo", ""))[:200], engine="llm",
            )

    # fallback
    d = template_reply(persona, sent, author, comment)
    if d is None:
        return _mk(sent, author, comment, "", ACTION_IGNORE, 0.9, "spam/ofensa detectado")
    return d


def _norm_simples(t: str) -> str:
    """Minúsculas, sem acento, só alfanumérico."""
    import unicodedata as _ud

    t = _ud.normalize("NFKD", t or "")
    t = "".join(c for c in t if not _ud.combining(c))
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _strip_vocativo_handle(txt: str, author: str) -> str:
    """Remove um vocativo que nada mais é do que o handle repetido.

    O modelo escreve "@cliente_dificil Cliente difícil, ..." — repetir o handle
    como se fosse o nome da pessoa soa robótico numa resposta pública.
    """
    if not author:
        return txt
    m = re.match(r"^@(\S+)\s+(.*)$", txt, flags=re.S)
    if not m:
        return txt
    mencao, resto = m.group(1), m.group(2)

    alvo = _norm_simples(author)
    if not alvo:
        return txt

    palavras = resto.split()
    for n in range(1, min(4, len(palavras)) + 1):
        prefixo = " ".join(palavras[:n])
        if _norm_simples(prefixo) == alvo:
            sobra = " ".join(palavras[n:]).lstrip(" ,;:!.-")
            return f"@{mencao} {sobra}".strip()
    return txt


def personalize(draft: Draft, persona: Persona, author: str) -> Draft:
    """Garante o @ de menção, como o dono faz manualmente."""
    if draft.action != ACTION_REPLY or not draft.text:
        return draft
    txt = draft.text.strip()

    if txt.startswith("@"):
        txt = _strip_vocativo_handle(txt, author)

    if persona.usa_at_mencao and author and not txt.lstrip().startswith("@"):
        txt = f"@{author} {txt}"
    draft.text = re.sub(r"\s{2,}", " ", txt).strip()
    return draft
