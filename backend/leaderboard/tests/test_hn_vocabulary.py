"""The seeded provider vocabulary, and the migration that applies it.

The seed is configuration the whole filter rests on, so its invariants are
checked here rather than discovered during a deploy. A duplicate alias key, for
instance, would fail the `uniq_provider_alias_key` constraint *inside the
migration* -- an `IntegrityError` part-way through `migrate`, which is a bad place
to learn about a typo.
"""

from __future__ import annotations

import importlib
from collections import Counter

import pytest
from django.apps import apps as global_apps
from django.db import IntegrityError, transaction

from leaderboard.constants import EntityKind, MatchMode
from leaderboard.hn_matching import PhraseIndex, find_phrases
from leaderboard.hn_vocabulary import SEED_ENTITIES, aliases_by_key
from leaderboard.models import ProviderAlias, ProviderEntity
from leaderboard.normalization import normalize_model_key
from leaderboard.services.discussions import load_entity_vocabulary


class TestSeedShape:
    @pytest.mark.parametrize("entity", SEED_ENTITIES, ids=lambda e: e.slug)
    def test_every_entity_has_at_least_one_alias(self, entity):
        """An entity with no alias can never be tagged, so it would be invisible in
        the filter it exists to populate."""
        assert entity.aliases

    @pytest.mark.parametrize("entity", SEED_ENTITIES, ids=lambda e: e.slug)
    def test_every_alias_normalizes_to_something(self, entity):
        for alias in entity.aliases:
            assert normalize_model_key(alias.text), f"{entity.slug}: {alias.text!r} normalizes to nothing"

    def test_slugs_are_unique(self):
        slugs = [entity.slug for entity in SEED_ENTITIES]
        assert [slug for slug, count in Counter(slugs).items() if count > 1] == []

    def test_alias_keys_are_globally_unique(self):
        """Two entities claiming one spelling would make every tag ambiguous, which
        is why the database refuses it. Catching it here names the culprit."""
        keys = [
            normalize_model_key(alias.text)
            for entity in SEED_ENTITIES
            for alias in entity.aliases
        ]
        duplicates = sorted({key for key, count in Counter(keys).items() if count > 1})
        assert duplicates == []

    def test_every_service_names_a_vendor_that_exists(self):
        """A dangling `vendor` would silently break the provider roll-up -- the
        thing that makes 'Claude' count as Anthropic."""
        vendors = {entity.slug for entity in SEED_ENTITIES if entity.kind == EntityKind.VENDOR}
        for entity in SEED_ENTITIES:
            if entity.vendor:
                assert entity.vendor in vendors, f"{entity.slug} -> {entity.vendor}"

    def test_only_services_declare_a_vendor(self):
        for entity in SEED_ENTITIES:
            if entity.kind == EntityKind.VENDOR:
                assert not entity.vendor, f"{entity.slug} is a vendor but names one"

    def test_kinds_are_the_two_the_filter_offers(self):
        assert {entity.kind for entity in SEED_ENTITIES} <= set(EntityKind.values)

    def test_modes_are_all_real(self):
        for entity in SEED_ENTITIES:
            for alias in entity.aliases:
                assert alias.mode in MatchMode.values, f"{entity.slug}: {alias.mode}"

    def test_lmarena_organizations_are_spellings_the_source_uses(self):
        """The field is a cross-link target, so it can only be a value LMArena
        actually publishes."""
        observed = {
            "alibaba", "anthropic", "baidu", "bytedance", "deepseek", "diffbot",
            "google", "ibm", "inception-ai", "meta", "minimax", "mistral",
            "moonshot", "openai", "perplexity", "poolside", "tencent", "thinky",
            "upstage", "xai", "xiaomi", "zai",
        }
        for entity in SEED_ENTITIES:
            if entity.lmarena_organization:
                assert entity.lmarena_organization in observed, entity.slug


class TestSeedBehaviour:
    """A handful of firings through the real vocabulary, not a synthetic one."""

    @pytest.fixture
    def vocabulary(self):
        return PhraseIndex.build(
            (alias.text, alias.mode, alias.text)
            for entity in SEED_ENTITIES
            for alias in entity.aliases
        )

    @pytest.mark.parametrize(
        ("text", "key"),
        [
            ("GPT-5 released", "gpt"),
            ("I use Claude Code daily", "claude-code"),
            ("Claude 3.5 Sonnet", "claude"),
            ("Gemini 2.0 Flash benchmarks", "gemini"),
            ("Qwen3 vs Llama 4", "qwen"),
            ("Google DeepMind paper", "deepmind"),
            ("Fine-tuning a local model with Ollama", "ollama"),
            ("OpenRouter pricing changed", "openrouter"),
            ("Hugging Face datasets", "hugging-face"),
        ],
    )
    def test_expected_subject_fires(self, vocabulary, text, key):
        assert key in [match.key for match in find_phrases(text, vocabulary)]

    @pytest.mark.parametrize(
        "text",
        [
            # The ambiguity the seed deliberately refuses to tag.
            "A meta discussion about moderation",
            "The cursor position is stored per line",
        ],
    )
    def test_known_ambiguous_words_are_handled_deliberately(self, vocabulary, text):
        """`Meta` alone is not an alias; `Cursor` is, as a documented judgement
        call. This pins which way each went, so a future edit has to be conscious.
        """
        keys = [match.key for match in find_phrases(text, vocabulary)]
        if "meta" in text.lower():
            assert "meta" not in keys
        if "cursor" in text.lower():
            assert "cursor" in keys


@pytest.mark.django_db
class TestSeedMigration:
    def test_the_vocabulary_is_in_the_database(self):
        assert ProviderEntity.objects.count() == len(SEED_ENTITIES)
        assert ProviderAlias.objects.count() == len(aliases_by_key())

    def test_services_are_linked_to_their_vendor(self):
        """The roll-up is what makes a Provider filter useful, so it is worth
        asserting on the applied rows rather than only on the seed tuple."""
        claude = ProviderEntity.objects.get(slug="claude")

        assert claude.vendor is not None
        assert claude.vendor.slug == "anthropic"

    def test_a_vendor_has_no_vendor_of_its_own(self):
        assert ProviderEntity.objects.get(slug="anthropic").vendor is None

    def test_the_migration_is_idempotent(self):
        """Re-running it must not duplicate or renumber anything.

        The seed function is called directly rather than by re-running `migrate`,
        because `migrate` would skip it -- the row is already recorded as applied,
        which is exactly the state a *re-deploy* re-runs the function in only if
        someone forces it. Asserting here is what makes that safe.
        """
        module = importlib.import_module(
            "leaderboard.migrations.0009_seed_provider_vocabulary"
        )
        before = (ProviderEntity.objects.count(), ProviderAlias.objects.count())

        module.seed_vocabulary(global_apps, None)

        assert (ProviderEntity.objects.count(), ProviderAlias.objects.count()) == before

    def test_the_loaded_vocabulary_matches_the_seed(self):
        vocabulary = load_entity_vocabulary()

        assert len(vocabulary.index) == len(aliases_by_key())

    def test_one_alias_key_cannot_belong_to_two_entities(self):
        """The constraint, exercised directly -- it is the 'never guess' rule
        expressed where an admin form cannot bypass it.

        The insert is wrapped in its own `atomic` block so the expected failure
        does not poison the test's transaction, which is what lets the assertion
        afterwards still run.
        """
        first = ProviderEntity.objects.get(slug="openai")
        second = ProviderEntity.objects.get(slug="anthropic")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ProviderAlias.objects.create(
                    entity=first, alias_text="Anthropic", alias_key="anthropic"
                )

        assert second.aliases.filter(alias_key="anthropic").exists()
