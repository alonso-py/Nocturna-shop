from database import get_connection
from flask_bcrypt import Bcrypt
bcrypt = Bcrypt()
hashed = bcrypt.generate_password_hash('admin123').decode('utf-8')
conn = get_connection()
cur = conn.cursor()
cur.execute("INSERT INTO users (name,email,password,role) VALUES (?,?,?,?)", ('Admin','admin@admin.com',hashed,'admin'))
conn.commit()
cur.close()
conn.close()
print('Admin creado')