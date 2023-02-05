class TimescaleRouter:
    """
    A router to control all database operations on models in the
    auth and contenttypes applications.
    """

    route_app_labels = {"jejak"}

    def db_for_read(self, model, **hints):
        """
        Attempts to read timescale models go to timescale_db read replicas.
        """
        if model._meta.app_label in self.route_app_labels:
            return "timescale_read"
        return None

    def db_for_write(self, model, **hints):
        """
        Attempts to write timescale models go to timescale_db.
        """
        if model._meta.app_label in self.route_app_labels:
            return "timescale"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations if databases are same.
        """
        db_set = {"timescale", "timescale_read"}
        if obj1._state.db in db_set and obj2._state.db in db_set:
            return True

        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Make sure the timescale apps only appear in the 'timescale' database.
        """
        if app_label in self.route_app_labels:
            return db == "timescale"

        return False
