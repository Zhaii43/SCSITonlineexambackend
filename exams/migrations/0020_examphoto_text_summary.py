from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0019_merge_0010_examresult_penalty_fields_0018_shuffle_and_pool'),
    ]

    operations = [
        migrations.AlterField(
            model_name='examphoto',
            name='photo',
            field=models.ImageField(blank=True, null=True, upload_to='exam_photos/'),
        ),
        migrations.AddField(
            model_name='examphoto',
            name='text_summary',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='examphoto',
            name='is_text_only',
            field=models.BooleanField(default=False),
        ),
    ]
