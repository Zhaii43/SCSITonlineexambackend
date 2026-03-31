from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0017_user_unique_contact_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='declaration_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='declaration_verified_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='declaration_verified_users', to='user.user'),
        ),
        migrations.AddField(
            model_name='user',
            name='declaration_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
