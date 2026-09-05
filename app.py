import streamlit as st
import pandas as pd
from google import genai
import os
from datetime import date
from streamlit_gsheets import GSheetsConnection

COLUMNS = ["Date", "Place Name", "Cuisine/Activity", "Rating", "Notes"]
WORKSHEET = "Trips"  # name of the tab inside your Google Sheet

st.set_page_config(page_title="Family Trip Planner", page_icon="🚗", layout="centered")
st.title("🚗 Family Trip & Dinner Planner")

# --- Google Sheets connection (shared store for both of us) ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df = conn.read(worksheet=WORKSHEET, ttl=0)
        df = df.dropna(how="all")  # drop blank trailing rows Sheets sometimes returns
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[COLUMNS]
    except Exception:
        # Empty/brand-new sheet, or the worksheet doesn't exist yet
        return pd.DataFrame(columns=COLUMNS)

def save_data(df):
    conn.update(worksheet=WORKSHEET, data=df)

# --- Pull Gemini API Key Securely from Streamlit Secrets ---
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    api_key = None

with st.sidebar:
    st.header("⚙️ Status")
    if api_key:
        st.success("Gemini API Key loaded securely! ✨")
    else:
        st.error("Gemini API Key not found in Streamlit Secrets.")

df = load_data()
tab1, tab2, tab3 = st.tabs(["📝 Log a Trip", "📅 Past Trips", "✨ AI Suggestions"])

with tab1:
    st.subheader("Add a New Trip or Dinner")
    with st.form("add_trip_form"):
        trip_date = st.date_input("Date", date.today())
        place_name = st.text_input("Place Name")
        cuisine = st.text_input("Cuisine or Activity")
        rating = st.slider("Rating", 1, 5, 3)
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save Entry")

        if submitted:
            if place_name and cuisine:
                new_entry = pd.DataFrame([{
                    "Date": str(trip_date),
                    "Place Name": place_name,
                    "Cuisine/Activity": cuisine,
                    "Rating": rating,
                    "Notes": notes
                }])
                updated_df = pd.concat([df, new_entry], ignore_index=True)
                save_data(updated_df)
                st.success(f"Successfully added '{place_name}'!")
                st.rerun()
            else:
                st.error("Please fill out at least the Place Name and Cuisine/Activity.")

with tab2:
    st.subheader("Our Travel & Dining History")
    if not df.empty:
        st.dataframe(df.sort_values(by="Date", ascending=False), use_container_width=True)
    else:
        st.info("No trips logged yet.")

with tab3:
    st.subheader("Surprise Us!")
    location = st.text_input("Where are we looking?", value="Cambridge, UK")

    if st.button("Get AI Suggestions ✨"):
        if not api_key:
            st.error("Gemini API Key not found in Streamlit Secrets.")
        elif df.empty:
            st.warning("Log at least one past trip first.")
        elif not location:
            st.warning("Please enter your location.")
        else:
            try:
                # Initialize the modern Google GenAI client
                client = genai.Client(api_key=api_key)
                recent_trips = df.tail(10).to_dict(orient='records')
                prompt = f"""
                My wife, our 4-year-old daughter, and I are looking for our next family-friendly weekend trip or dinner spot near {location}.
                Here are our most recent outings: {recent_trips}
                Suggest 3 NEW, highly-rated local places. DO NOT suggest overlapping cuisines/places.
                """
                with st.spinner("Finding fresh recommendations..."):
                    response = client.models.generate_content(
                        model='gemini-3.6-flash',
                        contents=prompt,
                    )
                    st.markdown(response.text)
            except Exception as e:
                st.error(f"An API error occurred: {e}")