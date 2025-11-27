import streamlit as st
import telebot # New library for Bot functionality
import google.generativeai as genai
import requests
import json
import pickle
import re
import os
import time

# 1. SETUP PAGE (Minimal UI)
st.set_page_config(page_title="TPSC Bot Server", page_icon="🤖")
st.title("🤖 TPSC Telegram Bot Server")

# 2. LOAD SECRETS
try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    serper_key = st.secrets["SERPER_API_KEY"]
    bot_token = st.secrets["TELEGRAM_BOT_TOKEN"]
    
    genai.configure(api_key=gemini_key)
    bot = telebot.TeleBot(bot_token) # Initialize the Bot
except Exception as e:
    st.error(f"Secrets Error: {e}")
    st.stop()

# 3. LOAD LOCAL MODEL (The Brain)
@st.cache_resource
def load_model():
    model_path = "hoax_detector_final.pkl"
    
    # Debugging: Check if file exists
    if not os.path.exists(model_path):
        return None
        
    try:
        with open(model_path, "rb") as f:
            loaded_model = pickle.load(f)
            return loaded_model
    except Exception as e:
        return None

model = load_model()

# UI STATUS INDICATOR
if model:
    st.success("✅ Brain Loaded: 'hoax_detector_final.pkl' is active.")
else:
    st.warning("⚠️ Brain Missing: 'hoax_detector_final.pkl' not found. Running in Search-Only mode.")

st.info("Status: Click Start below to activate the listening loop.")

# 4. UTILITY FUNCTIONS
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
    
    # Send "Typing..." status
    bot.send_chat_action(chat_id, 'typing')
    temp_msg = bot.reply_to(message, "🕵️ *TPSC sedang menginvestigasi...*", parse_mode="Markdown")
    
    try:
        # A. SEARCH
        results = google_search(f"{user_text} berita validasi")
        
        if not results:
            bot.edit_message_text("❌ Tidak ditemukan berita relevan di Google.", chat_id, temp_msg.message_id)
            return

        # B. LOCAL AI FILTERING
        evidence_for_gemini = ""
        for doc in results:
            full_text = f"{doc.get('title')} {doc.get('snippet')}"
            link = doc.get('link')
            
            # Predict
            hoax_score = 0.5 # Default if model fails
            tag = "⚪ [ANALYZING]"
            
            if model:
                try:
                    clean_input = clean_text_for_model(full_text)
                    # Assumes the pickle is a full pipeline (Vector + Model)
                    probs = model.predict_proba([clean_input])[0]
                    # Find which index is "Hoax"
                    hoax_idx = 1 # Default assumption
                    if hasattr(model, 'classes_'):
                        classes = list(model.classes_)
                        if "Hoax" in classes:
                            hoax_idx = classes.index("Hoax")
                    
                    hoax_score = probs[hoax_idx]
                except Exception as e:
                    print(f"Prediction Error: {e}")

            # Tagging Logic
            if hoax_score > 0.7: tag = "⛔ [SUSPECT]"
            elif hoax_score > 0.4: tag = "⚠️ [NEUTRAL]"
            else: tag = "✅ [TRUSTED]"
            
            evidence_for_gemini += f"{tag} {doc.get('title')} (Link: {link})\n"

        # C. GEMINI REASONING (With Visual Rubric)
        prompt = f"""
        Peran: Kamu adalah TPSC-Bot.
        TUGAS: Analisis KLAIM USER berdasarkan BUKTI AI Lokal.
        
        KLAIM: "{user_text}"
        BUKTI:
        {evidence_for_gemini}
        
        INSTRUKSI KHUSUS:
        1. Hitung Confidence Score (0-100%).
        2. Gunakan Visual Bar untuk Confidence Score:
           - 80-100%: 🟩🟩🟩🟩🟩 (Trust)
           - 50-79%: 🟨🟨🟨⬜⬜ (Caution)
           - 0-49%: 🟥🟥🟥⬜⬜ (Danger)
        
        OUTPUT FORMAT (Telegram Markdown):
        *LAPORAN TPSC HYBRID*
        ------------------------------
        📊 *Status:* [FAKTA / HOAKS / TIDAK JELAS]
        
        [VISUAL BAR] *Confidence:* [SCORE]%
        
        *📋 Analisis AI:*
        [Jelaskan kesimpulan dalam 2 kalimat]
        
        *🔗 Sumber:*
        [List 2 link terbaik]
        
        _Powered by TPSC_
        """
        
        model_gemini = genai.GenerativeModel('gemini-2.0-flash')
        response = model_gemini.generate_content(prompt)
        final_msg = response.text

        # D. SEND RESULT
        bot.delete_message(chat_id, temp_msg.message_id) 
        bot.send_message(chat_id, final_msg, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Error: {str(e)}")

# 6. START BUTTON (To Run the Loop)
if st.button("🚀 START BOT POLLING"):
    st.success("Bot is running... Go to Telegram!")
    bot.infinity_polling()