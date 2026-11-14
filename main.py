"""QG RENDA — servidor MVP de microtarefas e recompensas.

O sistema registra saldos reais em centavos APENAS após revisão humana e
verificação manual do financiamento. NÃO processa transferências de dinheiro.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
import re

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('DATABASE_PATH', str(BASE_DIR / 'data' / 'qg-renda.sqlite3')))
COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'false').lower() == 'true'
APP_ORIGIN = (os.environ.get('APP_ORIGIN') or ('https://' + os.environ['RENDER_EXTERNAL_HOSTNAME'] if os.environ.get('RENDER_EXTERNAL_HOSTNAME') else '')).rstrip('/')
DEMO_ONLY = os.environ.get('DEMO_ONLY', 'false').lower() == 'true'
ADMIN_EMAIL = os.environ.get('BOOTSTRAP_ADMIN_EMAIL', '').strip().lower()
ADMIN_PASSWORD = os.environ.get('BOOTSTRAP_ADMIN_PASSWORD', '')
MIN_WITHDRAWAL_CENTS = max(100, int(os.environ.get('MIN_WITHDRAWAL_CENTS', '2000')))
SESSION_SECONDS = 7 * 86400
COOKIE_NAME = 'qgr_session'

app = FastAPI(title='QG RENDA API', docs_url=None, redoc_url=None, openapi_url=None)
app.mount('/assets', StaticFiles(directory=BASE_DIR / 'static'), name='assets')


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=20000')
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return 'scrypt$16384$8$1$' + salt.hex() + '$' + derived.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        alg, n, r, p, salt, hashed = encoded.split('$')
        if alg != 'scrypt':
            return False
        key = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(key, bytes.fromhex(hashed))
    except (ValueError, TypeError):
        return False


def init_db():
    with db() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            payouts_enabled INTEGER NOT NULL DEFAULT 0,
            balance_cents INTEGER NOT NULL DEFAULT 0 CHECK (balance_cents >= 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            csrf TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            sponsor TEXT NOT NULL,
            reward_cents INTEGER NOT NULL DEFAULT 0 CHECK(reward_cents >= 0),
            budget_cents INTEGER NOT NULL DEFAULT 0 CHECK(budget_cents >= 0),
            spent_cents INTEGER NOT NULL DEFAULT 0 CHECK(spent_cents >= 0 AND spent_cents <= budget_cents),
            reserved_cents INTEGER NOT NULL DEFAULT 0 CHECK(reserved_cents >= 0 AND spent_cents + reserved_cents <= budget_cents),
            demo INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            task_id INTEGER NOT NULL REFERENCES tasks(id),
            evidence TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
            reviewed_at TEXT,
            reviewer_note TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, task_id)
        );
        CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            related_id INTEGER,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            status TEXT NOT NULL CHECK(status IN ('requested','paid','rejected')),
            external_reference TEXT,
            reviewer_note TEXT,
            created_at TEXT NOT NULL,
            processed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS privacy_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            type TEXT NOT NULL DEFAULT 'deletion',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        ''')
        # Migração compatível com bancos gerados pela versão inicial do MVP.
        if 'reserved_cents' not in {r['name'] for r in con.execute('PRAGMA table_info(tasks)')}: 
            con.execute('ALTER TABLE tasks ADD COLUMN reserved_cents INTEGER NOT NULL DEFAULT 0')
        if con.execute('SELECT COUNT(*) AS c FROM tasks').fetchone()['c'] == 0:
            con.execute('''INSERT INTO tasks (title, description, sponsor, demo, reward_cents,
                           budget_cents, active, created_at) VALUES (?, ?, ?, 1, 0, 0, 1, ?)''',
                        ('Conheça o funcionamento',
                         'Tarefa de teste: envie uma frase explicando o que você espera da plataforma. Não gera saldo.',
                         'QG RENDA (demonstração)', now()))
        if ADMIN_EMAIL and ADMIN_PASSWORD:
            if len(ADMIN_PASSWORD) < 12:
                raise RuntimeError('BOOTSTRAP_ADMIN_PASSWORD deve ter pelo menos 12 caracteres.')
            admin = con.execute('SELECT id FROM users WHERE email=?', (ADMIN_EMAIL,)).fetchone()
            if admin is None:
                con.execute('INSERT INTO users (name,email,password_hash,is_admin,created_at) VALUES (?,?,?,?,?)',
                            ('Administrador', ADMIN_EMAIL, hash_password(ADMIN_PASSWORD), 1, now()))


@app.on_event('startup')
def startup():
    init_db()


@app.middleware('http')
async def security_headers(request: Request, call_next):
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        origin = request.headers.get('origin')
        expected = APP_ORIGIN or str(request.base_url).rstrip('/')
        if origin and origin.rstrip('/') != expected:
            return JSONResponse({'detail': 'Origem de requisição não permitida.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'public, max-age=300'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
        "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    if COOKIE_SECURE:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


_login_attempts: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


def limit_auth(request: Request):
    key = request.client.host if request.client else 'unknown'
    stamp = time.time()
    with _rate_lock:
        _login_attempts[key] = [t for t in _login_attempts.get(key, []) if stamp-t < 900]
        if len(_login_attempts[key]) >= 15:
            raise HTTPException(429, 'Muitas tentativas. Tente novamente mais tarde.')
        _login_attempts[key].append(stamp)
        if len(_login_attempts) > 10000:
            _login_attempts.clear()


def session_token() -> tuple[str, str, str]:
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash, secrets.token_urlsafe(32)


def start_session(response: Response, uid: int):
    token, token_hash, csrf = session_token()
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS)).isoformat()
    with db() as con:
        con.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires_at,created_at) VALUES (?,?,?,?,?)',
                    (token_hash, uid, csrf, expiry, now()))
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=COOKIE_SECURE,
                        samesite='strict', max_age=SESSION_SECONDS, path='/')
    return csrf


def current_user(
    request: Request,
    token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
    csrf_header: Annotated[str | None, Header(alias='X-CSRF-Token')] = None,
):
    if not token:
        raise HTTPException(401, 'Entre para continuar.')
    digest = hashlib.sha256(token.encode()).hexdigest()
    with db() as con:
        row = con.execute('''SELECT u.*, s.csrf, s.expires_at, s.token_hash
                             FROM sessions s JOIN users u ON s.user_id=u.id
                             WHERE s.token_hash=?''', (digest,)).fetchone()
    if not row or row['expires_at'] < now():
        raise HTTPException(401, 'Sessão expirada. Entre novamente.')
    if request.method in ('POST', 'PATCH', 'PUT', 'DELETE'):
        if not csrf_header or not hmac.compare_digest(csrf_header, row['csrf']):
            raise HTTPException(403, 'Token de proteção inválido.')
    return dict(row)


def admin_user(user=Depends(current_user)):
    if not user['is_admin']:
        raise HTTPException(403, 'Acesso exclusivo da administração.')
    return user


def user_public(user):
    return {key: user[key] for key in ('id', 'name', 'email', 'is_admin', 'payouts_enabled', 'balance_cents', 'created_at')}


class Register(BaseModel):
    name: str = Field(min_length=2, max_length=70)
    email: str = Field(min_length=5, max_length=180)
    password: str = Field(min_length=10, max_length=200)
    accepted_terms: bool

    @field_validator('email')
    @classmethod
    def check_email(cls, v):
        v = v.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', v):
            raise ValueError('Informe um e-mail válido.')
        return v

    @field_validator('name')
    @classmethod
    def check_name(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError('Nome muito curto.')
        return v


class Login(BaseModel):
    email: str
    password: str


class SubmissionInput(BaseModel):
    task_id: int = Field(gt=0)
    evidence: str = Field(min_length=10, max_length=1000)


class NewTask(BaseModel):
    title: str = Field(min_length=5, max_length=100)
    description: str = Field(min_length=15, max_length=1000)
    sponsor: str = Field(min_length=2, max_length=100)
    reward_cents: int = Field(ge=0, le=1000000)
    budget_cents: int = Field(ge=0, le=100000000)
    demo: bool = True
    funding_confirmed: bool = False


class ReviewSubmission(BaseModel):
    decision: Literal['approve', 'reject']
    note: str = Field(default='', max_length=500)


class PayoutRequest(BaseModel):
    amount_cents: int = Field(ge=100)


class PayoutReview(BaseModel):
    decision: Literal['mark_paid', 'reject']
    external_reference: str = Field(default='', max_length=100)
    note: str = Field(default='', max_length=500)


class Eligibility(BaseModel):
    enabled: bool
    verified_compliance: bool


@app.get('/')
def index():
    return FileResponse(BASE_DIR / 'static' / 'index.html')


@app.get('/privacidade')
def privacy():
    return FileResponse(BASE_DIR / 'static' / 'privacidade.html')


@app.get('/termos')
def terms():
    return FileResponse(BASE_DIR / 'static' / 'termos.html')


@app.get('/api/config')
def config():
    return {'demo_only': DEMO_ONLY, 'automatic_payments': False}


@app.get('/api/health')
def health():
    return {'status': 'ok', 'app': 'qg-renda', 'time': now()}


@app.post('/api/auth/register', status_code=201)
def register(body: Register, response: Response, request: Request):
    limit_auth(request)
    if not body.accepted_terms:
        raise HTTPException(400, 'É necessário aceitar os termos para criar uma conta.')
    with db() as con:
        try:
            con.execute('INSERT INTO users(name,email,password_hash,created_at) VALUES (?,?,?,?)',
                        (body.name, body.email, hash_password(body.password), now()))
            uid = con.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Este e-mail já está cadastrado.')
    csrf = start_session(response, uid)
    return {'message': 'Conta criada.', 'csrf': csrf, 'user': user_by_id(uid)}


def user_by_id(uid: int):
    with db() as con:
        row = con.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    return user_public(row) if row else None


@app.post('/api/auth/login')
def login(body: Login, response: Response, request: Request):
    limit_auth(request)
    with db() as con:
        row = con.execute('SELECT * FROM users WHERE email=?', (body.email.strip().lower(),)).fetchone()
    if not row or not verify_password(body.password, row['password_hash']):
        raise HTTPException(401, 'E-mail ou senha incorretos.')
    csrf = start_session(response, row['id'])
    return {'message': 'Login efetuado.', 'csrf': csrf, 'user': user_public(row)}


@app.get('/api/auth/me')
def me(user=Depends(current_user)):
    return {'user': user_public(user), 'csrf': user['csrf']}


@app.post('/api/auth/logout')
def logout(response: Response, user=Depends(current_user)):
    with db() as con:
        con.execute('DELETE FROM sessions WHERE token_hash=?', (user['token_hash'],))
    response.delete_cookie(COOKIE_NAME, path='/', secure=COOKIE_SECURE, httponly=True, samesite='strict')
    return {'ok': True}


@app.get('/api/tasks')
def tasks(user=Depends(current_user)):
    with db() as con:
        results = con.execute('''SELECT t.*,s.status AS my_status
            FROM tasks t LEFT JOIN submissions s ON s.task_id=t.id AND s.user_id=?
            WHERE t.active=1 ORDER BY t.demo ASC, t.id DESC''', (user['id'],)).fetchall()
    return {'tasks': [{**dict(row), 'slots_remaining': None if row['demo'] else
             max(0, (row['budget_cents'] - row['spent_cents'] - row['reserved_cents']) // max(1, row['reward_cents']))}
             for row in results]}


@app.post('/api/submissions', status_code=201)
def submit(body: SubmissionInput, user=Depends(current_user)):
    if DEMO_ONLY:
        with db() as con:
            row = con.execute('SELECT demo FROM tasks WHERE id=?', (body.task_id,)).fetchone()
        if row and not row['demo']:
            raise HTTPException(403, 'Ambiente de demonstração: tarefas remuneradas desativadas.')
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        task = con.execute('SELECT * FROM tasks WHERE id=? AND active=1', (body.task_id,)).fetchone()
        if not task:
            raise HTTPException(404, 'Tarefa não disponível.')
        if not task['demo'] and not user['payouts_enabled']:
            raise HTTPException(403, 'Sua conta ainda não foi habilitada para recompensas reais.')
        if not task['demo']:
            reserved = con.execute('''UPDATE tasks SET reserved_cents=reserved_cents+?
                   WHERE id=? AND budget_cents-spent_cents-reserved_cents>=?''',
                   (task['reward_cents'], task['id'], task['reward_cents']))
            if reserved.rowcount != 1:
                raise HTTPException(409, 'Orçamento desta tarefa esgotado.')
        try:
            con.execute('INSERT INTO submissions (user_id,task_id,evidence,status,created_at) VALUES (?,?,?,?,?)',
                        (user['id'], body.task_id, body.evidence.strip(), 'pending', now()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Você já enviou esta tarefa.')
        con.execute('COMMIT')
    return {'message': 'Enviado para análise. Nenhum valor foi creditado ainda.'}


@app.get('/api/dashboard')
def dashboard(user=Depends(current_user)):
    with db() as con:
        submissions = [dict(row) for row in con.execute('''SELECT s.id,s.evidence,s.status,s.created_at,
           s.reviewer_note,t.title,t.reward_cents,t.demo FROM submissions s
           JOIN tasks t ON t.id=s.task_id WHERE s.user_id=? ORDER BY s.id DESC LIMIT 50''', (user['id'],))]
        ledger = [dict(row) for row in con.execute('SELECT * FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 100', (user['id'],))]
        withdrawals = [dict(row) for row in con.execute('SELECT * FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 50', (user['id'],))]
    return {'user': user_by_id(user['id']), 'submissions': submissions,
            'ledger': ledger, 'withdrawals': withdrawals, 'min_withdrawal_cents': MIN_WITHDRAWAL_CENTS}


@app.post('/api/withdrawals', status_code=201)
def request_withdrawal(body: PayoutRequest, user=Depends(current_user)):
    if DEMO_ONLY:
        raise HTTPException(403, 'Ambiente de demonstração: saques desativados.')
    if not user['payouts_enabled']:
        raise HTTPException(403, 'Conta não habilitada para saques.')
    if body.amount_cents < MIN_WITHDRAWAL_CENTS:
        raise HTTPException(400, 'Valor abaixo do saque mínimo.')
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        result = con.execute('UPDATE users SET balance_cents=balance_cents-? WHERE id=? AND balance_cents>=?',
                             (body.amount_cents, user['id'], body.amount_cents))
        if result.rowcount != 1:
            raise HTTPException(409, 'Saldo insuficiente.')
        con.execute('INSERT INTO withdrawals(user_id,amount_cents,status,created_at) VALUES (?,?,?,?)',
                    (user['id'], body.amount_cents, 'requested', now()))
        wid = con.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
        con.execute('INSERT INTO ledger(user_id,kind,amount_cents,related_id,description,created_at) VALUES (?,?,?,?,?,?)',
                    (user['id'], 'withdrawal_hold', -body.amount_cents, wid, 'Solicitação de saque (reserva)', now()))
        con.execute('COMMIT')
    return {'message': 'Saque solicitado; aguardando pagamento manual externo.', 'withdrawal_id': wid}


@app.get('/api/privacy/export')
def export_data(user=Depends(current_user)):
    with db() as con:
        data = {'user': user_public(user)}
        for table in ('submissions', 'ledger', 'withdrawals', 'privacy_requests'):
            data[table] = [dict(row) for row in con.execute(f'SELECT * FROM {table} WHERE user_id=?', (user['id'],))]
    return data


@app.post('/api/privacy/request-deletion', status_code=201)
def deletion_request(user=Depends(current_user)):
    with db() as con:
        exists = con.execute('SELECT id FROM privacy_requests WHERE user_id=? AND status=?', (user['id'], 'pending')).fetchone()
        if not exists:
            con.execute('INSERT INTO privacy_requests(user_id,type,status,created_at) VALUES (?,?,?,?)',
                        (user['id'], 'deletion', 'pending', now()))
    return {'message': 'Pedido registrado; revisão conforme obrigações legais de retenção.'}


@app.get('/api/admin/overview')
def admin_overview(user=Depends(admin_user)):
    with db() as con:
        counts = {}
        for name, query in {
            'users': 'SELECT COUNT(*) FROM users',
            'paid_tasks': 'SELECT COUNT(*) FROM tasks WHERE demo=0',
            'pending_submissions': "SELECT COUNT(*) FROM submissions WHERE status='pending'",
            'pending_withdrawals': "SELECT COUNT(*) FROM withdrawals WHERE status='requested'",
            'privacy_requests': "SELECT COUNT(*) FROM privacy_requests WHERE status='pending'",
        }.items():
            counts[name] = con.execute(query).fetchone()[0]
        counts['committed_budget_cents'] = con.execute('SELECT COALESCE(SUM(budget_cents),0) FROM tasks WHERE demo=0').fetchone()[0]
        counts['spent_budget_cents'] = con.execute('SELECT COALESCE(SUM(spent_cents),0) FROM tasks WHERE demo=0').fetchone()[0]
        counts['reserved_budget_cents'] = con.execute('SELECT COALESCE(SUM(reserved_cents),0) FROM tasks WHERE demo=0').fetchone()[0]
    return counts


@app.post('/api/admin/tasks', status_code=201)
def create_task(body: NewTask, user=Depends(admin_user)):
    if DEMO_ONLY and not body.demo:
        raise HTTPException(403, 'Ambiente de demonstração: tarefas remuneradas desativadas.')
    if body.demo and (body.reward_cents != 0 or body.budget_cents != 0):
        raise HTTPException(400, 'Tarefas demonstrativas não podem gerar saldo.')
    if not body.demo:
        if not body.funding_confirmed:
            raise HTTPException(400, 'Confirme primeiro a existência de recursos recebidos do patrocinador.')
        if body.reward_cents < 100 or body.budget_cents < body.reward_cents:
            raise HTTPException(400, 'Recompensa mínima R$ 1,00 e orçamento igual ou maior.')
    with db() as con:
        con.execute('''INSERT INTO tasks(title,description,sponsor,reward_cents,budget_cents,demo,created_at)
            VALUES(?,?,?,?,?,?,?)''', (body.title.strip(), body.description.strip(), body.sponsor.strip(),
                                      body.reward_cents, body.budget_cents, int(body.demo), now()))
    return {'message': 'Tarefa criada. A confirmação de financiamento é responsabilidade do administrador.'}


@app.get('/api/admin/submissions')
def admin_submissions(user=Depends(admin_user)):
    with db() as con:
        data = [dict(r) for r in con.execute('''SELECT s.*,u.name AS username,u.email,t.title,
            t.reward_cents,t.demo FROM submissions s JOIN users u ON u.id=s.user_id
            JOIN tasks t ON t.id=s.task_id ORDER BY CASE WHEN s.status='pending' THEN 0 ELSE 1 END,s.id DESC LIMIT 100''')]
    return {'submissions': data}


@app.post('/api/admin/submissions/{sid}/review')
def review_submission(sid: int, body: ReviewSubmission, user=Depends(admin_user)):
    if DEMO_ONLY:
        with db() as con:
            row = con.execute('SELECT t.demo FROM submissions s JOIN tasks t ON s.task_id=t.id WHERE s.id=?', (sid,)).fetchone()
        if row and not row['demo']:
            raise HTTPException(403, 'Ambiente de demonstração: recompensas reais desativadas.')
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        item = con.execute('''SELECT s.*,t.demo,t.reward_cents,t.spent_cents,t.budget_cents,t.active,
             u.payouts_enabled FROM submissions s JOIN tasks t ON s.task_id=t.id
             JOIN users u ON s.user_id=u.id WHERE s.id=?''', (sid,)).fetchone()
        if not item:
            raise HTTPException(404, 'Envio não encontrado.')
        if item['status'] != 'pending':
            raise HTTPException(409, 'Envio já analisado.')
        if body.decision == 'approve' and not item['demo']:
            if not item['payouts_enabled']:
                raise HTTPException(409, 'Usuário não está habilitado para recompensas reais.')
            updated = con.execute('''UPDATE tasks SET spent_cents=spent_cents+?,
                    reserved_cents=reserved_cents-?
                 WHERE id=? AND reserved_cents>=?''',
                 (item['reward_cents'], item['reward_cents'], item['task_id'], item['reward_cents']))
            if updated.rowcount != 1:
                raise HTTPException(409, 'Reserva não encontrada para esta tarefa.')
            con.execute('UPDATE users SET balance_cents=balance_cents+? WHERE id=?',
                        (item['reward_cents'], item['user_id']))
            con.execute('INSERT INTO ledger(user_id,kind,amount_cents,related_id,description,created_at) VALUES (?,?,?,?,?,?)',
                        (item['user_id'], 'reward', item['reward_cents'], sid, 'Recompensa aprovada por tarefa', now()))
        if body.decision == 'reject' and not item['demo']:
            con.execute('UPDATE tasks SET reserved_cents=reserved_cents-? WHERE id=? AND reserved_cents>=?',
                        (item['reward_cents'], item['task_id'], item['reward_cents']))
        con.execute('UPDATE submissions SET status=?,reviewed_at=?,reviewer_note=? WHERE id=?',
                    ('approved' if body.decision == 'approve' else 'rejected', now(), body.note, sid))
        con.execute('COMMIT')
    return {'message': 'Envio analisado.'}


@app.get('/api/admin/withdrawals')
def admin_withdrawals(user=Depends(admin_user)):
    with db() as con:
        data = [dict(row) for row in con.execute('''SELECT w.*,u.name AS username,u.email
            FROM withdrawals w JOIN users u ON u.id=w.user_id
            ORDER BY CASE WHEN w.status='requested' THEN 0 ELSE 1 END,w.id DESC LIMIT 100''')]
    return {'withdrawals': data}


@app.post('/api/admin/withdrawals/{wid}/review')
def admin_review_withdrawal(wid: int, body: PayoutReview, user=Depends(admin_user)):
    if DEMO_ONLY:
        raise HTTPException(403, 'Ambiente de demonstração: pagamento de saques desativado.')
    if body.decision == 'mark_paid' and len(body.external_reference.strip()) < 6:
        raise HTTPException(400, 'Registre a referência de um pagamento externo já concluído.')
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        withdrawal = con.execute('SELECT * FROM withdrawals WHERE id=?', (wid,)).fetchone()
        if not withdrawal:
            raise HTTPException(404, 'Saque não encontrado.')
        if withdrawal['status'] != 'requested':
            raise HTTPException(409, 'Saque já processado.')
        if body.decision == 'reject':
            con.execute('UPDATE users SET balance_cents=balance_cents+? WHERE id=?',
                        (withdrawal['amount_cents'], withdrawal['user_id']))
            con.execute('INSERT INTO ledger(user_id,kind,amount_cents,related_id,description,created_at) VALUES (?,?,?,?,?,?)',
                        (withdrawal['user_id'], 'withdrawal_refund', withdrawal['amount_cents'], wid,
                         'Estorno de saque rejeitado', now()))
        con.execute('''UPDATE withdrawals SET status=?,external_reference=?,reviewer_note=?,processed_at=? WHERE id=?''',
                    ('paid' if body.decision == 'mark_paid' else 'rejected',
                     body.external_reference.strip() if body.decision == 'mark_paid' else None,
                     body.note, now(), wid))
        con.execute('COMMIT')
    return {'message': 'Status atualizado. O servidor não envia Pix automaticamente.'}


@app.get('/api/admin/users')
def admin_users(user=Depends(admin_user)):
    with db() as con:
        rows = con.execute('''SELECT id,name,email,is_admin,payouts_enabled,balance_cents,created_at
            FROM users ORDER BY id DESC LIMIT 200''').fetchall()
    return {'users': [dict(row) for row in rows]}


@app.post('/api/admin/users/{uid}/eligibility')
def set_eligibility(uid: int, body: Eligibility, user=Depends(admin_user)):
    if DEMO_ONLY and body.enabled:
        raise HTTPException(403, 'Ambiente de demonstração: recompensas reais desativadas.')
    if body.enabled and not body.verified_compliance:
        raise HTTPException(400, 'Confirme a verificação legal/contratual da conta antes de habilitar recompensas.')
    with db() as con:
        result = con.execute('UPDATE users SET payouts_enabled=? WHERE id=? AND is_admin=0',
                             (int(body.enabled), uid))
        if result.rowcount != 1:
            raise HTTPException(404, 'Usuário não encontrado ou é administrador.')
    return {'message': 'Elegibilidade alterada. Auditoria/documentos devem ser mantidos em sistema adequado.'}


@app.get('/api/admin/privacy-requests')
def admin_privacy(user=Depends(admin_user)):
    with db() as con:
        rows = con.execute('''SELECT p.*,u.email,u.name FROM privacy_requests p
            JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 100''').fetchall()
    return {'requests': [dict(row) for row in rows]}

# Rotas isoladas do Asaas Sandbox: sem repasses nem créditos reais.
from asaas_sandbox import install_asaas_sandbox
install_asaas_sandbox(app, connect, admin_user)
