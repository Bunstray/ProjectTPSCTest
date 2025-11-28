import streamlit as st
import telebot
import google.generativeai as genai
import requests
import json
import pickle
import re
import os
import pandas as pd
import threading
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# 1. SETUP PAGE CONFIGURATION
st.set_page_config(
    page_title="HODEAI Server", 
    page_icon="🔒", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CUSTOM CSS ---
st.markdown("""
<style>
    .stMetric {
        background-color: #0E1117;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #262730;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔐 AUTHENTICATION SYSTEM
# ==========================================
def check_password():
    """Returns `True` if the user had the correct password."""
    
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["ADMIN_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't store the password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input
        st.text_input(
            "🔑 Enter Admin Password", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password incorrect, show input + error
        st.text_input(
            "🔑 Enter Admin Password", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct
        return True

if not check_password():
    st.stop()  # STOP EXECUTION HERE if not logged in

# ==========================================
# 🚀 MAIN APP LOGIC (Only runs if logged in)
# ==========================================

# --- GLOBAL VARIABLES ---
if 'bot_instance' not in st.session_state:
    st.session_state.bot_instance = None

# --- GOOGLE SHEETS SETUP ---
SHEET_NAME = "TPSC_Bot_Logs"

def connect_to_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1
        return sheet
    except Exception as e:
        return None

def log_to_sheet(message, answer_text, verdict="ERROR"):
    try:
        sheet = connect_to_sheet()
        if sheet:
            timestamp = (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
            user_id = str(message.from_user.id)
            username = f"@{message.from_user.username}" if message.from_user.username else "No Username"
            first_name = message.from_user.first_name
            question = message.text
            
            sheet.append_row([timestamp, user_id, username, first_name, question, answer_text, verdict])
            print(f"✅ Logged: {verdict}")
    except Exception as e:
        print(f"❌ Logging Failed: {e}")

# 2. LOAD SECRETS & INITIALIZE BOT
try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    serper_key = st.secrets["SERPER_API_KEY"]
    bot_token = st.secrets["TELEGRAM_BOT_TOKEN"]
    genai.configure(api_key=gemini_key)
    
    if st.session_state.bot_instance is None:
        st.session_state.bot_instance = telebot.TeleBot(bot_token, threaded=False)
    
    bot = st.session_state.bot_instance
except Exception as e:
    st.error(f"Secrets Error: {e}")
    st.stop()

# 3. LOAD BRAIN
@st.cache_resource
def load_model():
    model_path = "hoax_detector_final.pkl"
    if not os.path.exists(model_path): return None
    try:
        with open(model_path, "rb") as f:
            return pickle.load(f)
    except: return None
model = load_model()

# 4. UTILITIES
def clean_text_for_model(text):
    text = str(text)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    caps_count = sum(1 for c in text if c.isupper())
    length = len([c for c in text if c.isalpha()])
    style_tokens = ""
    if length > 0 and (caps_count / length) > 0.3: style_tokens += " token_shouting "
    if "!!" in text or "??" in text: style_tokens += " token_excessive_bang "
    clickbait_triggers = ['viralkan', 'sebarkan', 'awas', 'hati-hati', 'terbongkar']
    if any(word in text.lower() for word in clickbait_triggers): style_tokens += " token_clickbait "
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', '', text) 
    return text + style_tokens

def google_search(query):
    url = "https://google.serper.dev/search"
    payload = json.dumps({"q": query, "gl": "id", "hl": "id", "num": 5})
    headers = {'X-API-KEY': serper_key, 'Content-Type': 'application/json'}
    try:
        response = requests.post(url, headers=headers, data=payload)
        return response.json().get("organic", [])
    except: return []

def extract_verdict(text):
    match = re.search(r'\*?Status:\*?\s*(.*)', text, re.IGNORECASE)
    if match:
        raw_verdict = match.group(1).strip()
        clean_verdict = re.sub(r'[\[\]]', '', raw_verdict)
        return clean_verdict
    return "UNKNOWN"

# 5. BOT HANDLERS
if not bot.message_handlers:
    
    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        welcome_text = """
        👋 *Halo! Saya HODEAI Bot.*
        Kirimkan judul berita untuk cek fakta.
        """
        bot.reply_to(message, welcome_text, parse_mode="Markdown")

    @bot.message_handler(func=lambda message: True and not message.text.startswith('/'))
    def handle_message(message):
        is_thread_alive = False
        for t in threading.enumerate():
            if t.name == "TPSC_Worker":
                is_thread_alive = True
                break
        
        if not is_thread_alive: return 

        user_text = message.text
        chat_id = message.chat.id
        
        bot.send_chat_action(chat_id, 'typing')
        temp_msg = bot.reply_to(message, "🕵️ *HODEAI sedang menginvestigasi...*", parse_mode="Markdown")
        
        try:
            results = google_search(f"{user_text} berita validasi")
            if not results:
                err = "❌ Tidak ditemukan berita relevan."
                bot.edit_message_text(err, chat_id, temp_msg.message_id)
                log_to_sheet(message, err, "NOT FOUND")
                return

            evidence_for_gemini = ""
            for doc in results:
                full_text = f"{doc.get('title')} {doc.get('snippet')}"
                link = doc.get('link')
                hoax_score = 0.5 
                if model:
                    try:
                        clean_input = clean_text_for_model(full_text)
                        probs = model.predict_proba([clean_input])[0]
                        hoax_idx = 1
                        if hasattr(model, 'classes_'):
                            classes = list(model.classes_)
                            if "Hoax" in classes: hoax_idx = classes.index("Hoax")
                        hoax_score = probs[hoax_idx]
                    except: pass

                if hoax_score > 0.7: tag = "⛔ [SUSPECT]"
                elif hoax_score > 0.4: tag = "⚠️ [NEUTRAL]"
                else: tag = "✅ [TRUSTED]"
                evidence_for_gemini += f"{tag} {doc.get('title')} (Link: {link})\n"

            prompt = f"""
            Peran: Kamu adalah HODEAI-Bot.
            KLAIM: "{user_text}"
            BUKTI: {evidence_for_gemini}
            
            INSTRUKSI:
            1. Hitung Confidence Score (0-100%).
            2. Gunakan Visual Bar: 🟩(Trust) 🟨(Caution) 🟥(Danger).
            
            OUTPUT FORMAT (Telegram Markdown):
            *HASIL CEK FAKTA*
            ------------------------------
            📊 *Status:* [FAKTA / HOAKS / TIDAK JELAS]
            [VISUAL BAR] *Confidence:* [SCORE]%
            
            *📋 Analisis AI:*
            [Jelaskan kesimpulan dalam 2 kalimat]
            
            *🔗 Sumber:*
            [List 2 link terbaik]
            
            _Powered by HODE AI_
            """
            
            try:
                model_gemini = genai.GenerativeModel('gemini-2.0-flash')
                response = model_gemini.generate_content(prompt)
                final_msg = response.text
            except Exception as e:
                if "429" in str(e) or "exhausted" in str(e):
                    model_gemini = genai.GenerativeModel('gemini-1.5-flash')
                    response = model_gemini.generate_content(prompt)
                    final_msg = response.text
                else:
                    raise e

            verdict_text = extract_verdict(final_msg)

            bot.delete_message(chat_id, temp_msg.message_id) 
            log_to_sheet(message, final_msg, verdict_text)
            
            try:
                bot.send_message(chat_id, final_msg, parse_mode="Markdown")
            except:
                bot.send_message(chat_id, final_msg)

        except Exception as e:
            err_msg = f"⚠️ System Error: {str(e)}"
            bot.send_message(chat_id, err_msg)
            log_to_sheet(message, err_msg, "SYSTEM ERROR")

# 5.1 BACKGROUND THREAD
def start_bot_background():
    try:
        st.session_state.bot_instance.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"Bot Error: {e}")

# =========================================================
# 6. UI DASHBOARD IMPLEMENTATION
# =========================================================

# Check Status Global
is_running_global = False
for thread in threading.enumerate():
    if thread.name == "TPSC_Worker":
        is_running_global = True
        break

# --- HEADER ---
st.title("🎛️ HODEAI Control Panel")
st.caption(f"Server Time: {(datetime.utcnow() + timedelta(hours=7)).strftime('%H:%M:%S (GMT+7)')}")

# --- METRICS ROW ---
m1, m2, m3 = st.columns(3)

with m1:
    if is_running_global:
        st.metric("System Status", "ONLINE", "Running")
    else:
        st.metric("System Status", "OFFLINE", "- Stopped")

with m2:
    if connect_to_sheet():
        st.metric("Database", "CONNECTED", "Google Sheets")
    else:
        st.metric("Database", "ERROR", "Check Secrets")

with m3:
    if model:
        st.metric("AI Brain", "ACTIVE", "Local Model Loaded")
    else:
        st.metric("AI Brain", "MISSING", "Search Only Mode")

st.markdown("---")

# --- MAIN CONTROLS ---
tab1, tab2 = st.tabs(["🚀 SERVER CONTROL", "📊 USER STATISTICS"])

with tab1:
    st.subheader("Process Management")
    if is_running_global:
        st.success("✅ **The Bot is currently ACTIVE.**")
        st.info("To stop, close this tab.")
    else:
        st.warning("⚠️ **The Bot is currently STOPPED.**")
        if st.button("▶️ ACTIVATE BOT SERVER", type="primary", use_container_width=True):
            if hasattr(bot, 'stop_polling_flag'):
                bot.stop_polling_flag = False
            t = threading.Thread(target=start_bot_background, name="TPSC_Worker")
            t.daemon = True
            t.start()
            st.rerun()

with tab2:
    # DATA LOADING
    sheet = connect_to_sheet()
    if sheet:
        try:
            data = sheet.get_all_records()
            if data:
                df = pd.DataFrame(data)
                
                # ---------------- SECTION A: USER LEADERBOARD ----------------
                st.subheader("🏆 User Leaderboard")
                
                col_search, _ = st.columns([2, 1])
                with col_search:
                    search_query = st.text_input("🔍 Search User", placeholder="Type username, Name, or ID...")
                
                if "User ID" in df.columns:
                    # 1. Calc Stats
                    user_stats = df.groupby(["User ID", "Name", "Username"]).size().reset_index(name='Messages Sent')
                    
                    if "Timestamp" in df.columns:
                        last_active = df.groupby("User ID")["Timestamp"].max().reset_index(name='Last Active')
                        user_stats = pd.merge(user_stats, last_active, on="User ID")
                    
                    # 2. Filter Logic
                    if search_query:
                        user_stats = user_stats[
                            user_stats['Name'].str.contains(search_query, case=False, na=False) |
                            user_stats['Username'].str.contains(search_query, case=False, na=False) |
                            user_stats['User ID'].astype(str).str.contains(search_query, case=False, na=False)
                        ]

                    user_stats = user_stats.sort_values(by="Messages Sent", ascending=False)
                    
                    # 3. Render Table (Centered 'Messages Sent')
                    styled_stats = user_stats.style.set_properties(
                        subset=['Messages Sent'], 
                        **{'text-align': 'center'}
                    ).set_table_styles([
                        {'selector': 'th.col_heading', 'props': 'text-align: center;'},
                        {'selector': 'td', 'props': 'text-align: center;'}
                    ], overwrite=False)
                    
                    st.dataframe(
                        styled_stats, 
                        use_container_width=True,
                        column_config={
                            "User ID": st.column_config.TextColumn("User ID"),
                        }
                    )
                
                st.markdown("---")
                
                # ---------------- SECTION B: RAW LOGS ----------------
                col_x, col_y = st.columns([3, 1])
                with col_x:
                    st.subheader("📝 Message Logs")
                with col_y:
                    if st.button("🔄 Refresh Logs"):
                        st.rerun()

                # Filters for Logs
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    log_search = st.text_input("🔍 Search Content", placeholder="Search within messages/answers...")
                with col_f2:
                    if "Verdict" in df.columns:
                        unique_verdicts = df["Verdict"].unique().tolist()
                        verdict_filter = st.multiselect("⚖️ Filter by Verdict", unique_verdicts)
                    else:
                        verdict_filter = []

                # Apply Filters
                df_filtered = df.copy()
                
                if log_search:
                    df_filtered = df_filtered[
                        df_filtered['Question'].str.contains(log_search, case=False, na=False) |
                        df_filtered['Answer'].str.contains(log_search, case=False, na=False)
                    ]
                
                if verdict_filter:
                    df_filtered = df_filtered[df_filtered['Verdict'].isin(verdict_filter)]

                # Sort Date
                if "Timestamp" in df_filtered.columns:
                    df_filtered = df_filtered.sort_values(by="Timestamp", ascending=False)

                st.dataframe(df_filtered, use_container_width=True, height=400)
                
            else:
                st.info("Database is empty.")
        except Exception as e:
            st.error(f"Error reading database: {e}")
    else:
        st.error("Cannot connect to Google Sheets.")