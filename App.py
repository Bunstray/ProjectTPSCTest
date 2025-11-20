import streamlit as st
import google.generativeai as genai
from duckduckgo_search import DDGS

# 1. SETUP
st.set_page_config(page_title="Cek Fakta AI", page_icon="🛡️")
st.title("🛡️ Cek Fakta Berita Indonesia")

# Get API Key from Streamlit Secrets (we will set this later)
api_key = st.secrets["GEMINI_API_KEY"] 
genai.configure(api_key=api_key)

# 2. INPUT
user_text = st.text_area("Masukkan judul atau isi berita yang mencurigakan:", height=100)

if st.button("Cek Fakta"):
    with st.spinner('Sedang mencari referensi di internet...'):
        
        # 3. SEARCH (The "Eyes")
        # Uses DuckDuckGo to search for the news text + "hoax" or "fakta"
        results = []
        with DDGS() as ddgs:
            # Search for the claim directly
            search_query = f"{user_text} fakta hoax indonesia"
            # Get top 5 results
            results = list(ddgs.text(search_query, region='id-id', max_results=5))

        if not results:
            st.error("Tidak ditemukan berita terkait. AI tidak dapat memverifikasi.")
        else:
            # 4. PREPARE CONTEXT
            evidence_text = ""
            for doc in results:
                evidence_text += f"- {doc['title']}: {doc['body']} (Link: {doc['href']})\n"

            # 5. REASONING (The "Brain")
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            prompt = f"""
            Peran: Kamu adalah "CekFaktaBot", asisten AI investigasi berita yang objektif, skeptis, namun santai. Target audiensmu adalah masyarakat umum Indonesia.
            
            TUGAS UTAMA:
            Analisis KLAIM USER berdasarkan BUKTI PENCARIAN yang disediakan di bawah.
            
            KLAIM USER:
            "{user_text}"
            
            BUKTI PENCARIAN (Dari Internet):
            {evidence_text}
            
            ATURAN ANALISIS:
            1. JANGAN gunakan pengetahuan bawaanmu. HANYA gunakan fakta yang ada di "BUKTI PENCARIAN".
            2. Jika bukti menyebutkan "TurnBackHoax", "Kominfo", atau "Cek Fakta" membantah klaim ini -> Label: HOAKS.
            3. Jika bukti berasal dari situs satir/humor (seperti PosRonda, The Onion) -> Label: SATIRE.
            4. Jika bukti mengonfirmasi kejadian tapi detailnya salah -> Label: MISINFORMASI.
            5. Jika tidak ada bukti yang relevan sama sekali -> Label: TIDAK TERBUKTI (Minta user cek kata kunci).
            
            FORMAT JAWABAN (Gunakan format Markdown):
            
            ## ⚖️ Vonis: [HOAKS / FAKTA / SATIRE / TIDAK TERBUKTI]
            
            **Penjelasan Singkat:**
            [Tulis 2-3 kalimat santai bahasa Indonesia. Jelaskan kenapa ini hoaks/fakta. Contoh: "Tenang guys, ini cuma editan. Foto aslinya itu kejadian tahun 2019..."]
            
            **Bukti Temuan:**
            * [Poin 1 dari berita A]
            * [Poin 2 dari berita B]
            
            ⚠️ *Analisis ini dibuat otomatis berdasarkan pencarian internet. Selalu cek ulang sumber.*
            """

            response = model.generate_content(prompt)
            
            # 6. OUTPUT
            st.markdown("### Hasil Analisis AI:")
            st.write(response.text)
            
            st.markdown("### Sumber Referensi:")
            for doc in results:
                st.markdown(f"- [{doc['title']}]({doc['href']})")