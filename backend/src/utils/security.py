import hashlib
import hmac
import secrets
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from src.config.settings import SECRET
from src.models.database import engine
from src.models.tables import users

bearer = HTTPBearer(auto_error=False)


def protect(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 240000)
    return f'{salt}:{digest.hex()}'


def token_for(username):
    return jwt.encode({'sub': username, 'exp': int(time.time()) + 28800}, SECRET, algorithm='HS256')


def signed_in(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        if credentials is None:
            raise jwt.InvalidTokenError()
        username = jwt.decode(credentials.credentials, SECRET, algorithms=['HS256'],
                              options={'require': ['sub', 'exp']})['sub']
    except jwt.InvalidTokenError as error:
        raise HTTPException(401, '请重新登录。') from error
    with engine.connect() as connection:
        account = connection.execute(select(users.c.username, users.c.role).where(users.c.username == username)).mappings().one_or_none()
    if account is None:
        raise HTTPException(401, '账号不可用。')
    return account


def allowed(role):
    def check(account=Depends(signed_in)):
        if account['role'] != role:
            raise HTTPException(403, '当前角色无权执行此操作。')
        return account
    return check


def authenticate(username, password):
    with engine.connect() as connection:
        row = connection.execute(select(users).where(users.c.username == username)).mappings().one_or_none()
    if row is None or not hmac.compare_digest(row['password'], protect(password, row['password'].split(':')[0])):
        raise HTTPException(401, '账号或密码有误。')
    return {'token': token_for(username), 'account': {'username': username, 'role': row['role']}}
