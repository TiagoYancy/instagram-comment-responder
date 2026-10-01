"""Classificação de sentimento e intenção de comentários (PT-BR + multilíngue leve).

Funciona offline por regras — sem dependência de LLM. É o primeiro estágio;
o LLM (quando ligado) refina depois.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def _norm(t: str) -> str:
    """Minúsculas, sem acento, espaços colapsados."""
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


# ---------------------------------------------------------------- léxicos
ELOGIO = [
    "falou tudo", "falo tudo", "adorei", "amei", "perfeito", "otimo", "excelente",
    "parabens", "muito bom", "top", "maravilh", "show", "sensacional", "bravo",
    "salvei", "melhor", "incrivel", "obrigad", "obg", "valeu", "gratidao",
    "que verdade", "pura verdade", "e isso mesmo", "mandou bem", "arrasou",
    "bien dit", "perfetto", "bravissima",
]

CONCORDANCIA = [
    "concordo", "concord", "vdd", "verdade", "e verdade", "exatamente", "isso mesmo",
    "desse jeito", "e desse jeito", "e desse geito", "assim mesmo", "com certeza",
    "claro que", "realmente", "sim ", "isso ", "correto", "certo", "exato",
    "penso igual", "tambem acho", "verita", "everdadi", "e a mais pura verdade",
]

PERGUNTA_MARK = [
    "de onde voce", "qual cidade", "quanto custa", "quanto cobrar", "como faco",
    "como faz", "voce tem", "tem como", "sera que", "posso", "me ajuda",
    "onde voce", "qual o valor", "quanto e", "como assim", "me indica",
]

DUVIDA = [
    "como faco", "como faz", "preciso de ajuda", "me ajuda", "nao sei como",
    "o que faco", "dica", "me ensina", "conselho", "socorro", "duvida",
    "nao consigo", "ta dificil", "estou perdida",
]

CRITICA = [
    "discordo", "nao concordo", "isso nao", "ta errado", "e errado", "papo furado",
    "cobrar caro", "so quer", "nao gostei", "ruim", "pessimo", "absurdo", "ridiculo",
    "mentira", "engano", "charlatao", "exploracao",
]

SPAM_MARK = [
    "http://", "https://", "www.", ".com.br", "clique aqui", "link na bio",
    "siga meu", "meu perfil", "promocao", "compre agora", "whatsapp",
    "ganhe dinheiro", "renda extra", "investimento", "curso gratis",
    "telegram", "grupo vip", "golpe",
]

OFENSA = [
    "idiota", "burra", "burro", "otaria", "otario", "imbecil", "lixo", "merda",
    "va se", "cala a boca", "vagabunda", "vadia", "fdp", "puta",
]

# relato pessoal: verbos de experiência em 1ª pessoa
EXPERIENCIA_MARK = [
    "aconteceu comigo", "ja passei", "passei por isso", "eu ja ", "eu tambem",
    "eu tbm", "comigo foi", "fiz ", "eu faco", "eu faço", "eu nunca", "eu sempre",
    "eu coloquei", "eu peguei", "eu recuso", "tomei", "ja recusei", "aprendi",
    "anos atras", "na minha casa", "aqui no meu", "no meu atelie",
]

RELATO_LONGO_MIN = 220  # chars: relato pessoal costuma ser longo


@dataclass
class Sentiment:
    label: str
    confidence: float
    scores: dict[str, float]
    signals: list[str]


def _count(text: str, needles: list[str]) -> tuple[int, list[str]]:
    hits = [n for n in needles if n in text]
    return len(hits), hits


def classify(comment: str) -> Sentiment:
    """Classifica um comentário em um dos sentimentos de config.SENTIMENTS."""
    raw = (comment or "").strip()
    t = _norm(raw)
    scores: dict[str, float] = {k: 0.0 for k in
                                ("elogio", "concordancia", "pergunta", "experiencia",
                                 "duvida", "critica", "spam", "outro")}
    signals: list[str] = []

    if not t:
        return Sentiment("outro", 0.3, scores, ["vazio"])

    # --- spam / ofensa (curto-circuito: prioridade alta)
    n_spam, h_spam = _count(t, SPAM_MARK)
    n_ofensa, h_ofensa = _count(t, OFENSA)
    if n_spam >= 2 or (n_spam >= 1 and len(t) < 60):
        scores["spam"] += 0.9
        signals.append(f"spam:{h_spam[:3]}")
    if n_ofensa:
        scores["spam"] += 0.8
        signals.append(f"ofensa:{h_ofensa[:2]}")

    # --- crítica
    n_crit, h_crit = _count(t, CRITICA)
    if n_crit:
        scores["critica"] += 0.35 * n_crit
        signals.append(f"critica:{h_crit[:3]}")

    # --- dúvida / pergunta
    # Nota: "como faço X?" é simultaneamente pergunta e pedido de ajuda.
    # Damos precedência à dúvida (é o que pede resposta substantiva).
    n_duv, h_duv = _count(t, DUVIDA)
    if n_duv:
        scores["duvida"] += 0.5 * n_duv
        signals.append(f"duvida:{h_duv[:3]}")
    n_perg, h_perg = _count(t, PERGUNTA_MARK)
    if n_perg:
        scores["pergunta"] += 0.45 * n_perg
        signals.append(f"pergunta:{h_perg[:3]}")
    if raw.count("?") >= 1:
        scores["pergunta"] += 0.3
        signals.append("interrogacao")
    # "como faço X?" casa nas duas listas; o pedido de ajuda é o sinal mais forte.
    if n_duv and scores["pergunta"] > 0:
        scores["pergunta"] *= 0.5
        signals.append("desempate:duvida>pergunta")

    # --- elogio
    n_elo, h_elo = _count(t, ELOGIO)
    if n_elo:
        scores["elogio"] += 0.3 * n_elo
        signals.append(f"elogio:{h_elo[:3]}")

    # --- concordância
    n_con, h_con = _count(t, CONCORDANCIA)
    if n_con:
        scores["concordancia"] += 0.3 * n_con
        signals.append(f"concordancia:{h_con[:3]}")

    # --- experiência (relato pessoal)
    n_exp, h_exp = _count(t, EXPERIENCIA_MARK)
    if n_exp:
        scores["experiencia"] += 0.25 * n_exp
        signals.append(f"experiencia:{h_exp[:3]}")
    if len(raw) >= RELATO_LONGO_MIN and n_exp:
        scores["experiencia"] += 0.35
        signals.append("relato_longo")

    # --- comentários curtos de puro apoio (👏, ❤️, "Vdd")
    so_emoji = re.sub(r"[\s\W_]+", "", raw, flags=re.UNICODE) == ""
    if len(t) <= 12 and (so_emoji or t in ("vdd", "sim", "isso", "amem", "ok")):
        scores["concordancia"] += 0.45
        signals.append("apoio_curto")

    # desempate
    best = max(scores, key=lambda k: scores[k])
    best_score = scores[best]
    if best_score <= 0.0:
        return Sentiment("outro", 0.35, scores, signals or ["sem_sinal"])

    ordered = sorted(scores.values(), reverse=True)
    margem = ordered[0] - ordered[1] if len(ordered) > 1 else ordered[0]
    conf = min(0.95, 0.45 + best_score * 0.35 + margem * 0.35)
    return Sentiment(best, round(conf, 3), scores, signals)
