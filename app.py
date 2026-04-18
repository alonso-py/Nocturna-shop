from flask import Flask, render_template, request, redirect, session, url_for, flash
import os
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from flask_bcrypt import Bcrypt
from database import get_connection, init_db
import sqlite3
from datetime import datetime
import stripe

# ==================== CONFIGURACIÓN DE ENTORNO ====================
load_dotenv()   # ← Esto debe ir ANTES de leer las variables

app = Flask(__name__)

# Clave secreta de Flask
app.secret_key = os.getenv('FLASK_SECRET')
if not app.secret_key:
    raise RuntimeError("¡Falta FLASK_SECRET en el archivo .env!")

# Clave de Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
if not stripe.api_key:
    raise RuntimeError("¡Falta STRIPE_SECRET_KEY en el archivo .env!")

bcrypt = Bcrypt(app)

# ==================== INICIALIZACIÓN ====================
with app.app_context():
    init_db()

# Ensure DB and tables exist
with app.app_context():
    init_db()

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('INSERT INTO users (name,email,password,role) VALUES (?,?,?,?)', (name,email,hashed,role))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    next_page = request.args.get('next')  # 🔥 importante

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and bcrypt.check_password_hash(user[3], password):
            session['user_id'] = user[0]
            session['name'] = user[1]
            session['role'] = user[4]

            # 🔥 si venía de otra página (carrito, comprar, etc)
            if next_page:
                return redirect(next_page)

            # 🔥 si no, redirección normal por rol
            if session['role'] == 'admin':
                return redirect(url_for('admin_panel'))
            elif session['role'] == 'seller':
                return redirect(url_for('seller_panel'))
            elif session['role'] == 'buyer':
                return redirect(url_for('buyer_products'))
            else:
                error = 'Rol no válido'
        else:
            error = 'Correo o contraseña incorrecta'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('buyer_products'))


@app.route('/')
def index():
    return redirect(url_for('buyer_products'))



@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', name=session.get('name'), role=session.get('role'))


# SELLER: add product
@app.route('/add_product', methods=['GET','POST'])
def add_product():
    if 'user_id' not in session or session.get('role') != 'seller':
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        stock = request.form['stock']
        description = request.form.get('description','')
        category_id = request.form['category_id']
        user_id = session['user_id']

        image_file = request.files.get('image')
        filename = None
        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(image_path)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            '''INSERT INTO products 
               (name, price, stock, description, user_id, image, category_id) 
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (name, price, stock, description, user_id, filename, category_id)
        )
        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('seller_panel'))

    # 👇 GET
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM categories")
    categories = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('add_product.html', categories=categories)




@app.route('/products')
def products():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM products')
    products = cur.fetchall()
    cur.close()
    conn.close()

    products_mapped = [{
        'id': p[0],
        'name': p[1],
        'price': p[2],
        'description': p[3],
        'user_id': p[4],
        'image': p[5]
    } for p in products]

    return render_template('products.html', products=products_mapped)


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM products WHERE id = ?', (product_id,))
    p = cur.fetchone()
    cur.close()
    conn.close()
    if not p:
        return 'Producto no encontrado', 404
    product = {'id': p[0], 'name': p[1], 'price': p[2], 'description': p[3], 'user_id': p[4], 'image': p[5]}
    return render_template('product_detail.html', product=product)


@app.route('/edit_product/<int:product_id>', methods=['GET','POST'])
def edit_product(product_id):
    if 'user_id' not in session or session.get('role') != 'seller':
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    # Producto
    cur.execute('SELECT * FROM products WHERE id = ?', (product_id,))
    p = cur.fetchone()
    if not p:
        cur.close()
        conn.close()
        return 'Producto no encontrado', 404

    # Categorías
    cur.execute('SELECT id, name FROM categories')
    categories = cur.fetchall()

    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        stock = request.form['stock']
        description = request.form.get('description','')
        category_id = request.form['category_id']

        image_file = request.files.get('image')
        filename = p[5]

        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(image_path)

        cur.execute(
            '''UPDATE products 
               SET name=?, price=?, stock=?, description=?, image=?, category_id=?
               WHERE id=?''',
            (name, price, stock, description, filename, category_id, product_id)
        )

        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('seller_panel'))

    product = {
        'id': p[0],
        'name': p[1],
        'price': p[2],
        'stock' : p[3],
        'description': p[4],
        'user_id': p[5],
        'image': p[6],
        'category_id': p[7]
    }

    cur.close()
    conn.close()

    return render_template(
        'edit_product.html',
        product=product,
        categories=categories
    )


@app.route('/delete_product/<int:product_id>')
def delete_product(product_id):
    if 'user_id' not in session or session.get('role') != 'seller':
        return redirect(url_for('login'))
    conn = get_connection(); cur = conn.cursor()
    cur.execute('SELECT image FROM products WHERE id = ?', (product_id,))
    p = cur.fetchone()
    if p and p[0]:
        path = os.path.join(app.config['UPLOAD_FOLDER'], p[0])
        if os.path.exists(path): os.remove(path)
    cur.execute('DELETE FROM products WHERE id = ?', (product_id,))
    conn.commit(); cur.close(); conn.close()
    return redirect(url_for('seller_panel'))


# CART: add, view, remove
@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    if 'user_id' not in session or session.get('role') != 'buyer':
        flash("Debes iniciar sesión como comprador", "warning")
        return redirect(url_for('login', next=request.url))

    conn = get_connection()
    cur = conn.cursor()

    # 1. Obtener el stock actual del producto
    cur.execute("SELECT stock, name FROM products WHERE id = ?", (product_id,))
    product = cur.fetchone()

    if not product:
        flash("Producto no encontrado", "danger")
        conn.close()
        return redirect(url_for('buyer_products'))

    stock_disponible = int(product[0])
    nombre_producto = product[1]

    # 2. Ver cuántos tiene ya el usuario en el carrito
    cur.execute("""
        SELECT quantity FROM cart 
        WHERE user_id = ? AND product_id = ?
    """, (session['user_id'], product_id))
    
    row = cur.fetchone()
    cantidad_actual = int(row[0]) if row else 0

    nueva_cantidad = cantidad_actual + 1

    # 3. Validar si hay suficiente stock
    if nueva_cantidad > stock_disponible:
        flash(f"Solo hay {stock_disponible} unidades disponibles de '{nombre_producto}'", "warning")
        conn.close()
        return redirect(url_for('cart'))

    # 4. Actualizar o insertar en el carrito
    if row:  # Ya existe en el carrito
        cur.execute("""
            UPDATE cart 
            SET quantity = ? 
            WHERE user_id = ? AND product_id = ?
        """, (nueva_cantidad, session['user_id'], product_id))
    else:  # Es la primera vez que lo agrega
        cur.execute("""
            INSERT INTO cart (user_id, product_id, quantity)
            VALUES (?, ?, 1)
        """, (session['user_id'], product_id))

    conn.commit()
    cur.close()
    conn.close()

    flash(f"'{nombre_producto}' agregado al carrito", "success")
    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    if 'user_id' not in session or session.get('role') != 'buyer':
        return redirect(url_for('login', next=request.url))  # 🔥 redirige y regresa aquí

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT cart.id, products.name, products.price, cart.quantity, cart.product_id
        FROM cart
        JOIN products ON cart.product_id = products.id
        WHERE cart.user_id=?
    """, (session['user_id'],))

    items = cur.fetchall()

    cur.close()
    conn.close()

    total = sum(p[2] * p[3] for p in items)

    return render_template('cart.html', items=items, total=total)


@app.route('/remove_from_cart/<int:cart_id>')
def remove_from_cart(cart_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM cart WHERE id=?", (cart_id,))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('cart'))



# BUYER pages: list and detail
@app.route('/buyer')
def buyer_panel():
    if 'user_id' not in session or session.get('role') != 'buyer':
        return redirect(url_for('login'))
    return redirect(url_for('buyer_products'))


@app.route('/buyer/products')
def buyer_products():

    search = request.args.get('q', '')
    category_id = request.args.get('category')

    conn = get_connection()
    cur = conn.cursor()

    cur.execute('SELECT id, name FROM categories')
    categories = cur.fetchall()

    query = 'SELECT * FROM products'
    params = []
    conditions = []

    if search:
        conditions.append('name LIKE ?')
        params.append(f'%{search}%')

    if category_id:
        conditions.append('category_id = ?')
        params.append(category_id)

    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)

    cur.execute(query, params)
    rows = cur.fetchall()

    cur.close()
    conn.close()

    products = [
        {
            'id': r[0],
            'name': r[1],
            'price': r[2],
            'description': r[3],
            'user_id': r[4],
            'image': r[5]
        } for r in rows
    ]

    return render_template(
        'buyer_products.html',
        products=products,
        categories=categories,
        selected_category=category_id,
        search=search
    )

@app.route('/buyer/product/<int:product_id>')
def buyer_product_detail(product_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('SELECT * FROM products WHERE id = ?', (product_id,))
    r = cur.fetchone()

    cur.close()
    conn.close()

    if not r:
        return 'Producto no encontrado', 404

    product = {
        'id': r[0],
        'name': r[1],
        'price': r[2],
        'description': r[3],
        'user_id': r[4],
        'image': r[5]
    }

    return render_template('buyer_product_detail.html', product=product)

@app.route('/my_orders')
def my_orders():
    if 'user_id' not in session or session.get('role') != 'buyer':
        return redirect('/login')

    conn = get_connection()
    orders = conn.execute("""
        SELECT id, created_at, total, status
        FROM orders
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (session['user_id'],)).fetchall()
    conn.close()

    return render_template('my_orders.html', orders=orders)

@app.route('/order/<int:order_id>')
def order_detail(order_id):
    if 'user_id' not in session or session.get('role') != 'buyer':
        return redirect('/login')

    conn = get_connection()
    conn.row_factory = sqlite3.Row

    order = conn.execute("""
        SELECT *
        FROM orders
        WHERE id = ? AND user_id = ?
    """, (order_id, session['user_id'])).fetchone()

    if not order:
        conn.close()
        return "Pedido no encontrado", 404

    items = conn.execute("""
        SELECT p.name, oi.quantity, oi.price
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = ?
    """, (order_id,)).fetchall()

    conn.close()

    return render_template(
        'order_detail.html',
        order=order,
        items=items
    )


# ADMIN and seller panels
@app.route('/admin')
def admin_panel():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = get_connection(); cur = conn.cursor()
    cur.execute('SELECT id,name,email,role FROM users')
    users = cur.fetchall(); cur.close(); conn.close()
    users_mapped = [{'id':u[0],'name':u[1],'email':u[2],'role':u[3]} for u in users]
    return render_template('admin_panel.html', name=session.get('name'), users=users_mapped)

# PANEL ADMIN
@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('admin_dashboard.html')

@app.route('/admin/users')
def admin_users():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email, role FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('admin_users.html', users=users)

@app.route('/admin/edit_user/<int:user_id>', methods=['GET', 'POST'])
def admin_edit_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        role = request.form['role']

        cur.execute("""
            UPDATE users SET name=?, email=?, role=?
            WHERE id=?
        """, (name, email, role, user_id))

        conn.commit()
        conn.close()
        return redirect(url_for('admin_users'))

    cur.execute("SELECT id, name, email, role FROM users WHERE id=?", (user_id,))
    user = cur.fetchone()
    conn.close()

    return render_template('admin_edit_user.html', user=user)

@app.route('/admin/delete_user/<int:user_id>')
def admin_delete_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    if user_id == session['user_id']:
        return "No puedes eliminar tu propio usuario"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

    return redirect(url_for('admin_users'))



@app.route('/admin/products')
def admin_products():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT products.id, products.name, products.price, products.stock, users.name 
        FROM products
        LEFT JOIN users ON products.user_id = users.id
    """)
    products = cur.fetchall()
    print(products)
    cur.close()
    conn.close()

    return render_template('admin_products.html', products=products)



# AGREGAR PRODUCTO (admin)
@app.route('/admin/add_product', methods=['GET', 'POST'])
def admin_add_product():

    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        desc = request.form.get('description', '')
        image = None

        if 'image' in request.files:
            img = request.files['image']
            if img.filename:
                img.save(os.path.join(app.config['UPLOAD_FOLDER'], img.filename))
                image = img.filename

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO products (name, price, description, image)
            VALUES (?, ?, ?, ?)
        """, (name, price, desc, image))
        conn.commit()
        conn.close()

        return redirect(url_for('admin_products'))

    return render_template('admin_add_product.html')

@app.route('/admin/delete_product/<int:product_id>')
def admin_delete_product(product_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    # borrar imagen si existe
    cur.execute("SELECT image FROM products WHERE id=?", (product_id,))
    img = cur.fetchone()

    if img and img[0]:
        path = os.path.join(app.config['UPLOAD_FOLDER'], img[0])
        if os.path.exists(path):
            os.remove(path)

    cur.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('admin_products'))


@app.route('/seller')
def seller_panel():
    if 'user_id' not in session or session.get('role') != 'seller':
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        'SELECT * FROM products WHERE user_id = ?',
        (session['user_id'],)
    )
    prods = cur.fetchall()
    cur.close()
    conn.close()

    products = [{
        'id': p[0],
        'name': p[1],
        'price': p[2],
        'description': p[3],
        'user_id': p[4],
        'image': p[5]
    } for p in prods]

    return render_template(
        'seller_panel.html',
        name=session.get('name'),
        products=products
    )
    
@app.route('/seller/products')
def seller_products():
    if 'user_id' not in session or session.get('role') != 'seller':
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        'SELECT * FROM products WHERE user_id = ?',
        (session['user_id'],)
    )
    prods = cur.fetchall()
    cur.close()
    conn.close()

    products = [{
        'id': p[0],
        'name': p[1],
        'price': p[2],
        'description': p[3],
        'user_id': p[4],
        'image': p[5]
    } for p in prods]

    return render_template(
        'seller_products.html',
        products=products,
        name=session.get('name')
    )

    



@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'user_id' not in session or session.get('role') != 'buyer':
        return redirect(url_for('login', next=request.url))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT products.id, products.name, products.price, cart.quantity
        FROM cart
        JOIN products ON cart.product_id = products.id
        WHERE cart.user_id=?
    """, (session['user_id'],))

    items = cur.fetchall()
    total = sum(i[2] * i[3] for i in items)

    if request.method == 'POST':
        address = request.form['address']
        payment = request.form['payment']

        cur.execute("""
            INSERT INTO orders (user_id, total, address, payment_method, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            session['user_id'],
            total,
            address,
            payment,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        order_id = cur.lastrowid

        for i in items:
            product_id = i[0]
            quantity = i[3]
            price = i[2]

            # 🔥 1. Verificar stock actual
            cur.execute("SELECT stock FROM products WHERE id=?", (product_id,))
            result = cur.fetchone()

            if not result:
                flash("Producto no encontrado")
                conn.rollback()
                return redirect(url_for('cart'))

            stock = int(result[0])

            if quantity > stock:
                flash(f"No hay suficiente stock. Solo quedan {stock}")
                conn.rollback()
                return redirect(url_for('cart'))

            # 🔥 2. Guardar en order_items
            cur.execute("""
                INSERT INTO order_items (order_id, product_id, quantity, price)
                VALUES (?, ?, ?, ?)
            """, (order_id, product_id, quantity, price))

            # 🔥 3. DESCONTAR STOCK
            cur.execute("""
                UPDATE products
                SET stock = stock - ?
                WHERE id = ?
            """, (quantity, product_id))

        cur.execute("DELETE FROM cart WHERE user_id=?", (session['user_id'],))
        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('order_success'))

    cur.close()
    conn.close()
    return render_template('checkout.html', items=items, total=total)

@app.route('/create-checkout-session')
def create_checkout_session():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT products.name, products.price, cart.quantity
        FROM cart
        JOIN products ON cart.product_id = products.id
        WHERE cart.user_id=?
    """, (session['user_id'],))

    items = cur.fetchall()
    conn.close()

    line_items = []

    for item in items:
        name = item[0]
        price = int(item[1] * 100)  # centavos
        quantity = item[2]

        line_items.append({
            'price_data': {
                'currency': 'mxn',
                'product_data': {'name': name},
                'unit_amount': price,
            },
            'quantity': quantity,
        })

    session_stripe = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=line_items,
        mode='payment',
        success_url='http://localhost:5000/order_success',
        cancel_url='http://localhost:5000/cart',
    )

    return redirect(session_stripe.url)

@app.route('/order_success')
def order_success():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    # 🔥 obtener carrito
    cur.execute("""
        SELECT products.id, products.name, products.price, cart.quantity
        FROM cart
        JOIN products ON cart.product_id = products.id
        WHERE cart.user_id=?
    """, (session['user_id'],))

    items = cur.fetchall()
    total = sum(i[2] * i[3] for i in items)

    # 🔥 crear orden
    cur.execute("""
        INSERT INTO orders (user_id, total, address, payment_method, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session['user_id'],
        total,
        "Pagado con Stripe",
        "Tarjeta",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    order_id = cur.lastrowid

    # 🔥 guardar productos + descontar stock
    for i in items:
        product_id = i[0]
        quantity = i[3]
        price = i[2]

        cur.execute("""
            INSERT INTO order_items (order_id, product_id, quantity, price)
            VALUES (?, ?, ?, ?)
        """, (order_id, product_id, quantity, price))

        cur.execute("""
            UPDATE products
            SET stock = stock - ?
            WHERE id = ?
        """, (quantity, product_id))

    # 🔥 limpiar carrito
    cur.execute("DELETE FROM cart WHERE user_id=?", (session['user_id'],))

    conn.commit()
    cur.close()
    conn.close()

    return render_template('order_success.html')

@app.route('/seller/orders')
def seller_orders():
    if 'user_id' not in session or session.get('role') != 'seller':
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            orders.id AS order_id,
            orders.created_at,
            orders.total,
            products.name,
            order_items.quantity,
            order_items.price,
            (order_items.quantity * order_items.price) AS subtotal
        FROM order_items
        JOIN orders ON order_items.order_id = orders.id
        JOIN products ON order_items.product_id = products.id
        WHERE products.user_id = ?
        ORDER BY orders.created_at DESC
    """, (session['user_id'],))

    sales = cur.fetchall()
    cur.execute("""
        SELECT SUM(order_items.quantity * order_items.price)
        FROM order_items
        JOIN products ON order_items.product_id = products.id
        WHERE products.user_id = ?
    """, (session['user_id'],))
    total = cur.fetchone()[0] or 0
    
    cur.close()
    conn.close()

    return render_template('seller_orders.html', sales=sales, total=total)

@app.route('/seller/dashboard')
def seller_dashboard():
    if 'user_id' not in session or session.get('role') != 'seller':
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    # TOTAL GANADO
    cur.execute("""
        SELECT SUM(order_items.quantity * order_items.price)
        FROM order_items
        JOIN products ON order_items.product_id = products.id
        WHERE products.user_id = ?
    """, (session['user_id'],))
    total_ganado = cur.fetchone()[0] or 0

    # TOTAL PRODUCTOS
    cur.execute("""
        SELECT COUNT(*) FROM products WHERE user_id = ?
    """, (session['user_id'],))
    total_productos = cur.fetchone()[0]

    # TOTAL VENTAS
    cur.execute("""
        SELECT SUM(order_items.quantity)
        FROM order_items
        JOIN products ON order_items.product_id = products.id
        WHERE products.user_id = ?
    """, (session['user_id'],))
    total_ventas = cur.fetchone()[0] or 0

    # ÚLTIMAS VENTAS
    cur.execute("""
        SELECT 
            orders.created_at,
            products.name,
            order_items.quantity,
            order_items.price
        FROM order_items
        JOIN orders ON order_items.order_id = orders.id
        JOIN products ON order_items.product_id = products.id
        WHERE products.user_id = ?
        ORDER BY orders.created_at DESC
        LIMIT 5
    """, (session['user_id'],))
    ultimas = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'seller_dashboard.html',
        total_ganado=total_ganado,
        total_productos=total_productos,
        total_ventas=total_ventas,
        ultimas=ultimas
    )


if __name__ == '__main__':
    app.run(debug=True)


@app.route('/my_addresses')
def my_addresses():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        'SELECT * FROM addresses WHERE user_id = ?',
        (session['user_id'],)
    )

    addresses = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('my_addresses.html', addresses=addresses)

@app.route('/add_address', methods=['GET', 'POST'])
def add_address():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        full_name = request.form['full_name']
        street = request.form['street']
        city = request.form['city']
        state = request.form['state']
        postal_code = request.form['postal_code']
        phone = request.form.get('phone')

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO addresses
            (user_id, full_name, street, city, state, postal_code, phone)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            session['user_id'],
            full_name,
            street,
            city,
            state,
            postal_code,
            phone
        ))

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('my_addresses'))

    return render_template('add_address.html')
