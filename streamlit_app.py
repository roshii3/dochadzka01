import streamlit as st
from datetime import datetime, time
import pytz
from supabase import create_client, Client
import re
import time as tmode
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Dochádzka", page_icon="🕒", layout="centered")

# Skrytie hamburger menu a footeru
hide_menu = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
"""
st.markdown(hide_menu, unsafe_allow_html=True)
# ==============================
# Nastavenia databázy
# ==============================
DATABAZA_URL = st.secrets.get("DATABAZA_URL")
DATABAZA_KEY = st.secrets.get("DATABAZA_KEY")
databaza: Client = create_client(DATABAZA_URL, DATABAZA_KEY)

# ==============================
# Automatická cesta pre uloženie kódu zariadenia
# ==============================
app_dir = Path.home() / ".dochadzka_app"
app_dir.mkdir(parents=True, exist_ok=True)
DEVICE_FILE = app_dir / "device_code.txt"

# Načítanie uloženého kódu
if "device_code" not in st.session_state:
    if DEVICE_FILE.exists():
        with open(DEVICE_FILE, "r") as f:
            st.session_state.device_code = f.read().strip()
    else:
        st.session_state.device_code = None

def set_device_code(code: str):
    """Uloží kód zariadenia do session a do lokálneho súboru"""
    st.session_state.device_code = code.strip()
    with open(DEVICE_FILE, "w") as f:
        f.write(code.strip())

tz = pytz.timezone("Europe/Bratislava")
POSITIONS = [
    "Veliteľ","CCTV","Brány","Sklad2",
    "Turniket2","Plombovac2","Sklad3",
    "Turniket3","Plombovac3"
]

# ==============================
# Overenie zariadenia v DB
# ==============================
def verify_device(code: str) -> bool:
    result = databaza.table("devices").select("code").eq("code", code.strip()).execute()
    return bool(result.data and len(result.data) > 0)

# ==============================
# Validácia času
# ==============================
def valid_arrival(now):
    return (time(5,0) <= now.time() <= time(7,0)) or (time(13,0) <= now.time() <= time(15,0))

def valid_departure(now):
    return (time(13,30) <= now.time() <= time(15,0)) or (time(21,0) <= now.time() <= time(23,0))

# ==============================
# Validácia QR kódu zamestnanca
# ==============================
def is_valid_code(code: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9]{10}", code))

# ==============================
# Uloženie záznamu
# ==============================
def save_attendance(user_code, position, action, now=None):
    user_code = user_code.strip()
    if not is_valid_code(user_code):
        st.warning("⚠️ Neplatné číslo čipu!")
        return False

    if not now:
        now = datetime.now(tz)
    is_valid = valid_arrival(now) if action == "Príchod" else valid_departure(now)

    databaza.table("attendance").insert({
        "user_code": user_code,
        "position": position,
        "action": action,
        "timestamp": now.isoformat(),
        "valid": is_valid
    }).execute()
    return is_valid

# ==============================
# Zamestnanecký view
# ==============================
def zamestnanec_view():
    if "temp_user_code" not in st.session_state:
        st.session_state.temp_user_code = ""
    if "selected_position" not in st.session_state:
        st.session_state.selected_position = None
    if "last_message" not in st.session_state:
        st.session_state.last_message = ""
    if "reload_counter" not in st.session_state:
        st.session_state.reload_counter = 0

    # 🔐 kontrola zariadenia
    if not st.session_state.device_code:
        st.subheader("Autorizácia zariadenia")
        input_code = st.text_input("Zadaj kód zariadenia")
        if st.button("Potvrdiť kód"):
            if input_code.strip():
                if verify_device(input_code):
                    set_device_code(input_code)
                    st.success("Zariadenie autorizované ✅")
                    st.experimental_rerun()
                else:
                    st.error("❌ Kód zariadenia nie je povolený!")
            else:
                st.warning("Zadaj platný kód zariadenia!")
        return

    now = datetime.now(tz)
    st.subheader(f"🕒 Aktuálny čas: {now.strftime('%H:%M:%S')}")

    if st.button("🆕 Nový príchod/odchod"):
        st.session_state.temp_user_code = ""
        st.session_state.selected_position = None
        st.session_state.last_message = ""
        st.session_state.reload_counter += 1
        st.experimental_rerun()

    input_key = f"user_code_input_{st.session_state.reload_counter}"
    user_code = st.text_input(
        "Naskenuj svoj QR kód",
        value=st.session_state.temp_user_code,
        key=input_key
    ).replace(" ", "")

    st.write("👉 Vyber svoju pozíciu:")
    cols = st.columns(3)
    for i, pos in enumerate(POSITIONS):
        if cols[i % 3].button(pos):
            st.session_state.selected_position = pos

    if st.session_state.selected_position:
        st.info(f"Vybraná pozícia: {st.session_state.selected_position}")

    col1, col2 = st.columns(2)

    if col1.button("✅ Príchod", key="prichod_btn"):
        if not user_code or not st.session_state.selected_position:
            st.session_state.last_message = "⚠️ Zadaj QR kód a vyber pozíciu!"
        else:
            is_valid = save_attendance(user_code, st.session_state.selected_position, "Príchod", now)
            st.session_state.last_message = f"Príchod zaznamenaný {'(platný)' if is_valid else '(mimo času)'} ✅"
            st.session_state.temp_user_code = ""
            st.session_state.selected_position = None
            st.session_state.reload_counter += 1

    if col2.button("🚪 Odchod", key="odchod_btn"):
        if not user_code or not st.session_state.selected_position:
            st.session_state.last_message = "⚠️ Zadaj QR kód a vyber pozíciu!"
        else:
            is_valid = save_attendance(user_code, st.session_state.selected_position, "Odchod", now)
            st.session_state.last_message = f"Odchod zaznamenaný {'(platný)' if is_valid else '(mimo času)'} ✅"
            st.session_state.temp_user_code = ""
            st.session_state.selected_position = None
            st.session_state.reload_counter += 1

    if st.session_state.last_message:
        message_placeholder = st.empty()
        message_placeholder.success(st.session_state.last_message)
        tmode.sleep(3)
        message_placeholder.empty()
        st.session_state.last_message = ""

# ==============================
# Spustenie app
# ==============================
def main():
    zamestnanec_view()

if __name__ == "__main__":
    main()
