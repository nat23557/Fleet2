from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cash_management", "0007_bankaccount_branch_purpose"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankaccount",
            name="account_number",
            field=models.CharField(blank=True, max_length=32),
        ),
    ]

