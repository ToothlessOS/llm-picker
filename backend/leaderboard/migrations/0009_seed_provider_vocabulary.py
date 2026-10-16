"""Seed `ProviderEntity` / `ProviderAlias` from `leaderboard/hn_vocabulary.py`.

A data migration rather than a fixture or a `post_migrate` signal, so the seed set
is versioned alongside the schema it applies to and re-running `migrate` is a
no-op.

Vendors are created before services, because a service's `vendor` is a self-FK and
the roll-up is what makes a Provider filter useful -- a thread that only ever says
"Claude" should still be an Anthropic thread.

Idempotent in the same way `0002_seed_model_aliases` is: each row is upserted on
its identity, and only the fields the seed defines are written. An entity or alias
a reviewer adds or narrows in the admin afterwards is never touched by a re-run.
"""

from django.db import migrations


def seed_vocabulary(apps, schema_editor):
    from leaderboard.hn_vocabulary import SEED_ENTITIES
    from leaderboard.normalization import normalize_model_key

    ProviderEntity = apps.get_model("leaderboard", "ProviderEntity")
    ProviderAlias = apps.get_model("leaderboard", "ProviderAlias")

    entities: dict[str, object] = {}

    # Vendors first, in seed order, so every `vendor` reference below resolves.
    for seed in SEED_ENTITIES:
        if seed.kind != "vendor":
            continue
        entity, _ = ProviderEntity.objects.update_or_create(
            slug=seed.slug,
            defaults={
                "label": seed.label,
                "kind": seed.kind,
                "vendor": None,
                "lmarena_organization": seed.lmarena_organization,
                "is_active": True,
                "note": seed.note,
            },
        )
        entities[seed.slug] = entity

    for seed in SEED_ENTITIES:
        if seed.kind == "vendor":
            continue
        entity, _ = ProviderEntity.objects.update_or_create(
            slug=seed.slug,
            defaults={
                "label": seed.label,
                "kind": seed.kind,
                "vendor": entities.get(seed.vendor),
                "lmarena_organization": seed.lmarena_organization,
                "is_active": True,
                "note": seed.note,
            },
        )
        entities[seed.slug] = entity

    for seed in SEED_ENTITIES:
        entity = entities[seed.slug]
        for alias in seed.aliases:
            # Keyed on `alias_key` rather than `(entity, alias_key)`, because the
            # column is globally unique: two entities cannot both claim a
            # spelling, and that is the point. Keying on the pair would let a
            # re-run create the collision the constraint exists to prevent.
            ProviderAlias.objects.update_or_create(
                alias_key=normalize_model_key(alias.text),
                defaults={
                    "entity": entity,
                    "alias_text": alias.text,
                    "match_mode": alias.mode,
                },
            )


def unseed_vocabulary(apps, schema_editor):
    """Reverse only what the seed would have created.

    Deliberately narrow: an entity or alias a reviewer added through the admin
    represents review work with no other record, so only the slugs and alias keys
    the seed names are removed -- and entities are removed last, so a service the
    reviewer kept does not lose its vendor mid-way.
    """
    from leaderboard.hn_vocabulary import SEED_ENTITIES
    from leaderboard.normalization import normalize_model_key

    ProviderEntity = apps.get_model("leaderboard", "ProviderEntity")
    ProviderAlias = apps.get_model("leaderboard", "ProviderAlias")

    for seed in SEED_ENTITIES:
        for alias in seed.aliases:
            ProviderAlias.objects.filter(alias_key=normalize_model_key(alias.text)).delete()

    ProviderEntity.objects.filter(slug__in=[seed.slug for seed in SEED_ENTITIES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("leaderboard", "0008_add_token_prefix_match_mode"),
    ]

    operations = [
        migrations.RunPython(seed_vocabulary, unseed_vocabulary),
    ]
