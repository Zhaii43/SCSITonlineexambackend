from django.db import migrations, models


def convert_open_to_under_review(apps, schema_editor):
    QuestionIssueReport = apps.get_model('exams', 'QuestionIssueReport')
    QuestionIssueReport.objects.filter(status='open').update(status='under_review')


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0021_questionissuereport_questionissuemessage'),
    ]

    operations = [
        migrations.RunPython(convert_open_to_under_review, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='questionissuereport',
            name='status',
            field=models.CharField(
                choices=[
                    ('under_review', 'Under Review'),
                    ('resolved', 'Resolved'),
                    ('rejected', 'Rejected'),
                ],
                default='under_review',
                max_length=20,
            ),
        ),
    ]
