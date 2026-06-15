from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext
SECRET_KEY = "zlagoda-super-secret-key-don-not-share"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
#збіг введеного з базою
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)
#хешування
def get_password_hash(password):
    return pwd_context.hash(password)
#JWT
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    #шифрування
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt