# Generated by Django 4.1.10 on 2023-07-30 17:49

from django.db import migrations


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('users', '0002_squashed_0004'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserToken',
            fields=[
            ],
            options={
                'verbose_name': 'token',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('users.token',),
        ),
    ]
