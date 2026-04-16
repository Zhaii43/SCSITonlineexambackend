from django.db import migrations
from django.utils import timezone


def backfill_masterlist_student_approval(apps, schema_editor):
    User = apps.get_model('user', 'User')
    now = timezone.now()

    stuck_students = User.objects.filter(
        role='student',
        account_source='masterlist_import',
        is_approved=False,
    )

    for student in stuck_students.iterator():
        student.is_approved = True
        if student.approved_at is None:
            student.approved_at = now
        student.save(update_fields=['is_approved', 'approved_at'])


class Migration(migrations.Migration):
    dependencies = [
        ('user', '0024_masterlistimportrun_masterlistimportemailstatus'),
    ]

    operations = [
        migrations.RunPython(
            backfill_masterlist_student_approval,
            migrations.RunPython.noop,
        ),
    ]
