from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cash_management", "0006_exchangerate"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankaccount",
            name="branch",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="bankaccount",
            name="purpose",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]

