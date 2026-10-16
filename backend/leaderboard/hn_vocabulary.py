"""Seed data for `ProviderEntity` / `ProviderAlias`, applied by migration 0009.

This is the vocabulary the discussion filter is built from: the Provider and
Service dropdowns, and the tags on each thread. Two things about it are worth
stating plainly.

**Why a seed is right here, when `aliases.py` ships empty.** A *model* alias is a
judgement -- `gpt-5` might or might not be `gpt-5-mini`, and guessing produced a
wrong answer on real data, which is why that file refuses to seed anything. A
*provider* alias is not a judgement of that kind: "Anthropic" means the vendor
Anthropic, and "Qwen" means Alibaba's model family. There is nothing to infer, so
a reviewed list is knowledge rather than a guess.

**What is deliberately absent.** Common English words are left out even where they
name a real product, because a false tag is worse than a missing one: it puts a
thread in a filter it does not belong in, silently. So `Meta` alone is absent (HN
discusses "meta" constantly in the ordinary sense) while `Meta AI` and `Llama` are
present; `Continue` is absent entirely. `Cursor` is the one judgement call kept in
-- it is genuinely ambiguous with a text cursor, but it is also one of the most
discussed tools on the site, and omitting it would leave the Service filter unable
to answer one of its most likely questions. A reviewer who disagrees can narrow it
in the admin.

**How these fire.** `word` matches one whole word, `token_run` matches a whole
hyphen-joined token run, and `token_prefix` matches a leading token run of a
single word. Vendor and service stems use `token_prefix`, which is what makes
`gpt` reach "GPT-5" and `claude` reach "claude-3-opus" -- so the list stays a list
of subjects rather than an enumeration of versions. See `hn_matching.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import EntityKind, MatchMode


@dataclass(frozen=True)
class SeedAlias:
    """One spelling that tags an entity, and the rule that lets it fire."""

    text: str
    mode: str = MatchMode.TOKEN_PREFIX


@dataclass(frozen=True)
class SeedEntity:
    """A vendor or service, its reviewed spellings, and its vendor if it is one."""

    slug: str
    label: str
    kind: str
    #: For a service, the vendor that ships it. This is what makes a Provider
    #: filter useful: a thread that only ever says "Claude" is still an Anthropic
    #: thread.
    vendor: str = ""
    #: The exact `LMArenaEntry.organization` spelling, where one exists. Used only
    #: to cross-link; never a FK.
    lmarena_organization: str = ""
    aliases: tuple[SeedAlias, ...] = field(default_factory=tuple)
    note: str = ""


def _aliases(*texts: str, mode: str = MatchMode.TOKEN_PREFIX) -> tuple[SeedAlias, ...]:
    return tuple(SeedAlias(text=text, mode=mode) for text in texts)


#: Vendors first, then the services that belong to them. Order within each group
#: is by how much of the discussion they account for.
SEED_ENTITIES: tuple[SeedEntity, ...] = (
    # -- vendors ------------------------------------------------------------ #
    SeedEntity(
        slug="openai",
        label="OpenAI",
        kind=EntityKind.VENDOR,
        lmarena_organization="openai",
        aliases=_aliases("OpenAI"),
    ),
    SeedEntity(
        slug="anthropic",
        label="Anthropic",
        kind=EntityKind.VENDOR,
        lmarena_organization="anthropic",
        aliases=_aliases("Anthropic"),
    ),
    SeedEntity(
        slug="google",
        label="Google",
        kind=EntityKind.VENDOR,
        lmarena_organization="google",
        aliases=_aliases("Google"),
    ),
    SeedEntity(
        slug="meta",
        label="Meta",
        kind=EntityKind.VENDOR,
        lmarena_organization="meta",
        # `Meta` alone is deliberately absent: HN uses the word in its ordinary
        # sense far too often for the tag to mean anything.
        aliases=_aliases("Meta AI", mode=MatchMode.TOKEN_RUN),
        note="The bare word 'Meta' is not an alias -- it is too common in prose.",
    ),
    SeedEntity(
        slug="deepseek",
        label="DeepSeek",
        kind=EntityKind.VENDOR,
        lmarena_organization="deepseek",
        aliases=_aliases("DeepSeek"),
    ),
    SeedEntity(
        slug="alibaba",
        label="Alibaba",
        kind=EntityKind.VENDOR,
        lmarena_organization="alibaba",
        aliases=_aliases("Alibaba"),
    ),
    SeedEntity(
        slug="moonshot",
        label="Moonshot AI",
        kind=EntityKind.VENDOR,
        lmarena_organization="moonshot",
        aliases=_aliases("Moonshot"),
    ),
    SeedEntity(
        slug="minimax",
        label="MiniMax",
        kind=EntityKind.VENDOR,
        lmarena_organization="minimax",
        aliases=_aliases("MiniMax"),
    ),
    SeedEntity(
        slug="mistral",
        label="Mistral AI",
        kind=EntityKind.VENDOR,
        lmarena_organization="mistral",
        aliases=_aliases("Mistral"),
    ),
    SeedEntity(
        slug="xai",
        label="xAI",
        kind=EntityKind.VENDOR,
        lmarena_organization="xai",
        aliases=_aliases("xAI"),
    ),
    SeedEntity(
        slug="zai",
        label="Z.ai",
        kind=EntityKind.VENDOR,
        lmarena_organization="zai",
        aliases=_aliases("Zhipu", "Z.ai"),
        note="Published as Zhipu AI and as Z.ai; both spellings are aliases.",
    ),
    SeedEntity(
        slug="bytedance",
        label="ByteDance",
        kind=EntityKind.VENDOR,
        lmarena_organization="bytedance",
        aliases=_aliases("ByteDance"),
    ),
    SeedEntity(
        slug="tencent",
        label="Tencent",
        kind=EntityKind.VENDOR,
        lmarena_organization="tencent",
        aliases=_aliases("Tencent"),
    ),
    SeedEntity(
        slug="baidu",
        label="Baidu",
        kind=EntityKind.VENDOR,
        lmarena_organization="baidu",
        aliases=_aliases("Baidu"),
    ),
    SeedEntity(
        slug="xiaomi",
        label="Xiaomi",
        kind=EntityKind.VENDOR,
        lmarena_organization="xiaomi",
        aliases=_aliases("Xiaomi"),
    ),
    SeedEntity(
        slug="microsoft",
        label="Microsoft",
        kind=EntityKind.VENDOR,
        aliases=_aliases("Microsoft"),
    ),
    SeedEntity(
        slug="nvidia",
        label="NVIDIA",
        kind=EntityKind.VENDOR,
        aliases=_aliases("NVIDIA"),
    ),
    SeedEntity(
        slug="amazon",
        label="Amazon",
        kind=EntityKind.VENDOR,
        aliases=_aliases("Amazon"),
    ),
    SeedEntity(
        slug="cohere",
        label="Cohere",
        kind=EntityKind.VENDOR,
        aliases=_aliases("Cohere"),
    ),
    SeedEntity(
        slug="ibm",
        label="IBM",
        kind=EntityKind.VENDOR,
        lmarena_organization="ibm",
        aliases=_aliases("IBM", mode=MatchMode.WORD),
    ),
    SeedEntity(
        slug="perplexity",
        label="Perplexity",
        kind=EntityKind.VENDOR,
        lmarena_organization="perplexity",
        aliases=_aliases("Perplexity"),
    ),
    # -- services and model families ---------------------------------------- #
    SeedEntity(
        slug="chatgpt",
        label="ChatGPT",
        kind=EntityKind.SERVICE,
        vendor="openai",
        aliases=_aliases("ChatGPT"),
    ),
    SeedEntity(
        slug="gpt",
        label="GPT",
        kind=EntityKind.SERVICE,
        vendor="openai",
        aliases=_aliases("GPT"),
    ),
    SeedEntity(
        slug="codex",
        label="Codex",
        kind=EntityKind.SERVICE,
        vendor="openai",
        aliases=_aliases("Codex", "OpenAI Codex"),
    ),
    SeedEntity(
        slug="claude",
        label="Claude",
        kind=EntityKind.SERVICE,
        vendor="anthropic",
        aliases=_aliases("Claude"),
    ),
    SeedEntity(
        slug="claude-code",
        label="Claude Code",
        kind=EntityKind.SERVICE,
        vendor="anthropic",
        aliases=_aliases("Claude Code", mode=MatchMode.TOKEN_RUN),
    ),
    SeedEntity(
        slug="gemini",
        label="Gemini",
        kind=EntityKind.SERVICE,
        vendor="google",
        aliases=_aliases("Gemini"),
    ),
    SeedEntity(
        slug="gemma",
        label="Gemma",
        kind=EntityKind.SERVICE,
        vendor="google",
        aliases=_aliases("Gemma"),
    ),
    SeedEntity(
        slug="deepmind",
        label="Google DeepMind",
        kind=EntityKind.SERVICE,
        vendor="google",
        aliases=_aliases("DeepMind", "Google DeepMind"),
    ),
    SeedEntity(
        slug="gemini-cli",
        label="Gemini CLI",
        kind=EntityKind.SERVICE,
        vendor="google",
        aliases=_aliases("Gemini CLI", mode=MatchMode.TOKEN_RUN),
    ),
    SeedEntity(
        slug="llama",
        label="Llama",
        kind=EntityKind.SERVICE,
        vendor="meta",
        aliases=_aliases("Llama"),
    ),
    SeedEntity(
        slug="qwen",
        label="Qwen",
        kind=EntityKind.SERVICE,
        vendor="alibaba",
        aliases=_aliases("Qwen"),
    ),
    SeedEntity(
        slug="kimi",
        label="Kimi",
        kind=EntityKind.SERVICE,
        vendor="moonshot",
        aliases=_aliases("Kimi"),
    ),
    SeedEntity(
        slug="glm",
        label="GLM",
        kind=EntityKind.SERVICE,
        vendor="zai",
        aliases=_aliases("GLM", mode=MatchMode.WORD),
    ),
    SeedEntity(
        slug="grok",
        label="Grok",
        kind=EntityKind.SERVICE,
        vendor="xai",
        aliases=_aliases("Grok"),
    ),
    SeedEntity(
        slug="doubao",
        label="Doubao",
        kind=EntityKind.SERVICE,
        vendor="bytedance",
        aliases=_aliases("Doubao"),
    ),
    SeedEntity(
        slug="hunyuan",
        label="Hunyuan",
        kind=EntityKind.SERVICE,
        vendor="tencent",
        aliases=_aliases("Hunyuan"),
    ),
    SeedEntity(
        slug="ernie",
        label="Ernie",
        kind=EntityKind.SERVICE,
        vendor="baidu",
        aliases=_aliases("Ernie"),
    ),
    SeedEntity(
        slug="phi",
        label="Phi",
        kind=EntityKind.SERVICE,
        vendor="microsoft",
        aliases=_aliases("Phi"),
    ),
    SeedEntity(
        slug="copilot",
        label="Copilot",
        kind=EntityKind.SERVICE,
        vendor="microsoft",
        aliases=_aliases("Copilot", "GitHub Copilot"),
    ),
    SeedEntity(
        slug="command-r",
        label="Command R",
        kind=EntityKind.SERVICE,
        vendor="cohere",
        aliases=_aliases("Command R", mode=MatchMode.TOKEN_RUN),
    ),
    SeedEntity(
        slug="bedrock",
        label="AWS Bedrock",
        kind=EntityKind.SERVICE,
        vendor="amazon",
        aliases=_aliases("Bedrock"),
    ),
    # -- tooling and platforms ---------------------------------------------- #
    SeedEntity(
        slug="cursor",
        label="Cursor",
        kind=EntityKind.SERVICE,
        # The one ambiguous entry kept in on purpose. A text cursor is a real
        # collision, but leaving it out would leave the Service filter unable to
        # answer one of its most likely questions.
        aliases=_aliases("Cursor"),
        note=(
            "Ambiguous with a text cursor. Kept because it is one of the most "
            "discussed tools on the site; narrow it if the tag proves noisy."
        ),
    ),
    SeedEntity(
        slug="windsurf",
        label="Windsurf",
        kind=EntityKind.SERVICE,
        aliases=_aliases("Windsurf"),
    ),
    SeedEntity(
        slug="aider",
        label="Aider",
        kind=EntityKind.SERVICE,
        aliases=_aliases("Aider"),
    ),
    SeedEntity(
        slug="cline",
        label="Cline",
        kind=EntityKind.SERVICE,
        aliases=_aliases("Cline"),
    ),
    SeedEntity(
        slug="ollama",
        label="Ollama",
        kind=EntityKind.SERVICE,
        aliases=_aliases("Ollama"),
    ),
    SeedEntity(
        slug="vllm",
        label="vLLM",
        kind=EntityKind.SERVICE,
        aliases=_aliases("vLLM"),
    ),
    SeedEntity(
        slug="llama-cpp",
        label="llama.cpp",
        kind=EntityKind.SERVICE,
        aliases=_aliases("llama.cpp", mode=MatchMode.TOKEN_RUN),
    ),
    SeedEntity(
        slug="lm-studio",
        label="LM Studio",
        kind=EntityKind.SERVICE,
        aliases=_aliases("LM Studio", mode=MatchMode.TOKEN_RUN),
    ),
    SeedEntity(
        slug="openrouter",
        label="OpenRouter",
        kind=EntityKind.SERVICE,
        aliases=_aliases("OpenRouter"),
    ),
    SeedEntity(
        slug="hugging-face",
        label="Hugging Face",
        kind=EntityKind.SERVICE,
        aliases=_aliases("Hugging Face", "HuggingFace"),
    ),
)


def aliases_by_key() -> dict[str, tuple[SeedEntity, SeedAlias]]:
    """Every alias keyed by its normalized form, for the uniqueness check.

    The database enforces this too (`uniq_provider_alias_key`), but a duplicate in
    the seed would fail a migration rather than a review -- and the failure would
    be an `IntegrityError` in the middle of a deploy.
    """
    from .normalization import normalize_model_key

    resolved: dict[str, tuple[SeedEntity, SeedAlias]] = {}
    for entity in SEED_ENTITIES:
        for alias in entity.aliases:
            resolved[normalize_model_key(alias.text)] = (entity, alias)
    return resolved


__all__ = ["SEED_ENTITIES", "SeedAlias", "SeedEntity", "aliases_by_key"]
