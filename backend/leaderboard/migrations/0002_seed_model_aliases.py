"""Seed `ModelAlias` from `leaderboard/aliases.py`.

A data migration rather than a fixture or a `post_migrate` signal, so that the
seed set is versioned alongside the schema it applies to and re-running
`migrate` is a no-op.

The seed tuple is empty by design -- see `aliases.py`. This migration exists so
that the *mechanism* is in place and tested: adding a reviewed mapping to
`SEED_ALIASES` and running `migrate` is the whole workflow, and it is idempotent
because each row is upserted on its identity rather than inserted.

Aliases added through the Django admin after this point are never touched by a
re-run: the `update_or_create` only writes the fields the seed defines, and only
for the rows the seed names.
"""

from django.db import migrations


def seed_aliases(apps, schema_editor):
    from leaderboard.aliases import SEED_ALIASES

    ModelAlias = apps.get_model("leaderboard", "ModelAlias")
    for alias in SEED_ALIASES:
        ModelAlias.objects.update_or_create(
            source=alias.source,
            category=alias.category or "",
            raw_name=alias.raw_name,
            defaults={
                "canonical_key": alias.canonical_key,
                "note": alias.note,
            },
        )


def unseed_aliases(apps, schema_editor):
    """Reverse only what the seed would have created.

    Deliberately narrow: an alias a human added through the admin must survive a
    `migrate leaderboard 0001`, because it represents review work that has no
    other record. Only rows whose `raw_name` the seed names are removed.
    """
    from leaderboard.aliases import SEED_ALIASES

    ModelAlias = apps.get_model("leaderboard", "ModelAlias")
    for alias in SEED_ALIASES:
        ModelAlias.objects.filter(
            source=alias.source,
            category=alias.category or "",
            raw_name=alias.raw_name,
            canonical_key=alias.canonical_key,
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("leaderboard", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_aliases, unseed_aliases),
    ]
