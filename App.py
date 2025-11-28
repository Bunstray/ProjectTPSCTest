import streamlit as st
import telebot
import google.generativeai as genai
import requests
import json
import pickle
import re
import os
import csv
import pandas as pd
from datetime import datetime

# 1. SETUP PAGE
st.set_page_config(page_title="TPSC Bot Server", page_icon="🤖", layout="wide")
st.title("🤖 TPSC Bot Server & Full Logs")

# --- LOGGING SETUP ---
LOG_FILE = "bot_logs.csv"

# Initialize CSV with "Question" and "Answer" columns
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Timestamp", "User ID", "Username", "Name", "Question", "Answer"])

def log_interaction(message, answer_text):
    """Saves User Question AND Bot Answer to CSV"""
    try:
        user_id = message.from_user.id
        username = f"@{message.from_user.username}" if message.from_user.username else "No Username"
        first_name = message.from_user.first_name
        question = message.text
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([timestamp, user_id, username, first_name, question, answer_text])
    except Exception as e:
        print(f"Logging Error: {e}")

# 2. LOAD SECRETS
try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    serper_key = st.secrets["SERPER_API_KEY"]
    bot_token = st.secrets["TELEGRAM_BOT_TOKEN"]
    
    genai.configure(api_key=gemini_key)
    bot = telebot.TeleBot(bot_token)
except Exception as e:
    st.error(f"Secrets Error: {e}")
    st.stop()

# 3. LOAD MODEL
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

# 5. TELEGRAM BOT LOGIC
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_text = message.text
    chat_id = message.chat.id
    
    bot.send_chat_action(chat_id, 'typing')
    temp_msg = bot.reply_to(message, "🕵️ *TPSC sedang menginvestigasi...*", parse_mode="Markdown")
    
    try:
        # A. SEARCH
        results = google_search(f"{user_text} berita validasi")
        
        if not results:
            error_msg = "❌ Tidak ditemukan berita relevan di Google."
            bot.edit_message_text(error_msg, chat_id, temp_msg.message_id)
            log_interaction(message, error_msg) # Log the failure
            return

        # B. LOCAL AI FILTERING
        evidence_for_gemini = ""
        for doc in results:
            full_text = f"{doc.get('title')} {doc.get('snippet')}"
            link = doc.get('link')
            
            # Predict
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

        # C. GEMINI REASONING
        prompt = f"""
        Peran: Kamu adalah TPSC-Bot.
        KLAIM: "{user_text}"
        BUKTI: {evidence_for_gemini}
        
        INSTRUKSI KHUSUS:
        1. Hitung Confidence Score (0-100%).
        2. Gunakan Visual Bar:
           - 80-100%: 🟩🟩🟩🟩🟩 (Trust)
           - 50-79%: 🟨🟨🟨⬜⬜ (Caution)
           - 0-49%: 🟥🟥🟥⬜⬜ (Danger)
        
        OUTPUT FORMAT (Telegram Markdown):
        *HASIL CEK FAKTA*
        ------------------------------
        📊 *Status:* [FAKTA / HOAKS / TIDAK JELAS]
        
        [VISUAL BAR] *Confidence:* [SCORE]%
        
        *📋 Analisis AI:*
        [Jelaskan kesimpulan dalam 2 kalimat]
        
        *🔗 Sumber:*
        [List 2 hingga 3 link terbaik]
        
        _Powered by CekFaktaTPSC_
        """
        
        model_gemini = genai.GenerativeModel('gemini-2.0-flash')
        response = model_gemini.generate_content(prompt)
        final_msg = response.text

        # D. SEND & LOG
        bot.delete_message(chat_id, temp_msg.message_id) 
        
        # 1. Log the full conversation to CSV
        log_interaction(message, final_msg)
        
        # 2. Send to user
        try:
            bot.send_message(chat_id, final_msg, parse_mode="Markdown")
        except:
            bot.send_message(chat_id, final_msg)

    except Exception as e:
        error_text = f"⚠️ System Error: {str(e)}"
        bot.send_message(chat_id, error_text)
        log_interaction(message, error_text)


# 6. DASHBOARD
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("⚙️ Control Panel")
    if st.button("🚀 START BOT POLLING"):
        st.success("Bot is running... Go to Telegram!")
        bot.infinity_polling()

with col2:
    st.subheader("📜 Q&A Logs")
    if st.button("🔄 Refresh Table"):
        if os.path.exists(LOG_FILE):
            try:
                df = pd.read_csv(LOG_FILE)
                # Sort newest first
                df = df.sort_values(by="Timestamp", ascending=False)
                st.dataframe(df, height=400)
            except:
                st.error("Log file is corrupted. Please delete bot_logs.csv")
        else:
            st.warning("No logs found yet.")
            
    # Load table on start
    if os.path.exists(LOG_FILE):
        try:
            df = pd.read_csv(LOG_FILE)
            df = df.sort_values(by="Timestamp", ascending=False)
            st.dataframe(df, height=400)
        except: pass