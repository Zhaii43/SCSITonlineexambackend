from django.db import migrations


def backfill_is_draft(apps, schema_editor):
    """Set is_draft=False for all exams that already have questions — they were complete before the draft feature."""
    Exam = apps.get_model('exams', 'Exam')
    Exam.objects.filter(questions__isnull=False).distinct().update(is_draft=False)


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0023_add_is_draft_to_exam'),
    ]

    operations = [
        migrations.RunPython(backfill_is_draft, migrations.RunPython.noop),
    ]
