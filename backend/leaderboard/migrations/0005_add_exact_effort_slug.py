"""Add `MatchMethod.EXACT_EFFORT_SLUG` to the choices on `ModelMatch.match_method`.

Choices are enforced by Django, not by the database, so this is a no-op at the
SQLite level -- `match_method` is already a `varchar(32)` and the new value is 17
characters. It is recorded anyway because the choices list is the schema's own
statement of what a stored method can mean, and a missing migration here would
leave `makemigrations --check` dirty without failing any test.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leaderboard', '0004_alter_unmatchedrecord_reason'),
    ]

    operations = [
        migrations.AlterField(
            model_name='modelmatch',
            name='match_method',
            field=models.CharField(choices=[('alias', 'Alias override'), ('exact_key', 'Exact normalized key'), ('exact_name', 'Exact AA name'), ('exact_slug', 'Exact AA slug'), ('exact_effort_slug', 'Exact AA slug + stated effort'), ('harness_fold', 'Harness-wrapper fold')], max_length=32),
        ),
    ]
