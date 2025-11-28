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
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# 1. SETUP PAGE
st.set_page_config(page_title="HODEAI Bot Server", page_icon="🤖", layout="wide")
st.title("🤖 HODEAI Bot Server")

if 'bot_running' not in st.session_state:
    st.session_state.bot_running = False

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
    """Writes to Google Sheet with Verdict Column"""
    try:
        sheet = connect_to_sheet()
        if sheet:
            # FIXED: Syntax error removed here (was timestamp = timestamp =)
            timestamp = (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
            
            user_id = str(message.from_user.id)
            username = f"@{message.from_user.username}" if message.from_user.username else "No Username"
            first_name = message.from_user.first_name
            question = message.text
            
            # Append Row: [Timestamp, ID, User, Name, Q, A, Verdict]
            sheet.append_row([timestamp, user_id, username, first_name, question, answer_text, verdict])
            print(f"✅ Logged: {verdict}")
    except Exception as e:
        print(f"❌ Logging Failed: {e}")

# 2. LOAD SECRETS
try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    serper_key = st.secrets["SERPER_API_KEY"]
    bot_token = st.secrets["TELEGRAM_BOT_TOKEN"]
    genai.configure(api_key=gemini_key)
    
    if 'bot_instance' not in st.session_state:
        st.session_state.bot_instance = telebot.TeleBot(bot_token)
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

# HELPER: Extract Verdict from Text
def extract_verdict(text):
    # Regex to find text after "*Status:*" or "Status:"
    match = re.search(r'\*?Status:\*?\s*(.*)', text, re.IGNORECASE)
    if match:
        # Get the text, remove brackets [] and extra spaces
        raw_verdict = match.group(1).strip()
        clean_verdict = re.sub(r'[\[\]]', '', raw_verdict)
        return clean_verdict
    return "UNKNOWN"

# 5. BOT HANDLERS
if not bot.message_handlers:
    
    # --- HANDLER 1: COMMANDS (Free & Fast) ---
    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        welcome_text = """
        👋 *Halo! Saya HODEAI Bot.*
        
        Saya adalah asisten AI Cek Fakta Hybrid.
        Kirimkan judul berita, rumor, atau pesan forward WA ke sini.
        """
        bot.reply_to(message, welcome_text, parse_mode="Markdown")

    # --- HANDLER 2: TEXT MESSAGES ---
    @bot.message_handler(func=lambda message: True and not message.text.startswith('/'))
    def handle_message(message):
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
            
            # RETRY LOGIC FOR 429 ERRORS
            try:
                model_gemini = genai.GenerativeModel('gemini-2.0-flash')
                response = model_gemini.generate_content(prompt)
                final_msg = response.text
            except Exception as e:
                if "429" in str(e) or "exhausted" in str(e):
                    # Fallback to stable model if flash is busy
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

# 5.1 BACKGROUND THREAD FUNCTION
def start_bot_background():
    try:
        # Infinity polling keeps the bot running forever
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"Bot Polling Error: {e}")

# 6. DASHBOARD
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("⚙️ Control Panel")
    
    # --- STATUS INDICATOR ---
    if st.session_state.bot_running:
        st.success("🟢 **STATUS: ONLINE**")
        st.caption("Bot is active and listening to Telegram.")
    else:
        st.error("🔴 **STATUS: OFFLINE**")
        st.caption("Bot is sleeping. Click start to activate.")
        
    st.markdown("---")

    # --- BUTTON LOGIC ---
    if not st.session_state.bot_running:
        if st.button("🚀 START BOT POLLING", type="primary"):
            t = threading.Thread(target=start_bot_background)
            t.daemon = True
            t.start()
            st.session_state.bot_running = True
            st.rerun()
    else:
        if st.button("🛑 STOP BOT (Reload Page)"):
            st.session_state.bot_running = False
            st.rerun()

with col2:
    st.subheader("📜 Live Google Sheet Logs")
    if st.button("🔄 Check Sheet Status"):
        sheet = connect_to_sheet()
        if sheet:
            st.success(f"✅ Connected to: {SHEET_NAME}")
            try:
                data = sheet.get_all_records()
                if data:
                    df = pd.DataFrame(data)
                    # Convert Timestamp for Sorting
                    if "Timestamp" in df.columns:
                        df = df.sort_values(by="Timestamp", ascending=False)
                    st.dataframe(df, height=400)
                else:
                    st.info("Sheet is connected but empty.")
            except:
                st.warning("Could not read data. Did you add the 'Verdict' header in Column G?")
        else:
            st.error("❌ Connection Failed.")