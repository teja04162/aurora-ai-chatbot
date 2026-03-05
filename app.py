import os
import sqlite3
import time
from datetime import datetime

import bcrypt
import streamlit as st
from google import genai  # pip install google-genai
from google.genai import errors as genai_errors


# -----------------------------
# Model retry + fallback (503 fix)
# -----------------------------
MODEL_PRIMARY = "models/gemini-flash-latest"
MODEL_FALLBACKS = [
    "models/gemini-flash-lite-latest",
    "models/gemini-2.0-flash-lite",
]

def generate_with_retry(client, contents, max_attempts=5):
    """
    Retries on Gemini 503 (high demand) with exponential backoff,
    and falls back to lighter models if needed.
    """
    models_to_try = [MODEL_PRIMARY] + MODEL_FALLBACKS
    last_err = None

    for model_name in models_to_try:
        for attempt in range(1, max_attempts + 1):
            try:
                resp = client.models.generate_content(model=model_name, contents=contents)
                return resp, model_name
            except genai_errors.ServerError as e:
                last_err = e
                sleep_s = min(2 ** attempt, 12)  # 2,4,8,12,12...
                time.sleep(sleep_s)
            except Exception as e:
                last_err = e
                break

    raise last_err


# -----------------------------
# Product config
# -----------------------------
APP_NAME = "Aurora AI"
TAGLINE = "Your personal assistant • Secure accounts • Saved chats"
MODEL = MODEL_PRIMARY
DB_PATH = "aurora_ai.db"


# -----------------------------
# CSS: New Design System
# -----------------------------
def inject_css():
    st.markdown(
        """
        <style>
          /* Hide Streamlit chrome */
          #MainMenu, footer, header {visibility: hidden;}
          .block-container { max-width: 1200px; padding-top: 1rem; padding-bottom: 2rem; }

          /* Background */
          .stApp {
            background: radial-gradient(1200px 800px at 15% 0%, rgba(120,140,255,.14), transparent 55%),
                        radial-gradient(1000px 700px at 90% 15%, rgba(255,120,200,.12), transparent 50%),
                        radial-gradient(900px 650px at 60% 100%, rgba(100,255,200,.10), transparent 55%);
          }

          /* Top bar */
          .topbar {
            display:flex; justify-content:space-between; align-items:center;
            padding: 12px 14px;
            border: 1px solid rgba(255,255,255,0.10);
            background: rgba(18,18,24,0.55);
            backdrop-filter: blur(10px);
            border-radius: 18px;
            margin-bottom: 14px;
          }
          .brand {
            display:flex; align-items:center; gap:12px;
          }
          .logo {
            width:42px; height:42px; border-radius: 16px;
            display:flex; align-items:center; justify-content:center;
            background: linear-gradient(135deg, rgba(110,140,255,.35), rgba(255,120,210,.25));
            border: 1px solid rgba(255,255,255,0.12);
            box-shadow: 0 10px 30px rgba(0,0,0,.25);
            font-size: 18px;
          }
          .brand h1 {
            font-size: 16px; margin:0; font-weight: 800; line-height:1.1;
          }
          .brand p {
            font-size: 12px; margin:0; opacity: .75;
          }
          .pill {
            font-size: 12px;
            padding: 7px 10px;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.12);
            background: rgba(255,255,255,0.05);
            opacity: .95;
            white-space: nowrap;
          }

          /* Cards */
          .card {
            border: 1px solid rgba(255,255,255,0.10);
            background: rgba(18,18,24,0.45);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,.22);
          }
          .hero-title {
            font-size: 28px;
            margin: 0 0 6px 0;
            font-weight: 900;
            letter-spacing: -0.02em;
          }
          .hero-sub {
            opacity: .8;
            margin: 0 0 14px 0;
          }
          .muted { opacity: .75; }

          /* Sidebar */
          section[data-testid="stSidebar"] {
            border-right: 1px solid rgba(255,255,255,0.08);
            background: rgba(18,18,24,0.35);
            backdrop-filter: blur(10px);
          }

          /* Chat container feel */
          .chat-shell {
            border: 1px solid rgba(255,255,255,0.10);
            background: rgba(18,18,24,0.35);
            backdrop-filter: blur(10px);
            border-radius: 22px;
            padding: 14px;
          }

          /* Buttons spacing */
          .stButton>button, .stDownloadButton>button {
            border-radius: 12px !important;
            padding: 0.55rem 0.85rem !important;
            border: 1px solid rgba(255,255,255,0.14) !important;
            background: rgba(255,255,255,0.06) !important;
          }
          .stButton>button:hover, .stDownloadButton>button:hover {
            border-color: rgba(255,255,255,0.25) !important;
            background: rgba(255,255,255,0.10) !important;
          }

          /* Inputs */
          .stTextInput input, .stPassword input {
            border-radius: 14px !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# DB
# -----------------------------
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash BLOB NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

def user_exists(email: str) -> bool:
    conn = db()
    try:
        row = conn.execute("SELECT 1 FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        return bool(row)
    finally:
        conn.close()

def create_user(email: str, password: str):
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    conn = db()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.strip().lower(), pw_hash, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

def verify_user(email: str, password: str):
    conn = db()
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email=?",
            (email.strip().lower(),),
        ).fetchone()
        if not row:
            return None
        user_id, pw_hash = row
        if bcrypt.checkpw(password.encode("utf-8"), pw_hash):
            return user_id
        return None
    finally:
        conn.close()

def load_messages(user_id: int, limit: int = 300):
    conn = db()
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE user_id=? ORDER BY id ASC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [{"role": r[0], "content": r[1]} for r in rows]
    finally:
        conn.close()

def save_message(user_id: int, role: str, content: str):
    conn = db()
    try:
        conn.execute(
            "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (user_id, role, content, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

def clear_messages(user_id: int):
    conn = db()
    try:
        conn.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()

def export_txt(messages):
    lines = []
    for m in messages:
        lines.append(f"{m['role'].upper()}: {m['content']}\n")
    return "\n".join(lines).strip()


# -----------------------------
# Gemini
# -----------------------------
def gemini_client():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        st.error('❌ GEMINI_API_KEY not set. In PowerShell:  $env:GEMINI_API_KEY="YOUR_KEY"')
        st.stop()
    return genai.Client(api_key=key)


# -----------------------------
# UI blocks
# -----------------------------
def topbar(right_text: str):
    st.markdown(
        f"""
        <div class="topbar">
          <div class="brand">
            <div class="logo">✦</div>
            <div>
              <h1>{APP_NAME}</h1>
              <p>{TAGLINE}</p>
            </div>
          </div>
          <div class="pill">{right_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def auth_view():
    topbar("Secure Login")

    col1, col2 = st.columns([1.1, 0.9], gap="large")

    with col1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown(f'<div class="hero-title">Welcome to {APP_NAME}</div>', unsafe_allow_html=True)
        st.markdown('<div class="hero-sub">Sign in to continue. Your chats are saved per account.</div>', unsafe_allow_html=True)

        email = st.text_input("Email", placeholder="you@example.com", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")

        c1, c2 = st.columns([1, 1])
        with c1:
            login = st.button("Login", use_container_width=True)
        with c2:
            guest = st.button("Use demo account", use_container_width=True)

        if guest:
            demo_email = "demo@aurora.local"
            demo_pass = "demo1234"
            if not user_exists(demo_email):
                create_user(demo_email, demo_pass)
            uid = verify_user(demo_email, demo_pass)
            st.session_state.user_id = uid
            st.session_state.user_email = demo_email
            st.session_state.messages = load_messages(uid)
            st.rerun()

        if login:
            uid = verify_user(email, password)
            if uid:
                st.session_state.user_id = uid
                st.session_state.user_email = email.strip().lower()
                st.session_state.messages = load_messages(uid)
                st.rerun()
            else:
                st.error("Invalid email or password.")

        st.markdown('<p class="muted">Tip: Passwords are stored hashed (bcrypt) in SQLite.</p>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Create account")
        new_email = st.text_input("Email ", placeholder="you@example.com", key="signup_email")
        new_pass = st.text_input("Password ", type="password", key="signup_pass")
        new_pass2 = st.text_input("Confirm password", type="password", key="signup_pass2")
        create = st.button("Sign up", use_container_width=True)

        if create:
            e = new_email.strip().lower()
            if not e or "@" not in e:
                st.error("Enter a valid email.")
            elif len(new_pass) < 6:
                st.error("Password must be at least 6 characters.")
            elif new_pass != new_pass2:
                st.error("Passwords do not match.")
            elif user_exists(e):
                st.error("Account already exists. Please login.")
            else:
                create_user(e, new_pass)
                st.success("Account created! Now login on the left ✅")

        st.markdown("<hr/>", unsafe_allow_html=True)
        st.markdown("**What you get**")
        st.markdown("- ✅ Per-user chat history")
        st.markdown("- ✅ Logout + New chat")
        st.markdown("- ✅ Product UI layout")
        st.markdown("</div>", unsafe_allow_html=True)

def workspace_view():
    topbar(f"Signed in: {st.session_state.user_email} • {MODEL.replace('models/','')}")

    with st.sidebar:
        st.markdown(f"### {APP_NAME}")
        nav = st.radio("Workspace", ["Chat", "History", "Settings"], index=0)

        st.divider()
        if st.button("➕ New chat", use_container_width=True):
            clear_messages(st.session_state.user_id)
            st.session_state.messages = []
            st.rerun()

        st.download_button(
            "⬇️ Export chat (.txt)",
            data=export_txt(st.session_state.get("messages", [])),
            file_name=f"aurora_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
            use_container_width=True,
        )

        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.user_id = None
            st.session_state.user_email = None
            st.session_state.messages = []
            st.rerun()

        st.caption("Next upgrades (I can add):")
        st.caption("• Multiple chat threads per user")
        st.caption("• News + FX tools")
        st.caption("• PDF chat")

    if nav == "History":
        st.subheader("History")
        msgs = st.session_state.messages
        if not msgs:
            st.info("No saved messages yet.")
            return
        st.markdown('<div class="card">', unsafe_allow_html=True)
        for i, m in enumerate(msgs[-80:], start=1):
            preview = m["content"][:220] + ("…" if len(m["content"]) > 220 else "")
            st.markdown(f"**{i}. {m['role'].upper()}** — {preview}")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if nav == "Settings":
        st.subheader("Settings")
        st.markdown('<div class="card">', unsafe_allow_html=True)
        tone = st.selectbox("Tone", ["Friendly", "Professional", "Tutor", "Concise"], index=0)
        length = st.selectbox("Reply length", ["Short", "Medium", "Long"], index=1)
        st.caption("These can be applied to system prompts next.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown('<div class="chat-shell">', unsafe_allow_html=True)

    if not st.session_state.messages:
        st.markdown(
            """
            <div class="card">
              <div class="hero-title">Start a new conversation</div>
              <div class="hero-sub">
                Ask anything. Your messages are saved under your account.
              </div>
              <div class="muted">Examples: “Create a resume for data analyst”, “Explain system design basics”.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("")

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    user_text = st.chat_input("Message Aurora…")
    if user_text:
        st.session_state.messages.append({"role": "user", "content": user_text})
        save_message(st.session_state.user_id, "user", user_text)
        with st.chat_message("user"):
            st.markdown(user_text)

        client = gemini_client()
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                contents = []
                for mm in st.session_state.messages:
                    role = "user" if mm["role"] == "user" else "model"
                    contents.append({"role": role, "parts": [{"text": mm["content"]}]})

                try:
                    resp, used_model = generate_with_retry(client, contents)
                    answer = getattr(resp, "text", str(resp))
                except Exception:
                    st.error("The AI is under heavy load right now. Please try again in a moment.")
                    st.stop()

            st.markdown(answer)
            st.caption(f"Answered by: {used_model.replace('models/','')}")

        st.session_state.messages.append({"role": "assistant", "content": answer})
        save_message(st.session_state.user_id, "assistant", answer)

    st.markdown("</div>", unsafe_allow_html=True)


# -----------------------------
# Main
# -----------------------------
def main():
    st.set_page_config(page_title=APP_NAME, page_icon="✦", layout="wide")
    inject_css()
    init_db()

    if "user_id" not in st.session_state:
        st.session_state.user_id = None
        st.session_state.user_email = None
        st.session_state.messages = []

    if not st.session_state.user_id:
        auth_view()
    else:
        if "messages" not in st.session_state or st.session_state.messages is None:
            st.session_state.messages = load_messages(st.session_state.user_id)
        workspace_view()

if __name__ == "__main__":
    main()