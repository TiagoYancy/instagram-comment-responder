# Instagram Comment Responder

Ferramenta autônoma que responde comentários no Instagram **no estilo do dono da
conta** — capta o tom, o vocabulário e o jeito de tratar o público, e reproduz
isso em cada resposta.

Nasceu analisando o perfil [@amigodacostureira](https://www.instagram.com/amigodacostureira/)
(nicho: costura, precificação e empreendedorismo para costureiras).

---

## Como funciona

```
comentário novo
      │
      ▼
┌─────────────────┐   ┌──────────────────┐   ┌─────────────────┐
│ 1. SENTIMENTO   │──▶│ 2. GERAÇÃO       │──▶│ 3. POLÍTICA     │
│ regras + LLM    │   │ LLM + persona    │   │ auto/aprova/skip│
└─────────────────┘   └──────────────────┘   └─────────────────┘
                                                      │
                            ┌─────────────────────────┼──────────────────┐
                            ▼                         ▼                  ▼
                     publica sozinho         fila de aprovação      ignora
```

**1. Sentimento** (`sentiment.py`) — classifica o comentário em `elogio`,
`concordancia`, `pergunta`, `experiencia`, `duvida`, `critica`, `spam` ou `outro`.
Roda offline por regras (rápido e sem custo), com sinais explicáveis.

**2. Geração** (`generator.py`) — monta a resposta usando o *system prompt* da
persona, que contém: tom, comprimento de frase, emojis favoritos, tratamento,
gírias, valores e **exemplos reais de respostas do dono** (few-shot). Se o LLM
estiver fora, cai em templates fiéis à persona.

**3. Política** (`policy.py`) — decide o destino. Esta é a peça que implementa
sua escolha de aprovar antes ou agir sozinho.

---

## Modos de operação

| Modo | Comportamento |
|---|---|
| `dry_run` | **Default.** Nunca publica. Só registra o que faria. Use para testar. |
| `approve` | Gera o rascunho e **espera sua aprovação** antes de publicar. |
| `auto` | **100% automático.** Publica sozinho quando a confiança ≥ `IG_MIN_CONFIDENCE`. |

Você troca de modo a qualquer momento, sem reiniciar nada:

```bash
python -m ig_responder mode auto       # passa a agir sozinho
python -m ig_responder mode approve    # volta a pedir aprovação
python -m ig_responder mode dry_run    # modo seguro, não publica
```

### Barreiras que valem mesmo no modo `auto`

O modo automático **não** publica tudo. Estas travas são permanentes:

- **Crítica / discordância** → sempre vai para aprovação humana. Risco de imagem.
- **Spam / ofensa** → sempre ignorado.
- **Confiança abaixo do mínimo** → vai para aprovação.
- **Texto com promessa comercial** (preço, desconto, prazo, "eu garanto") → aprovação.
- **Texto vazio** → aprovação.
- Teto de `IG_MAX_REPLIES` respostas por execução, com pausa entre elas.

---

## Instalação

Requer só Python 3.10+ (sem dependências externas obrigatórias).

```bash
cd /home/hermes/instagram-responder
cp .env.example .env
# preencha IG_ACCESS_TOKEN e IG_USER_ID
```

### Obter as credenciais

1. A conta do Instagram precisa ser **Profissional** (Comercial ou de Criador).
2. No [Meta for Developers](https://developers.facebook.com/), crie um app e
   adicione o produto **Instagram → API setup with Instagram login**.
3. Permissões necessárias:
   - `instagram_business_basic`
   - `instagram_business_manage_comments`
4. Gere o token de acesso e copie o **Instagram user ID** para o `.env`.
5. Para produção, troque o token de curta duração por um de longa duração
   (60 dias) e renove antes de expirar.

> O token é de uma conta profissional. Guarde o `.env` fora do controle de versão.

---

## Uso

```bash
# Aprende/atualiza a persona a partir de um corpus raspado de posts
python -m ig_responder learn data/corpus_amigodacostureira.json --handle @amigodacostureira

# Busca comentários novos, gera respostas e aplica a política
python -m ig_responder scan --posts 10 --comments 50

# Vê a fila de aprovação
python -m ig_responder queue

# Aprova (e publica) — opcionalmente reescrevendo o texto
python -m ig_responder approve 12
python -m ig_responder approve 12 --text "@maria Exatamente! Seu tempo tem valor. ❤️"

# Rejeita
python -m ig_responder reject 13 --reason "fora do tom"

# Estatísticas
python -m ig_responder stats

# Teste offline, sem tocar na API do Instagram
python -m ig_responder demo
```

---

## A persona

`data/persona.json` descreve como o dono fala. Pode ser:

- **aprendida** do corpus real (`learn`), e/ou
- **editada à mão** — é só JSON, mexa à vontade.

Campos principais:

```json
{
  "handle": "@amigodacostureira",
  "nicho": "costura, precificação e empreendedorismo para costureiras",
  "tom": ["acolhedor e respeitoso", "didático sem ser professoral", "..."],
  "comprimento_frase": "curta",
  "usa_at_mencao": true,
  "emojis_favoritos": ["❤️", "👏", "🎯"],
  "tratamento": "você",
  "nunca_faz": ["não usa 'vc' nem 'kkk'", "não promete preço ou prazo", "..."],
  "estrategia_por_sentimento": { "elogio": "...", "critica": "..." },
  "exemplos": {
    "experiencia": [
      { "comentario": "...", "resposta": "@fulana Isso, Fulana! 👏 ..." }
    ]
  },
  "valores": ["costura é trabalho, tempo e experiência", "..."]
}
```

**Quanto melhores os `exemplos` reais, mais fiel fica a voz.** É o campo de maior
retorno: são eles que ensinam o LLM a soar como o dono, e não como um bot.

---

## Arquitetura

```
ig_responder/
  config.py      credenciais, modos, limites
  persona.py     perfil de voz + aprendizado a partir do corpus
  sentiment.py   classificação de sentimento (offline, explicável)
  generator.py   geração da resposta (LLM ou template)
  policy.py      auto-publica vs. aprovação humana vs. ignora
  client.py      Instagram Graph API (comentários, respostas)
  store.py       SQLite: vistos, rascunhos, fila, histórico
  runner.py      orquestração do ciclo completo
  cli.py         interface de linha de comando
```

O `store.py` mantém um registro de tudo: comentário lido, sentimento atribuído,
resposta gerada, decisão tomada e resultado. Nada é respondido duas vezes.

---

## Testes

```bash
python -m pytest tests/ -q
```

32 testes cobrindo classificação de sentimento, aprendizado de persona,
política de decisão (incluindo as travas do modo automático) e persistência.

---

## Onde a resposta é publicada

A ferramenta responde **no campo de resposta do comentário**, exatamente como
quando você toca em "Responder" no app. A conversa fica encadeada: o seguidor vê
a sua resposta indentada logo abaixo do comentário dele, com o seu avatar.

O único endpoint de escrita usado é:

```
POST /{IG_COMMENT_ID}/replies   {"message": "..."}
```

O `{IG_COMMENT_ID}` é o id **do comentário**, não do post. A ferramenta **nunca**
publica um comentário novo no post mencionando a pessoa — isso criaria um
comentário solto na thread, sem encadeamento, e não é o que você faz manualmente.

Há testes que travam esse comportamento (`tests/test_endpoint_resposta.py`):
qualquer escrita para `/{media}/comments` faz a suíte falhar.

### Formato do texto

Confirmado em captura de tela da conta real:

```
@pizolatojozelia Falou uma coisa importantíssima! 🍑❤️
@pizolatojozelia Você acha que a maior dificuldade da costureira é
descobrir quanto cobrar ou ter coragem de manter o preço? 🎯
```

Regras que a ferramenta aplica (`tests/test_formato_resposta.py`):

- começa **sempre** com `@menção` ao autor do comentário
- **parágrafo único** — quebra de linha é colapsada em espaço
- **emoji no final**, 1 a 2 no máximo
- comentário curto de opinião → resposta curta e calorosa, muitas vezes
  terminando com uma **pergunta** que puxa conversa
- relato pessoal → reconhece o relato e pergunta como está sendo a mudança

A menção `@usuario` é o conteúdo da resposta, **não** o mecanismo de entrega: ela
vive dentro da resposta encadeada, nunca como comentário avulso.

---

## Limites conhecidos

- **Curtir comentário não é possível** pela API pública da Meta. A ferramenta
  falha de forma explícita em vez de fingir sucesso.
- **Só responde comentários de nível superior.** A API não permite responder
  a uma resposta; a Meta anexa a mensagem ao comentário raiz.
- **Não responde comentários ocultos** nem de vídeos ao vivo.
- **O Instagram limita chamadas.** Respeite `IG_MAX_REPLIES` e `IG_REPLY_DELAY`.
- A raspagem de páginas públicas (usada só para montar o corpus inicial) é
  frágil por natureza — serve para aprender a persona, não para operar.
