from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0015_emailchangeotp'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_transferee',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='is_irregular',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='extra_approved',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='extra_approved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='extra_approved_users', to='user.user'),
        ),
        migrations.AddField(
            model_name='user',
            name='extra_approved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
