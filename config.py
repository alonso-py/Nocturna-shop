import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('FLASK_SECRET')
    if not SECRET_KEY:
        raise RuntimeError("¡Falta FLASK_SECRET en el archivo .env!")
    
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')