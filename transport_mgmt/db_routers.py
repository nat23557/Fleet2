class WareDGTRouter:
    """Route all WareDGT app models to the 'warehouse' DB.

    - Reads/Writes: WareDGT -> 'warehouse'; others -> default
    - Relations: allow relations involving WareDGT to proceed (Django will
      handle cross-DB lookups as separate queries; FKs are not enforced across DBs)
    - Migrations: apply WareDGT migrations only on 'warehouse'; prevent other
      apps from migrating into 'warehouse'.
    """

    WARE_APP = 'WareDGT'

    def db_for_read(self, model, **hints):
        return 'warehouse' if model._meta.app_label == self.WARE_APP else None

    def db_for_write(self, model, **hints):
        return 'warehouse' if model._meta.app_label == self.WARE_APP else None

    def allow_relation(self, obj1, obj2, **hints):
        # Allow any relation that involves a WareDGT model
        if obj1._meta.app_label == self.WARE_APP or obj2._meta.app_label == self.WARE_APP:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.WARE_APP:
            return db == 'warehouse'
        # Block other apps from migrating into 'warehouse'
        if db == 'warehouse':
            return False
        return None

