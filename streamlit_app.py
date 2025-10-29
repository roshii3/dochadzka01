import streamlit as st
from datetime import datetime, time, timedelta, date
import pytz
from supabase import create_client, Client
import re
from pathlib import Path

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

tz = pytz.timezone("Europe/Bratislava")
POSITIONS = [
    "Veliteľ","CCTV","Brány","Sklad2",
    "Turniket2","Plombovac2","Sklad3",
    "Turniket3","Plombovac3"
]

# ==============================
# Načítanie uloženého kódu a dátumu
# ==============================
if "device_code" not in st.session_state:
    if DEVICE_FILE.exists():
        with open(DEVICE_FILE, "r") as f:
            content = f.read().strip().split("|")  # uložené vo formáte: code|YYYY-MM-DD
            if len(content) == 2:
                code, saved_date = content
                if saved_date == date.today().isoformat():
                    st.session_state.device_code = code
                else:
                    st.session_state.device_code = None
            else:
                st.session_state.device_code = None
    else:
        st.session_state.device_code = None

def set_device_code(code: str):
    """Uloží kód zariadenia do session a do lokálneho súboru s dátumom"""
    st.session_state.device_code = code.strip()
    with open(DEVICE_FILE, "w") as f:
        f.write(f"{code.strip()}|{date.today().isoformat()}")

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
        return False, "⚠️ Neplatné číslo čipu!"
    
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
    return is_valid, None

# ==============================
# Zamestnanecký view
# ==============================
def zamestnanec_view():
    # Inicializácia session_state
    for key in ["temp_user_code","selected_position","top_message","message_timer"]:
        if key not in st.session_state:
            st.session_state[key] = "" if key != "selected_position" else None

    # reload_counter vždy int
    if "reload_counter" not in st.session_state or not isinstance(st.session_state.reload_counter, int):
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

    # 🔝 horné hlásenie s časovačom
    top_placeholder = st.empty()
    if st.session_state.top_message:
        color = "green" if "(platný)" in st.session_state.top_message else "red"
        top_placeholder.markdown(f"<div style='color:{color}; font-size:20px'>{st.session_state.top_message}</div>", unsafe_allow_html=True)
        # nastav časovač na automatické zmiznutie správy po 3 sekundách
        if st.session_state.message_timer is None:
            st.session_state.message_timer = datetime.now() + timedelta(seconds=3)
        elif datetime.now() >= st.session_state.message_timer:
            st.session_state.top_message = ""
            st.session_state.message_timer = None
            st.experimental_rerun()

    # tlačidlo pre nový záznam
    if st.button("🆕 Nový príchod/odchod"):
        st.session_state.temp_user_code = ""
        st.session_state.selected_position = None
        st.session_state.reload_counter += 1
        st.experimental_rerun()

    input_key = f"user_code_input_{st.session_state.reload_counter}"
    user_code = st.text_input(
        "Naskenuj svoj QR kód",
        value=st.session_state.temp_user_code,
        key=input_key,
        type="password"
    ).replace(" ", "")
    st.session_state.temp_user_code = user_code

    # výber pozície
    st.write("👉 Vyber svoju pozíciu:")
    cols = st.columns(3)
    for i, pos in enumerate(POSITIONS):
        if cols[i % 3].button(pos):
            st.session_state.selected_position = pos

    if st.session_state.selected_position:
        st.info(f"Vybraná pozícia: {st.session_state.selected_position}")

    col1, col2 = st.columns(2)

    def save_and_notify(action_name):
        nonlocal user_code
        if not user_code or not st.session_state.selected_position:
            st.session_state.top_message = "⚠️ Zadaj QR kód a vyber pozíciu!"
            st.session_state.message_timer = datetime.now() + timedelta(seconds=3)
        else:
            now_corrected = datetime.now(tz) + timedelta(hours=1)
            is_valid, error_msg = save_attendance(user_code, st.session_state.selected_position, action_name, now_corrected)
            if error_msg:
                st.session_state.top_message = error_msg
                st.session_state.message_timer = datetime.now() + timedelta(seconds=3)
            else:
                status_text = "platný" if is_valid else "mimo času"
                st.session_state.top_message = f"{action_name} zaznamenaný ({status_text}) ✅"
                st.session_state.message_timer = datetime.now() + timedelta(seconds=3)
                st.session_state.temp_user_code = ""
                st.session_state.selected_position = None
                st.session_state.reload_counter += 1
            st.experimental_rerun()

    if col1.button("✅ Príchod", key="prichod_btn"):
        save_and_notify("Príchod")

    if col2.button("🚪 Odchod", key="odchod_btn"):
        save_and_notify("Odchod")

# ==============================
# Spustenie app
# ==============================
def main():
    zamestnanec_view()

if __name__ == "__main__":
    main()
