from pymongo.errors import DuplicateKeyError
from fastapi import HTTPException


class Accounts:
    def __init__(self, db):
        self.users = db.users
        self.sessions = db.sessions
        self.users.create_index("email", unique=True)
        self.sessions.create_index("expires", expireAfterSeconds=0)

    def register(self, username, email, password_hash):
        record = dict(username=username, email=email, password_hash=password_hash)
        try:
            self.users.insert_one(record)
        except DuplicateKeyError:
            raise HTTPException(409, "An account already uses this email.") from None
        return record

    def find_login(self, email):
        return self.users.find_one({"email": email})

    def start_session(self, sid, owner, expires):
        self.sessions.insert_one({"_id": sid, "owner": owner, "expires": expires})

    def profile(self, sid, owner, now):
        if self.sessions.find_one({"_id": sid, "owner": owner, "expires": {"$gt": now}}):
            return self.users.find_one({"_id": owner}, {"username": 1, "email": 1})

    def revoke(self, sid, owner):
        self.sessions.delete_one({"_id": sid, "owner": owner})

