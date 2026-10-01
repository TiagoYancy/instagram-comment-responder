"""CLI da ferramenta de respostas autônomas no Instagram.

Uso:
  python -m ig_responder learn <corpus.json> [--handle @conta]
  python -m ig_responder scan [--posts 10] [--comments 50]
  python -m ig_responder queue [--limit 20]
  python -m ig_responder approve <id> [--text "novo texto"]
  python -m ig_responder reject <id> [--reason "..."]
  python -m ig_responder mode [approve|auto|dry_run]
  python -m ig_responder stats
  python -m ig_responder demo            # roda offline com comentários de exemplo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .client import GraphClient
from .config import DATA_DIR, ROOT, Settings
from .generator import LLMClient, generate, personalize
from .persona import Persona, default_persona, learn_persona
from .policy import DECISION_AUTO_PUBLISH, DECISION_NEEDS_APPROVAL, decide
from .runner import Responder
from .sentiment import classify
from .store import Store


def _load_settings(args) -> Settings:
    s = Settings.load()
    if getattr(args, "mode", None):
        s.approval_mode = args.mode
    s.validate_mode()
    return s


# ------------------------------------------------------------------ learn
def cmd_learn(args) -> int:
    corpus_path = Path(args.corpus)
    if not corpus_path.exists():
        print(f"corpus não encontrado: {corpus_path}")
        return 2
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    base = default_persona() if not args.raw else Persona()
    p = learn_persona(corpus, handle=args.handle or base.handle, base=base)
    out = p.save(Path(args.out) if args.out else None)
    print(f"persona salva em {out}")
    print(json.dumps({
        "handle": p.handle,
        "tom": p.tom,
        "emojis_favoritos": p.emojis_favoritos,
        "tratamento": p.tratamento,
        "comprimento_frase": p.comprimento_frase,
        "usa_at_mencao": p.usa_at_mencao,
        "girias": p.girias,
        "exemplos_por_sentimento": {k: len(v) for k, v in p.exemplos.items()},
    }, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------- scan
def cmd_scan(args) -> int:
    s = _load_settings(args)
    r = Responder(s)
    rep = r.ingest(media_limit=args.posts, comment_limit=args.comments)
    print(rep.as_text())
    print("\nmodo:", s.approval_mode)
    return 0 if rep.errors == 0 else 1


# ------------------------------------------------------------------ queue
def cmd_queue(args) -> int:
    s = _load_settings(args)
    store = Store(s.db_path)
    rows = store.pending(limit=args.limit)
    if not rows:
        print("fila vazia ✅")
        return 0
    print(f"{len(rows)} rascunho(s) aguardando:\n")
    for r in rows:
        print(f"── #{r['id']}  @{r['author']}  [{r['sentiment']} "
              f"sent={r['sentiment_conf']:.2f} conf={r['confidence']:.2f}]")
        print(f"   comentário: {r['comment_text'][:160]}")
        print(f"   resposta  : {r['reply_text'] or '(vazio)'}")
        print(f"   motivo    : {r['decision_reason']}")
        print()
    print("aprovar:  python -m ig_responder approve <id>")
    print("rejeitar: python -m ig_responder reject <id>")
    return 0


# ---------------------------------------------------------------- approve
def cmd_approve(args) -> int:
    s = _load_settings(args)
    r = Responder(s)
    ok, info = r.approve(args.id, args.text)
    print(("✅ " if ok else "❌ ") + info)
    return 0 if ok else 1


def cmd_reject(args) -> int:
    s = _load_settings(args)
    r = Responder(s)
    ok, info = r.reject(args.id, args.reason or "")
    print(("✅ " if ok else "❌ ") + info)
    return 0 if ok else 1


# ------------------------------------------------------------------- mode
def cmd_mode(args) -> int:
    s = _load_settings(args)
    store = Store(s.db_path)
    if args.value:
        r = Responder(s, store=store)
        ok, info = r.set_mode(args.value)
        print(("✅ " if ok else "❌ ") + info)
        return 0 if ok else 1
    atual = store.get_setting("approval_mode", s.approval_mode)
    print(f"modo atual: {atual}")
    print("  approve -> você aprova cada resposta antes de publicar")
    print("  auto    -> publica sozinho acima da confiança mínima")
    print("  dry_run -> nunca publica (só registra)")
    return 0


# ------------------------------------------------------------------ stats
def cmd_stats(args) -> int:
    s = _load_settings(args)
    store = Store(s.db_path)
    print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
    print("modo:", store.get_setting("approval_mode", s.approval_mode))
    return 0


# ------------------------------------------------------------------- demo
DEMO_COMMENTS = [
    ("costureira_ana", "Que verdade! Falou tudo, vou começar a cobrar o meu valor 👏👏"),
    ("atelie_maria", "Vdd, eu sempre tive vergonha de cobrar mais"),
    ("joana.lima", "Aconteceu comigo semana passada: a cliente levou 4 peças e pediu desconto. Aprendi a dizer não e hoje trabalho em paz."),
    ("rosa_costuras", "de onde você é? qual cidade?"),
    ("nova_costureira", "como faço para parar de dar desconto sem perder cliente?"),
    ("promo_br", "GANHE DINHEIRO EM CASA!! clique aqui http://spam.example.com renda extra garantida"),
    ("cliente_chateada", "isso é papo de quem cobra caro, discordo totalmente"),
    ("admiradora", "Perfeito 👏 Salvei para ouvir todos os dias."),
]


def cmd_demo(args) -> int:
    """Executa o pipeline completo offline, sem tocar na API do Instagram."""
    s = Settings.load()
    s.approval_mode = args.mode or "dry_run"
    s.validate_mode()

    persona = Persona.load(s.persona_path)
    llm = LLMClient(s)

    print(f"persona: {persona.handle} | nicho: {persona.nicho}")
    print(f"modo: {s.approval_mode} | LLM: {'ligado' if llm.enabled else 'desligado'}")
    print("=" * 78)

    resumo = {"auto": 0, "fila": 0, "ignorado": 0}
    for autor, texto in DEMO_COMMENTS:
        sent = classify(texto)
        draft = generate(persona, sent, autor, texto, s, llm)
        draft = personalize(draft, persona, autor)
        decision = decide(draft, s)

        if decision.kind == DECISION_AUTO_PUBLISH:
            resumo["auto"] += 1
            tag = "✅ PUBLICA"
        elif decision.kind == DECISION_NEEDS_APPROVAL:
            resumo["fila"] += 1
            tag = "⏳ APROVAÇÃO"
        else:
            resumo["ignorado"] += 1
            tag = "⏭️  IGNORA"

        print(f"\n{tag}  @{autor}")
        print(f"   comentário : {texto[:110]}")
        print(f"   sentimento : {sent.label} (conf {sent.confidence:.2f})  sinais: {', '.join(sent.signals[:4])}")
        print(f"   resposta   : {draft.text or '(nada)'}")
        print(f"   motor      : {draft.engine} | confiança {draft.confidence:.2f}")
        print(f"   decisão    : {decision.reason}")

    print("\n" + "=" * 78)
    print(f"publicaria sozinho: {resumo['auto']} | fila humana: {resumo['fila']} | ignorados: {resumo['ignorado']}")
    return 0


# ------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ig_responder",
                                 description="Respostas autônomas no Instagram no estilo do dono da conta")
    ap.add_argument("--mode", choices=["approve", "auto", "dry_run"],
                    help="sobrescreve o modo de aprovação nesta execução")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("learn", help="aprende a persona a partir de um corpus raspado")
    p.add_argument("corpus")
    p.add_argument("--handle", default="")
    p.add_argument("--out", default="")
    p.add_argument("--raw", action="store_true", help="não usar a persona padrão como base")
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("scan", help="busca comentários novos e gera respostas")
    p.add_argument("--posts", type=int, default=10)
    p.add_argument("--comments", type=int, default=50)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("queue", help="mostra a fila de aprovação")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser("approve", help="aprova e publica um rascunho")
    p.add_argument("id", type=int)
    p.add_argument("--text", default=None)
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reject", help="rejeita um rascunho")
    p.add_argument("id", type=int)
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("mode", help="vê ou troca o modo (approve|auto|dry_run)")
    p.add_argument("value", nargs="?", default="")
    p.set_defaults(func=cmd_mode)

    p = sub.add_parser("stats", help="estatísticas")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("demo", help="roda offline com comentários de exemplo")
    p.set_defaults(func=cmd_demo)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
