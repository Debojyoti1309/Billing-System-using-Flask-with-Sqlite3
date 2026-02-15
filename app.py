from flask import Flask, render_template, request, redirect, session, send_file, flash, url_for, jsonify
import sqlite3, os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# SECURITY: Key is generated randomly on every server restart
app.secret_key = os.urandom(24) 
DB = "database.db"

# ================= DATABASE CONNECTION =================
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row  
    return con

# ================= LOGIN REQUIRED DECORATOR =================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# ================= CACHE PREVENTION =================
@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ================= AUTO-COMPLETE API =================
@app.route("/get_customers")
@login_required
def get_customers():
    search = request.args.get('q', '')
    con = db()
    query = "SELECT DISTINCT customer, phone, address FROM invoices WHERE customer LIKE ? LIMIT 5"
    rows = con.execute(query, (f'%{search}%',)).fetchall()
    con.close()
    return jsonify([{'name': r['customer'], 'phone': r['phone'], 'address': r['address']} for r in rows])

# ================= LOGIN =================
@app.route("/", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]
        con = db()
        user = con.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        con.close()
        
        if user and check_password_hash(user['password'], p):
            session["user"] = u
            return redirect("/dashboard")
        else:
            error = "Invalid Username or Password!"
            
    return render_template("login.html", error=error)

# ================= REGISTER (USER ONLY) =================
@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        u = request.form.get("username")
        ph = request.form.get("phone")
        p = request.form.get("password")
        date_now = datetime.now().strftime("%d-%m-%Y %H:%M")

        con = db()
        try:
            # 1. Check if user already exists
            existing = con.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()
            if existing:
                error = "Username already taken!"
            else:
                # 2. Hash password and insert
                hashed_p = generate_password_hash(p)
                con.execute("INSERT INTO users (username, password, phone, created_at) VALUES (?,?,?,?)", 
                            (u, hashed_p, ph, date_now))
                con.commit()
                flash("Account created! Please login.", "success")
                return redirect(url_for("login"))
        except Exception as e:
            error = "Database error. Please try again."
        finally:
            con.close()
            
    return render_template("register.html", error=error)

# ================= MANAGE USERS (UPDATED WITH SEARCH) =================
@app.route("/manage_users")
@login_required
def manage_users():
    if session.get('user') != 'admin':
        flash("Access Denied", "danger")
        return redirect(url_for('dashboard_view'))
    
    search_query = request.args.get('search', '').strip()
    con = db()
    
    if search_query:
        # Search by username or phone
        query = "SELECT id, username, phone, created_at FROM users WHERE username LIKE ? OR phone LIKE ?"
        users = con.execute(query, (f'%{search_query}%', f'%{search_query}%')).fetchall()
    else:
        users = con.execute("SELECT id, username, phone, created_at FROM users").fetchall()
    
    con.close()
    return render_template("manage_users.html", users=users, search_query=search_query)

# ================= UPDATE USER (ADMIN ONLY) =================
@app.route("/update_user/<int:user_id>", methods=['POST'])
@login_required
def update_user(user_id):
    if session.get('user') != 'admin':
        return redirect(url_for('dashboard_view'))
        
    new_username = request.form.get('username')
    new_phone = request.form.get('phone')
    new_password = request.form.get('password')

    con = db()
    try:
        if new_password: # Only update password if a new one is provided
            hashed_pw = generate_password_hash(new_password)
            con.execute("UPDATE users SET username=?, phone=?, password=? WHERE id=?", 
                        (new_username, new_phone, hashed_pw, user_id))
        else:
            con.execute("UPDATE users SET username=?, phone=? WHERE id=?", 
                        (new_username, new_phone, user_id))
        con.commit()
        flash(f"Account for {new_username} updated.", "success")
    except:
        flash("Error: Username might already be taken.", "danger")
    finally:
        con.close()
    
    return redirect(url_for('manage_users'))

# ================= DELETE USER =================
@app.route("/delete_user/<int:user_id>")
@login_required
def delete_user(user_id):
    if session.get('user') != 'admin':
        return redirect(url_for('dashboard_view'))
    
    con = db()
    user = con.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    if user and user['username'] == 'admin':
        flash("Cannot delete Master Admin!", "danger")
    else:
        con.execute("DELETE FROM users WHERE id=?", (user_id,))
        con.commit()
        flash("User removed.", "success")
    con.close()
    return redirect(url_for('manage_users'))

# ================= ADMIN: ADD NEW USER =================
@app.route("/admin_add_user", methods=['POST'])
@login_required
def admin_add_user():
    if session.get('user') != 'admin':
        return redirect(url_for('dashboard_view'))
        
    username = request.form.get('username')
    password = generate_password_hash(request.form.get('password'))
    phone = request.form.get('phone')
    date_now = datetime.now().strftime("%d-%m-%Y %H:%M")

    con = db()
    try:
        con.execute("INSERT INTO users (username, password, phone, created_at) VALUES (?,?,?,?)", 
                    (username, password, phone, date_now))
        con.commit()
        flash(f"User {username} created.", "success")
    except:
        flash("User already exists!", "danger")
    finally:
        con.close()
    return redirect(url_for('manage_users'))

# ================= FORGOT PASSWORD =================
@app.route("/forgot_password", methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username')
        phone = request.form.get('phone')
        new_password = request.form.get('new_password')
        
        con = db()
        user = con.execute("SELECT * FROM users WHERE username = ? AND phone = ?", 
                           (username, phone)).fetchone()
        
        if user:
            hashed_pw = generate_password_hash(new_password)
            con.execute("UPDATE users SET password = ? WHERE username = ?", (hashed_pw, username))
            con.commit()
            con.close()
            flash("Password reset successful!", "success")
            return redirect(url_for('login'))
        else:
            con.close()
            flash("Verification failed.", "danger")
            
    return render_template("forgot_password.html")

# ================= DASHBOARD =================
@app.route("/dashboard")
@login_required
def dashboard_view():
    con = db()
    total_rev = con.execute("SELECT SUM(total) FROM invoices").fetchone()[0] or 0
    inv_count = con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
    cur_month = datetime.now().strftime('%m-%Y')
    mon_sales = con.execute("SELECT SUM(total) FROM invoices WHERE date LIKE ?", (f'%{cur_month}',)).fetchone()[0] or 0
    con.close()

    return render_template("dashboard.html", 
                           revenue=f"{total_rev:,.2f}", 
                           count=inv_count, 
                           monthly=f"{mon_sales:,.2f}",
                           datetime_now=datetime.now().strftime("%B %Y"))

# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ================= CREATE INVOICE =================
@app.route("/create", methods=["GET","POST"])
@login_required
def create_invoice():
    if request.method=="POST":
        inv = "INV"+datetime.now().strftime("%Y%m%d%H%M%S")
        date = datetime.now().strftime("%d-%m-%Y")
        name = request.form["name"]
        address = request.form["address"]
        phone = request.form["phone"]
        total = request.form["total"]
        payment = request.form["payment_mode"]

        con = db(); cur = con.cursor()
        cur.execute("""
            INSERT INTO invoices (invoice_no,date,customer,address,phone,total,payment_mode,created_by,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """,(inv,date,name,address,phone,total,payment,session["user"],datetime.now().strftime("%d-%m-%Y %H:%M")))
        con.commit(); con.close()

        generate_pdf(inv, name, address, phone,
                     request.form.getlist("desc[]"),
                     request.form.getlist("qty[]"),
                     request.form.getlist("rate[]"),
                     total, payment)

        return redirect(url_for('preview', inv=inv))
    return render_template("create_invoice.html")

@app.route("/preview/<inv>")
@login_required
def preview(inv):
    con = db()
    # This fetches the phone number and customer name for the WhatsApp link
    invoice = con.execute("SELECT * FROM invoices WHERE invoice_no = ?", (inv,)).fetchone()
    con.close()
    return render_template("preview.html", inv=inv, invoice=invoice)

@app.route("/pdf/<inv>")
@login_required
def pdf(inv):
    return send_file(f"invoices/{inv}.pdf")

# ================= HISTORY =================
@app.route('/invoice_history')
@login_required
def invoice_history():
    search_query = request.args.get('search', '').strip()
    con = db()
    if search_query:
        query = "SELECT * FROM invoices WHERE invoice_no LIKE ? OR customer LIKE ? ORDER BY id DESC"
        rows = con.execute(query, (f"%{search_query}%", f"%{search_query}%")).fetchall()
    else:
        rows = con.execute("SELECT * FROM invoices ORDER BY id DESC").fetchall()
    con.close()
    return render_template('invoice_history.html', rows=rows, search_query=search_query)

# ================= DELETE INVOICE =================
@app.route('/delete_invoice/<invoice_no>', methods=['POST'])
@login_required
def delete_invoice(invoice_no):
    if session.get('user') != 'admin':
        flash("Unauthorized", "danger")
        return redirect(url_for("invoice_history"))

    con = db(); cur = con.cursor()
    cur.execute("DELETE FROM invoices WHERE invoice_no = ?", (invoice_no,))
    con.commit(); con.close()
    
    pdf_path = f"invoices/{invoice_no}.pdf"
    if os.path.exists(pdf_path): os.remove(pdf_path)
        
    flash(f"Invoice {invoice_no} deleted.", "success")
    return redirect(url_for("invoice_history"))

@app.route("/backup_db")
@login_required
def backup_db():
    if session.get('user') != 'admin':
        return redirect(url_for('dashboard_view'))
    return send_file(DB, as_attachment=True)

# ================= PDF GENERATOR =================
def generate_pdf(inv, name, address, phone, desc, qty, rate, total, payment):
    os.makedirs("invoices", exist_ok=True)
    path = f"invoices/{inv}.pdf"
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    brand_purple = (0.35, 0.17, 0.51) 
   # --- LOGO (Left Top - Left Justified) ---
    try:
        # Use a relative path with forward slashes for cross-platform compatibility
        logo_path = "static/logo1.png" 
        
        if os.path.exists(logo_path):
            # drawImage(image, x, y, width, height)
            # h is A4 height. y = h - 90 puts it at the top.
            c.drawImage(logo_path, 40, h - 90, width=70, height=70, mask='auto')
        else:
            # This will print in your terminal if the file is missing
            print(f"Logo not found at: {os.path.abspath(logo_path)}")
    except Exception as e:
        print(f"Error loading logo: {e}")

# --- Header Section (Increased space from logo) ---
    c.setFillColorRGB(*brand_purple)
    c.setFont("Helvetica-Bold", 24)
    # Changed w/2 + 30 to w/2 + 60 for more breathing room
    c.drawCentredString(w/2 + 60, h - 50, "Demo Co In")
    
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 10)
    c.drawCentredString(w/2 + 60, h - 65, "Registration No: 123456789-2026")

    # --- Contact Info ---
    c.setFont("Helvetica", 9)
    c.drawCentredString(w/2 + 60, h - 85, "Email: friendsforever27373@gmail.com  |  Phone: 8250894939")

    # --- Invoice Title ---
    c.setFillColorRGB(*brand_purple)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(w/2, h - 115, "INVOICE")

    # --- Bill To & Invoice Details ---
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, h - 150, "Bill To:")
    
    c.setFont("Helvetica", 11)
    c.drawString(50, h - 165, f"Name: {name}")
    c.drawString(50, h - 180, f"Address: {address}")
    
    c.drawRightString(w - 50, h - 150, f"Invoice Number: {inv}")
    c.drawRightString(w - 50, h - 165, f"Invoice Date: {datetime.now().strftime('%d-%m-%Y')}")

    # --- Table Headers ---
    y = h - 220
    c.setFillColorRGB(*brand_purple)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Item Description")
    c.drawString(300, y, "Quantity")
    c.drawString(400, y, "Rate")
    c.drawString(500, y, "Total")
    c.line(50, y - 5, w - 50, y - 5)
    
    # --- Items ---
    y -= 25
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 11)
    for i in range(len(desc)):
        try:
            line_total = float(qty[i]) * float(rate[i])
        except:
            line_total = 0
            
        c.drawString(50, y, desc[i])
        c.drawString(310, y, str(qty[i]))
        c.drawString(400, y, str(rate[i]))
        c.drawString(500, y, f"{line_total:.2f}")
        y -= 20

    # --- Totals Section ---
    y -= 30
    c.setStrokeColorRGB(*brand_purple)
    c.line(350, y + 15, w - 50, y + 15)
    
    c.setFont("Helvetica-Bold", 11)
    c.drawString(350, y, "Total Amount:")
    c.drawRightString(w - 50, y, f"Rs. {total}")

    # --- Payment Info & Terms ---
    y -= 40
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Payment information: Cash / Online (Gpay, PhonePe, Paytm)")
    c.drawRightString(w - 50, y, f"PAID VIA: {str(payment).upper()}")

    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, 140, "Terms and Conditions")
    c.setFont("Helvetica", 8)
    terms = [
        "1. Payment must be made within the due date mentioned on the invoice.",
        "2. Payments once made are non-refundable unless approved by the Trust authority.",
        "3. Any dispute must be reported within 7 days of invoice date.",
        "4. This invoice is valid only with authorized signature and official seal."
    ]
    ty = 125
    for t in terms:
        c.drawString(50, ty, t)
        ty -= 12

    # --- Signature ---
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(w - 50, 60, "__________________________")
    c.drawRightString(w - 90, 45, "Sign & Stamp")
    
    c.save()

if __name__ == "__main__":

    app.run(debug=True)
