import os
import shutil
import secrets
import smtplib
from email.mime.text import MIMEText
from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from mako.lookup import TemplateLookup
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import SessionLocal, Part, Lead, AdminUser, User, hash_password, verify_password
import requests
import uvicorn

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_LOGIN = "puzikov18.09.1988@gmail.com"
SMTP_PASSWORD = "cbwawljxutelfjxl"   # не забудь сменить, если светил

ADMIN_EMAILS = [
    "puzikov18.09.1988@gmail.com",    # твой
    "почта_заказчика@домен.ru"        # заказчик
]

def send_admin_email(subject: str, text: str):
    for email in ADMIN_EMAILS:
        msg = MIMEText(text, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_LOGIN
        msg["To"] = email
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_LOGIN, SMTP_PASSWORD)
                server.send_message(msg)
            print(f"✅ Email отправлен на {email}")
        except Exception as e:
            print(f"❌ Ошибка отправки на {email}: {e}")

# ---------- Настройки Telegram ----------
TELEGRAM_TOKEN = "8991674022:AAFyOPVH468qm4vlr4QtmZBbhsA0XQLDQNI"
TELEGRAM_CHAT_ID = "5977647337"

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram не настроен: отсутствует токен или chat_id")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=12,
            proxies={"http": None, "https": None}
        )
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")

# ---------- FastAPI ----------
app = FastAPI()
template_lookup = TemplateLookup(directories=[os.path.join(os.path.dirname(__file__), "templates")])
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------- Зависимости ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def check_admin(request: Request):
    return request.cookies.get("admin") == "1"

def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if user_id:
        try:
            user = db.query(User).filter(User.id == int(user_id)).first()
            return user
        except:
            pass
    return None

# ---------- Публичные маршруты ----------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, search: str = "", category: str = "",
                db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(Part)
    if search:
        query = query.filter(func.lower(Part.name).contains(func.lower(search)))
    if category:
        query = query.filter(Part.category == category)
    parts = query.all()
    categories = [c[0] for c in db.query(Part.category).distinct() if c[0]]
    success = request.query_params.get("success")
    template = template_lookup.get_template("index.html")
    return HTMLResponse(template.render(parts=parts, search=search, current_category=category,
                                        categories=categories, current_user=current_user, success=success))

@app.get("/part/{part_id}", response_class=HTMLResponse)
async def part_detail(request: Request, part_id: int, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(404, "Запчасть не найдена")
    template = template_lookup.get_template("detail.html")
    success = request.query_params.get("success")
    return HTMLResponse(template.render(part=part, success=success, current_user=current_user))

@app.post("/part/{part_id}/lead")
async def send_lead(part_id: int, name: str = Form(...), phone: str = Form(...),
                    email: str = Form(...),  # email клиента (для подтверждения)
                    message: str = Form(""),
                    db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    lead = Lead(
        part_id=part_id,
        name=name,
        phone=phone,
        message=message,
        user_id=current_user.id if current_user else None
    )
    db.add(lead)
    db.commit()

    part = db.query(Part).filter(Part.id == part_id).first()
    if part:
        text = (
            f"🛠 Новая заявка!\n"
            f"Запчасть: {part.name}\n"
            f"Цена: {part.price} ₽\n"
            f"Имя: {name}\n"
            f"Телефон: {phone}\n"
            f"Email: {email}\n"
            f"Сообщение: {message or '—'}\n"
            f"Клиент: {'Зарегистрирован' if current_user else 'Гость'}"
        )
    else:
        text = f"Новая заявка!\nИмя: {name}\nТелефон: {phone}\nEmail: {email}\nСообщение: {message or '—'}"

    # Отправка уведомлений
    send_telegram(text)
    send_admin_email("🛠 Новая заявка на сайте", text)

    # Отправка подтверждения клиенту (если email указан)
    if email:
        client_subject = f"Ваша заявка на {part.name if part else 'запчасть'}"
        client_body = (
            f"Здравствуйте, {name}!\n\n"
            f"Вы оставили заявку на запчасть: {part.name if part else '—'}\n"
            f"Цена: {part.price if part else '—'} ₽\n"
            f"Ваш телефон: {phone}\n"
            f"Сообщение: {message or '—'}\n\n"
            f"Мы свяжемся с вами в ближайшее время.\n"
            f"С уважением, Amurskзапчасти"
        )
        try:
            send_client_email(email, client_subject, client_body)
        except:
            pass

    return RedirectResponse("/?success=1", status_code=303)

# ---------- Отправка письма клиенту (можно использовать ту же функцию, но с другим получателем) ----------
def send_client_email(to_email: str, subject: str, text: str):
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_LOGIN
    msg["To"] = to_email
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_LOGIN, SMTP_PASSWORD)
        server.send_message(msg)

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    template = template_lookup.get_template("register.html")
    error = request.query_params.get("error")
    return HTMLResponse(template.render(error=error))

@app.post("/register")
async def register(name: str = Form(...), phone: str = Form(...),
                   password: str = Form(...), db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.phone == phone).first()
    if existing:
        return RedirectResponse("/register?error=phone_exists", status_code=303)
    user = User(name=name, phone=phone, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(key="user_id", value=str(user.id))
    return response

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    template = template_lookup.get_template("login.html")
    error = request.query_params.get("error")
    return HTMLResponse(template.render(error=error))

@app.post("/login")
async def login(phone: str = Form(...), password: str = Form(...),
                db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == phone).first()
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse("/login?error=invalid", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(key="user_id", value=str(user.id))
    return response

@app.get("/logout")
async def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("user_id")
    return response

@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    leads = db.query(Lead).filter(Lead.user_id == current_user.id).order_by(Lead.created_at.desc()).all()
    template = template_lookup.get_template("profile.html")
    return HTMLResponse(template.render(current_user=current_user, leads=leads))

# ---------- Админка ----------
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, db: Session = Depends(get_db)):
    if not check_admin(request):
        error = request.query_params.get("error")
        template = template_lookup.get_template("admin.html")
        return HTMLResponse(
            template.render(admin_ok=False, error=error, leads=[], parts=[], edit_part=None, show_form=False, users=[]))

    section = request.query_params.get("section", "leads")
    edit_id = request.query_params.get("edit")
    edit_part = None
    show_form = False
    if edit_id:
        show_form = True
        if edit_id != "new":
            try:
                edit_part = db.query(Part).filter(Part.id == int(edit_id)).first()
            except ValueError:
                pass

    leads = db.query(Lead).order_by(Lead.created_at.desc()).all() if section == "leads" else []
    parts = db.query(Part).all() if section == "parts" else []
    if section == "users":
        users = db.query(User).all()
        print("ПОЛЬЗОВАТЕЛИ В БАЗЕ:", [(u.id, u.name, u.phone) for u in users])
    else:
        users = []

    password_error = None
    password_ok = None
    if section == "password":
        password_error = request.query_params.get("password_error")
        password_ok = request.query_params.get("password_ok")

    template = template_lookup.get_template("admin.html")
    return HTMLResponse(template.render(admin_ok=True, section=section, leads=leads, parts=parts,
                                        edit_part=edit_part, show_form=show_form,
                                        password_error=password_error, password_ok=password_ok,
                                        users=users))

@app.post("/admin/login")
async def admin_login(request: Request, username: str = Form(...), password: str = Form(...),
                      db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter_by(username=username, password=password).first()
    if not user:
        return RedirectResponse("/admin?error=1", status_code=303)
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(key="admin", value="1")
    return response

@app.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse("/admin", status_code=303)
    response.delete_cookie("admin")
    return response

@app.post("/admin/change_password")
async def admin_change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db)
):
    if not check_admin(request):
        return RedirectResponse("/admin", status_code=303)
    user = db.query(AdminUser).filter_by(username="admin").first()
    if not user or user.password != old_password:
        return RedirectResponse("/admin?section=password&password_error=1", status_code=303)
    user.password = new_password
    db.commit()
    return RedirectResponse("/admin?section=password&password_ok=1", status_code=303)

@app.post("/admin/parts/add")
async def admin_add_part(request: Request, name: str = Form(...), price: int = Form(...),
                         category: str = Form(""), description: str = Form(""),
                         photo: UploadFile = File(None), db: Session = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin", status_code=303)
    photo_path = None
    if photo and photo.filename:
        os.makedirs("static/images", exist_ok=True)
        filename = f"{secrets.token_hex(8)}_{photo.filename}"
        filepath = f"static/images/{filename}"
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        photo_path = f"/static/images/{filename}"
    part = Part(name=name, price=price, category=category, description=description, photo=photo_path)
    db.add(part)
    db.commit()
    return RedirectResponse("/admin?section=parts", status_code=303)

@app.post("/admin/parts/edit/{part_id}")
async def admin_edit_part(request: Request, part_id: int, name: str = Form(...), price: int = Form(...),
                          category: str = Form(""), description: str = Form(""),
                          photo: UploadFile = File(None), db: Session = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin", status_code=303)
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(404, "Запчасть не найдена")
    part.name = name
    part.price = price
    part.category = category
    part.description = description
    if photo and photo.filename:
        os.makedirs("static/images", exist_ok=True)
        filename = f"{secrets.token_hex(8)}_{photo.filename}"
        filepath = f"static/images/{filename}"
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        part.photo = f"/static/images/{filename}"
    db.commit()
    return RedirectResponse("/admin?section=parts", status_code=303)

@app.get("/admin/parts/delete/{part_id}")
async def admin_delete_part(request: Request, part_id: int, db: Session = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin", status_code=303)
    part = db.query(Part).filter(Part.id == part_id).first()
    if part:
        db.delete(part)
        db.commit()
    return RedirectResponse("/admin?section=parts", status_code=303)

@app.get("/admin/lead/process/{lead_id}")
async def admin_process_lead(request: Request, lead_id: int, db: Session = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin", status_code=303)
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if lead:
        lead.is_processed = 1
        db.commit()
    return RedirectResponse("/admin?section=leads", status_code=303)
@app.get("/support", response_class=HTMLResponse)
async def support_page(request: Request):
    template = template_lookup.get_template("support.html")
    success = request.query_params.get("success")
    return HTMLResponse(template.render(success=success))

@app.post("/support")
async def support_send(name: str = Form(...), contact: str = Form(...), message: str = Form(...)):
    text = f"📩 Новое обращение в поддержку!\nИмя: {name}\nКонтакты: {contact}\nВопрос: {message}"
    send_telegram(text)
    send_admin_email("📩 Обращение в поддержку", text)
    return RedirectResponse(url="/?success=1", status_code=303)

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)