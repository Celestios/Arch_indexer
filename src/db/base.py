from db.connection import DbConnection

class BaseRepository:
    """
    Base Repository class representing a database connection.
    """
    def __init__(self, db_conn: DbConnection):
        self.db_conn = db_conn
