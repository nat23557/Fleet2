from django.db import transaction
from pathlib import Path
from django.core.files.base import ContentFile


def link_ecx_receipts_and_delete_movement(entry):
    """
    1) Copy the ECX receipt files -> entry.attachments(kind=ECX_RECEIPT)
    2) Copy the weighbridge certificate to the BinCardEntry
    3) Delete the EcxMovement to keep UI clean.
    Safe to call only when entry.ecx_movement is set.
    """
    if not getattr(entry, "ecx_movement_id", None):
        return

    mv = entry.ecx_movement

    # The movement may have been deleted by a previous call, leaving the
    # in-memory relation with a null primary key. Safeguard against that
    # scenario by bailing out early.
    if mv is None or mv.pk is None:
        return

    with transaction.atomic():
        if not entry.attachments.filter(kind="ecx_receipt").exists():
            for r in mv.receipt_files.all():
                entry.attachments.create(
                    kind="ecx_receipt",
                    file=r.image,
                )
        # Copy weighbridge certificate from movement if entry lacks one
        if not entry.weighbridge_certificate and mv.weighbridge_certificate:
            try:
                with mv.weighbridge_certificate.open("rb") as fh:
                    entry.weighbridge_certificate.save(
                        Path(mv.weighbridge_certificate.name).name,
                        ContentFile(fh.read()),
                        save=False,
                    )
                entry.save(update_fields=["weighbridge_certificate"])
            except Exception:
                pass
        mv.delete()

