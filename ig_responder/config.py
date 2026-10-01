"""Configuração da ferramenta de respostas autônomas no Instagram."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"

# ---------------------------------------------------------------- API Graph
# Instagram API with Instagram Login (Business Login for Instagram)
GRAPH_HOST = os.getenv("IG_GRAPH_HOST", "https://graph.instagram.com")
GRAPH_VERSION = os.getenv("IG_GRAPH_VERSION", "v23.0")

# Permissões exigidas: instagram_business_basic + instagram_business_manage_comments
REQUIRED_SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_comments",
]

# ------------------------------------------------------------- Comportamento
APPROVAL_MODES = ("approve", "auto", "dry_run")
#   approve  -> gera rascunho e espera aprovação humana antes de publicar
#   auto     -> publica sozinho quando a confiança >= min_confidence
#   dry_run  -> nunca publica, só registra o que faria (default seguro)

# Sentimentos que a ferramenta sabe detectar
SENTIMENTS = (
    "elogio",       # "que verdade", "adorei", "falou tudo"
    "concordancia",  # "vdd", "é isso mesmo", "concordo"
    "pergunta",     # "de onde você é?", "quanto cobrar?"
    "experiencia",  # relato pessoal da seguidora
    "duvida",       # pedido de ajuda/conselho
    "critica",      # discordância
    "spam",         # link, propaganda, ofensa
    "outro",
)

# Ações possíveis
ACTION_REPLY = "reply"
ACTION_LIKE_ONLY = "like_only"
ACTION_IGNORE = "ignore"
ACTION_ESCALATE = "escalate"   # manda para aprovação humana obrigatória


@dataclass
class Settings:
    """Configuração carregada de variáveis de ambiente / arquivo .env."""

    access_token: str = ""
    ig_user_id: str = ""
    approval_mode: str = "dry_run"
    min_confidence: float = 0.75
    max_replies_per_run: int = 20
    reply_delay_seconds: float = 12.0
    allow_emoji: bool = True
    llm_base_url: str = "http://127.0.0.1:8642/v1"
    llm_api_key: str = ""
    llm_model: str = "hermes-agent"
    llm_enabled: bool = True
    llm_timeout: int = 120
    persona_path: Path = field(default_factory=lambda: DATA_DIR / "persona.json")
    db_path: Path = field(default_factory=lambda: DATA_DIR / "responder.sqlite3")

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        env_file = env_file or (ROOT / ".env")
        if env_file.exists():
            for raw in env_file.read_text(encoding="utf-8").splitlines():
                raw = raw.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                k, v = raw.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

        return cls(
            access_token=os.getenv("IG_ACCESS_TOKEN", ""),
            ig_user_id=os.getenv("IG_USER_ID", ""),
            approval_mode=os.getenv("IG_APPROVAL_MODE", "dry_run").lower(),
            min_confidence=float(os.getenv("IG_MIN_CONFIDENCE", "0.75")),
            max_replies_per_run=int(os.getenv("IG_MAX_REPLIES", "20")),
            reply_delay_seconds=float(os.getenv("IG_REPLY_DELAY", "12")),
            allow_emoji=os.getenv("IG_ALLOW_EMOJI", "1") not in ("0", "false", "False"),
            llm_base_url=os.getenv("IG_LLM_BASE_URL", "http://127.0.0.1:8642/v1"),
            llm_api_key=os.getenv("IG_LLM_API_KEY", os.getenv("API_SERVER_KEY", "")),
            llm_model=os.getenv("IG_LLM_MODEL", "hermes-agent"),
            llm_enabled=os.getenv("IG_LLM_ENABLED", "1") not in ("0", "false", "False"),
            llm_timeout=int(os.getenv("IG_LLM_TIMEOUT", "120")),
        )

    def validate_mode(self) -> None:
        if self.approval_mode not in APPROVAL_MODES:
            raise ValueError(
                f"IG_APPROVAL_MODE inválido: {self.approval_mode!r}. "
                f"Use um de {APPROVAL_MODES}."
            )
