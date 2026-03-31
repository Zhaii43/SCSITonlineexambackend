from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0009_examphoto'),
    ]

    operations = [
        migrations.AddField(
            model_name='examresult',
            name='score_before_penalty',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='examresult',
            name='penalty_percent',
            field=models.IntegerField(default=0),
        ),
    ]

